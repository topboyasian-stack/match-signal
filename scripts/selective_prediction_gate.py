#!/usr/bin/env python3
"""Apply the research-derived selective candidate gate.

The full raw prediction pool is preserved in data/prediction_pool.json. The public
prediction feed is reduced to candidates whose tournament and selection segments
have enough settled history, sufficient realized accuracy, and current confidence
>= 0.65. No probabilities are modified. PAPER ONLY; live eligibility stays false.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS = DATA / "predictions.json"
POOL = DATA / "prediction_pool.json"
EVAL = DATA / "sports_evaluation.json"

MIN_CONFIDENCE = 0.65


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


def main():
    predictions = load(PREDICTIONS, [])
    evaluation = load(EVAL, {})
    if not isinstance(predictions, list):
        predictions = []
    POOL.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    qualified_tournaments = evaluation.get("qualified_tournaments", {})
    qualified_selections = evaluation.get("qualified_selections", {})
    qualified_pairs = {
        sport: {(x.get("tournament"), x.get("selection")) for x in rows}
        for sport, rows in qualified_selections.items()
    }
    qualified_tour = {
        sport: {x.get("tournament") for x in rows}
        for sport, rows in qualified_tournaments.items()
    }

    selected = []
    rejected = 0
    reasons = {}
    for row in predictions:
        sport = str(row.get("sport") or "").lower()
        tour = tournament(row)
        pick = selection(row)
        conf = row.get("confidence")
        reasons_list = []
        if tour not in qualified_tour.get(sport, set()):
            reasons_list.append("tournament_not_qualified")
        if (tour, pick) not in qualified_pairs.get(sport, set()):
            reasons_list.append("selection_not_qualified")
        if not isinstance(conf, (int, float)) or float(conf) < MIN_CONFIDENCE:
            reasons_list.append("confidence_below_0.65")

        row = dict(row)
        if not reasons_list:
            row["candidate_status"] = "SELECTED"
            row["selection_gate"] = {
                "status": "passed",
                "sport": sport,
                "tournament": tour,
                "selection": pick,
                "confidence_threshold": MIN_CONFIDENCE,
                "mode": "PAPER_ONLY",
            }
            row["live_eligible"] = False
            selected.append(row)
        else:
            rejected += 1
            reasons[" + ".join(reasons_list)] = reasons.get(" + ".join(reasons_list), 0) + 1

    # The dashboard-facing feed is deliberately the selected subset. The full
    # pool remains available for research/audit and settlement history is kept
    # separately, so filtering does not erase historical observations.
    PREDICTIONS.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "status": "ok",
        "mode": "PAPER_ONLY",
        "input_predictions": len(predictions),
        "selected_predictions": len(selected),
        "filtered_predictions": rejected,
        "selection_rate": round(len(selected) / len(predictions), 4) if predictions else 0.0,
        "rejection_reasons": reasons,
        "policy": "Only tournament+selection segments meeting historical minimums and current confidence >= 0.65 are surfaced. Raw predictions remain in prediction_pool.json.",
    }
    (DATA / "selection_gate.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
