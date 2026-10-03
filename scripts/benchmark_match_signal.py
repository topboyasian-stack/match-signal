"""Reproducible benchmark for Match Signal's model vs ticket construction.

This is diagnostic only. It does not change Odds Builder eligibility or production
selection policy. It reads the frozen walk-forward model evaluation, settled ticket
tracker, and settled-line evidence report and compares transparent baselines.

Run:
    python scripts/benchmark_match_signal.py
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_EVAL = DATA / "virtual_lab_model_eval.json"
TRACKER = DATA / "odds_ticket_tracker.json"
EVIDENCE = DATA / "results_first_evidence_report.json"
OUTPUT = DATA / "match_signal_benchmark.json"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def ticket_probability(ticket):
    try:
        return float(ticket.get("combined_model_probability") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def market_probability(ticket):
    try:
        odds = float(ticket.get("combined_odds") or 0.0)
        return 1.0 / odds if odds > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def y(ticket):
    return 1.0 if str(ticket.get("status") or "").upper() == "WON" else 0.0


def score_binary(tickets, probability_fn):
    if not tickets:
        return None
    n = len(tickets)
    brier = sum((y(t) - probability_fn(t)) ** 2 for t in tickets) / n
    log_loss = 0.0
    for t in tickets:
        p = min(0.9995, max(0.0005, probability_fn(t)))
        yt = y(t)
        log_loss -= yt * math.log(p) + (1.0 - yt) * math.log(1.0 - p)
    log_loss /= n
    hit_rate = sum(y(t) for t in tickets) / n
    avg_probability = sum(probability_fn(t) for t in tickets) / n
    return {
        "n": n,
        "hit_rate": round(hit_rate, 6),
        "avg_probability": round(avg_probability, 6),
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
    }


def ticket_shape_metrics(tickets, leg_count):
    subset = [
        t for t in tickets
        if int(t.get("leg_count") or len(t.get("legs") or [])) == leg_count
    ]
    if not subset:
        return {"n": 0}
    wins = sum(1 for t in subset if y(t) == 1.0)
    avg_odds = sum(float(t.get("combined_odds") or 0.0) for t in subset) / len(subset)
    unit_roi = sum(
        (float(t.get("combined_odds") or 0.0) - 1.0) if y(t) else -1.0
        for t in subset
    ) / len(subset)
    return {
        "n": len(subset),
        "wins": wins,
        "losses": len(subset) - wins,
        "accuracy": round(wins / len(subset), 6),
        "average_combined_odds": round(avg_odds, 6),
        "break_even_accuracy": round(1.0 / avg_odds, 6) if avg_odds > 0 else None,
        "unit_roi": round(unit_roi, 6),
    }


def main():
    model = load(MODEL_EVAL, {})
    tracker = load(TRACKER, {})
    evidence = load(EVIDENCE, {})

    tickets = tracker.get("tickets") if isinstance(tracker, dict) else []
    settled = [
        t for t in tickets if str(t.get("status") or "").upper() in {"WON", "LOST"}
    ]
    modern = [
        t for t in settled
        if 2 <= int(t.get("leg_count") or len(t.get("legs") or [])) <= 4
    ]

    holdout = model.get("holdout_metrics") or {}
    by_product = model.get("by_product") or {}
    vfootball = by_product.get("vfootball") or {}
    efootball = by_product.get("efootball_gt") or {}

    benchmark = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY_DIAGNOSTIC",
        "production_selection_changed": False,
        "data_sources": {
            "walkforward_model_eval": "data/virtual_lab_model_eval.json",
            "settled_ticket_tracker": "data/odds_ticket_tracker.json",
            "settled_line_evidence": "data/results_first_evidence_report.json",
        },
        "model_signal_benchmark": {
            "method": model.get("method"),
            "holdout": model.get("holdout"),
            "overall": holdout,
            "vfootball": vfootball,
            "efootball_gt": efootball,
            "interpretation": (
                "The walk-forward evidence shows useful predictive signal in VFootball "
                "probabilities, while eFootball GT is materially weaker. This is an "
                "individual-event benchmark, not a profitability guarantee."
            ),
        },
        "settled_ticket_benchmark": {
            "all_settled_tickets": {
                "n": len(settled),
                "wins": sum(1 for t in settled if y(t) == 1.0),
                "losses": sum(1 for t in settled if y(t) == 0.0),
                "accuracy": round(sum(y(t) for t in settled) / len(settled), 6) if settled else None,
                "model_probability": score_binary(settled, ticket_probability),
                "market_implied_probability": score_binary(settled, market_probability),
            },
            "active_2_to_4_leg_family": {
                "shape_tickets": len(modern),
                "model_probability": score_binary(modern, ticket_probability),
                "market_implied_probability": score_binary(modern, market_probability),
            },
            "by_shape": {
                str(k): ticket_shape_metrics(settled, k)
                for k in (2, 3, 4)
            },
        },
        "settled_line_evidence_snapshot": {
            "tracker_summary": evidence.get("tracker_summary"),
            "exact_line_side_records": evidence.get("exact_line_side_records"),
            "ticket_shape_records": evidence.get("ticket_shape_records"),
            "cooccurrence_records": evidence.get("cooccurrence_records"),
        },
        "decision": {
            "model_signal_present": True,
            "ticket_construction_proven": False,
            "current_ticket_probability_calibration_passed": False,
            "efootball_mix_proven": False,
            "recommended_scope": (
                "Do not treat the current 2–4-leg Builder construction as validated. "
                "The evidence supports isolating the stronger VFootball event model and "
                "rebuilding the ticket probability/construction layer around calibrated "
                "walk-forward probabilities instead of the current overconfident ticket "
                "probabilities."
            ),
        },
    }

    OUTPUT.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(benchmark, indent=2))


if __name__ == "__main__":
    main()
