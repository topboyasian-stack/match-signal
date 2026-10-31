#!/usr/bin/env python3
"""Idempotently settle only timestamped NBA full-game totals from exact ESPN event IDs."""
import json
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "nba_predictions.json"
SNAPSHOTS = ROOT / "data" / "nba_totals_publication_snapshots.json"
LEDGER = ROOT / "data" / "nba_totals_ledger.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignalResearch/1.0 (paper-only NBA totals ledger)"})

def load(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def price_audit_fields(prediction, market, pred_time):
    """Preserve price evidence and explicitly flag whether it is ROI-grade."""
    quote_time = parse_time(market.get("quote_timestamp"))
    published_time = parse_time(prediction.get("published_at"))
    publication_basis = "published_at" if published_time else "prediction_created_at_proxy"
    reference_time = published_time or pred_time

    def positive_decimal(value):
        try:
            value = float(value)
            return value if math.isfinite(value) and value > 1.0 else None
        except (TypeError, ValueError):
            return None

    over_odds = positive_decimal(market.get("over_odds"))
    under_odds = positive_decimal(market.get("under_odds"))
    age_at_reference = (
        (reference_time - quote_time).total_seconds() / 60
        if reference_time and quote_time else None
    )
    age_at_start = None
    start_time = parse_time(prediction.get("start_time"))
    if start_time and quote_time:
        age_at_start = (start_time - quote_time).total_seconds() / 60

    fresh_at_reference = (
        age_at_reference is not None and 0 <= age_at_reference <= 15
    )
    price_pair_valid = over_odds is not None and under_odds is not None
    explicit_snapshot = bool(
        published_time
        and prediction.get("publication_snapshot_id")
        and prediction.get("publication_snapshot_verified") is True
    )
    source = str(market.get("source") or "").strip().lower()
    source_verified = source == "sportybet nigeria"

    reasons = []
    if not explicit_snapshot:
        reasons.append("no_verified_immutable_publication_snapshot")
    if not quote_time:
        reasons.append("missing_quote_timestamp")
    elif age_at_reference is None or age_at_reference < 0:
        reasons.append("quote_not_proven_available_at_publication")
    elif age_at_reference > 15:
        reasons.append("quote_older_than_15_minutes_at_publication")
    if not price_pair_valid:
        reasons.append("missing_or_invalid_over_under_decimal_prices")
    if not source_verified:
        reasons.append("bookmaker_source_not_verified_as_sportybet_nigeria")

    return {
        "over_odds": over_odds,
        "under_odds": under_odds,
        "quote_age_minutes_at_publication": round(age_at_reference, 3) if age_at_reference is not None else None,
        "quote_age_minutes_at_start": round(age_at_start, 3) if age_at_start is not None else None,
        "quote_fresh_at_publication": fresh_at_reference,
        "price_pair_valid": price_pair_valid,
        "publication_time_basis": publication_basis,
        "publication_snapshot_verified": explicit_snapshot,
        "price_source_verified": source_verified,
        "roi_eligible": not reasons,
        "roi_ineligibility_reasons": reasons,
    }


def result_for(prediction, event):
    """Return a settlement record only when exact identity and pregame evidence pass."""
    if str(prediction.get("event_id") or "") != str(event.get("id") or ""):
        return None
    status = (event.get("status") or {}).get("type") or {}
    if not (status.get("completed") or status.get("state") == "post"):
        return None
    pred_time = parse_time(prediction.get("published_at") or prediction.get("prediction_created_at") or prediction.get("generated_at"))
    start_time = parse_time(prediction.get("start_time"))
    if not pred_time or not start_time or pred_time >= start_time:
        return None
    market = ((prediction.get("markets") or {}).get("total_ou") or {})
    if str(market.get("market_id") or "") != "225":
        return None
    line = market.get("line")
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    if not 100 <= line <= 300:
        return None
    pick = str(market.get("pick") or "").lower()
    if pick not in ("over", "under"):
        return None
    comp = (event.get("competitions") or [{}])[0]
    teams = comp.get("competitors") or []
    home = next((x for x in teams if x.get("homeAway") == "home"), None)
    away = next((x for x in teams if x.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    try:
        hs, aws = float(home["score"]), float(away["score"])
    except (KeyError, TypeError, ValueError):
        return None
    if hs < 0 or aws < 0:
        return None
    total = hs + aws
    outcome = "over" if total > line else "under" if total < line else "push"
    price_audit = price_audit_fields(prediction, market, pred_time)
    return {
        "ledger_id": "nba-total:" + str(event["id"]),
        "sport": "basketball", "league": "NBA", "event_id": str(event["id"]),
        "start_time": prediction["start_time"], "published_at": prediction.get("published_at"),
        "publication_snapshot_id": prediction.get("publication_snapshot_id"),
        "publication_snapshot_verified": prediction.get("publication_snapshot_verified") is True,
        "publication_snapshot_kind": prediction.get("publication_snapshot_kind"),
        "player_1": prediction.get("player_1"),
        "player_2": prediction.get("player_2"), "prediction_created_at": pred_time.isoformat(),
        "model": prediction.get("model"), "totals_model_version": prediction.get("totals_model_version"), "expected_total": prediction.get("expected_total"),
        "market_id": "225", "market_source": market.get("source"),
        "quote_timestamp": market.get("quote_timestamp"), "line": line, "pick": pick,
        **price_audit,
        "final_score": [int(hs) if hs.is_integer() else hs, int(aws) if aws.is_integer() else aws],
        "final_total": total, "result": outcome,
        "settled": True, "settled_at": datetime.now(timezone.utc).isoformat(),
        "settlement_source": "ESPN official scoreboard event ID; final score includes overtime",
        "paper_only": True,
    }

def main():
    predictions = load(PREDICTIONS, [])
    snapshots = load(SNAPSHOTS, [])
    if not isinstance(predictions, list):
        predictions = []
    if not isinstance(snapshots, list):
        snapshots = []
    # The frozen publication record takes precedence over the mutable current desk row.
    candidates_by_id = {str(p.get("event_id")): p for p in predictions if p.get("event_id")}
    snapshots_by_id = {}
    for snapshot in sorted(snapshots, key=lambda row: str(row.get("published_at") or "") if isinstance(row, dict) else ""):
        if isinstance(snapshot, dict) and snapshot.get("event_id"):
            snapshots_by_id.setdefault(str(snapshot["event_id"]), snapshot)
    candidates_by_id.update(snapshots_by_id)
    candidates = list(candidates_by_id.values())
    old = load(LEDGER, {"records": []})
    records = old.get("records", []) if isinstance(old, dict) else []
    by_id = {str(r.get("event_id")): r for r in records if r.get("event_id")}
    # Add price-audit metadata to legacy rows without changing their settled outcome.
    # A frozen snapshot is preferred; a mutable current row is explicitly unverified.
    predictions_by_id = {str(p.get("event_id")): p for p in predictions if p.get("event_id")}
    for eid, row in by_id.items():
        if "roi_eligible" in row:
            continue
        prediction = snapshots_by_id.get(eid) or predictions_by_id.get(eid)
        market = ((prediction or {}).get("markets") or {}).get("total_ou") or {}
        try:
            row_line_matches = float(row.get("line")) == float(market.get("line"))
        except (TypeError, ValueError):
            row_line_matches = False
        if prediction and row.get("pick") == market.get("pick") and row_line_matches:
            audit = price_audit_fields(
                prediction, market,
                parse_time(prediction.get("prediction_created_at") or prediction.get("generated_at") or prediction.get("published_at"))
            )
            is_frozen_snapshot = bool(
                prediction.get("publication_snapshot_verified") is True
                and prediction.get("publication_snapshot_id")
                and prediction.get("published_at")
            )
            audit["publication_snapshot_verified"] = is_frozen_snapshot
            audit["roi_eligible"] = bool(audit["roi_eligible"] and is_frozen_snapshot)
            audit["price_audit_backfilled"] = True
            if not is_frozen_snapshot:
                audit["roi_ineligibility_reasons"] = sorted(set(
                    audit["roi_ineligibility_reasons"] + ["backfilled_from_current_prediction_not_frozen_snapshot"]
                ))
            row.update(audit)
        else:
            row.update({
                "over_odds": None, "under_odds": None,
                "quote_age_minutes_at_publication": None, "quote_age_minutes_at_start": None,
                "quote_fresh_at_publication": False, "price_pair_valid": False,
                "publication_time_basis": "unavailable_for_legacy_record",
                "publication_snapshot_verified": False, "price_source_verified": False,
                "roi_eligible": False, "price_audit_backfilled": True,
                "roi_ineligibility_reasons": ["no_matching_prediction_snapshot_for_legacy_record"],
            })
    # Reconcile every prediction date, including recently completed games missed by a prior run.
    dates = set()
    for p in candidates:
        dt = parse_time(p.get("start_time"))
        if dt:
            dates.add(dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
    added = 0
    for day in sorted(dates):
        try:
            response = SESSION.get(BASE + "/scoreboard", params={"dates": day}, timeout=20)
            response.raise_for_status()
            events = response.json().get("events") or []
        except (requests.RequestException, ValueError) as exc:
            print("Scoreboard fetch failed for", day, ":", str(exc)[:180])
            continue
        event_by_id = {str(e.get("id")): e for e in events if e.get("id")}
        for p in candidates:
            eid = str(p.get("event_id") or "")
            event = event_by_id.get(eid)
            if not event or eid in by_id:
                continue
            row = result_for(p, event)
            if row:
                by_id[eid] = row
                added += 1
    records = sorted(by_id.values(), key=lambda x: x.get("start_time", ""))
    decided = [r for r in records if r.get("result") in ("over", "under")]
    wins = sum(r.get("pick") == r.get("result") for r in decided)
    roi_decided = [
        r for r in decided
        if r.get("roi_eligible") is True
        and isinstance(r.get("over_odds"), (int, float))
        and isinstance(r.get("under_odds"), (int, float))
    ]
    roi_wins = sum(r.get("pick") == r.get("result") for r in roi_decided)
    roi_profit = sum(
        (float(r["over_odds"] if r.get("pick") == "over" else r["under_odds"]) - 1)
        if r.get("pick") == r.get("result") else -1
        for r in roi_decided
    )
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN public NBA scoreboard",
        "market_definition": "SportyBet market 225 full-game totals, overtime included",
        "paper_only": True,
        "settlement_rules": ["Exact ESPN event ID only", "Pre-game prediction timestamp required",
                             "Market ID 225 and saved Over/Under line/pick required",
                             "Final official score includes overtime", "Pushes excluded from accuracy",
                             "Existing settlement outcomes are never overwritten",
                             "ROI requires a verified immutable publication snapshot, fresh quote and both valid prices"],
        "summary": {"settled": len(records), "decided": len(decided), "correct": wins,
                    "accuracy": wins / len(decided) if decided else None,
                    "pushes": sum(r.get("result") == "push" for r in records),
                    "over_settled": sum(r.get("pick") == "over" for r in decided),
                    "under_settled": sum(r.get("pick") == "under" for r in decided),
                    "roi_eligible_decided": len(roi_decided),
                    "roi_eligible_correct": roi_wins,
                    "roi_eligible_accuracy": roi_wins / len(roi_decided) if roi_decided else None,
                    "roi_eligible_unit_profit": round(roi_profit, 4) if roi_decided else None,
                    "roi_eligible_roi": round(roi_profit / len(roi_decided), 4) if roi_decided else None,
                    "roi_basis": "Flat 1-unit stake at the saved selected-side SportyBet decimal price; pushes excluded; only verified publication snapshots count"},
        "records": records,
    }
    LEDGER.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"new_settlements": added, **payload["summary"], "updated_at": payload["updated_at"]}))

if __name__ == "__main__":
    main()
