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
    sportybet_event_id = str(market.get("sportybet_event_id") or "").strip()
    quote_capture_basis = str(market.get("quote_capture_basis") or "").strip()

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
    if not sportybet_event_id:
        reasons.append("missing_exact_sportybet_event_id")
    if quote_capture_basis != "SportyBet API response observed_at":
        reasons.append("missing_sportybet_observed_at_provenance")

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
        "sportybet_event_id": sportybet_event_id,
        "quote_capture_basis": quote_capture_basis,
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
    model_version = str(prediction.get("totals_model_version") or "legacy")
    snapshot_id = str(prediction.get("publication_snapshot_id") or "mutable")
    ledger_identity = ":".join((str(event["id"]), model_version, snapshot_id))
    return {
        "ledger_id": "nba-total:" + ledger_identity,
        "sport": "basketball", "league": "NBA", "event_id": str(event["id"]),
        "start_time": prediction["start_time"], "published_at": prediction.get("published_at"),
        "publication_snapshot_id": prediction.get("publication_snapshot_id"),
        "publication_snapshot_verified": prediction.get("publication_snapshot_verified") is True,
        "publication_snapshot_kind": prediction.get("publication_snapshot_kind"),
        "player_1": prediction.get("player_1"),
        "player_2": prediction.get("player_2"), "prediction_created_at": pred_time.isoformat(),
        "model": prediction.get("model"), "totals_model_version": prediction.get("totals_model_version"), "expected_total": prediction.get("expected_total"),
        "market_id": "225", "market_source": market.get("source"),
        "sportybet_event_id": market.get("sportybet_event_id"),
        "quote_capture_basis": market.get("quote_capture_basis"),
        "quote_timestamp": market.get("quote_timestamp"), "line": line, "pick": pick,
        **price_audit,
        "final_score": [int(hs) if hs.is_integer() else hs, int(aws) if aws.is_integer() else aws],
        "final_total": total, "result": outcome,
        "settled": True, "settled_at": datetime.now(timezone.utc).isoformat(),
        "settlement_source": "ESPN official scoreboard event ID; final score includes overtime",
        "paper_only": True,
    }

def candidate_key(row):
    """One independent settlement cohort per event and totals-model version."""
    return (
        str(row.get("event_id") or ""),
        str(row.get("totals_model_version") or "legacy"),
    )


def ledger_key(row):
    return (
        str(row.get("event_id") or ""),
        str(row.get("totals_model_version") or "legacy"),
    )


