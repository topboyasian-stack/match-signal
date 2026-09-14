"""Strict chronological out-of-sample NBA value test.

This test deliberately does not tune the model, EV threshold, or calibration on
its holdout period. It evaluates the model probabilities already persisted in
nba_market_matches.json on the final 20% of chronologically matched games.

Purpose: distinguish a genuinely out-of-sample value signal from an in-sample
historical result. This is research-only and never promotes NBA to production.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INPUT = DATA / "nba_market_matches.json"
OUTPUT = DATA / "nba_oos_value_test.json"
HOLDOUT_FRACTION = 0.20
EV_THRESHOLD = 0.025
MIN_HOLDOUT = 100


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def american_to_decimal(american: float) -> float:
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def logloss(p: float, y: int) -> float:
    p = min(max(p, 1e-12), 1.0 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def evaluate(rows):
    if not rows:
        return {"n": 0}

    model_correct = 0
    market_correct = 0
    model_brier = 0.0
    model_logloss = 0.0
    market_brier = 0.0
    bets = []

    for r in rows:
        y = 1 if float(r["home_score"]) > float(r["away_score"]) else 0
        mp = float(r["model_home_prob"])
        kp = float(r["market_home_prob"])
        model_pick = 1 if mp >= 0.5 else 0
        market_pick = 1 if kp >= 0.5 else 0

        model_correct += model_pick == y
        market_correct += market_pick == y
        model_brier += (mp - y) ** 2
        model_logloss += logloss(mp, y)
        market_brier += (kp - y) ** 2

        if model_pick:
            odds = float(r["home_ml"])
            market_prob = kp
            prob = mp
        else:
            odds = float(r["away_ml"])
            market_prob = 1.0 - kp
            prob = 1.0 - mp

        decimal = american_to_decimal(odds)
        ev = prob * decimal - 1.0
        if ev >= EV_THRESHOLD:
            won = (model_pick == y)
            profit = (decimal - 1.0) if won else -1.0
            bets.append({"ev": ev, "profit": profit, "won": won})

    n = len(rows)
    return {
        "n": n,
        "model_accuracy": model_correct / n,
        "market_accuracy": market_correct / n,
        "accuracy_delta": (model_correct - market_correct) / n,
        "model_brier": model_brier / n,
        "model_logloss": model_logloss / n,
        "market_brier": market_brier / n,
        "ev_threshold": EV_THRESHOLD,
        "value_bets": len(bets),
        "value_coverage": len(bets) / n,
        "mean_ev": sum(x["ev"] for x in bets) / len(bets) if bets else None,
        "roi": sum(x["profit"] for x in bets) / len(bets) if bets else None,
        "profit_units": sum(x["profit"] for x in bets),
        "value_accuracy": sum(x["won"] for x in bets) / len(bets) if bets else None,
    }


def main():
    rows = load(INPUT)
    if not isinstance(rows, list):
        raise RuntimeError("nba_market_matches.json must contain a list")

    usable = []
    for r in rows:
        required = (
            "date", "home_score", "away_score", "model_home_prob",
            "market_home_prob", "home_ml", "away_ml"
        )
        if not all(k in r and r[k] is not None for k in required):
            continue
        try:
            float(r["model_home_prob"])
            float(r["market_home_prob"])
            float(r["home_ml"])
            float(r["away_ml"])
        except (TypeError, ValueError):
            continue
        usable.append(r)

    usable.sort(key=lambda r: str(r["date"]))
    n = len(usable)
    if n < MIN_HOLDOUT:
        raise RuntimeError(f"Only {n} usable matched games; need at least {MIN_HOLDOUT}")

    split = max(1, int(n * (1.0 - HOLDOUT_FRACTION)))
    development = usable[:split]
    holdout = usable[split:]

    result = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "paper_only": True,
        "test": "strict chronological 80/20 holdout",
        "source": "data/nba_market_matches.json",
        "model_source": "persisted walk-forward model probabilities",
        "ev_threshold": EV_THRESHOLD,
        "total_usable_matched_games": n,
        "development_games": len(development),
        "holdout_games": len(holdout),
        "development_end": development[-1]["date"],
        "holdout_start": holdout[0]["date"],
        "holdout_end": holdout[-1]["date"],
        "holdout": evaluate(holdout),
        "release_decision": "RESEARCH_ONLY",
        "reason": "Strict holdout is a diagnostic only; NBA remains paper-only until a pre-registered value rule produces positive out-of-sample ROI with adequate contemporaneous market coverage.",
    }

    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
