"""Maintain a clean, append-only V4 paper ledger and validation metrics.

The ledger is deliberately separate from the legacy prediction_history.json so
old market-heavy predictions cannot contaminate V4 evaluation.

One row represents one sport/league/event/model-version.  While an event is
still upcoming, the latest model/market snapshot is retained.  Once kickoff
has passed, the snapshot is frozen and settlement is copied from the normal
settlement history on a later pipeline run.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEDGER_PATH = DATA / "v4_paper_ledger.json"
REPORT_PATH = DATA / "v4_validation.json"
START_AT = "2026-09-13T00:00:00+00:00"
MODEL_PREFIX = "4.3"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def model_is_v4(row):
    version = str(row.get("model_version") or "")
    return version.startswith(MODEL_PREFIX) and str(row.get("testing_mode") or "").lower() == "paper"


def key_for(row):
    return ":".join([
        str(row.get("sport") or ""),
        str(row.get("league") or ""),
        str(row.get("event_id") or ""),
        str(row.get("model_version") or ""),
    ])


def candidate(row):
    try:
        probs = row.get("calibrated_probabilities") or row.get("probabilities") or {}
        pick = row.get("pick")
        p = float(probs.get(pick))
        edge = float(row.get("edge"))
        ev = float((row.get("value") or {}).get("expected_value"))
        return p >= 0.55 and edge >= 0.035 and ev >= 0.05
    except (TypeError, ValueError):
        return False


def implied_probability(american):
    try:
        odds = float(american)
        decimal = 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)
        return 1 / decimal
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def profit_for_result(row):
    """Flat one-unit paper stake profit using the frozen American price."""
    if row.get("actual") != row.get("pick"):
        return -1.0
    try:
        odds = float(row.get("frozen_odds"))
        return odds / 100.0 if odds > 0 else 100.0 / abs(odds)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def sync_ledger(predictions, history, ledger):
    by_key = {str(row.get("ledger_key")): row for row in ledger if row.get("ledger_key")}
    history_by_event = {}
    for row in history:
        if not model_is_v4(row):
            continue
        history_by_event[(str(row.get("sport")), str(row.get("league")), str(row.get("event_id")))] = row

    for pred in predictions:
        if not model_is_v4(pred) or not pred.get("event_id"):
            continue
        ledger_key = key_for(pred)
        row = by_key.get(ledger_key)
        if row is None:
            row = {
                "ledger_key": ledger_key,
                "prediction_id": f"V4-{str(pred.get('event_id'))}-{str(pred.get('calculated_at') or now_iso()).replace(':', '').replace('.', '')}",
                "first_seen_at": pred.get("calculated_at") or now_iso(),
                "first_snapshot": {},
            }
            by_key[ledger_key] = row
            ledger.append(row)

        current_time = pred.get("calculated_at") or now_iso()
        row["latest_seen_at"] = current_time
        row["sport"] = pred.get("sport")
        row["league"] = pred.get("league")
        row["event_id"] = str(pred.get("event_id"))
        row["start_time"] = pred.get("start_time")
        row["player_1"] = pred.get("player_1")
        row["player_2"] = pred.get("player_2")
        row["model_version"] = pred.get("model_version")
        row["calibration_version"] = pred.get("calibration_version")
        row["architecture"] = pred.get("architecture")
        row["testing_mode"] = "paper"
        row["live_eligible"] = False

        probs = pred.get("calibrated_probabilities") or pred.get("probabilities") or {}
        market = pred.get("market_probabilities") or {}
        odds = pred.get("market_odds")
        pick = pred.get("pick")
        pick_prob = probs.get(pick) if isinstance(probs, dict) else None
        pick_index = {"p1": 0, "draw": 1, "p2": 2}.get(pick)
        pick_odds = odds[pick_index] if isinstance(odds, list) and pick_index is not None and pick_index < len(odds) else None

        snapshot = {
            "calculated_at": current_time,
            "probabilities": probs,
            "independent_probabilities": pred.get("independent_probabilities"),
            "market_probabilities": market,
            "market_odds": odds,
            "pick": pick,
            "pick_probability": pick_prob,
            "edge": pred.get("edge"),
            "expected_value": (pred.get("value") or {}).get("expected_value"),
            "decision": pred.get("decision"),
            "decision_reason": pred.get("decision_reason"),
            "market_source": pred.get("market_source"),
            "market_provider": pred.get("market_provider"),
            "odds_timestamp": pred.get("odds_timestamp"),
            "diagnostics": pred.get("independent_diagnostics"),
        }
        row["latest_snapshot"] = snapshot
        if not row.get("first_snapshot"):
            row["first_snapshot"] = snapshot

        kickoff = parse_dt(pred.get("start_time"))
        if kickoff and datetime.now(timezone.utc) >= kickoff and not row.get("frozen_at"):
            # Freeze the last available pre-kickoff snapshot. This prevents
            # later model/odds changes from rewriting the evaluated forecast.
            row["frozen_at"] = now_iso()
            row["frozen_snapshot"] = snapshot
            row["frozen_pick"] = pick
            row["frozen_probabilities"] = probs
            row["frozen_market_probabilities"] = market
            row["frozen_odds"] = pick_odds
            row["frozen_edge"] = pred.get("edge")
            row["frozen_expected_value"] = (pred.get("value") or {}).get("expected_value")
            row["paper_value_candidate"] = candidate(pred)

    # Copy authoritative settlement fields once the normal settlement workflow
    # has settled the same V4 event in prediction_history.json.
    for row in ledger:
        hist = history_by_event.get((str(row.get("sport")), str(row.get("league")), str(row.get("event_id"))))
        if not hist or not hist.get("settled"):
            continue
        row.update({
            "settled": True,
            "settled_at": hist.get("settled_at"),
            "actual": hist.get("actual"),
            "correct": bool(hist.get("correct")),
            "brier": hist.get("brier"),
            "final_score": hist.get("final_score"),
            "actual_markets": hist.get("actual_markets"),
        })
        if row.get("paper_value_candidate"):
            row["paper_profit_1u"] = profit_for_result(row)
    return ledger


def metrics(ledger):
    settled = [r for r in ledger if r.get("settled") and r.get("frozen_probabilities")]
    metrics = {}
    for sport in ("football", "tennis", "basketball"):
        group = [r for r in settled if r.get("sport") == sport]
        accuracy = sum(bool(r.get("correct")) for r in group) / len(group) if group else None
        brier_values = [float(r["brier"]) for r in group if r.get("brier") is not None]
        candidates = [r for r in group if r.get("paper_value_candidate")]
        profits = [float(r["paper_profit_1u"]) for r in candidates if r.get("paper_profit_1u") is not None]
        stake = len(profits)
        profit = sum(profits)
        roi = profit / stake if stake else None
        wins = sum(1 for r in candidates if r.get("correct"))
        metrics[sport] = {
            "settled": len(group),
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
            "brier": round(sum(brier_values) / len(brier_values), 6) if brier_values else None,
            "value_candidates": len(candidates),
            "value_candidates_won": wins,
            "paper_units_staked": stake,
            "paper_profit_1u": round(profit, 4) if stake else 0.0,
            "paper_roi": round(roi, 4) if roi is not None else None,
        }

    edge_buckets = []
    for low, high in ((0.0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 1.0)):
        group = [r for r in settled if r.get("frozen_edge") is not None and low <= float(r["frozen_edge"]) < high]
        edge_buckets.append({
            "range": f"{low:.0%}-{high:.0%}",
            "settled": len(group),
            "accuracy": round(sum(bool(r.get("correct")) for r in group) / len(group), 4) if group else None,
            "mean_edge": round(sum(float(r["frozen_edge"]) for r in group) / len(group), 4) if group else None,
        })
    return metrics, edge_buckets


def main():
    ledger = load(LEDGER_PATH, [])
    predictions = load(DATA / "predictions.json", [])
    history = load(DATA / "prediction_history.json", [])
    ledger = sync_ledger(predictions, history, ledger)
    ledger.sort(key=lambda r: (str(r.get("start_time") or ""), str(r.get("ledger_key") or "")))
    save(LEDGER_PATH, ledger)

    by_sport, edge_buckets = metrics(ledger)
    report = {
        "generated_at": now_iso(),
        "validation_start": START_AT,
        "model_family": MODEL_PREFIX,
        "mode": "PAPER_ONLY",
        "live_trading_approved": False,
        "ledger_rows": len(ledger),
        "settled_rows": sum(1 for r in ledger if r.get("settled")),
        "pending_rows": sum(1 for r in ledger if not r.get("settled")),
        "metrics": by_sport,
        "edge_buckets": edge_buckets,
        "rules": {
            "one_row_per_event_model_version": True,
            "freeze_at_kickoff": True,
            "flat_stake_units_for_value_roi": 1,
            "value_candidate_min_confidence": 0.55,
            "value_candidate_min_edge": 0.035,
            "value_candidate_min_ev": 0.05,
            "legacy_history_excluded_from_v4_metrics": True,
        },
    }
    save(REPORT_PATH, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
