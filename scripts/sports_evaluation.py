#!/usr/bin/env python3
"""Cross-sport settled-prediction evaluation and conservative selection gate.

Evaluates football, tennis and basketball from their authoritative local history
stores. It ranks tournaments/leagues and selections by settled wins, then emits a
research-only gate for selective future predictions. No probabilities are changed
and nothing is marked live-eligible. PAPER ONLY.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "sports_evaluation.json"

# Conservative sample requirements: these are research filters, not claims of
# statistical significance. A segment must earn its way into the next-match
# candidate pool rather than every fixture being surfaced as a pick.
MIN_TOURNAMENT_N = 8
MIN_TOURNAMENT_ACCURACY = 0.65
MIN_SELECTION_N = 3
MIN_SELECTION_ACCURACY = 0.67
MIN_CONFIDENCE = 0.65


def load(name: str, default):
    try:
        with (DATA / name).open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def rows_from(value):
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        for key in ("predictions", "history", "recent_settled"):
            if isinstance(value.get(key), list):
                return [r for r in value[key] if isinstance(r, dict)]
    return []


def canonical(rows):
    out = {}
    for row in rows:
        if not row.get("settled"):
            continue
        sport = str(row.get("sport") or "").lower()
        event_id = row.get("event_id")
        if not sport or event_id is None:
            continue
        key = f"{sport}:{event_id}"
        # Prefer the richer/latest settled copy.
        if key not in out or str(row.get("settled_at") or "") > str(out[key].get("settled_at") or ""):
            out[key] = row
    return list(out.values())


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


def metrics(rows):
    if not rows:
        return {"n": 0, "wins": 0, "losses": 0, "accuracy": None, "avg_confidence": None}
    wins = sum(bool(r.get("correct")) for r in rows)
    conf = [float(r["confidence"]) for r in rows if isinstance(r.get("confidence"), (int, float))]
    return {
        "n": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "accuracy": round(wins / len(rows), 4),
        "avg_confidence": round(mean(conf), 4) if conf else None,
    }


def grouped(rows, fn):
    buckets = defaultdict(list)
    for row in rows:
        buckets[str(fn(row))].append(row)
    return {k: metrics(v) for k, v in sorted(buckets.items())}


def confidence_band(value):
    if not isinstance(value, (int, float)):
        return "unknown"
    if value < 0.50:
        return "<0.50"
    if value < 0.55:
        return "0.50-0.55"
    if value < 0.60:
        return "0.55-0.60"
    if value < 0.65:
        return "0.60-0.65"
    if value < 0.70:
        return "0.65-0.70"
    if value < 0.80:
        return "0.70-0.80"
    return "0.80-1.00"


def main():
    sources = {
        "football": rows_from(load("prediction_history.json", [])),
        "basketball": rows_from(load("basketball_history.json", [])),
        # Tennis is currently stored in the shared prediction history. If a
        # dedicated tennis history is introduced later, this remains compatible.
    }
    all_rows = canonical([r for rows in sources.values() for r in rows])
    by_sport = {sport: [r for r in all_rows if str(r.get("sport") or "").lower() == sport] for sport in ("football", "tennis", "basketball")}

    tournament_stats = {}
    selection_stats = {}
    winners = []
    for sport, rows in by_sport.items():
        tournament_stats[sport] = grouped(rows, tournament)
        selection_stats[sport] = grouped(rows, selection)
        for row in rows:
            if row.get("correct") is True:
                winners.append({
                    "sport": sport,
                    "tournament": tournament(row),
                    "league": row.get("league"),
                    "selection": selection(row),
                    "confidence": row.get("confidence"),
                    "player_1": row.get("player_1"),
                    "player_2": row.get("player_2"),
                    "event_id": row.get("event_id"),
                })

    highest_won_tournaments = {}
    for sport, stats in tournament_stats.items():
        highest_won_tournaments[sport] = sorted(
            ({"tournament": k, **v} for k, v in stats.items()),
            key=lambda x: (x["wins"], x["accuracy"] or 0, x["n"]),
            reverse=True,
        )[:10]

    # A segment qualifies for the conservative candidate gate only when there
    # is enough history and the realized accuracy is materially better than the
    # 50% baseline. This is intentionally selective and can return zero picks.
    qualified_tournaments = {}
    for sport, stats in tournament_stats.items():
        qualified_tournaments[sport] = [
            {"tournament": k, **v}
            for k, v in stats.items()
            if v["n"] >= MIN_TOURNAMENT_N and (v["accuracy"] or 0) >= MIN_TOURNAMENT_ACCURACY
        ]

    qualified_selections = {}
    for sport, rows in by_sport.items():
        buckets = defaultdict(list)
        for row in rows:
            buckets[(tournament(row), selection(row))].append(row)
        qualified_selections[sport] = []
        for (tour, pick), bucket in buckets.items():
            m = metrics(bucket)
            if m["n"] >= MIN_SELECTION_N and (m["accuracy"] or 0) >= MIN_SELECTION_ACCURACY:
                qualified_selections[sport].append({"tournament": tour, "selection": pick, **m})
        qualified_selections[sport].sort(key=lambda x: (x["accuracy"], x["wins"], x["n"]), reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "overall": {sport: metrics(rows) for sport, rows in by_sport.items()},
        "tournament_stats": tournament_stats,
        "selection_stats": selection_stats,
        "confidence_stats": {sport: grouped(rows, lambda r: confidence_band(r.get("confidence"))) for sport, rows in by_sport.items()},
        "highest_won_tournaments": highest_won_tournaments,
        "won_predictions": sorted(winners, key=lambda x: (x["sport"], x["tournament"], -(x["confidence"] or 0))),
        "qualified_tournaments": qualified_tournaments,
        "qualified_selections": qualified_selections,
        "cut_down_policy": {
            "min_tournament_settled": MIN_TOURNAMENT_N,
            "min_tournament_accuracy": MIN_TOURNAMENT_ACCURACY,
            "min_selection_settled": MIN_SELECTION_N,
            "min_selection_accuracy": MIN_SELECTION_ACCURACY,
            "min_confidence_for_future_candidate": MIN_CONFIDENCE,
            "rule": "Only qualified tournament/selection segments with current confidence >= 0.65 should enter the selective candidate pool; everything else remains PAPER ONLY research and is not surfaced as a preferred pick.",
            "no_probability_manipulation": True,
        },
        "settled_source_counts": {sport: len(rows) for sport, rows in by_sport.items()},
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "settled": result["settled_source_counts"], "qualified_tournaments": result["qualified_tournaments"], "qualified_selections": result["qualified_selections"]}, indent=2))


if __name__ == "__main__":
    main()
