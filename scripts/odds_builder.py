"""Build a guarded 3-4 selection accumulator for manual betting.

Research-only: never places or shares/stakes a wager. The builder selects
existing Match Signal paper candidates and calculates model fair odds plus a
reference accumulator. Actual bookmaker odds are intentionally left for the
user to verify in SportyBet/Stake because the direct SportyBet API is blocked
from the GitHub runner.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CANDIDATES = DATA / "selection_candidates.json"
PREDICTIONS = DATA / "predictions.json"
OUTPUT = DATA / "odds_builder.json"
MIN_LEGS, MAX_LEGS = 3, 4
MIN_PROB = 0.65


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fair_odds(probability: float) -> float:
    return round(1.0 / probability, 3) if probability > 0 else 0.0


def football_candidates():
    raw = load(CANDIDATES, [])
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw:
        if not isinstance(x, dict) or x.get("candidate_status") != "SELECTED" or x.get("sport") != "football":
            continue
        probs = x.get("probabilities") or {}
        pick = x.get("pick")
        try:
            probability = float(probs.get(pick, x.get("confidence", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if probability >= MIN_PROB and pick in {"p1", "draw", "p2"}:
            out.append({**x, "builder_market": "1X2", "builder_probability": probability, "builder_pick": pick})
    return out


def tennis_candidates():
    raw = load(PREDICTIONS, [])
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw:
        if not isinstance(x, dict) or x.get("sport") != "tennis":
            continue
        probs = x.get("probabilities") or {}
        pick = x.get("pick")
        try:
            match_prob = float(probs.get(pick, 0) or 0) if pick else 0.0
        except (TypeError, ValueError):
            match_prob = 0.0
        total = (x.get("analytics") or {}).get("total_games") or {}
        ou_pick = total.get("pick")
        try:
            ou_prob = float(total.get(ou_pick, 0) or 0) if ou_pick else 0.0
        except (TypeError, ValueError):
            ou_prob = 0.0

        if match_prob >= MIN_PROB:
            out.append({**x, "builder_market": "winner", "builder_probability": match_prob, "builder_pick": pick})
        elif ou_pick in {"over", "under"} and ou_prob >= MIN_PROB and total.get("line") is not None:
            out.append({**x, "builder_market": "total_games", "builder_probability": ou_prob, "builder_pick": ou_pick})
    return out


def make_leg(x):
    probability = float(x["builder_probability"])
    reference = fair_odds(probability)
    if x.get("sport") == "tennis":
        if x.get("builder_market") == "total_games":
            market = f"Total Games {x.get('builder_pick')} {x.get('analytics', {}).get('total_games', {}).get('line')}"
            pick = f"{x.get('player_1')} vs {x.get('player_2')} — {market}"
        else:
            pick = f"{x.get('player_1')} vs {x.get('player_2')} — {x.get('builder_pick')}"
        return {
            "sport": "tennis", "competition": x.get("league"), "event_id": x.get("event_id"),
            "start_time": x.get("start_time"), "match": f"{x.get('player_1')} vs {x.get('player_2')}",
            "market": x.get("builder_market"), "pick": pick,
            "model_probability": round(probability, 6), "model_fair_odds": reference,
            "source": x.get("model"), "decision": x.get("decision", "PAPER ONLY"),
        }
    return {
        "sport": "football", "competition": x.get("league"), "event_id": x.get("event_id"),
        "start_time": x.get("start_time"), "match": f"{x.get('home_team')} vs {x.get('away_team')}",
        "market": "1X2", "pick": x.get("builder_pick"),
        "model_probability": round(probability, 6), "model_fair_odds": reference,
        "source": x.get("model"), "decision": x.get("decision", "PAPER ONLY"),
    }


def main():
    football = football_candidates()
    tennis = tennis_candidates()
    all_candidates = football + tennis
    all_candidates.sort(key=lambda x: float(x.get("builder_probability", 0) or 0), reverse=True)
    selected = [make_leg(x) for x in all_candidates[:MAX_LEGS]]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "target_legs": "3-4",
        "sports_supported": ["football", "tennis"],
        "selection_policy": {
            "min_model_probability": MIN_PROB,
            "requires_existing_research_gate_for_football": True,
            "requires_paper_probability_threshold_for_tennis": True,
            "public_prediction_feed_unchanged": True,
        },
        "bookmaker_odds": {
            "status": "MANUAL_CONFIRMATION_REQUIRED",
            "sportybet_direct_feed": "BLOCKED_FROM_GITHUB_RUNNER",
            "stake_direct_feed": "NOT_CONNECTED",
            "instruction": "Verify each displayed selection and enter the actual current bookmaker odds in your betslip before placing any wager.",
        },
        "candidates_considered": {"football": len(football), "tennis": len(tennis)},
        "qualified_legs": selected,
        "leg_count": len(selected),
        "status": "QUALIFIED_ACCUMULATOR" if len(selected) >= MIN_LEGS else "NO_3_LEG_QUALIFIED_SET",
        "reference_combined_odds": round(math.prod(x["model_fair_odds"] for x in selected), 3) if selected else None,
        "reference_odds_type": "MODEL_FAIR_ODDS_NOT_BOOKMAKER_PRICE",
        "actual_combined_odds": None,
        "notes": [
            "Booking/share-code generation has been removed.",
            "The user manually builds the accumulator on SportyBet or Stake.",
            "Reference combined odds are the product of 1/model-probability and are NOT a quoted bookmaker price.",
            "No accumulator is forced when fewer than three selections pass the existing research threshold.",
        ],
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
