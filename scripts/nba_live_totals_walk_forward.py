#!/usr/bin/env python3
"""Evaluate archived NBA live total estimates by game period.

Only archived estimates for completed games are scored. A single near-target
snapshot per game and period prevents five-minute refreshes being counted as
independent samples.
"""
import gzip
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OBSERVATIONS = DATA / "nba_live_observations.json.gz"
LEGACY_OBSERVATIONS = DATA / "nba_live_observations.json"
HISTORY = DATA / "nba_history.json"
OUTPUT = DATA / "nba_live_totals_oos.json"
MIN_PERIOD_SAMPLE = 30
PERIOD_TARGET_TOLERANCE_MINUTES = 2.5
PERIOD_TARGETS = (
    ("Q1_end", 11.5, 8.0, 12.0),
    ("Halftime", 23.5, 20.0, 24.0),
    ("Q3_end", 35.5, 32.0, 36.0),
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


def observation_coverage(games, model_version=None):
    """Describe V5 live observations separately from settled accuracy samples."""
    statuses = {}
    period_snapshots = {"Q1": 0, "Halftime": 0, "Q3": 0, "Q4": 0}
    event_ids = set()
    live_snapshot_count = available_count = stats_based = score_clock_only = 0
    for event_id, game in (games or {}).items():
        game_has_model_observation = False
        for snapshot in game.get("snapshots") or []:
            if snapshot.get("game_state") != "live":
                continue
            if model_version and snapshot.get("pregame_totals_model_version") != model_version:
                continue
            game_has_model_observation = True
            live_snapshot_count += 1
            projection = snapshot.get("live_total_projection") or {}
            status = str(projection.get("status") or "MISSING_PROJECTION")
            statuses[status] = statuses.get(status, 0) + 1
            if status != "AVAILABLE":
                continue
            available_count += 1
            if projection.get("uses_live_boxscore_stats") is True:
                stats_based += 1
            else:
                score_clock_only += 1
            elapsed = number(projection.get("elapsed_minutes"))
            if elapsed is None:
                continue
            if 0 <= elapsed < 12:
                period_snapshots["Q1"] += 1
            elif 12 <= elapsed < 24:
                period_snapshots["Halftime"] += 1
            elif 24 <= elapsed < 36:
                period_snapshots["Q3"] += 1
            elif 36 <= elapsed <= 48:
                period_snapshots["Q4"] += 1
        if game_has_model_observation:
            event_ids.add(str(event_id))
    return {
        "model_version": model_version,
        "v5_live_events_observed": len(event_ids),
        "v5_live_snapshots": live_snapshot_count,
        "available_estimates": available_count,
        "estimate_status_counts": statuses,
        "available_snapshots_by_period": period_snapshots,
        "period_target_elapsed_minutes": {label: target for label, target, _, _ in PERIOD_TARGETS},
        "boxscore_possession_estimates": stats_based,
        "score_clock_fallback_estimates": score_clock_only,
        "accuracy_sample_unit": "one distinct settled game per period, not each five-minute snapshot",
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
        snapshots = game.get("snapshots") or []
        # The live recorder's ESPN event IDs differ from the NBA stats
        # provider's game IDs. Prefer this exact ESPN event's saved final row.
        final_rows = [row for row in snapshots if row.get("game_state") == "final"]
        final_rows.sort(key=lambda row: str(row.get("observed_at") or ""))
        actual = None
        if final_rows:
            final_row = final_rows[-1]
            home_score = number((final_row.get("home") or {}).get("score"))
            away_score = number((final_row.get("away") or {}).get("score"))
            if home_score is not None and away_score is not None:
                actual = home_score + away_score
        actual_source = "ESPN final scoreboard snapshot" if actual is not None else None
        if actual is None:
            actual = finals.get(str(event_id))
            if actual is not None:
                actual_source = "NBA historical score row with matching event ID"
        if actual is None:
            continue
        candidates = []
        for snapshot in snapshots:
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
                "actual_source": actual_source,
                "observed_at": observed_at.isoformat(),
                "projection_source": projection.get("projection_source"),
                "uses_live_boxscore_stats": projection.get("uses_live_boxscore_stats") is True,
            })
        for label, target, low, high in PERIOD_TARGETS:
            period_rows = [row for row in candidates if low <= row["elapsed_minutes"] <= high]
            if not period_rows:
                continue
            best = min(period_rows, key=lambda row: (abs(row["elapsed_minutes"] - target), row["observed_at"]))
            # Five-minute capture cadence can land just before/after a boundary.
            # Do not label an early-quarter estimate as an end-of-period sample.
            if abs(best["elapsed_minutes"] - target) <= PERIOD_TARGET_TOLERANCE_MINUTES:
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
        "selection": "One nearest target snapshot per settled event at end of Q1 (11.5m), halftime (23.5m), end of Q3 (35.5m), and mid-Q4 (42m); snapshots farther than the target tolerance are excluded, and missing projections/unsettled games are never imputed.",
        "period_target_tolerance_minutes": PERIOD_TARGET_TOLERANCE_MINUTES,
        "minimum_games_per_period": MIN_PERIOD_SAMPLE,
        "observation_coverage": observation_coverage(games, model_version),
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


def load_observation_archive():
    if OBSERVATIONS.exists():
        with gzip.open(OBSERVATIONS, "rt", encoding="utf-8") as source:
            payload = json.load(source)
        return payload if isinstance(payload, dict) else {"games": {}}
    if LEGACY_OBSERVATIONS.exists():
        payload = json.loads(LEGACY_OBSERVATIONS.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"games": {}}
    return {"games": {}}


def main():
    observations = load_observation_archive()
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    # Read the model version without importing the full training pipeline
    # (which pulls pandas/pyarrow); the five-minute recorder needs only stdlib.
    model_source = (ROOT / "scripts" / "expansion_pipeline.py").read_text(encoding="utf-8")
    match = re.search(r'^NBA_TOTALS_MODEL_VERSION\s*=\s*"([^"]+)"', model_source, re.MULTILINE)
    model_version = match.group(1) if match else None
    result = evaluate(observations, history, model_version)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
