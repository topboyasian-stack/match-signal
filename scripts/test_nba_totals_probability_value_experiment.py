#!/usr/bin/env python3
"""Tests for the research-only empirical-residual NBA value experiment."""
from datetime import datetime, timedelta, timezone

from nba_totals_probability_value_experiment import (
    _settlement_probabilities,
    _value_decision,
    snapshot_clv_audit,
    prospective_snapshot_coverage,
    probability_score_summary,
    historical_probability_validation,
    run_experiment,
)
from nba_totals_walk_forward import EVALUATION_CUTOFF_UTC


def test_probability_mass_and_integer_push():
    probabilities = _settlement_probabilities(
        200.0, 200.0, [-2, -1, 0, 0, 1, 2]
    )
    assert abs(probabilities["over"] + probabilities["under"] + probabilities["push"] - 1.0) < 1e-9
    assert probabilities == {"over": 2 / 6, "under": 2 / 6, "push": 2 / 6}


def test_snapshot_clv_uses_only_later_exact_pregame_quote():
    def snapshot(snapshot_id, published, quote, line, over, under, event="event-clv"):
        return {
            "event_id": event,
            "start_time": "2026-11-03T20:00:00+00:00",
            "published_at": published,
            "publication_snapshot_id": snapshot_id,
            "markets": {"total_ou": {
                "market_id": "225",
                "source": "SportyBet Nigeria",
                "sportybet_event_id": "sr:match:clv",
                "quote_capture_basis": "SportyBet API response observed_at",
                "quote_timestamp": quote,
                "line": line,
                "over_odds": over,
                "under_odds": under,
            }},
        }

    opening = snapshot(
        "open-id", "2026-11-03T17:00:03+00:00",
        "2026-11-03T17:00:00+00:00", 220.5, 1.90, 1.90,
    )
    latest = snapshot(
        "close-id", "2026-11-03T19:30:03+00:00",
        "2026-11-03T19:30:00+00:00", 219.5, 1.88, 1.92,
    )
    after_tip = snapshot(
        "after-id", "2026-11-03T20:00:03+00:00",
        "2026-11-03T20:00:00+00:00", 218.5, 1.80, 2.00,
    )
    bet = {
        "event_id": "event-clv",
        "player_1": "A", "player_2": "B",
        "pick": "over",
        "publication_snapshot_id": "open-id",
    }
    report = snapshot_clv_audit([bet], [opening, latest, after_tip])
    assert report["near_close_observations"] == 1
    assert report["positive_probability_clv_n"] == 1
    assert report["positive_line_clv_n"] == 1
    fixture = report["fixtures"][0]
    assert fixture["clv_status"] == "NEAR_CLOSE_CAPTURED"
    assert fixture["latest_pregame"]["snapshot_id"] == "close-id"
    assert fixture["latest_pregame"]["line"] == 219.5
    assert fixture["is_official_bookmaker_close"] is False


def test_snapshot_clv_excludes_old_update_from_near_close_sample():
    opening = {
        "event_id": "event-old",
        "start_time": "2026-11-03T20:00:00+00:00",
        "published_at": "2026-11-03T17:00:03+00:00",
        "publication_snapshot_id": "old-open",
        "markets": {"total_ou": {
            "market_id": "225", "source": "SportyBet Nigeria",
            "sportybet_event_id": "sr:match:old",
            "quote_capture_basis": "SportyBet API response observed_at",
            "quote_timestamp": "2026-11-03T17:00:00+00:00",
            "line": 220.5, "over_odds": 1.9, "under_odds": 1.9,
        }},
    }
    update = {
        **opening,
        "published_at": "2026-11-03T18:00:03+00:00",
        "publication_snapshot_id": "old-update",
        "markets": {"total_ou": {
            **opening["markets"]["total_ou"],
            "quote_timestamp": "2026-11-03T18:00:00+00:00",
            "line": 221.5,
        }},
    }
    report = snapshot_clv_audit(
        [{"event_id": "event-old", "pick": "under", "publication_snapshot_id": "old-open"}],
        [opening, update],
        close_window_minutes=45,
    )
    assert report["near_close_observations"] == 0
    assert report["fixtures"][0]["clv_status"] == "LATER_PREGAME_CAPTURE_OUTSIDE_CLOSE_WINDOW"


