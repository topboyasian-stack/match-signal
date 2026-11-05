"""Offline leakage and probability-contract tests for the football ensemble."""
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from football_prequential_ensemble import (  # noqa: E402
    CompetitionElo,
    apply_blend,
    blend_probs,
    fit_development_blend,
    fit_development_accuracy_blend,
    normalize_probs,
    safe_history_cutoff,
    _model_name_for_development,
    global_blend_scope_gate,
)


def test_probability_vectors_are_normalized():
    result = normalize_probs({"p1": 2, "draw": 1, "p2": 1})
    assert abs(sum(result.values()) - 1.0) < 1e-12
    assert result["p1"] == 0.5

def test_history_cutoff_uses_conservative_settlement_buffer():
    forecast_at = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    cutoff = safe_history_cutoff(forecast_at)
    assert cutoff == forecast_at - timedelta(hours=4)
    assert safe_history_cutoff(None) is None


def test_elo_does_not_use_same_kickoff_or_future_results():
    cutoff = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    history = [
        {
            "sport": "football", "league": "Premier League", "event_id": "before",
            "start_time": (cutoff - timedelta(days=1)).isoformat(),
            "player_1": "Arsenal", "player_2": "Chelsea",
            "final_score": [4, 0], "settled": True,
        },
        {
            "sport": "football", "league": "Premier League", "event_id": "same",
            "start_time": cutoff.isoformat(),
            "player_1": "Arsenal", "player_2": "Chelsea",
            "final_score": [0, 4], "settled": True,
        },
        {
            "sport": "football", "league": "Premier League", "event_id": "future",
            "start_time": (cutoff + timedelta(days=1)).isoformat(),
            "player_1": "Arsenal", "player_2": "Chelsea",
            "final_score": [0, 8], "settled": True,
        },
    ]
    elo = CompetitionElo(history)
    elo.advance_before(cutoff)
    assert elo.index == 1
    after_one = elo.predict("Premier League", "Arsenal", "Chelsea")
    elo.advance_before(cutoff + timedelta(seconds=1))
    assert elo.index == 2
    after_same = elo.predict("Premier League", "Arsenal", "Chelsea")
    assert after_one != after_same
    assert elo.index == 2  # the future match remains unavailable


def test_blend_weights_are_probabilities_and_apply_consistently():
    published = {"p1": 0.5, "draw": 0.25, "p2": 0.25}
    dixon = {"p1": 0.6, "draw": 0.2, "p2": 0.2}
    elo = {"p1": 0.4, "draw": 0.3, "p2": 0.3}
    result = blend_probs([published, dixon, elo], [0.2, 0.5, 0.3])
    assert abs(sum(result.values()) - 1.0) < 1e-12
    row = {"published": published, "dixon_coles": dixon, "elo": elo}
    assert apply_blend(row, [0.2, 0.5, 0.3]) == result


def test_development_fit_uses_only_passed_development_rows():
    rows = []
    for index in range(40):
        rows.append({
            "published": {"p1": 0.34, "draw": 0.33, "p2": 0.33},
            "dixon_coles": {"p1": 0.80, "draw": 0.10, "p2": 0.10},
            "elo": {"p1": 0.45, "draw": 0.30, "p2": 0.25},
            "actual": "p1",
        })
    fit = fit_development_blend(rows)
    assert fit["development_n"] == 40
    assert abs(sum(fit["weights"]) - 1.0) < 1e-12
    assert fit["weights"][1] >= fit["weights"][0]


def test_accuracy_first_blend_fits_on_development_rows_only():
    rows = []
    for index in range(40):
        rows.append({
            "published": {"p1": 0.40, "draw": 0.30, "p2": 0.30},
            "dixon_coles": {"p1": 0.60, "draw": 0.20, "p2": 0.20},
            "elo": {"p1": 0.70, "draw": 0.15, "p2": 0.15},
            "actual": "p1" if index < 24 else "draw",
        })
    fit = fit_development_accuracy_blend(rows)
    assert fit["development_n"] == 40
    assert len(fit["weights"]) == 3
    assert abs(sum(fit["weights"]) - 1.0) < 1e-12
    assert fit["candidate_count"] == 66
    assert fit["objective"].startswith("maximum development top-pick accuracy")



def test_competition_model_choice_uses_development_rows_only():
    rows = []
    for index in range(40):
        rows.append({
            "published": {"p1": 0.34, "draw": 0.33, "p2": 0.33},
            "dixon_coles": {"p1": 0.45, "draw": 0.30, "p2": 0.25},
            "elo": {"p1": 0.80, "draw": 0.10, "p2": 0.10},
            "dixon_elo_blend": {"p1": 0.60, "draw": 0.20, "p2": 0.20},
            "fitted_blend": {"p1": 0.55, "draw": 0.25, "p2": 0.20},
            "actual": "p1",
        })
    selected, metrics = _model_name_for_development(rows)
    assert selected == "elo"
    assert metrics["elo"]["n"] == 40



def test_global_blend_scope_uses_global_fit_and_independent_holdout_not_local_dev_count():
    published = {"brier": 0.62, "log_loss": 1.08, "accuracy": 0.50}
    improving = {"brier": 0.59, "log_loss": 1.02, "accuracy": 0.50}

    # The model weights came from the global development set. A competition can
    # use them with a sufficient independent holdout even when its own slice of
    # the development data is smaller than the per-competition-fit minimum.
    ucl_like = global_blend_scope_gate(improving, published, 24, 36)
    assert ucl_like["passed"] is True
    assert ucl_like["competition_development_n"] == 24
    assert ucl_like["competition_development_sample_required"] is False
    assert ucl_like["competition_development_sample_informational_passed"] is False
    assert ucl_like["holdout_n"] == 36

    accuracy_drop = {"brier": 0.57, "log_loss": 0.95, "accuracy": 0.48}
    failed_accuracy = global_blend_scope_gate(accuracy_drop, published, 24, 36)
    assert failed_accuracy["passed"] is False
    assert failed_accuracy["accuracy_passed"] is False

    no_brier_lift = {"brier": 0.618, "log_loss": 1.0, "accuracy": 0.50}
    failed_brier = global_blend_scope_gate(no_brier_lift, published, 24, 36)
    assert failed_brier["passed"] is False
    assert failed_brier["brier_passed"] is False

    small_holdout = global_blend_scope_gate(improving, published, 100, 19)
    assert small_holdout["passed"] is False
    assert small_holdout["holdout_sample_passed"] is False

if __name__ == "__main__":
    test_probability_vectors_are_normalized()
    test_history_cutoff_uses_conservative_settlement_buffer()
    test_elo_does_not_use_same_kickoff_or_future_results()
    test_blend_weights_are_probabilities_and_apply_consistently()
    test_development_fit_uses_only_passed_development_rows()
    test_accuracy_first_blend_fits_on_development_rows_only()
    test_competition_model_choice_uses_development_rows_only()
    test_global_blend_scope_uses_global_fit_and_independent_holdout_not_local_dev_count()
    print("Football prequential ensemble tests passed.")
