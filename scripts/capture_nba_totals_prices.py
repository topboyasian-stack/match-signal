#!/usr/bin/env python3
"""Capture and freeze fresh SportyBet market-225 NBA total prices.

This small scheduled task refreshes only quotes for already-published V5 NBA
predictions. It never rebuilds the model, changes probabilities, or invents a
line when SportyBet does not expose the exact fixture and both prices.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from expansion_pipeline import NBA_TOTALS_MODEL_VERSION
from live_expansion_pipeline import (
    DATA,
    append_nba_totals_publication_snapshots,
    dt,
    S,
    sportybet_total_for_fixture,
    nba_team_key,
)
from nba_totals_walk_forward import evaluate as evaluate_nba_totals

PREDICTIONS = DATA / "nba_predictions.json"
SNAPSHOTS = DATA / "nba_totals_publication_snapshots.json"
LEDGER = DATA / "nba_totals_ledger.json"
HISTORY = DATA / "nba_history.json"
REPORT = DATA / "nba_totals_oos_value_test.json"
STATUS = DATA / "nba_totals_price_capture_status.json"


def sportybet_basketball_feed_paged(max_pages=5):
    """Read up to five seven-day SportyBet pages and merge events without duplicates."""
    url = "https://match-signal.pages.dev/api/sportybet-basketball"
    events_by_id = {}
    page_errors = []
    for page in range(1, max(1, int(max_pages)) + 1):
        try:
            response = S.get(
                url,
                params={"pageSize": 100, "timeline": 168, "pageNum": page},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok") is not True:
                raise RuntimeError(payload.get("error") or "SportyBet source did not return ok=true")
            page_events = payload.get("events")
            if not isinstance(page_events, list):
                raise RuntimeError("SportyBet page omitted its events array")
        except Exception as exc:
            page_errors.append(f"page {page}: {exc}")
            if page == 1:
                return [], "SportyBet feed unavailable: " + "; ".join(page_errors)
            break

        new_ids = 0
        for event in page_events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or event.get("id") or "")
            if not event_id:
                continue
            current = events_by_id.get(event_id)
            if current is None:
                current = dict(event)
                current["markets"] = []
                events_by_id[event_id] = current
                new_ids += 1
            else:
                old_fetch = dt(current.get("fetched_at"))
                new_fetch = dt(event.get("fetched_at"))
                if new_fetch and (not old_fetch or new_fetch >= old_fetch):
                    for key, value in event.items():
                        if key != "markets":
                            current[key] = value
            market_map = {
                (str(m.get("id") or ""), str(m.get("specifier") or "")): m
                for m in (current.get("markets") or [])
                if isinstance(m, dict)
            }
            for market in event.get("markets") or []:
                if isinstance(market, dict):
                    key = (str(market.get("id") or ""), str(market.get("specifier") or ""))
                    market_map[key] = market
            current["markets"] = list(market_map.values())

        # A short page is the provider's end marker. If pageNum is ignored or
        # returns a repeated page, stop instead of wasting more feed requests.
        if len(page_events) < 100 or new_ids == 0:
            break

    if not events_by_id:
        detail = "; ".join(page_errors) if page_errors else "SportyBet source returned zero upcoming basketball events"
        return [], detail
    error = "; ".join(page_errors) if page_errors else None
    return list(events_by_id.values()), error



def diagnose_fixture_quote(fixture, feed, now):
    """Explain why an upcoming NBA fixture has no fresh exact market-225 pair."""
    fixture_home = nba_team_key(fixture.get("home"))
    fixture_away = nba_team_key(fixture.get("away"))
    fixture_start = dt(fixture.get("date"))
    if not fixture_home or not fixture_away or not fixture_start:
        return "INVALID_FIXTURE_IDENTITY"
    named = []
    for event in feed or []:
        event_home = nba_team_key(event.get("home"))
        event_away = nba_team_key(event.get("away"))
        if (
            fixture_home == event_home and fixture_away == event_away
        ) or (
            fixture_home == event_away and fixture_away == event_home
        ):
            named.append(event)
    if not named:
        return "NO_EXACT_TEAM_EVENT_IN_FEED"
    timed = [
        event for event in named
        if dt(event.get("start_time")) is not None
        and abs((dt(event.get("start_time")) - fixture_start).total_seconds()) <= 45 * 60
    ]
    if not timed:
        return "SPORTYBET_START_TIME_MISMATCH_OVER_45_MIN"
    fresh = [
        event for event in timed
        if dt(event.get("fetched_at")) is not None
        and -120 <= (now - dt(event.get("fetched_at"))).total_seconds() <= 15 * 60
    ]
    if not fresh:
        return "SPORTYBET_EVENT_QUOTE_STALE_OR_TIMESTAMP_MISSING"
    market_events = [
        event for event in fresh
        if any(str(market.get("id")) == "225" for market in (event.get("markets") or []))
    ]
    if not market_events:
        return "MARKET_225_NOT_OFFERED_FOR_MATCHED_FIXTURE"
    # Reuse the production matcher so diagnostics validate line, market status and both active prices.
    if sportybet_total_for_fixture(fixture, fresh, expected_total=fixture.get("expected_total")):
        return "MATCHED"
    return "MARKET_225_LINE_OR_BOTH_PRICES_UNUSABLE"


def load_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, json.JSONDecodeError):
        return default


def attach_fresh_quote(prediction, quote, now):
    """Attach a strictly fresh market-225 pair; preserve older evidence unchanged."""
    if not isinstance(prediction, dict) or not isinstance(quote, dict):
        return False
    if prediction.get("totals_model_version") != NBA_TOTALS_MODEL_VERSION:
        return False
    start = dt(prediction.get("start_time"))
    quote_time = dt(quote.get("quote_timestamp"))
    if not start or now >= start or not quote_time:
        return False
    age = (now - quote_time).total_seconds()
    if age < -120 or age > 15 * 60 or quote_time >= start:
        return False
    if str(quote.get("market_id") or "") != "225":
        return False
    if str(quote.get("source") or "").strip().lower() != "sportybet nigeria":
        return False
    if not str(quote.get("sportybet_event_id") or "").strip():
        return False
    if quote.get("quote_capture_basis") != "SportyBet API response observed_at":
        return False
    try:
        line = float(quote.get("line"))
        over_odds = float(quote.get("over_odds"))
        under_odds = float(quote.get("under_odds"))
        expected = float(prediction.get("expected_total"))
    except (TypeError, ValueError):
        return False
    import math
    if not (100 <= line <= 300 and all(math.isfinite(x) and x > 1 for x in (over_odds, under_odds))):
        return False
    previous_market = ((prediction.get("markets") or {}).get("total_ou") or {})
    previous_time = dt(previous_market.get("quote_timestamp"))
    if previous_time and previous_time >= quote_time:
        return False

    edge = expected - line
    pick = "over" if edge >= 3.0 else "under" if edge <= -3.0 else None
    market = dict(quote)
    market.update({
        "expected_total": expected,
        "projection_edge_points": round(edge, 2),
        "lean": "OVER" if pick == "over" else "UNDER" if pick == "under" else "NO_CLEAR_LEAN",
        "pick": pick,
        "prediction_status": "LIVE_EXPERIMENTAL_NOT_QUALIFIED",
        "model_is_market_blind": True,
    })
    prediction.setdefault("markets", {})["total_ou"] = market
    quality = prediction.get("signal_quality") if isinstance(prediction.get("signal_quality"), dict) else {}
    quality["total_market_available"] = True
    quality["total_market_source"] = "SportyBet Nigeria market 225 (Over/Under incl. overtime)"
    prediction["signal_quality"] = quality
    return True


def capture(predictions, feed, now):
    stats = {
        "model_predictions_checked": 0,
        "upcoming_v5_predictions": 0,
        "exact_fresh_market_matches": 0,
        "prediction_price_updates": 0,
        "started_or_finished_skipped": 0,
        "fresh_price_snapshots_considered": 0,
        "price_match_status_counts": {},
        "unmatched_fixtures": [],
    }
    snapshot_candidates = []
    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue
        if prediction.get("totals_model_version") != NBA_TOTALS_MODEL_VERSION:
            continue
        stats["model_predictions_checked"] += 1
        start = dt(prediction.get("start_time"))
        if not start or start <= now:
            stats["started_or_finished_skipped"] += 1
            continue
        stats["upcoming_v5_predictions"] += 1
        fixture = {
            "home": prediction.get("player_1"),
            "away": prediction.get("player_2"),
            "date": prediction.get("start_time"),
        }
        quote = sportybet_total_for_fixture(
            fixture, feed, expected_total=prediction.get("expected_total")
        )
        if quote:
            stats["exact_fresh_market_matches"] += 1
            reason = "MATCHED"
            if attach_fresh_quote(prediction, quote, now):
                stats["prediction_price_updates"] += 1
        else:
            reason = diagnose_fixture_quote(fixture, feed, now)
            stats["unmatched_fixtures"].append({
                "event_id": str(prediction.get("event_id") or ""),
                "home": fixture["home"], "away": fixture["away"],
                "start_time": fixture["date"], "reason": reason,
            })
        stats["price_match_status_counts"][reason] = stats["price_match_status_counts"].get(reason, 0) + 1
        market = ((prediction.get("markets") or {}).get("total_ou") or {})
        quote_time = dt(market.get("quote_timestamp"))
        if (
            str(market.get("market_id") or "") == "225"
            and str(market.get("source") or "").strip().lower() == "sportybet nigeria"
            and market.get("quote_capture_basis") == "SportyBet API response observed_at"
            and quote_time is not None
            and 0 <= (now - quote_time).total_seconds() <= 15 * 60
            and quote_time < start
            and str(market.get("sportybet_event_id") or "").strip()
        ):
            stats["fresh_price_snapshots_considered"] += 1
            snapshot_candidates.append(prediction)
    return snapshot_candidates, stats


def capture_timestamp(feed, observed_at=None):
    """Use the post-response clock, bounded by the feed's own capture timestamp."""
    now = observed_at or datetime.now(timezone.utc)
    feed_stamps = [
        dt(event.get("fetched_at"))
        for event in (feed or [])
        if isinstance(event, dict) and dt(event.get("fetched_at")) is not None
    ]
    if feed_stamps:
        latest = max(feed_stamps)
        # The proxy stamps events just before returning its response. When its
        # clock is a few seconds ahead of the runner, the received feed is still
        # demonstrably in-hand before the immutable publication is appended.
        if now < latest <= now + timedelta(minutes=2):
            now = latest
    return now


