#!/usr/bin/env python3
"""Build an auditable breakdown of settled Match Signal predictions.

The script deliberately separates prediction fields from actual outcome fields.
It will NOT treat actual_markets.over_under or actual_markets.btts as model picks.
If O/U, BTTS, or handicap prediction fields are absent from the stored history,
the output marks those analyses unavailable instead of fabricating results.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "prediction_history.json"
OUTPUT = ROOT / "data" / "prediction_breakdown.json"

BANDS = [
    (0.50, 0.55, "0.50-0.55"),
    (0.55, 0.60, "0.55-0.60"),
    (0.60, 0.65, "0.60-0.65"),
    (0.65, 0.70, "0.65-0.70"),
    (0.70, 0.80, "0.70-0.80"),
    (0.80, 1.01, "0.80-1.00"),
]


def load_history() -> list[dict]:
    with HISTORY.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("predictions", data.get("history", []))
    if not isinstance(data, list):
        raise ValueError("prediction_history.json does not contain a prediction list")
    return [x for x in data if isinstance(x, dict) and x.get("settled") is True]


def band(conf: float | None) -> str:
    if conf is None:
        return "unknown"
    for lo, hi, label in BANDS:
        if lo <= conf < hi:
            return label
    return "unknown"


def metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "wins": 0, "losses": 0, "accuracy": None, "avg_confidence": None, "brier": None}
    wins = sum(bool(r.get("correct")) for r in rows)
    confs = [float(r["confidence"]) for r in rows if isinstance(r.get("confidence"), (int, float))]
    briers = [float(r["brier"]) for r in rows if isinstance(r.get("brier"), (int, float))]
    return {
        "n": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "accuracy": round(wins / len(rows), 4),
        "avg_confidence": round(mean(confs), 4) if confs else None,
        "brier": round(mean(briers), 4) if briers else None,
    }


def group(rows: list[dict], key_fn) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(key_fn(row))].append(row)
    return {k: metrics(v) for k, v in sorted(buckets.items())}


def pick_type(row: dict) -> str:
    pick = row.get("pick")
    if pick in {"p1", "draw", "p2"}:
        return "1X2"
    return "unknown"


def find_prediction(row: dict, aliases: tuple[str, ...]) -> object | None:
    """Find an explicitly stored market prediction without using actual outcome fields."""
    for key in aliases:
        if key in row:
            return row[key]
    for container_name in ("markets", "market_predictions", "predictions", "analysis"):
        container = row.get(container_name)
        if isinstance(container, dict):
            for key in aliases:
                if key in container:
                    value = container[key]
                    if isinstance(value, dict) and "pick" in value:
                        return value["pick"]
                    return value
    return None


def market_breakdown(rows: list[dict], market: str) -> dict:
    aliases = {
        "over_under": ("ou_pick", "over_under_pick", "over_under_prediction", "ou_prediction"),
        "btts": ("btts_pick", "btts_prediction", "btts_prediction_pick"),
        "handicap": ("handicap_pick", "handicap_prediction", "asian_handicap_pick"),
    }[market]
    actual_aliases = {
        "over_under": ("over_under", "ou", "total_goals"),
        "btts": ("btts",),
        "handicap": ("handicap", "asian_handicap"),
    }[market]
    eligible = []
    for row in rows:
        prediction = find_prediction(row, aliases)
        if prediction is None:
            continue
        actual = None
        actual_markets = row.get("actual_markets")
        if isinstance(actual_markets, dict):
            for key in actual_aliases:
                if key in actual_markets:
                    actual = actual_markets[key]
                    break
        if actual is None:
            actual = row.get("actual_" + market)
        if actual is None:
            continue
        r = dict(row)
        r["_market_correct"] = str(prediction).lower() == str(actual).lower()
        r["correct"] = r["_market_correct"]
        eligible.append(r)
    if not eligible:
        return {
            "status": "unavailable",
            "reason": "No explicit stored model prediction field was found; actual market outcomes are not used as predictions.",
            "metrics": metrics([]),
        }
    return {"status": "available", "metrics": metrics(eligible), "by_league": group(eligible, lambda r: r.get("league", "unknown"))}


def main() -> None:
    rows = load_history()
    football = [r for r in rows if str(r.get("sport", "")).lower() == "football"]

    result = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "settled_records": len(rows),
        "football_settled_records": len(football),
        "1x2": {
            "overall": metrics(football),
            "by_league": group(football, lambda r: r.get("league", "unknown")),
            "by_confidence_band": group(football, lambda r: band(r.get("confidence"))),
            "by_model": group(football, lambda r: r.get("model", "unknown")),
            "by_league_and_confidence": {
                league: group([r for r in football if r.get("league") == league], lambda r: band(r.get("confidence")))
                for league in sorted({r.get("league", "unknown") for r in football})
            },
        },
        "market_predictions": {
            "over_under": market_breakdown(football, "over_under"),
            "btts": market_breakdown(football, "btts"),
            "handicap": market_breakdown(football, "handicap"),
        },
        "scope_summary": {},
        "methodology": {
            "1x2": "Uses stored pick (p1/draw/p2), actual outcome, confidence, model and brier fields.",
            "market_types": "Only explicit stored model prediction fields are eligible. actual_markets is treated as outcome data only.",
            "settled_only": True,
            "paper_only": True,
        },
    }

    for league in ("EPL", "Bundesliga", "Champions League"):
        scoped = [r for r in football if r.get("league") == league]
        result["scope_summary"][league] = {
            "overall": metrics(scoped),
            "by_confidence_band": group(scoped, lambda r: band(r.get("confidence"))),
            "by_model": group(scoped, lambda r: r.get("model", "unknown")),
        }

    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(OUTPUT), "settled_records": len(rows), "football": len(football)}, indent=2))


if __name__ == "__main__":
    main()
