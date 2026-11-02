#!/usr/bin/env python3
"""Research-only nonlinear NBA totals candidate experiment.

Uses only pre-tip historical team data, keeps SportyBet prices out of model
features, and leaves the production V5 model and frozen prospective holdout
untouched. A passing candidate is eligible for prospective review only.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline

from expansion_pipeline import dt as parse_time
from nba_totals_walk_forward import (
    EVALUATION_CUTOFF_UTC,
    HISTORY,
    clean_history,
)
from nba_totals_feature_experiment import (
    HISTORICAL_VALIDATION_CUTOFF_UTC,
    attach_v5_predictions,
    build_feature_rows,
    paired_mae_stability,
    recent_team_stats,
    score_predictions,
    tune_v5_calibration,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "nba_totals_nonlinear_candidate_experiment.json"
MIN_TRAINING = 300
MIN_VALIDATION = 100
BOOTSTRAP_RESAMPLES = 4000

FEATURES = (
    "v5_prediction",
    "base_total",
    "pace_total",
    "baseline_total",
    "venue_delta",
    "rest_mean",
    "rest_imbalance",
    "home_games_last_7d",
    "away_games_last_7d",
    "recent5_form_delta",
    "recent10_form_delta",
    "recent_form_trend",
    "recent_pace_efficiency_delta",
    "recent_possessions_efficiency_delta",
    "home_recent5_pf",
    "home_recent5_pa",
    "away_recent5_pf",
    "away_recent5_pa",
    "home_recent10_pf",
    "home_recent10_pa",
    "away_recent10_pf",
    "away_recent10_pa",
    "home_recent10_pace",
    "away_recent10_pace",
    "home_recent10_off_rating",
    "away_recent10_off_rating",
    "home_recent10_def_rating",
    "away_recent10_def_rating",
    "home_recent10_possessions",
    "away_recent10_possessions",
    "recent10_matchup_total",
    "recent10_pace_efficiency_total",
)


def split_by_cutoff(rows, cutoff):
    """Chronological split; equality belongs to the later period."""
    point = parse_time(cutoff)
    before, after = [], []
    for row in rows:
        stamp = parse_time(row.get("date"))
        if stamp is None:
            continue
        (before if stamp < point else after).append(row)
    return before, after


def _finite(value, fallback=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def build_nonlinear_feature_rows(history):
    """Add individual-team rolling inputs while preserving strict pre-tip timing."""
    clean = clean_history(history)
    by_event = {row["event_id"]: row for row in clean}
    base_rows = {row["event_id"]: row for row in build_feature_rows(clean)}
    enriched = []

    for game in clean:
        row = base_rows.get(game["event_id"])
        if row is not None:
            cutoff = game["date"]
            h5 = recent_team_stats(game["home"], clean[:clean.index(game)], cutoff, window=5) or {}
            a5 = recent_team_stats(game["away"], clean[:clean.index(game)], cutoff, window=5) or {}
            h10 = recent_team_stats(game["home"], clean[:clean.index(game)], cutoff, window=10) or {}
            a10 = recent_team_stats(game["away"], clean[:clean.index(game)], cutoff, window=10) or {}
            item = dict(row)
            for side, stats in (("home_recent5", h5), ("away_recent5", a5)):
                for key in ("pf", "pa"):
                    item[f"{side}_{key}"] = stats.get(key)
            for side, stats in (("home_recent10", h10), ("away_recent10", a10)):
                for key in ("pf", "pa", "pace", "off_rating", "def_rating", "possessions"):
                    item[f"{side}_{key}"] = stats.get(key)

            required = (h10.get("pf"), h10.get("pa"), a10.get("pf"), a10.get("pa"))
            item["recent10_matchup_total"] = (
                (float(h10["pf"]) + float(a10["pa"]) +
                 float(a10["pf"]) + float(h10["pa"])) / 2.0
                if all(value is not None for value in required) else None
            )
            pace_keys = ("pace", "off_rating", "def_rating")
            if all(h10.get(key) is not None and a10.get(key) is not None for key in pace_keys):
                pace = (float(h10["pace"]) + float(a10["pace"])) / 2.0
                home_eff = (float(h10["off_rating"]) + float(a10["def_rating"])) / 2.0
                away_eff = (float(a10["off_rating"]) + float(h10["def_rating"])) / 2.0
                item["recent10_pace_efficiency_total"] = pace * (home_eff + away_eff) / 100.0
            else:
                item["recent10_pace_efficiency_total"] = None
            enriched.append(item)

    return sorted(enriched, key=lambda row: (str(row["date"]), str(row["event_id"])))


def _matrix(rows):
    return np.asarray([
        [_finite(row.get(name), np.nan) for name in FEATURES]
        for row in rows
    ], dtype=float)


def _candidate_models():
    return [
        ("hist_gradient_boosting", {
            "max_iter": 80, "learning_rate": 0.04, "max_leaf_nodes": 7,
            "min_samples_leaf": 25, "l2_regularization": 12.0,
            "random_state": 20261102
        }),
        ("extra_trees", {
            "n_estimators": 350, "max_depth": 5, "min_samples_leaf": 20,
            "max_features": 0.8, "n_jobs": -1, "random_state": 20261102
        }),
        ("random_forest", {
            "n_estimators": 350, "max_depth": 5, "min_samples_leaf": 20,
            "max_features": 0.8, "n_jobs": -1, "random_state": 20261102
        }),
    ]


def _estimator(name, params):
    if name == "hist_gradient_boosting":
        model = HistGradientBoostingRegressor(**params)
    elif name == "extra_trees":
        model = ExtraTreesRegressor(**params)
    elif name == "random_forest":
        model = RandomForestRegressor(**params)
    else:
        raise ValueError("Unknown model candidate: " + str(name))
    return make_pipeline(SimpleImputer(strategy="median"), model)


def _inner_cv_score(name, params, rows, x, residual):
    splitter = TimeSeriesSplit(n_splits=4)
    scores = []
    for train_index, valid_index in splitter.split(x):
        estimator = _estimator(name, params)
        estimator.fit(x[train_index], residual[train_index])
        correction = estimator.predict(x[valid_index])
        predictions = [
            float(rows[index]["v5_prediction"]) + float(adjustment)
            for index, adjustment in zip(valid_index, correction)
        ]
        actual = [float(rows[index]["actual_total"]) for index in valid_index]
        scores.append(sum(abs(a - p) for a, p in zip(actual, predictions)) / len(actual))
    return round(sum(scores) / len(scores), 6), [round(value, 6) for value in scores]


def run_experiment(history):
    rows = build_nonlinear_feature_rows(history)
    rows = [row for row in rows if parse_time(row["date"]) < EVALUATION_CUTOFF_UTC]
    training, validation = split_by_cutoff(rows, HISTORICAL_VALIDATION_CUTOFF_UTC)
    if len(training) < MIN_TRAINING or len(validation) < MIN_VALIDATION:
        raise RuntimeError(
            f"Insufficient frozen historical data: training={len(training)}, validation={len(validation)}"
        )

    weight, bias = tune_v5_calibration(training)
    training = attach_v5_predictions(training, weight, bias)
    validation = attach_v5_predictions(validation, weight, bias)
    x_train, x_valid = _matrix(training), _matrix(validation)
    residual = np.asarray([
        float(row["actual_total"]) - float(row["v5_prediction"])
        for row in training
    ], dtype=float)
    v5_predictions = [float(row["v5_prediction"]) for row in validation]
    v5_metrics = score_predictions(validation, v5_predictions)
    baseline_metrics = score_predictions(validation, [row["baseline_total"] for row in validation])

    candidates = []
    fitted = []
    for name, params in _candidate_models():
        cv_mae, fold_scores = _inner_cv_score(name, params, training, x_train, residual)
        estimator = _estimator(name, params)
        estimator.fit(x_train, residual)
        corrections = estimator.predict(x_valid)
        predictions = [base + float(correction) for base, correction in zip(v5_predictions, corrections)]
        metrics = score_predictions(validation, predictions)
        stability = paired_mae_stability(
            validation, v5_predictions, predictions, resamples=BOOTSTRAP_RESAMPLES, blocks=4
        )
        candidates.append({
            "name": name,
            "parameters": params,
            "inner_chronological_cv_mae": cv_mae,
            "inner_fold_mae": fold_scores,
            "validation": metrics,
            "mae_improvement_vs_v5": round(v5_metrics["mae"] - metrics["mae"], 4),
            "rmse_improvement_vs_v5": round(v5_metrics["rmse"] - metrics["rmse"], 4),
            "paired_mae_stability_vs_v5": stability,
            "abs_bias_within_3_points": abs(float(metrics["bias"])) <= 3.0,
        })
        fitted.append((cv_mae, name, predictions))

    candidates.sort(key=lambda row: (row["inner_chronological_cv_mae"], row["name"]))
    chosen_name = candidates[0]["name"]
    chosen_predictions = next(pred for _, name, pred in fitted if name == chosen_name)
    chosen = next(row for row in candidates if row["name"] == chosen_name)
    stability = chosen["paired_mae_stability_vs_v5"]
    review_pass = bool(
        chosen["mae_improvement_vs_v5"] > 0
        and chosen["rmse_improvement_vs_v5"] > 0
        and chosen["abs_bias_within_3_points"]
        and stability.get("ci95_lower") is not None
        and stability["ci95_lower"] > 0
        and stability.get("positive_chronological_blocks", 0) >= 3
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "experiment": "NBA_TOTALS_NONLINEAR_RESIDUAL_CANDIDATE_V1",
        "production_model_unchanged": "nba-total-v5-pace-efficiency-calibrated",
        "prospective_holdout_cutoff_utc": EVALUATION_CUTOFF_UTC.isoformat(),
        "prospective_holdout_used": False,
        "market_prices_used_as_model_inputs": False,
        "feature_columns": list(FEATURES),
        "feature_market_blind": True,
        "training_period": {
            "n": len(training), "start_utc": training[0]["date"], "end_utc": training[-1]["date"]
        },
        "historical_validation_period": {
            "n": len(validation), "start_utc": validation[0]["date"], "end_utc": validation[-1]["date"]
        },
        "v5_calibration_from_training_only": {
            "pace_blend_weight": weight, "bias_correction_points": round(bias, 4)
        },
        "historical_validation": {
            "v5": v5_metrics,
            "rolling_90_day_baseline": baseline_metrics,
            "selected_nonlinear_candidate": chosen,
            "candidate_results": candidates,
            "selected_predictions": chosen_predictions
        },
        "candidate_decision": (
            "NONLINEAR_CANDIDATE_FOR_PROSPECTIVE_REVIEW"
            if review_pass else "KEEP_V5_NO_NONLINEAR_PROMOTION"
        ),
        "release_decision": "RESEARCH_ONLY",
        "note": "This fixed historical validation can select a prospective candidate, but cannot release betting. The frozen post-cutoff sample and all SportyBet ROI/CLV gates remain untouched."
    }


def main():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    report = run_experiment(history)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    chosen = report["historical_validation"]["selected_nonlinear_candidate"]
    print(json.dumps({
        "experiment": report["experiment"],
        "training": report["training_period"]["n"],
        "validation": report["historical_validation_period"]["n"],
        "v5_mae": report["historical_validation"]["v5"]["mae"],
        "candidate": chosen["name"],
        "candidate_mae": chosen["validation"]["mae"],
        "candidate_mae_ci95_lower": chosen["paired_mae_stability_vs_v5"]["ci95_lower"],
        "decision": report["candidate_decision"],
        "release": report["release_decision"]
    }, indent=2))


if __name__ == "__main__":
    main()