def main():
    predictions = load_json(PREDICTIONS, [])
    snapshots = load_json(SNAPSHOTS, [])
    ledger_payload = load_json(LEDGER, {})
    history = load_json(HISTORY, [])
    ledger = ledger_payload.get("records", []) if isinstance(ledger_payload, dict) else ledger_payload
    if not isinstance(predictions, list):
        predictions = []
    if not isinstance(snapshots, list):
        snapshots = []
    if not isinstance(ledger, list):
        ledger = []
    if not isinstance(history, list):
        history = []

    feed, feed_error = sportybet_basketball_feed_paged()
    now = capture_timestamp(feed, datetime.now(timezone.utc))
    snapshot_candidates, stats = capture(predictions, feed, now)
    before_count = len(snapshots)
    snapshot_status = append_nba_totals_publication_snapshots(
        snapshot_candidates, SNAPSHOTS, published_at=now.isoformat()
    )
    after_snapshots = load_json(SNAPSHOTS, [])
    report = evaluate_nba_totals(
        history, ledger, after_snapshots if isinstance(after_snapshots, list) else [],
        predictions, as_of=now.isoformat()
    )

    PREDICTIONS.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status = {
        "checked_at": now.isoformat(),
        "paper_only": True,
        "model_version": NBA_TOTALS_MODEL_VERSION,
        "source": "SportyBet Nigeria public NBA feed via Match Signal regional proxy",
        "feed_error": feed_error,
        "feed_events": len(feed),
        "feed_events_with_market_225": sum(
            any(str(m.get("id")) == "225" for m in (event.get("markets") or []))
            for event in feed
        ),
        **stats,
        "immutable_snapshot_count_before": before_count,
        "immutable_snapshot_count_after": snapshot_status.get("total", 0),
        "immutable_snapshots_added": snapshot_status.get("added", 0),
        "publication_capture": report.get("publication_capture"),
        "release_decision": report.get("release_decision"),
        "note": (
            "Missing market-225 events are left unpriced. Per-fixture diagnostics distinguish "
            "unopened bookmaker markets from identity/time mismatch or an unusable price pair. "
            "No substitute bookmaker, old quote, synthetic price, or reconstructed line is inserted."
        ),
    }
    STATUS.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