def test_historical_probability_validation_uses_only_synthetic_lines():
    rows = [
        {
            "event_id": f"prob-{i}",
            "forecast_total": 220.0 + (i % 5),
            "actual_total": 220.0 + (i % 5) + ((i % 9) - 4),
        }
        for i in range(120)
    ]
    calibration_residuals = [((i % 15) - 7) * 1.2 for i in range(200)]
    result = historical_probability_validation(rows, calibration_residuals)
    assert result["unique_validation_games"] == 120
    assert result["synthetic_game_line_observations"] + result["pushes_excluded"] == 120 * 7
    assert len(result["by_line_offset"]) == 7
    assert result["not_a_sportybet_market_backtest"] is True
    clustered = result["event_clustered_score_diagnostics"]
    assert clustered["unique_validation_games_scored"] == 120
    assert clustered["synthetic_lines_treated_as_independent_games"] is False
    assert len(clustered["brier_difference_cluster_bootstrap_95_ci"]) == 2
    assert result["model_brier"] is not None
    assert result["coinflip_baseline_brier"] == 0.25


def test_prospective_probability_sample_requires_exact_snapshot_linkage():
    cutoff = EVALUATION_CUTOFF_UTC
    published = "2026-11-03T17:00:03+00:00"
    start = "2026-11-03T20:00:00+00:00"
    quote_time = "2026-11-03T17:00:00+00:00"
    snapshot = {
        "event_id": "event-prospective",
        "start_time": start,
        "published_at": published,
        "totals_model_version": "nba-total-v5-pace-efficiency-calibrated",
        "publication_snapshot_id": "prospective-snapshot-1",
        "publication_snapshot_verified": True,
        "publication_snapshot_kind": "immutable_sportybet_market_225_revision",
        "markets": {"total_ou": {
            "market_id": "225",
            "source": "SportyBet Nigeria",
            "sportybet_event_id": "sr:match:prospective",
            "quote_capture_basis": "SportyBet API response observed_at",
            "quote_timestamp": quote_time,
            "line": 220.5,
            "over_odds": 1.91,
            "under_odds": 1.89,
        }},
    }
    record = {
        "event_id": "event-prospective",
        "start_time": start,
        "published_at": published,
        "publication_snapshot_id": "prospective-snapshot-1",
        "quote_timestamp": quote_time,
        "market_id": "225",
        "market_source": "SportyBet Nigeria",
        "sportybet_event_id": "sr:match:prospective",
        "quote_capture_basis": "SportyBet API response observed_at",
        "line": 220.5,
        "over_odds": 1.91,
        "under_odds": 1.89,
    }
    report, event_ids = prospective_snapshot_coverage([record], [snapshot], cutoff)
    assert event_ids == {"event-prospective"}
    assert report["prospective_verified_fresh_market_225_snapshot_records"] == 1
    assert report["prospective_settled_selections_with_exact_snapshot_match"] == 1
    assert report["prospective_settled_selections_missing_or_mismatched_snapshot"] == 0
    assert report["cutoff_utc"] == cutoff.isoformat()

    altered_record = {**record, "over_odds": 2.01}
    bad_report, bad_ids = prospective_snapshot_coverage([altered_record], [snapshot], cutoff)
    assert bad_ids == set()
    assert bad_report["prospective_settled_selections_missing_or_mismatched_snapshot"] == 1
    assert bad_report["snapshot_linkage_failures"][0]["reason"] == "SNAPSHOT_FIELDS_DO_NOT_MATCH_SETTLEMENT_RECORD"


def test_probability_scores_compare_model_and_no_vig_market_descriptively():
    rows = [
        {
            "event_id": "a", "settled_result": "over",
            "model_probability": {"over": 0.65, "under": 0.35},
            "market_no_vig_probability": {"over": 0.50, "under": 0.50},
        },
        {
            "event_id": "b", "settled_result": "under",
            "model_probability": {"over": 0.40, "under": 0.60},
            "market_no_vig_probability": {"over": 0.50, "under": 0.50},
        },
    ]
    result = probability_score_summary(rows)
    assert result["n"] == 2
    assert result["model_brier"] < result["market_no_vig_brier"]
    assert result["model_log_loss"] < result["market_no_vig_log_loss"]
    assert result["sufficient_for_probability_validation"] is False
    assert len(result["over_probability_buckets"]) == 2


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
    assert report["prospective_probability_score_summary"]["n"] == 0
    assert report["prospective_probability_score_summary"]["sufficient_for_probability_validation"] is False
    assert report["prospective_pregame_snapshot_coverage"]["prospective_settled_selections_with_exact_snapshot_match"] == 0


if __name__ == "__main__":
    test_probability_mass_and_integer_push()
    test_snapshot_clv_uses_only_later_exact_pregame_quote()
    test_snapshot_clv_excludes_old_update_from_near_close_sample()
    test_historical_probability_validation_uses_only_synthetic_lines()
    test_prospective_probability_sample_requires_exact_snapshot_linkage()
    test_probability_scores_compare_model_and_no_vig_market_descriptively()
    test_value_decision_rejects_calibration_failure()
    test_value_decision_requires_positive_lower_bound_and_edge()
    test_push_does_not_count_as_a_loss()
    test_full_report_keeps_prospective_holdout_locked()
    print("NBA totals probability/value experiment tests: PASS (10 groups)")
