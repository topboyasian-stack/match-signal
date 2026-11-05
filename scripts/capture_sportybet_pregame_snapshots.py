#!/usr/bin/env python3
"""Capture immutable final-15-minute SportyBet winner snapshots for trial scoring.

This is a research ledger only. It does not modify predictions, ticket state,
qualification gates, stakes, or bookmaker execution.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS_PATH = DATA / "predictions.json"
LEDGER_PATH = DATA / "sportybet_pregame_snapshots.json"
sys.path.insert(0, str(ROOT / "scripts"))

from market_snapshot_freshness import is_fresh_pregame_snapshot, parse_utc, pregame_snapshot_age_seconds
import enrich_sportybet_odds as sportybet


EXPECTED_MARKET_ID = {"football": "1", "tennis": "186"}
ACTIVE_TENNIS_TOUR = "ATP"
PAGE_LIMIT = 10
MAX_LEDGER_ROWS = 12000


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def exact_snapshot_from_prediction(row, fetched_at):
    """Return a normalized immutable snapshot only for an exact fresh market."""
    if not isinstance(row, dict):
        return None
    sport = str(row.get("sport") or "").lower()
    if sport not in EXPECTED_MARKET_ID:
        return None
    if sport == "tennis" and str(row.get("league") or "").upper() != ACTIVE_TENNIS_TOUR:
        return None

    event_id = str(row.get("event_id") or "")
    start_time = row.get("start_time")
    if not event_id or not is_fresh_pregame_snapshot(fetched_at, start_time):
        return None

    winner = row.get("sportybet_winner_odds") or {}
    market_id = str(winner.get("market_id") or "")
    if market_id != EXPECTED_MARKET_ID[sport]:
        return None

    pick = str(row.get("pick") or "")
    if pick not in ({"p1", "p2", "draw"} if sport == "football" else {"p1", "p2"}):
        return None

    odds_map = {"p1": winner.get("p1"), "p2": winner.get("p2")}
    if sport == "football":
        odds_map["draw"] = winner.get("draw")
    try:
        prices = {key: float(value) for key, value in odds_map.items()}
    except (TypeError, ValueError):
        return None
    if any(value <= 1.0 for value in prices.values()):
        return None

    probabilities = row.get("probabilities") or {}
    try:
        probability = float(probabilities.get(pick))
        confidence = float(row.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not (0 < probability < 1 and 0 < confidence <= 1):
        return None

    snapshot_source = str(
        (row.get("sportybet_market_snapshot") or {}).get("source")
        or row.get("market_source")
        or ""
    )
    if "sportybet" not in snapshot_source.lower():
        return None

    age_seconds = pregame_snapshot_age_seconds(fetched_at, start_time)
    return {
        "event_id": event_id,
        "sport": sport,
        "league": row.get("league") or row.get("tour"),
        "player_1": row.get("player_1") or row.get("home_team"),
        "player_2": row.get("player_2") or row.get("away_team"),
        "start_time": start_time,
        "captured_at": fetched_at,
        "quote_age_seconds": round(float(age_seconds), 3),
        "market_id": market_id,
        "last_odds_change_time": (
            row.get("sportybet_winner_odds") or {}
        ).get("lastOddsChangeTime"),
        "source": "SportyBet NG",
        "match_type": (row.get("sportybet_market_snapshot") or {}).get("match_type"),
        "sportybet_event_id": (
            row.get("sportybet_market_snapshot") or {}
        ).get("sportybet_event_id"),
        "pick": pick,
        "model_probability": round(probability, 6),
        "confidence": round(confidence, 6),
        "model_version": row.get("model_version") or row.get("model"),
        "prices": prices,
    }


def fetch_current_events(sport):
    events = []
    errors = []
    for page in range(1, PAGE_LIMIT + 1):
        body = sportybet.fetch(sport, page=page)
        batch = sportybet.flatten(body)
        events.extend(batch)
        if len(batch) < 100:
            break
    unique = {str(event.get("eventId")): event for event in events if event.get("eventId")}
    return list(unique.values()), errors


def event_matches_prediction_time(prediction, event, tolerance_seconds=300):
    """Reject same-name fixtures whose scheduled kickoff does not match."""
    predicted_start = parse_utc(prediction.get("start_time"))
    try:
        raw_start = float(event.get("estimateStartTime") or 0)
        if raw_start <= 0:
            return False
        seconds = raw_start / 1000 if raw_start >= 100000000000 else raw_start
        market_start = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    return (
        predicted_start is not None
        and abs((market_start - predicted_start).total_seconds()) <= tolerance_seconds
    )


def build_current_snapshots(predictions, fetched_at):
    events_by_sport = {}
    capture_times = {}
    fetch_errors = {}
    for sport in ("football", "tennis"):
        try:
            events_by_sport[sport], _ = fetch_current_events(sport)
            # Stamp after the exact market catalogue has been received, never
            # before the network request begins.
            capture_times[sport] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            events_by_sport[sport] = []
            capture_times[sport] = None
            fetch_errors[sport] = f"{type(exc).__name__}: {exc}"

    candidates = 0
    matched = 0
    snapshots = []
    for original in predictions:
        if not isinstance(original, dict):
            continue
        sport = str(original.get("sport") or "").lower()
        if sport not in EXPECTED_MARKET_ID:
            continue
        if sport == "tennis" and str(original.get("league") or "").upper() != ACTIVE_TENNIS_TOUR:
            continue
        candidates += 1
        event, match_type = sportybet.find_event(original, events_by_sport.get(sport, []))
        if event is None:
            continue
        # The generic tennis matcher allows a broad 72-hour name/time window
        # for discovery. Evidence capture is stricter: a market may only be
        # frozen for the exact scheduled fixture within five minutes.
        if not event_matches_prediction_time(original, event):
            continue
        winner, _totals = sportybet.extract_markets(original, event)
        if not winner:
            continue
        # Build a local copy. The live prediction feed is left untouched by this
        # capture-only workflow.
        row = dict(original)
        row["sportybet_winner_odds"] = winner
        row["market_source"] = "SportyBet NG"
        row["sportybet_market_snapshot"] = {
            "source": "SportyBet NG",
            "fetched_at": fetched_at,
            "match_type": match_type,
            "sportybet_event_id": event.get("eventId"),
        }
        captured_at = capture_times.get(sport)
        if not captured_at:
            continue
        row["sportybet_market_snapshot"]["fetched_at"] = captured_at
        snapshot = exact_snapshot_from_prediction(row, captured_at)
        if snapshot is not None:
            snapshots.append(snapshot)
            matched += 1

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "capture_times_by_sport": capture_times,
        "candidates_seen": candidates,
        "pregame_snapshots": snapshots,
        "pregame_snapshot_count": matched,
        "sportybet_fetch_errors": fetch_errors,
    }


def append_snapshots(ledger, snapshots):
    if not isinstance(ledger, dict):
        ledger = {"version": 1, "snapshots": []}
    rows = ledger.get("snapshots")
    if not isinstance(rows, list):
        rows = []
    existing = {
        (str(row.get("event_id")), str(row.get("market_id")), str(row.get("captured_at")))
        for row in rows if isinstance(row, dict)
    }
    added = 0
    for snapshot in snapshots:
        key = (
            str(snapshot.get("event_id")),
            str(snapshot.get("market_id")),
            str(snapshot.get("captured_at")),
        )
        if key in existing:
            continue
        rows.append(snapshot)
        existing.add(key)
        added += 1

    rows.sort(key=lambda row: (str(row.get("captured_at") or ""), str(row.get("event_id") or "")))
    if len(rows) > MAX_LEDGER_ROWS:
        rows = rows[-MAX_LEDGER_ROWS:]
    ledger["version"] = 1
    ledger["policy"] = (
        "Append-only SportyBet NG exact winner snapshots; football market 1, "
        "ATP market 186; captured 0..15 minutes before kickoff only. "
        "Snapshots are joined to settled outcomes after the event and never "
        "pooled across sports or tennis tours."
    )
    ledger["snapshots"] = rows
    return ledger, added


def main():
    predictions = load_json(PREDICTIONS_PATH, [])
    if not isinstance(predictions, list):
        predictions = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    result = build_current_snapshots(predictions, fetched_at)

    ledger_existed = LEDGER_PATH.exists()
    ledger = load_json(LEDGER_PATH, {"version": 1, "snapshots": []})
    ledger, added = append_snapshots(ledger, result["pregame_snapshots"])
    if added or not ledger_existed:
        ledger["updated_at"] = result["fetched_at"]
        LEDGER_PATH.write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "status": "ok" if not result["sportybet_fetch_errors"] else "partial",
        "fetched_at": fetched_at,
        "prediction_candidates_seen": result["candidates_seen"],
        "fresh_pregame_snapshots": result["pregame_snapshot_count"],
        "new_immutable_snapshots": added,
        "fetch_errors": result["sportybet_fetch_errors"],
    }, indent=2))


if __name__ == "__main__":
    main()