def main():
    predictions = load(PREDICTIONS, [])
    snapshots = load(SNAPSHOTS, [])
    if not isinstance(predictions, list):
        predictions = []
    if not isinstance(snapshots, list):
        snapshots = []

    # A new model version starts its own immutable cohort for the same fixture.
    candidates_by_key = {}
    predictions_by_key = {}
    for prediction in predictions:
        if not prediction.get("event_id"):
            continue
        key = candidate_key(prediction)
        predictions_by_key[key] = prediction
        candidates_by_key[key] = prediction
    snapshots_by_key = {}
    for snapshot in sorted(
        snapshots,
        key=lambda row: (
            str(row.get("published_at") or ""),
            str(row.get("event_id") or ""),
            str(row.get("totals_model_version") or "legacy"),
        ),
    ):
        if not isinstance(snapshot, dict) or not snapshot.get("event_id"):
            continue
        key = candidate_key(snapshot)
        snapshots_by_key.setdefault(key, snapshot)
        # Frozen publication evidence always wins over a mutable prediction row.
        candidates_by_key[key] = snapshots_by_key[key]
    candidates = list(candidates_by_key.values())

    old = load(LEDGER, {"records": []})
    records = old.get("records", []) if isinstance(old, dict) else []
    by_key = {ledger_key(row): row for row in records if row.get("event_id")}

    # Add price audit metadata only to legacy rows which predate audit columns.
    # Settled outcomes are never overwritten and never borrow another model's quote.
    for key, row in list(by_key.items()):
        if "roi_eligible" in row:
            continue
        event_id, row_version = key
        matching = [
            snapshot for snapshot_key, snapshot in snapshots_by_key.items()
            if snapshot_key[0] == event_id and
            (row_version == "legacy" or snapshot_key[1] == row_version)
        ]
        prediction = matching[0] if matching else predictions_by_key.get(key)
        market = ((prediction or {}).get("markets") or {}).get("total_ou") or {}
        try:
            line_matches = float(row.get("line")) == float(market.get("line"))
        except (TypeError, ValueError):
            line_matches = False
        if prediction and row.get("pick") == market.get("pick") and line_matches:
            audit = price_audit_fields(
                prediction, market,
                parse_time(prediction.get("published_at") or prediction.get("prediction_created_at")
                           or prediction.get("generated_at"))
            )
            is_snapshot = bool(
                prediction.get("publication_snapshot_verified") is True
                and prediction.get("publication_snapshot_id")
                and prediction.get("published_at")
            )
            audit["publication_snapshot_verified"] = is_snapshot
            audit["roi_eligible"] = bool(audit["roi_eligible"] and is_snapshot)
            audit["price_audit_backfilled"] = True
            if not is_snapshot:
                audit["roi_ineligibility_reasons"] = sorted(set(
                    audit["roi_ineligibility_reasons"]
                    + ["backfilled_from_current_prediction_not_frozen_snapshot"]
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

    dates = set()
    for prediction in candidates:
        stamp = parse_time(prediction.get("start_time"))
        if stamp:
            dates.add(stamp.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d"))
    added = 0
    for day in sorted(dates):
        try:
            response = SESSION.get(BASE + "/scoreboard", params={"dates": day}, timeout=20)
            response.raise_for_status()
            events = response.json().get("events") or []
        except (requests.RequestException, ValueError) as exc:
            print("Scoreboard fetch failed for", day, ":", str(exc)[:180])
            continue
        event_by_id = {str(event.get("id")): event for event in events if event.get("id")}
        for prediction in candidates:
            event_id = str(prediction.get("event_id") or "")
            key = candidate_key(prediction)
            event = event_by_id.get(event_id)
            if not event or key in by_key:
                continue
            row = result_for(prediction, event)
            if row:
                by_key[key] = row
                added += 1

    records = sorted(
        by_key.values(),
        key=lambda row: (
            str(row.get("start_time") or ""),
            str(row.get("event_id") or ""),
            str(row.get("totals_model_version") or "legacy"),
        ),
    )
    decided = [row for row in records if row.get("result") in ("over", "under")]
    wins = sum(row.get("pick") == row.get("result") for row in decided)
    roi_decided = [
        row for row in decided
        if row.get("roi_eligible") is True
        and isinstance(row.get("over_odds"), (int, float))
        and isinstance(row.get("under_odds"), (int, float))
    ]
    roi_wins = sum(row.get("pick") == row.get("result") for row in roi_decided)
    roi_profit = sum(
        (float(row["over_odds"] if row.get("pick") == "over" else row["under_odds"]) - 1)
        if row.get("pick") == row.get("result") else -1
        for row in roi_decided
    )
    by_model_version = {}
    for row in records:
        version = str(row.get("totals_model_version") or "legacy")
        stats = by_model_version.setdefault(
            version, {"settled": 0, "decided": 0, "correct": 0, "over": 0, "under": 0}
        )
        stats["settled"] += 1
        if row.get("result") in ("over", "under"):
            stats["decided"] += 1
            stats["correct"] += int(row.get("pick") == row.get("result"))
            if row.get("pick") in ("over", "under"):
                stats[row["pick"]] += 1
    for stats in by_model_version.values():
        stats["accuracy"] = stats["correct"] / stats["decided"] if stats["decided"] else None

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN public NBA scoreboard",
        "market_definition": "SportyBet market 225 full-game totals, overtime included",
        "paper_only": True,
        "settlement_rules": [
            "Exact ESPN event ID only",
            "Pregame publication timestamp required",
            "Market ID 225 and saved Over/Under line/pick required",
            "Final official score includes overtime",
            "Pushes excluded from accuracy",
            "Existing model-version settlement outcomes are never overwritten",
            "Each event/model-version cohort is settled independently",
            "ROI requires a verified immutable publication snapshot, fresh quote and both valid prices",
        ],
        "summary": {
            "settled": len(records), "decided": len(decided), "correct": wins,
            "accuracy": wins / len(decided) if decided else None,
            "pushes": sum(row.get("result") == "push" for row in records),
            "over_settled": sum(row.get("pick") == "over" for row in decided),
            "under_settled": sum(row.get("pick") == "under" for row in decided),
            "roi_eligible_decided": len(roi_decided),
            "roi_eligible_correct": roi_wins,
            "roi_eligible_accuracy": roi_wins / len(roi_decided) if roi_decided else None,
            "roi_eligible_unit_profit": round(roi_profit, 4) if roi_decided else None,
            "roi_eligible_roi": round(roi_profit / len(roi_decided), 4) if roi_decided else None,
            "by_model_version": by_model_version,
            "roi_basis": "Flat 1-unit stake at the saved selected-side SportyBet decimal price; pushes excluded; only verified publication snapshots count",
        },
        "records": records,
    }
    LEDGER.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"new_settlements": added, **payload["summary"], "updated_at": payload["updated_at"]}))


if __name__ == "__main__":
    main()
