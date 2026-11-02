#!/usr/bin/env python3
"""Offline tests for historical-only NBA totals v6 feature experiments."""
from datetime import datetime, timedelta, timezone

from nba_totals_feature_experiment import (
    venue_total_from_history,
    fit_feature_adjustment,
    score_predictions,
    run_experiment,
)
from nba_totals_walk_forward import EVALUATION_CUTOFF_UTC


def test_venue_split_does_not_use_future_games():
    history = [
        {"date": "2026-01-01T00:00:00+00:00", "home": "A", "away": "B",
         "home_score": 110, "away_score": 100},
        {"date": "2026-01-02T00:00:00+00:00", "home": "B", "away": "A",
         "home_score": 90, "away_score": 120},
    ]
    cutoff = "2026-01-03T00:00:00+00:00"
    baseline = venue_total_from_history("A", "B", history, cutoff)
    with_future = venue_total_from_history(
        "A", "B",
        history + [{
            "date": "2026-01-04T00:00:00+00:00", "home": "A", "away": "B",
            "home_score": 300, "away_score": 300,
        }],
        cutoff,
    )
    assert baseline == with_future


def test_ridge_feature_adjustment_uses_training_fit():
    training = [
        {"x": float(i), "v5_prediction": 200.0, "actual_total": 200.0 + 2.0 * i}
        for i in range(1, 40)
    ]
    validation = [{"x": float(i), "v5_prediction": 200.0} for i in range(40, 50)]
    fitted = fit_feature_adjustment(training, validation, ["x"], ridge=0.01)
    assert fitted is not None
    assert len(fitted["predictions"]) == len(validation)
    assert all(value > 200.0 for value in fitted["predictions"])
    assert abs(fitted["coefficients"]["x"] - 2.0) < 0.1


def test_metric_calculation_and_frozen_prospective_boundary():
    rows = [
        {"actual_total": 210.0},
        {"actual_total": 220.0},
    ]
    assert score_predictions(rows, [211.0, 218.0]) == {
        "n": 2, "mae": 1.5, "rmse": 1.5811, "bias": -0.5
    }
    assert EVALUATION_CUTOFF_UTC.isoformat() == "2026-11-02T02:00:00+00:00"


def synthetic_history():
    teams = ["A", "B", "C", "D", "E", "F", "G", "H"]
    start = datetime(2025, 10, 1, tzinfo=timezone.utc)
    rows = []
    for day in range(365):
        stamp = start + timedelta(days=day)
        for game_index in range(2):
            home = teams[(day + game_index * 2) % len(teams)]
            away = teams[(day + game_index * 2 + 1) % len(teams)]
            home_strength = 106 + teams.index(home) * 1.4
            away_strength = 105 + teams.index(away) * 1.1
            variation = ((day * 7 + game_index * 11) % 19) - 9
            rows.append({
                "event_id": f"synthetic-{day}-{game_index}",
                "date": (stamp + timedelta(hours=game_index * 3)).isoformat(),
                "home": home, "away": away,
                "home_score": home_strength + variation,
                "away_score": away_strength - variation * 0.45,
            })
    return rows


def test_full_experiment_uses_historical_validation_and_preserves_future_holdout():
    report = run_experiment(synthetic_history())
    assert report["prospective_holdout_used"] is False
    assert report["prospective_holdout_cutoff_utc"] == "2026-11-02T02:00:00+00:00"
    assert report["training_period"]["n"] >= 100
    assert report["historical_validation_period"]["n"] >= 100
    assert report["production_model_unchanged"] == "nba-total-v5-pace-efficiency-calibrated"
    assert report["market_prices_used_as_model_inputs"] is False
    assert len(report["historical_validation"]["candidate_features"]) == 4


if __name__ == "__main__":
    test_venue_split_does_not_use_future_games()
    test_ridge_feature_adjustment_uses_training_fit()
    test_metric_calculation_and_frozen_prospective_boundary()
    test_full_experiment_uses_historical_validation_and_preserves_future_holdout()
    print("NBA totals v6 feature experiment tests: PASS (4 groups)")
