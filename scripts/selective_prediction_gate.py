#!/usr/bin/env python3
"""Apply research-derived selective candidate gates without hiding predictions.

The full prediction feed remains visible and auditable. The gate produces a
separate selected-candidate artifact; it never replaces data/predictions.json
with an empty subset. PAPER ONLY; live eligibility stays false.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS = DATA / "predictions.json"
POOL = DATA / "prediction_pool.json"
SELECTED = DATA / "selection_candidates.json"
EVAL = DATA / "sports_evaluation.json"
PRECISION = DATA / "tennis_precision_gate.json"
DEFAULT_MIN_CONFIDENCE = 0.65


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def tournament(row):
    return str(row.get("tournament") or row.get("competition") or row.get("league") or "unknown")


def selection(row):
    pick = row.get("pick")
    if pick in {"p1", "p2", "draw"}:
        return str(pick)
    markets = row.get("markets")
    if isinstance(markets, dict):
        for name in ("moneyline", "total_ou", "over_under", "btts", "spread"):
            item = markets.get(name)
            if isinstance(item, dict) and item.get("pick") is not None:
                return f"{name}:{item['pick']}"
    return "unselected"


def tennis_threshold():
    payload = load(PRECISION, {})
    selected = payload.get("selected") if isinstance(payload, dict) else None
    value = selected.get("threshold") if isinstance(selected, dict) else None
    if not isinstance(value, (int, float)):
        return DEFAULT_MIN_CONFIDENCE, "default"
    return max(DEFAULT_MIN_CONFIDENCE, min(0.85, float(value))), "walkforward_precision_gate"


def main():
    predictions = load(PREDICTIONS, [])
    evaluation = load(EVAL, {})
    if not isinstance(predictions, list):
        predictions = []

    POOL.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    qualified_tournaments = evaluation.get("qualified_tournaments", {})
    qualified_selections = evaluation.get("qualified_selections", {})
    qualified_pairs = {sport: {(x.get("tournament"), x.get("selection")) for x in rows} for sport, rows in qualified_selections.items()}
    qualified_tour = {sport: {x.get("tournament") for x in rows} for sport, rows in qualified_tournaments.items()}
    tennis_min_confidence, tennis_threshold_source = tennis_threshold()

    selected = []
    rejected = 0
    reasons = {}
    for original in predictions:
        row = dict(original)
        sport = str(row.get("sport") or "").lower()
        tour = tournament(row)
        pick = selection(row)
        conf = row.get("confidence")
        threshold = tennis_min_confidence if sport == "tennis" else DEFAULT_MIN_CONFIDENCE
        reasons_list = []
        if tour not in qualified_tour.get(sport, set()):
            reasons_list.append("tournament_not_qualified")
        if (tour, pick) not in qualified_pairs.get(sport, set()):
            reasons_list.append("selection_not_qualified")
        if not isinstance(conf, (int, float)) or float(conf) < threshold:
            reasons_list.append(f"confidence_below_{threshold:.2f}")

        row["candidate_status"] = "SELECTED" if not reasons_list else "RESEARCH_FILTERED"
        row["selection_gate"] = {
            "status": "passed" if not reasons_list else "filtered",
            "sport": sport,
            "tournament": tour,
            "selection": pick,
            "confidence_threshold": threshold,
            "threshold_source": tennis_threshold_source if sport == "tennis" else "default",
            "mode": "PAPER_ONLY",
            "reasons": reasons_list,
        }
        row["live_eligible"] = False
        if not reasons_list:
            selected.append(row)
        else:
            rejected += 1
            reason = " + ".join(reasons_list)
            reasons[reason] = reasons.get(reason, 0) + 1

    PREDICTIONS.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SELECTED.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "status": "ok",
        "mode": "PAPER_ONLY",
        "input_predictions": len(predictions),
        "selected_predictions": len(selected),
        "filtered_predictions": rejected,
        "selection_rate": round(len(selected) / len(predictions), 4) if predictions else 0.0,
        "rejection_reasons": reasons,
        "public_feed_preserved": True,
        "tennis_confidence_threshold": tennis_min_confidence,
        "tennis_threshold_source": tennis_threshold_source,
        "selected_artifact": "data/selection_candidates.json",
        "policy": "Selection is an analysis layer; it never deletes raw/current predictions from the public feed.",
    }
    (DATA / "selection_gate.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
