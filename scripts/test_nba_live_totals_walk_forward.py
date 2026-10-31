#!/usr/bin/env python3
"""Offline tests for the NBA live totals period evaluator."""
from nba_live_totals_walk_forward import evaluate


def test_period_estimates_are_paired_to_final_scores_and_separated():
    games = {}
    history = []
    for i in range(35):
        event_id = f"game-{i}"
        # The ESPN live event ID intentionally differs from an NBA stats game ID.
        history.append({"event_id": f"nba-stats-{i}", "home_score": 110, "away_score": 105})
        snapshots = []
        for elapsed, estimate in ((10.0, 217.0), (22.0, 216.0), (34.0, 214.0), (42.0, 213.0)):
            snapshots.append({
                "event_id": event_id,
                "game_state": "live",
                "observed_at": f"2026-10-{(i % 20) + 1:02d}T00:{int(elapsed):02d}:00+00:00",
                "pregame_totals_model_version": "model-v4",
                "live_total_projection": {
                    "status": "AVAILABLE",
                    "elapsed_minutes": elapsed,
                    "live_total_estimate": estimate,
                    "pregame_expected_total": 225.0,
                    "projection_source": "ESPN_LIVE_BOXSCORE_POSSESSIONS_AND_SCORE_PACE",
                    "uses_live_boxscore_stats": True,
                },
            })
        # Five-minute repeated capture within Q1 must still count as one game.
        snapshots.append(dict(
            snapshots[0],
            observed_at=f"2026-10-{(i % 20) + 1:02d}T00:11:00+00:00",
            live_total_projection={**snapshots[0]["live_total_projection"], "elapsed_minutes": 11.0},
        ))
        snapshots.append({
            "event_id": event_id,
            "game_state": "final",
            "observed_at": f"2026-10-{(i % 20) + 1:02d}T23:55:00+00:00",
            "home": {"score": "110"},
            "away": {"score": "105"},
        })
        games[event_id] = {"event_id": event_id, "snapshots": snapshots}

    result = evaluate({"games": games}, history, "model-v4")
    assert result["evidence_sufficient"] is True
    for bucket in ("Q1_end", "Halftime", "Q3_end", "Q4"):
        assert result["by_period"][bucket]["n"] == 35
    assert result["overall"]["n"] == 140
    assert result["overall"]["mae"] is not None


def test_unsettled_games_and_wrong_model_versions_are_excluded():
    observations = {"games": {
        "unfinished": {"snapshots": [{
            "game_state": "live",
            "pregame_totals_model_version": "model-v4",
            "live_total_projection": {"status": "AVAILABLE", "elapsed_minutes": 10,
                                      "live_total_estimate": 220, "pregame_expected_total": 225},
            "observed_at": "2026-10-31T00:10:00+00:00",
        }]},
        "legacy": {"snapshots": [{
            "game_state": "live",
            "pregame_totals_model_version": "old",
            "live_total_projection": {"status": "AVAILABLE", "elapsed_minutes": 10,
                                      "live_total_estimate": 220, "pregame_expected_total": 225},
            "observed_at": "2026-10-31T00:10:00+00:00",
        }]},
    }}
    result = evaluate(observations, [], "model-v4")
    assert result["overall"]["n"] == 0
    assert result["evidence_sufficient"] is False


if __name__ == "__main__":
    test_period_estimates_are_paired_to_final_scores_and_separated()
    test_unsettled_games_and_wrong_model_versions_are_excluded()
    print("NBA live totals period walk-forward tests: PASS")
