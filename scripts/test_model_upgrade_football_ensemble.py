"""Offline integration contract for validated football model updates."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_upgrade import (  # noqa: E402
    _competition_elo_probabilities,
    apply_validated_competition_probabilities,
    build_validation_audit,
)


def test_validated_scope_updates_forecast_but_preserves_all_release_flags():
    row = {
        "sport": "football",
        "probabilities": {"p1": 0.40, "draw": 0.30, "p2": 0.30},
        "calibrated_probabilities": {"p1": 0.40, "draw": 0.30, "p2": 0.30},
        "pick": "p1",
        "confidence": 0.40,
        "live_eligible": False,
        "betting_qualified": False,
        "qualified_for_builder": False,
        "builder_eligible": False,
        "real_money_eligible": False,
        "paper_only": True,
    }
    scope = {
        "status": "RESEARCH_SCOPE_VALIDATED",
        "selected_model": "elo",
        "development_n": 70,
        "holdout_n": 22,
        "development_metrics": {"brier": 0.50},
        "holdout_metrics": {"brier": 0.52, "accuracy": 0.60, "log_loss": 0.80},
        "published_holdout_metrics": {"brier": 0.60, "accuracy": 0.55, "log_loss": 0.90},
        "evidence": "development-selected model passed untouched chronological holdout",
    }
    selected = {"p1": 0.20, "draw": 0.20, "p2": 0.60}
    baseline = {"p1": 0.40, "draw": 0.30, "p2": 0.30}

    changed = apply_validated_competition_probabilities(row, baseline, selected, scope)

    assert changed is True
    assert row["pick"] == "p2"
    assert row["probabilities"] == {"p1": 0.2, "draw": 0.2, "p2": 0.6}
    assert row["published_model_probabilities"] == baseline
    assert row["football_model_validation"]["status"] == "RESEARCH_SCOPE_VALIDATED"
    assert row["football_model_validation"]["live_money_approved"] is False
    assert row["football_model_validation"]["ticket_release_approved"] is False
    assert row["live_eligible"] is False
    assert row["betting_qualified"] is False
    assert row["qualified_for_builder"] is False
    assert row["builder_eligible"] is False
    assert row["real_money_eligible"] is False
    assert row["paper_only"] is True


def test_unvalidated_scope_does_not_change_published_prediction():
    row = {
        "probabilities": {"p1": 0.40, "draw": 0.30, "p2": 0.30},
        "pick": "p1",
        "confidence": 0.40,
    }
    original = dict(row)
    scope = {"status": "RESEARCH_ONLY", "selected_model": "elo"}
    changed = apply_validated_competition_probabilities(
        row, original["probabilities"], {"p1": 0.1, "draw": 0.1, "p2": 0.8}, scope
    )
    assert changed is False
    assert row == original


def test_elo_requires_actual_forecast_timestamp_and_excludes_same_time_results():
    cutoff = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    history = [
        {
            "sport": "football", "league": "Champions League", "event_id": "prior",
            "start_time": (cutoff - timedelta(days=2)).isoformat(),
            "player_1": "Arsenal", "player_2": "Bayern Munich",
            "final_score": [4, 0], "settled": True,
        },
        {
            "sport": "football", "league": "Champions League", "event_id": "within-buffer",
            "start_time": (cutoff - timedelta(hours=1)).isoformat(),
            "player_1": "Arsenal", "player_2": "Bayern Munich",
            "final_score": [0, 5], "settled": True,
        },
        {
            "sport": "football", "league": "Champions League", "event_id": "same",
            "start_time": cutoff.isoformat(),
            "player_1": "Arsenal", "player_2": "Bayern Munich",
            "final_score": [0, 4], "settled": True,
        },
        {
            "sport": "football", "league": "Champions League", "event_id": "later",
            "start_time": (cutoff + timedelta(days=1)).isoformat(),
            "player_1": "Arsenal", "player_2": "Bayern Munich",
            "final_score": [0, 8], "settled": True,
        },
    ]
    no_timestamp = {
        "league": "Champions League",
        "player_1": "Arsenal", "player_2": "Bayern Munich",
        "start_time": cutoff.isoformat(),
    }
    assert _competition_elo_probabilities(history, no_timestamp, {}) is None

    row = dict(no_timestamp, calculated_at=cutoff.isoformat())
    cache = {}
    probabilities = _competition_elo_probabilities(history, row, cache)
    assert probabilities is not None
    assert len(cache) == 1
    state = next(iter(cache.values()))
    assert state.index == 1  # only the safely old event was applied; within-buffer, same-time and future rows are excluded


def test_validation_audit_is_fresh_and_never_approves_ticket_release():
    report = {
        "status": "ok",
        "total_eligible": 90,
        "development_n": 63,
        "holdout_n": 27,
        "promotion_allowed": False,
        "validated_competition_scopes": {
            "Bundesliga": {"status": "RESEARCH_SCOPE_VALIDATED"}
        },
    }
    audit = build_validation_audit(report, 20, 4, {"Bundesliga": 4}, 1)
    generated = datetime.fromisoformat(audit["generated_at_utc"])
    assert generated.tzinfo is not None
    assert audit["mode"] == "PAPER_RESEARCH_ONLY"
    assert audit["model_version"] == "5.0-prequential-competition-validated"
    assert audit["validated_scope_prediction_counts"] == {"Bundesliga": 4}
    assert audit["validated_model_prediction_updates"] == 4
    assert audit["live_money_approved"] is False
    assert audit["ticket_release_approved"] is False
    assert audit["release_gates_changed"] is False


if __name__ == "__main__":
    test_validated_scope_updates_forecast_but_preserves_all_release_flags()
    test_unvalidated_scope_does_not_change_published_prediction()
    test_elo_requires_actual_forecast_timestamp_and_excludes_same_time_results()
    test_validation_audit_is_fresh_and_never_approves_ticket_release()
    print("Validated football model integration contracts passed.")
