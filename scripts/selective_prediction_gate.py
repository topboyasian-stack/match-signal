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
    research_candidates = []
    rejected = 0
    reasons = {}
    paper_value_count = 0
    evidence_validated_count = 0

    def explicit_value_signal(row):
        # Football model_upgrade.py already performs the canonical independent
        # edge + EV test (>=3.5% edge and >=5% EV). Do not duplicate or loosen it.
        # Legacy decision flags are not sufficient by themselves. Current
        # qualification must be backed by the finalized contemporaneous market
        # snapshot and the unchanged edge/EV thresholds below.
        # SportyBet-enriched winner/total signals provide the same market-
        # independent edge comparison for Tennis and other feed rows.
        insights = row.get("market_insights") or {}
        winner_edge = insights.get("winner_model_edge_vs_market")
        if isinstance(winner_edge, (int, float)) and float(winner_edge) >= 0.035:
            return True, "sportybet_winner_edge"
        total = row.get("sportybet_total_market") or (insights.get("total") if isinstance(insights, dict) else None) or {}
        total_edge = total.get("model_edge_vs_market") if isinstance(total, dict) else None
        total_ev = total.get("expected_value") if isinstance(total, dict) else None
        if isinstance(total_edge, (int, float)) and float(total_edge) >= 0.035 and isinstance(total_ev, (int, float)) and float(total_ev) >= 0.05:
            return True, "sportybet_total_edge_ev"
        row_edge = row.get("edge")
        row_value = row.get("value") or {}
        row_ev = row_value.get("expected_value") if isinstance(row_value, dict) else None
        snapshot = row.get("sportybet_market_snapshot") or {}
        if isinstance(row_edge, (int, float)) and float(row_edge) >= 0.035 and isinstance(row_ev, (int, float)) and float(row_ev) >= 0.05 and snapshot.get("fetched_at"):
            return True, "sportybet_winner_edge_ev"
        return False, None

    for original in predictions:
        row = dict(original)
        sport = str(row.get("sport") or "").lower()
        tour = tournament(row)
        pick = selection(row)
        conf = row.get("confidence")
        threshold = tennis_min_confidence if sport == "tennis" else DEFAULT_MIN_CONFIDENCE
        qualified_tour_flag = tour in qualified_tour.get(sport, set())
        qualified_selection_flag = (tour, pick) in qualified_pairs.get(sport, set())
        confidence_ok = isinstance(conf, (int, float)) and float(conf) >= threshold
        value_ok, value_source = explicit_value_signal(row)

        # Evidence tier: historical tournament/selection track record increases
        # confidence in a candidate but does not make it a prerequisite.
        if qualified_selection_flag:
            evidence_tier = "VALIDATED_SEGMENT"
            evidence_validated_count += 1
        elif qualified_tour_flag:
            evidence_tier = "VALIDATED_TOURNAMENT"
            evidence_validated_count += 1
        else:
            evidence_tier = "GLOBAL_MODEL_ONLY"

        reasons_list = []
        if not confidence_ok:
            reasons_list.append(f"confidence_below_{threshold:.2f}")

        if confidence_ok:
            research_candidates.append(row)

        if confidence_ok and value_ok:
            row["candidate_status"] = "BETTING_QUALIFIED_PAPER"
            row["live_eligible"] = False
            row["qualification_basis"] = {
                "confidence_ok": True,
                "value_ok": True,
                "value_source": value_source,
                "evidence_tier": evidence_tier,
                "tournament_gate_non_blocking": True,
                "selection_gate_non_blocking": True,
            }
            selected.append(row)
            paper_value_count += 1
        else:
            row["candidate_status"] = "RESEARCH_CANDIDATE" if confidence_ok else "RESEARCH_FILTERED"
            row["live_eligible"] = False
            row["qualification_basis"] = {
                "confidence_ok": confidence_ok,
                "value_ok": value_ok,
                "value_source": value_source,
                "evidence_tier": evidence_tier,
                "tournament_gate_non_blocking": True,
                "selection_gate_non_blocking": True,
                "not_selected_reasons": reasons_list + ([] if value_ok else ["no_current_value_signal"]),
            }
            rejected += 0 if confidence_ok else 1
            if not confidence_ok or not value_ok:
                key = " + ".join(reasons_list + ([] if value_ok else ["no_current_value_signal"]))
                reasons[key] = reasons.get(key, 0) + 1

        row["selection_gate"] = {
            "status": "passed" if row["candidate_status"] == "BETTING_QUALIFIED_PAPER" else ("research" if confidence_ok else "filtered"),
            "sport": sport,
            "tournament": tour,
            "selection": pick,
            "confidence_threshold": threshold,
            "threshold_source": tennis_threshold_source if sport == "tennis" else "default",
            "mode": "PAPER_ONLY",
            "evidence_tier": evidence_tier,
            "tournament_gate_non_blocking": True,
            "selection_gate_non_blocking": True,
            "reasons": reasons_list + ([] if value_ok else ["no_current_value_signal"]),
        }

    PREDICTIONS.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SELECTED.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "status": "ok",
        "mode": "PAPER_ONLY",
        "input_predictions": len(predictions),
        "selected_predictions": len(selected),
        "paper_betting_qualified": paper_value_count,
        "research_candidates": len(research_candidates),
        "filtered_predictions": rejected,
        "selection_rate": round(len(selected) / len(predictions), 4) if predictions else 0.0,
        "rejection_reasons": reasons,
        "evidence_validated_count": evidence_validated_count,
        "public_feed_preserved": True,
        "tennis_confidence_threshold": tennis_min_confidence,
        "tennis_threshold_source": tennis_threshold_source,
        "selected_artifact": "data/selection_candidates.json",
        "policy": "Tournament/selection history is an evidence tier, not a hard prerequisite. Betting-qualified PAPER selections require current model confidence plus an independent current value signal. Live-money approval remains a separate risk gate.",
    }
    (DATA / "selection_gate.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
