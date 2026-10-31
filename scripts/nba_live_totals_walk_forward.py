#!/usr/bin/env python3
"""Evaluate archived NBA live total estimates by game period.

Only archived estimates for completed games are scored. A single near-target
snapshot per game and period prevents five-minute refreshes being counted as
independent samples.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OBSERVATIONS = DATA / "nba_live_observations.json"
HISTORY = DATA / "nba_history.json"
OUTPUT = DATA / "nba_live_totals_oos.json"
MIN_PERIOD_SAMPLE = 30
PERIOD_TARGETS = (
    ("Q1_end", 10.0, 6.0, 12.0),
    ("Halftime", 22.0, 12.0, 24.0),
    ("Q3_end", 34.0, 24.0, 36.0),
    ("Q4", 42.0, 36.0, 48.0),
)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def metrics(rows):
    live_errors = []
    pregame_errors = []
    for row in rows:
        actual = number(row.get("actual_total"))
        live = number(row.get("live_total_estimate"))
        pregame = number(row.get("pregame_expected_total"))
        if actual is None or live is None:
            continue
        live_errors.append(live - actual)
        if pregame is not None:
            pregame_errors.append(pregame - actual)
    count = len(live_errors)
    live_mae = sum(abs(value) for value in live_errors) / count if count else None
    pregame_mae = sum(abs(value) for value in pregame_errors) / len(pregame_errors) if pregame_errors else None
    return {
        "n": count,
        "mae": round(live_mae, 4) if live_mae is not None else None,
        "rmse": round(math.sqrt(sum(value * value for value in live_errors) / count), 4) if count else None,
        "bias": round(sum(live_errors) / count, 4) if count else None,
        "pregame_baseline_n": len(pregame_errors),
        "pregame_mae": round(pregame_mae, 4) if pregame_mae is not None else None,
        "mae_improvement_vs_pregame": (
            round(pregame_mae - live_mae, 4)
            if live_mae is not None and pregame_mae is not None else None
        ),
    }


def evaluate(observation_payload, history_rows, model_version=None):
    finals = {}
    for row in history_rows if isinstance(history_rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            total = float(row["home_score"]) + float(row["away_score"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(total) and total >= 0:
            finals[str(row.get("event_id") or "")] = total

    games = (observation_payload or {}).get("games") or {}
    selected = {label: [] for label, _, _, _ in PERIOD_TARGETS}
    for event_id, game in games.items():
        actual = finals.get(str(event_id))
        if actual is None:
            continue
        candidates = []
        for snapshot in game.get("snapshots") or []:
            if snapshot.get("game_state") != "live":
                continue
            if model_version and snapshot.get("pregame_totals_model_version") != model_version:
                continue
            projection = snapshot.get("live_total_projection") or {}
            if projection.get("status") != "AVAILABLE":
                continue
            elapsed = number(projection.get("elapsed_minutes"))
            live_estimate = number(projection.get("live_total_estimate"))
            pregame = number(projection.get("pregame_expected_total"))
            observed_at = parse_time(snapshot.get("observed_at"))
            if elapsed is None or live_estimate is None or observed_at is None:
                continue
            candidates.append({
                "event_id": str(event_id),
                "elapsed_minutes": elapsed,
                "live_total_estimate": live_estimate,
                "pregame_expected_total": pregame,
                "actual_total": actual,
                "observed_at": observed_at.isoformat(),
                "projection_source": projection.get("projection_source"),
                "uses_live_boxscore_stats": projection.get("uses_live_boxscore_stats") is True,
            })
        for label, target, low, high in PERIOD_TARGETS:
            period_rows = [row for row in candidates if low <= row["elapsed_minutes"] <= high]
            if not period_rows:
                continue
            best = min(period_rows, key=lambda row: (abs(row["elapsed_minutes"] - target), row["observed_at"]))
            if abs(best["elapsed_minutes"] - target) <= 4.5:
                selected[label].append(best)

    by_period = {label: metrics(rows) for label, rows in selected.items()}
    all_rows = [row for rows in selected.values() for row in rows]
    sufficient = all(by_period[label]["n"] >= MIN_PERIOD_SAMPLE for label, _, _, _ in PERIOD_TARGETS)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "evaluation_type": "NBA_LIVE_TOTALS_PERIOD_WALK_FORWARD_V1",
        "model_version": model_version,
        "source": "Archived ESPN live scoreboard/box-score estimates paired with official final totals",
        "observation_window_days": 30,
        "selection": "One nearest target snapshot per settled event and period; missing projections and unsettled games are excluded, never imputed.",
        "minimum_games_per_period": MIN_PERIOD_SAMPLE,
        "settled_events_with_observations": len({row["event_id"] for row in all_rows}),
        "by_period": by_period,
        "overall": metrics(all_rows),
        "evidence_sufficient": sufficient,
        "release_decision": "RESEARCH_ONLY",
        "release_reason": (
            "Every period bucket has at least 30 independently settled games."
            if sufficient else
            "Live estimates remain research-only until every period bucket has at least 30 settled games with archived same-period projections."
        ),
    }


def main():
    observations = (
        json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
        if OBSERVATIONS.exists() and OBSERVATIONS.stat().st_size else {"games": {}}
    )
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    from expansion_pipeline import NBA_TOTALS_MODEL_VERSION
    result = evaluate(observations, history, NBA_TOTALS_MODEL_VERSION)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
