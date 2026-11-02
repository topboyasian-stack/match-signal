#!/usr/bin/env python3
"""Historical-only ablation experiment for a separately versioned NBA totals v6 candidate.

This script does not change the live v5 model, consume bookmaker prices, or touch the
prospective holdout. Every feature for a game is derived strictly before its tip.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from expansion_pipeline import nba_total_components, dt as parse_time
from nba_totals_walk_forward import (
    EVALUATION_CUTOFF_UTC,
    HISTORY,
    build_forecasts,
    clean_history,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "nba_totals_v6_feature_experiment.json"
HISTORICAL_VALIDATION_CUTOFF_UTC = datetime(
    2026, 3, 26, 3, 59, 59, 999999, tzinfo=timezone.utc
)
RECENCY_HALF_LIFE_DAYS = 30.0
VENUE_SHRINKAGE_GAMES = 8.0
RIDGE_PENALTY = 12.0
PACE_BLEND_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


def _blank_stats():
    return {"pf_sum": 0.0, "pa_sum": 0.0, "weight_sum": 0.0, "games": 0}


def _mean(stats, key, fallback):
    weight = stats.get("weight_sum", 0.0)
    return stats.get(key + "_sum", 0.0) / weight if weight > 0 else fallback


def _venue_value(team, venue, key, state, league_fallback):
    overall = state.get((team, "all"), _blank_stats())
    split = state.get((team, venue), _blank_stats())
    overall_mean = _mean(overall, key, league_fallback)
    venue_mean = _mean(split, key, overall_mean)
    games = split.get("games", 0)
    alpha = games / (games + VENUE_SHRINKAGE_GAMES) if games else 0.0
    return alpha * venue_mean + (1.0 - alpha) * overall_mean


def venue_total_from_history(home, away, history, cutoff):
    """Estimate the venue matchup using only completed games before cutoff."""
    cut = parse_time(cutoff)
    if not cut:
        return None
    state = defaultdict(_blank_stats)
    league_points_sum = 0.0
    league_team_games = 0

    for row in history or []:
        played = parse_time(row.get("date"))
        if not played or played >= cut:
            continue
        try:
            home_points = float(row["home_score"])
            away_points = float(row["away_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v >= 0 for v in (home_points, away_points)):
            continue
        weight = math.exp(
            -math.log(2.0) * max(0.0, (cut - played).total_seconds() / 86400.0)
            / RECENCY_HALF_LIFE_DAYS
        )
        for team, venue, points_for, points_against in (
            (row.get("home"), "home", home_points, away_points),
            (row.get("away"), "away", away_points, home_points),
        ):
            if not team:
                continue
            for key in ("all", venue):
                stats = state[(str(team), key)]
                stats["pf_sum"] += weight * points_for
                stats["pa_sum"] += weight * points_against
                stats["weight_sum"] += weight
                stats["games"] += 1
        league_points_sum += home_points + away_points
        league_team_games += 2

    league_fallback = league_points_sum / league_team_games if league_team_games else 112.0
    home_pf = _venue_value(home, "home", "pf", state, league_fallback)
    home_pa = _venue_value(home, "home", "pa", state, league_fallback)
    away_pf = _venue_value(away, "away", "pf", state, league_fallback)
    away_pa = _venue_value(away, "away", "pa", state, league_fallback)
    expected_home = (home_pf + away_pa) / 2.0
    expected_away = (away_pf + home_pa) / 2.0
    return expected_home + expected_away


def recent_team_stats(team, history, cutoff, window=10):
    """Return last-N team-game PF/PA and pace/efficiency using only pre-tip data."""
    cut = parse_time(cutoff)
    if not cut:
        return None
    games = []
    for row in history or []:
        played = parse_time(row.get("date"))
        if not played or played >= cut:
            continue
        if row.get("home") == team:
            side = "home"
            points_for, points_against = row.get("home_score"), row.get("away_score")
        elif row.get("away") == team:
            side = "away"
            points_for, points_against = row.get("away_score"), row.get("home_score")
        else:
            continue
        try:
            points_for, points_against = float(points_for), float(points_against)
        except (TypeError, ValueError):
            continue
        item = {"pf": points_for, "pa": points_against}
        for key in ("pace", "off_rating", "def_rating", "possessions"):
            value = row.get(f"{side}_{key}")
            try:
                value = float(value)
                item[key] = value if math.isfinite(value) else None
            except (TypeError, ValueError):
                item[key] = None
        games.append((played, item))
    selected = [item for _, item in sorted(games, key=lambda pair: pair[0])[-max(1, int(window)):]]
    if not selected:
        return None
    result = {"games": len(selected)}
    for key in ("pf", "pa", "pace", "off_rating", "def_rating", "possessions"):
        values = [item[key] for item in selected if key in item and item[key] is not None]
        result[key] = sum(values) / len(values) if values else None
    return result


def build_feature_rows(history):
    """Build v5 base features plus candidate pregame-only venue/rest/schedule features."""
    clean = clean_history(history)
    forecast_by_id = {row["event_id"]: row for row in build_forecasts(clean)}
    prior = []
    feature_rows = []

    for game in clean:
        event_id = game["event_id"]
        forecast = forecast_by_id.get(event_id)
        if forecast:
            components = nba_total_components(game, prior)
            rest = components.get("rest_days") or {}
            home_rest = max(0.0, min(7.0, float(rest.get("home", 4.0))))
            away_rest = max(0.0, min(7.0, float(rest.get("away", 4.0))))
            cutoff = parse_time(game["date"])
            seven_days_ago = cutoff.timestamp() - 7 * 86400
            home_load = away_load = 0
            for earlier in prior:
                earlier_date = parse_time(earlier.get("date"))
                if not earlier_date or earlier_date.timestamp() < seven_days_ago:
                    continue
                if earlier.get("home") == game.get("home") or earlier.get("away") == game.get("home"):
                    home_load += 1
                if earlier.get("home") == game.get("away") or earlier.get("away") == game.get("away"):
                    away_load += 1

            venue_total = venue_total_from_history(
                game.get("home"), game.get("away"), prior, cutoff
            )
            home_recent5 = recent_team_stats(game.get("home"), prior, cutoff, window=5) or {}
            away_recent5 = recent_team_stats(game.get("away"), prior, cutoff, window=5) or {}
            home_recent10 = recent_team_stats(game.get("home"), prior, cutoff, window=10) or {}
            away_recent10 = recent_team_stats(game.get("away"), prior, cutoff, window=10) or {}

            def recent_matchup_total(home_stats, away_stats):
                required = (home_stats.get("pf"), home_stats.get("pa"), away_stats.get("pf"), away_stats.get("pa"))
                if any(value is None for value in required):
                    return None
                expected_home = (home_stats["pf"] + away_stats["pa"]) / 2.0
                expected_away = (away_stats["pf"] + home_stats["pa"]) / 2.0
                return expected_home + expected_away

            recent5_total = recent_matchup_total(home_recent5, away_recent5)
            recent10_total = recent_matchup_total(home_recent10, away_recent10)
            recent_pace_total = None
            if all(home_recent10.get(key) is not None and away_recent10.get(key) is not None
                   for key in ("pace", "off_rating", "def_rating")):
                recent_game_pace = (home_recent10["pace"] + away_recent10["pace"]) / 2.0
                recent_home_eff = (home_recent10["off_rating"] + away_recent10["def_rating"]) / 2.0
                recent_away_eff = (away_recent10["off_rating"] + home_recent10["def_rating"]) / 2.0
                if 75 <= recent_game_pace <= 115 and 75 <= recent_home_eff <= 145 and 75 <= recent_away_eff <= 145:
                    recent_pace_total = recent_game_pace * (recent_home_eff + recent_away_eff) / 100.0

            recent_possessions_total = None
            if all(home_recent10.get(key) is not None and away_recent10.get(key) is not None
                   for key in ("possessions", "off_rating", "def_rating")):
                recent_game_possessions = (
                    home_recent10["possessions"] + away_recent10["possessions"]
                ) / 2.0
                recent_home_eff = (home_recent10["off_rating"] + away_recent10["def_rating"]) / 2.0
                recent_away_eff = (away_recent10["off_rating"] + home_recent10["def_rating"]) / 2.0
                if 75 <= recent_game_possessions <= 115 and 75 <= recent_home_eff <= 145 and 75 <= recent_away_eff <= 145:
                    recent_possessions_total = recent_game_possessions * (recent_home_eff + recent_away_eff) / 100.0

            row = dict(forecast)
            row.update({
                "venue_total": venue_total,
                "venue_delta": (
                    venue_total - float(forecast["base_total"])
                    if venue_total is not None else 0.0
                ),
                "home_rest_days": home_rest,
                "away_rest_days": away_rest,
                "rest_mean": (home_rest + away_rest) / 2.0,
                "rest_imbalance": abs(home_rest - away_rest),
                "home_games_last_7d": home_load,
                "away_games_last_7d": away_load,
                "recent5_form_delta": (
                    recent5_total - float(forecast["base_total"]) if recent5_total is not None else 0.0
                ),
                "recent10_form_delta": (
                    recent10_total - float(forecast["base_total"]) if recent10_total is not None else 0.0
                ),
                "recent_form_trend": (
                    recent5_total - recent10_total
                    if recent5_total is not None and recent10_total is not None else 0.0
                ),
                "recent_pace_efficiency_delta": (
                    recent_pace_total - float(forecast["pace_total"])
                    if recent_pace_total is not None and forecast.get("pace_available") is True
                    else 0.0
                ),
                "recent_possessions_efficiency_delta": (
                    recent_possessions_total - float(forecast["pace_total"])
                    if recent_possessions_total is not None and forecast.get("pace_available") is True
                    else 0.0
                ),
            })
            feature_rows.append(row)
        prior.append(game)

    return feature_rows


def _blend(row, weight):
    base = float(row["base_total"])
    pace = row.get("pace_total")
    if row.get("pace_available") is not True or pace is None:
        return base
    return base + weight * (float(pace) - base)


def tune_v5_calibration(training_rows):
    candidates = []
    for weight in PACE_BLEND_GRID:
        errors = [
            _blend(row, weight) - float(row["actual_total"])
            for row in training_rows
        ]
        mae = sum(abs(error) for error in errors) / len(errors) if errors else float("inf")
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else float("inf")
        candidates.append((mae, rmse, weight))
    selected_weight = min(candidates)[2] if candidates else 0.0
    errors = [
        _blend(row, selected_weight) - float(row["actual_total"])
        for row in training_rows
    ]
    bias = sum(errors) / len(errors) if errors else 0.0
    return selected_weight, bias


def attach_v5_predictions(rows, weight, bias):
    prepared = []
    for row in rows:
        item = dict(row)
        item["v5_prediction"] = _blend(item, weight) - bias
        prepared.append(item)
    return prepared


def fit_feature_adjustment(training_rows, validation_rows, feature_names, ridge=RIDGE_PENALTY):
    """Fit a standardized ridge correction on training residuals only."""
    if not training_rows or not validation_rows or not feature_names:
        return None
    x_train = np.asarray([[float(row[name]) for name in feature_names] for row in training_rows], dtype=float)
    x_valid = np.asarray([[float(row[name]) for name in feature_names] for row in validation_rows], dtype=float)
    residual = np.asarray([
        float(row["actual_total"]) - float(row["v5_prediction"])
        for row in training_rows
    ], dtype=float)
    means = x_train.mean(axis=0)
    scales = x_train.std(axis=0)
    scales = np.where(scales < 1e-8, 1.0, scales)
    z_train = (x_train - means) / scales
    z_valid = (x_valid - means) / scales
    identity = np.eye(z_train.shape[1], dtype=float)
    beta = np.linalg.solve(z_train.T @ z_train + float(ridge) * identity, z_train.T @ residual)
    predictions = [
        float(row["v5_prediction"]) + float(adjustment)
        for row, adjustment in zip(validation_rows, z_valid @ beta)
    ]
    coefficients = {
        name: round(float(coefficient / scale), 6)
        for name, coefficient, scale in zip(feature_names, beta, scales)
    }
    return {"predictions": predictions, "coefficients": coefficients}


def paired_mae_stability(rows, baseline_predictions, candidate_predictions, resamples=4000, blocks=4):
    """Paired fixture bootstrap and ordered-block consistency for MAE improvement."""
    improvements = [
        abs(float(row["actual_total"]) - float(base))
        - abs(float(row["actual_total"]) - float(candidate))
        for row, base, candidate in zip(rows, baseline_predictions, candidate_predictions)
    ]
    if not improvements:
        return {
            "n": 0, "mean_mae_improvement": None,
            "ci95_lower": None, "ci95_upper": None,
            "positive_chronological_blocks": 0, "chronological_blocks": [],
        }
    n = len(improvements)
    rng = random.Random(20261102 + n)
    means = sorted(
        sum(improvements[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(max(100, int(resamples)))
    )
    lower_index = max(0, min(len(means) - 1, int(0.025 * (len(means) - 1))))
    upper_index = max(0, min(len(means) - 1, int(0.975 * (len(means) - 1))))
    block_results = []
    for index in range(max(1, int(blocks))):
        start = index * n // max(1, int(blocks))
        end = (index + 1) * n // max(1, int(blocks))
        values = improvements[start:end]
        if values:
            block_results.append({
                "block": index + 1,
                "n": len(values),
                "mae_improvement": round(sum(values) / len(values), 4),
                "positive": sum(values) > 0,
            })
    return {
        "n": n,
        "mean_mae_improvement": round(sum(improvements) / n, 4),
        "ci95_lower": round(means[lower_index], 4),
        "ci95_upper": round(means[upper_index], 4),
        "resamples": len(means),
        "positive_chronological_blocks": sum(row["positive"] for row in block_results),
        "chronological_blocks": block_results,
    }


def score_predictions(rows, predictions):
    errors = [
        float(prediction) - float(row["actual_total"])
        for row, prediction in zip(rows, predictions)
    ]
    if not errors:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    n = len(errors)
    return {
        "n": n,
        "mae": round(sum(abs(error) for error in errors) / n, 4),
        "rmse": round(math.sqrt(sum(error * error for error in errors) / n), 4),
        "bias": round(sum(errors) / n, 4),
    }


def _period(rows, key):
    stamps = [parse_time(row.get(key)) for row in rows]
    stamps = [stamp for stamp in stamps if stamp]
    return {
        "n": len(rows),
        "start_utc": min(stamps).isoformat() if stamps else None,
        "end_utc": max(stamps).isoformat() if stamps else None,
    }


def run_experiment(history):
    rows = [
        row for row in build_feature_rows(history)
        if parse_time(row["date"]) < EVALUATION_CUTOFF_UTC
    ]
    training = [
        row for row in rows
        if parse_time(row["date"]) < HISTORICAL_VALIDATION_CUTOFF_UTC
    ]
    validation = [
        row for row in rows
        if HISTORICAL_VALIDATION_CUTOFF_UTC <= parse_time(row["date"]) < EVALUATION_CUTOFF_UTC
    ]
    if len(training) < 100 or len(validation) < 100:
        raise RuntimeError(
            f"Insufficient fixed historical experiment data: train={len(training)}, validation={len(validation)}"
        )

    pace_weight, bias = tune_v5_calibration(training)
    training = attach_v5_predictions(training, pace_weight, bias)
    validation = attach_v5_predictions(validation, pace_weight, bias)
    v5_metrics = score_predictions(validation, [row["v5_prediction"] for row in validation])
    baseline_metrics = score_predictions(validation, [row["baseline_total"] for row in validation])

    feature_sets = {
        "venue_split_only": ["venue_delta"],
        "rest_only": ["rest_mean", "rest_imbalance"],
        "schedule_density_only": ["home_games_last_7d", "away_games_last_7d"],
        "recent5_form_only": ["recent5_form_delta"],
        "recent10_form_only": ["recent10_form_delta"],
        "recent_form_trend_only": ["recent_form_trend"],
        "recent_pace_efficiency_only": ["recent_pace_efficiency_delta"],
        "recent_possessions_efficiency_only": ["recent_possessions_efficiency_delta"],
        "recent_pace_possessions_combined": [
            "recent_pace_efficiency_delta", "recent_possessions_efficiency_delta",
        ],
        "recent_form_possessions_combined": [
            "recent10_form_delta", "recent_possessions_efficiency_delta",
        ],
        "recent_form_schedule_combined": [
            "recent5_form_delta", "recent10_form_delta", "recent_form_trend",
            "home_games_last_7d", "away_games_last_7d",
        ],
        "venue_rest_schedule_combined": [
            "venue_delta", "rest_mean", "rest_imbalance",
            "home_games_last_7d", "away_games_last_7d",
        ],
    }
    candidates = []
    for name, feature_names in feature_sets.items():
        fitted = fit_feature_adjustment(training, validation, feature_names)
        metrics = score_predictions(validation, fitted["predictions"])
        stability = paired_mae_stability(
            validation,
            [row["v5_prediction"] for row in validation],
            fitted["predictions"],
        )
        candidates.append({
            "name": name,
            "features": feature_names,
            "coefficients": fitted["coefficients"],
            "validation": metrics,
            "mae_improvement_vs_v5": round(v5_metrics["mae"] - metrics["mae"], 4),
            "rmse_improvement_vs_v5": round(v5_metrics["rmse"] - metrics["rmse"], 4),
            "paired_mae_stability_vs_v5": stability,
            "abs_bias_within_3_points": abs(metrics["bias"]) <= 3.0,
        })

    candidates.sort(key=lambda row: (
        row["validation"]["mae"],
        row["validation"]["rmse"],
        row["name"],
    ))
    best = candidates[0] if candidates else None
    stability = best.get("paired_mae_stability_vs_v5", {}) if best else {}
    improvement_pass = bool(
        best
        and best["mae_improvement_vs_v5"] > 0
        and best["rmse_improvement_vs_v5"] > 0
        and best["abs_bias_within_3_points"]
        and stability.get("ci95_lower") is not None
        and stability["ci95_lower"] > 0
        and stability.get("positive_chronological_blocks", 0) >= 3
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "experiment": "NBA_TOTALS_V6_HISTORICAL_FEATURE_ABLATION_V3",
        "production_model_unchanged": "nba-total-v5-pace-efficiency-calibrated",
        "prospective_holdout_cutoff_utc": EVALUATION_CUTOFF_UTC.isoformat(),
        "prospective_holdout_used": False,
        "historical_validation_cutoff_utc": HISTORICAL_VALIDATION_CUTOFF_UTC.isoformat(),
        "training_period": _period(training, "date"),
        "historical_validation_period": _period(validation, "date"),
        "v5_calibration_from_training_only": {
            "pace_blend_weight": pace_weight,
            "bias_correction_points": round(bias, 4),
            "training_games": len(training),
        },
        "historical_validation": {
            "v5": v5_metrics,
            "rolling_90_day_baseline": baseline_metrics,
            "candidate_features": candidates,
        },
        "candidate_decision": (
            "V6_CANDIDATE_FOR_PROSPECTIVE_REVIEW"
            if improvement_pass else "KEEP_V5_BASELINE_NO_FEATURE_UPGRADE"
        ),
        "decision_rule": "A feature candidate must improve MAE and RMSE vs v5, have absolute bias <=3, a positive lower 95% paired fixture-bootstrap bound for MAE improvement, and positive MAE improvement in at least 3 of 4 chronological validation blocks. Passing only authorizes prospective review; it does not qualify betting or change production.",
        "market_prices_used_as_model_inputs": False,
        "note": "Historical validation is for feature selection only. The fixed post-2026-11-02 prospective holdout remains untouched and the NBA release gate remains RESEARCH_ONLY.",
    }


def main():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    report = run_experiment(history)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": report["experiment"],
        "training_games": report["training_period"]["n"],
        "validation_games": report["historical_validation_period"]["n"],
        "v5_validation": report["historical_validation"]["v5"],
        "candidate_decision": report["candidate_decision"],
        "best_candidate": report["historical_validation"]["candidate_features"][0] if report["historical_validation"]["candidate_features"] else None,
        "output": str(OUTPUT.relative_to(ROOT)),
    }, indent=2))


if __name__ == "__main__":
    main()
