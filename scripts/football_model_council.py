"""Walk-forward football model council. PAPER/RESEARCH ONLY.

Compares the current published Football probabilities with the independent
venue-aware Poisson/Dixon-Coles model without changing the production pick.
No market odds are used by the independent model.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from independent_football_model import independent_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_json(name, default):
    try:
        value = json.loads((DATA / name).read_text(encoding="utf-8"))
        return value
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def parse_dt(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def actual_from_row(row):
    actual = row.get("actual")
    if actual in {"p1", "draw", "p2"}:
        return actual
    score = row.get("final_score")
    try:
        home, away = float(score[0]), float(score[1])
    except (TypeError, ValueError, IndexError):
        return None
    return "p1" if home > away else "p2" if away > home else "draw"


def event_from_row(row):
    return {
        "id": str(row.get("event_id") or ""),
        "date": row.get("start_time") or row.get("calculated_at"),
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": row.get("player_1") or "Home"},
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": row.get("player_2") or "Away"},
                    },
                ]
            }
        ],
    }


def pick_from_probs(probs):
    keys = ("p1", "draw", "p2")
    return max(keys, key=lambda key: float(probs.get(key, 0.0)))


def brier(probs, actual):
    return round(
        sum(
            (float(probs.get(key, 0.0)) - (1.0 if actual == key else 0.0)) ** 2
            for key in ("p1", "draw", "p2")
        ),
        6,
    )


def accuracy(rows, key):
    if not rows:
        return 0.0
    return round(sum(bool(r[key]) for r in rows) / len(rows), 4)


def prob_bands(rows, prob_key):
    bands = [
        ("50-55%", 0.50, 0.55),
        ("55-60%", 0.55, 0.60),
        ("60-65%", 0.60, 0.65),
        ("65-70%", 0.65, 0.70),
        ("70-75%", 0.70, 0.75),
        ("75-80%", 0.75, 0.80),
        ("80%+", 0.80, 1.01),
    ]
    output = []
    for label, lo, hi in bands:
        group = [r for r in rows if lo <= float(r[prob_key]) < hi]
        hits = sum(bool(r["independent_correct"] if prob_key == "independent_prob" else r["published_correct"]) for r in group)
        output.append({
            "label": label,
            "settled": len(group),
            "correct": hits,
            "accuracy": round(hits / len(group), 4) if group else None,
        })
    return output


def build():
    published_history = load_json("prediction_history.json", [])
    football_rows = [
        row for row in published_history
        if row.get("sport") == "football"
        and row.get("settled")
        and row.get("final_score")
        and row.get("player_1")
        and row.get("player_2")
    ]

    team_history = load_json("football_team_history.json", [])
    team_history = [
        row for row in team_history
        if row.get("sport") == "football" and row.get("settled") and row.get("final_score")
    ]
    source_history = team_history if team_history else football_rows
    source_name = "football_team_history" if team_history else "prediction_history_settled_fallback"

    evaluated = []
    skipped = 0
    by_league = defaultdict(list)

    for row in sorted(football_rows, key=lambda item: item.get("start_time") or item.get("calculated_at") or ""):
        actual = actual_from_row(row)
        cutoff = row.get("start_time") or row.get("calculated_at")
        if actual is None or not parse_dt(cutoff):
            skipped += 1
            continue

        independent = independent_prediction(
            event_from_row(row),
            row.get("league") or "global",
            source_history,
            cutoff=cutoff,
        )
        if not independent:
            skipped += 1
            continue

        indep_probs = {
            "p1": float(independent["p1"]),
            "draw": float(independent["draw"]),
            "p2": float(independent["p2"]),
        }
        published_probs = row.get("calibrated_probabilities") or row.get("probabilities") or {}
        if not all(key in published_probs for key in ("p1", "draw", "p2")):
            skipped += 1
            continue

        published_probs = {
            "p1": float(published_probs["p1"]),
            "draw": float(published_probs["draw"]),
            "p2": float(published_probs["p2"]),
        }

        independent_pick = pick_from_probs(indep_probs)
        published_pick = pick_from_probs(published_probs)
        record = {
            "league": row.get("league") or "Unknown",
            "event_id": str(row.get("event_id") or ""),
            "start_time": cutoff,
            "published_prob": round(max(published_probs.values()), 6),
            "independent_prob": round(max(indep_probs.values()), 6),
            "published_pick": published_pick,
            "independent_pick": independent_pick,
            "actual": actual,
            "published_correct": published_pick == actual,
            "independent_correct": independent_pick == actual,
            "published_brier": brier(published_probs, actual),
            "independent_brier": brier(indep_probs, actual),
            "independent_effective_sample": independent.get("effective_sample", 0),
            "independent_xg_home": independent.get("xg_home"),
            "independent_xg_away": independent.get("xg_away"),
        }
        record["agreement"] = published_pick == independent_pick
        evaluated.append(record)
        by_league[record["league"]].append(record)

    overall = {
        "settled_evaluated": len(evaluated),
        "skipped": skipped,
        "published_accuracy": accuracy(evaluated, "published_correct"),
        "independent_accuracy": accuracy(evaluated, "independent_correct"),
        "published_brier": round(sum(r["published_brier"] for r in evaluated) / len(evaluated), 4) if evaluated else None,
        "independent_brier": round(sum(r["independent_brier"] for r in evaluated) / len(evaluated), 4) if evaluated else None,
        "pick_agreement_rate": round(sum(r["agreement"] for r in evaluated) / len(evaluated), 4) if evaluated else None,
        "independent_beats_published_accuracy": (
            accuracy(evaluated, "independent_correct") > accuracy(evaluated, "published_correct")
            if evaluated else False
        ),
        "independent_beats_published_brier": (
            (sum(r["independent_brier"] for r in evaluated) / len(evaluated))
            < (sum(r["published_brier"] for r in evaluated) / len(evaluated))
            if evaluated else False
        ),
    }

    league_summary = {}
    for league, rows in sorted(by_league.items()):
        league_summary[league] = {
            "settled_evaluated": len(rows),
            "published_accuracy": accuracy(rows, "published_correct"),
            "independent_accuracy": accuracy(rows, "independent_correct"),
            "published_brier": round(sum(r["published_brier"] for r in rows) / len(rows), 4),
            "independent_brier": round(sum(r["independent_brier"] for r in rows) / len(rows), 4),
            "pick_agreement_rate": round(sum(r["agreement"] for r in rows) / len(rows), 4),
        }

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_RESEARCH_ONLY",
        "model_version": "FOOTBALL-STAT-COUNCIL-V1",
        "method": "venue-aware recency-weighted team attack/defence + league scoring baseline + Poisson/Dixon-Coles",
        "market_independent": True,
        "production_pick_unchanged": True,
        "builder_eligibility_unchanged": True,
        "history_source": source_name,
        "history_rows_available": len(source_history),
        "overall": overall,
        "by_league": league_summary,
        "published_probability_bands": prob_bands(evaluated, "published_prob"),
        "independent_probability_bands": prob_bands(evaluated, "independent_prob"),
        "latest_evaluated": evaluated[-50:],
        "promotion_policy": "Do not let the independent model override production or Builder qualification until it demonstrates a stable walk-forward advantage on accuracy/Brier across multiple settled windows.",
    }
    return payload


def main():
    payload = build()
    (DATA / "football_model_council.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ok",
        "model": payload["model_version"],
        "history_source": payload["history_source"],
        "settled_evaluated": payload["overall"]["settled_evaluated"],
        "published_accuracy": payload["overall"]["published_accuracy"],
        "independent_accuracy": payload["overall"]["independent_accuracy"],
        "published_brier": payload["overall"]["published_brier"],
        "independent_brier": payload["overall"]["independent_brier"],
        "pick_agreement_rate": payload["overall"]["pick_agreement_rate"],
    }, indent=2))


if __name__ == "__main__":
    main()
