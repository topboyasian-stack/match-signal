#!/usr/bin/env python3
"""Tests for the research-only empirical-residual NBA value experiment."""
from datetime import datetime, timedelta, timezone

from nba_totals_probability_value_experiment import (
    _settlement_probabilities,
    _value_decision,
    run_experiment,
)
from nba_totals_walk_forward import EVALUATION_CUTOFF_UTC


def test_probability_mass_and_integer_push():
    probabilities = _settlement_probabilities(
        200.0, 200.0, [-2, -1, 0, 0, 1, 2]
    )
    assert abs(probabilities["over"] + probabilities["under"] + probabilities["push"] - 1.0) < 1e-9
    assert probabilities == {"over": 2 / 6, "under": 2 / 6, "push": 2 / 6}


def test_value_decision_rejects_calibration_failure():
    result = _value_decision(
        200.0, 200.5, 1.95, 1.95, [5.0] * 100,
        calibration_ok=False, resamples=200,
    )
    assert result["decision"] == "NO BET"
    assert result["decision_is_authorized_for_betting"] is False
    assert result["calibration_check"] == "FAIL"


def test_value_decision_requires_positive_lower_bound_and_edge():
    result = _value_decision(
        200.0, 200.5, 1.90, 1.90, [10.0] * 120,
        calibration_ok=True, resamples=500,
    )
    assert result["decision"] == "OVER VALUE"
    assert result["bootstrap_95_lower_bound"]["over_expected_value"] >= 0.03
    assert result["bootstrap_95_lower_bound"]["over_probability_edge"] >= 0.04


def test_push_does_not_count_as_a_loss():
    result = _value_decision(
        200.0, 200.0, 1.90, 1.90, [0.0] * 120,
        calibration_ok=True, resamples=500,
    )
    assert result["model_probability"]["push"] == 1.0
    assert result["expected_value_per_unit"]["over"] == 0.0
    assert result["expected_value_per_unit"]["under"] == 0.0
    assert result["decision"] == "NO BET"


def synthetic_history():
    teams = [f"T{i}" for i in range(12)]
    start = datetime(2025, 8, 1, tzinfo=timezone.utc)
    rows = []
    for day in range(450):
        stamp = start + timedelta(days=day)
        for game_index in range(4):
            home = teams[(day + game_index * 2) % len(teams)]
            away = teams[(day + game_index * 2 + 1) % len(teams)]
            home_strength = 105 + teams.index(home) * 1.1
            away_strength = 104 + teams.index(away) * 0.9
            variation = ((day * 7 + game_index * 13) % 21) - 10
            rows.append({
                "event_id": f"value-synthetic-{day}-{game_index}",
                "date": (stamp + timedelta(hours=game_index * 2)).isoformat(),
                "home": home, "away": away,
                "home_score": home_strength + variation,
                "away_score": away_strength - variation * 0.4,
            })
    return rows


def test_full_report_keeps_prospective_holdout_locked():
    report = run_experiment(synthetic_history(), [], [], now=EVALUATION_CUTOFF_UTC)
    assert report["paper_only"] is True
    assert report["prospective_holdout_used_for_calibration"] is False
    assert report["live_value_decisions_authorized"] is False
    assert report["release_decision"] == "RESEARCH_ONLY"
    assert report["settled_v5_market_count"] == 0
    assert report["historical_value_signal_summary"]["n"] == 0
    assert report["historical_market_line_backtest_available"] is False
    assert report["archived_history_rows_with_any_market_data"] == 0
    assert report["model_projection_market_blind"] is True


if __name__ == "__main__":
    test_probability_mass_and_integer_push()
    test_value_decision_rejects_calibration_failure()
    test_value_decision_requires_positive_lower_bound_and_edge()
    test_push_does_not_count_as_a_loss()
    test_full_report_keeps_prospective_holdout_locked()
    print("NBA totals probability/value experiment tests: PASS (5 groups)")
