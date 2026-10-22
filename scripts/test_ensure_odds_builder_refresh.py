#!/usr/bin/env python3
"""Regression tests for the board-to-Builder fallback trigger."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ensure_odds_builder_refresh import (
    BUILDER_ARTIFACT_MAX_AGE_MINUTES,
    RECENT_RUN_COOLDOWN_MINUTES,
    UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES,
    evaluate_runs,
    builder_dispatch_command,
)

NOW = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)


def run(
    age_minutes: float,
    status: str = "completed",
    run_id: int = 123,
    conclusion: str = "success",
    event: str = "schedule",
) -> dict:
    stamp = NOW - timedelta(minutes=age_minutes)
    return {
        "databaseId": run_id,
        "status": status,
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
        "conclusion": conclusion if status == "completed" else None,
        "event": event,
    }


def artifact(age_minutes: int) -> str:
    return (NOW - timedelta(minutes=age_minutes)).isoformat().replace("+00:00", "Z")


class BuilderRefreshDecisionTests(unittest.TestCase):
    def test_board_triggered_builder_skips_recursive_promotion(self):
        self.assertEqual(
            builder_dispatch_command(),
            ["gh", "workflow", "run", "odds_builder.yml", "--ref", "main", "-f", "skip_promotion=true"],
        )

    def test_fresh_artifact_skips_even_when_run_history_is_old(self):
        result = evaluate_runs([run(60)], NOW, artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES - 1))
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_fresh")
        self.assertEqual(result["artifact_age_minutes"], BUILDER_ARTIFACT_MAX_AGE_MINUTES - 1)

    def test_stale_artifact_dispatches_even_when_a_completed_run_is_recent_but_outside_cooldown(self):
        result = evaluate_runs([run(RECENT_RUN_COOLDOWN_MINUTES + 5)], NOW, artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES + 4))
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_stale")
        self.assertEqual(result["artifact_age_minutes"], BUILDER_ARTIFACT_MAX_AGE_MINUTES + 4)

    def test_stale_artifact_dispatches_after_recent_completed_run(self):
        result = evaluate_runs([run(RECENT_RUN_COOLDOWN_MINUTES - 1)], NOW, artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES + 10))
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_stale")

    def test_stale_artifact_does_not_duplicate_active_run(self):
        result = evaluate_runs([run(30, "in_progress", 900)], NOW, artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES + 10))
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "active_builder_run")
        self.assertEqual(result["active_run_id"], 900)

    def test_missing_artifact_dispatches_when_no_recent_or_active_run_exists(self):
        result = evaluate_runs([run(RECENT_RUN_COOLDOWN_MINUTES + 1)], NOW, artifact_generated_at=None)
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_missing_or_invalid")

    def test_invalid_artifact_timestamp_is_treated_as_missing(self):
        result = evaluate_runs([run(20)], NOW, artifact_generated_at="not-a-date")
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_missing_or_invalid")

    def test_clock_skew_cannot_make_artifact_look_stale(self):
        future = (NOW + timedelta(minutes=3)).isoformat()
        result = evaluate_runs([run(60)], NOW, artifact_generated_at=future)
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_fresh")
        self.assertEqual(result["artifact_age_minutes"], 0.0)

    def test_old_artifact_not_hidden_by_a_recent_failed_run(self):
        result = evaluate_runs([run(12, conclusion="failure")], NOW, artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES + 8))
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_stale")


    def test_newer_board_and_stale_artifact_dispatch_after_recent_failed_builder(self):
        result = evaluate_runs(
            [run(2, conclusion="failure", run_id=906)],
            NOW,
            artifact_generated_at=artifact(BUILDER_ARTIFACT_MAX_AGE_MINUTES + 16),
            upstream_board_generated_at=artifact(3),
        )
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_newer_and_builder_stale_or_failed")
        self.assertEqual(result["last_run_id"], 906)

    def test_newer_upcoming_board_dispatches_when_builder_cycle_was_missed(self):
        result = evaluate_runs(
            [run(UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES + 1)],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_newer_than_builder_artifact")
        self.assertTrue(result["upcoming_board_newer_than_builder_artifact"])

    def test_newer_upcoming_board_does_not_duplicate_recent_recovery_dispatch(self):
        result = evaluate_runs(
            [run(0, event="workflow_dispatch")],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_newer_but_builder_recent")
        self.assertEqual(result["last_run_event"], "workflow_dispatch")
        self.assertEqual(result["upcoming_board_refresh_min_interval_minutes"], UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES)

    def test_recent_scheduled_builder_cycle_that_finished_before_board_queues_recovery(self):
        result = evaluate_runs(
            [run(2, run_id=903, event="schedule")],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_published_after_recent_builder_cycle")
        self.assertEqual(result["last_run_id"], 903)
        self.assertEqual(result["last_run_event"], "schedule")
        self.assertLess(result["run_age_minutes"], UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES)

    def test_recent_fallback_dispatch_that_predates_board_queues_follow_up_refresh(self):
        result = evaluate_runs(
            [run(2, run_id=904, event="workflow_dispatch")],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_published_after_recent_builder_cycle")
        self.assertEqual(result["last_run_id"], 904)
        self.assertEqual(result["last_run_event"], "workflow_dispatch")

    def test_fallback_dispatch_at_board_timestamp_does_not_duplicate_recovery(self):
        result = evaluate_runs(
            [run(0, run_id=905, event="workflow_dispatch")],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_newer_but_builder_recent")

    def test_newer_upcoming_board_does_not_dispatch_while_builder_run_is_active(self):
        result = evaluate_runs(
            [run(1, "in_progress", run_id=901)],
            NOW,
            artifact_generated_at=artifact(10),
            upstream_board_generated_at=artifact(1),
        )
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "active_builder_run")
        self.assertEqual(result["active_run_id"], 901)

    def test_board_published_after_active_builder_started_queues_follow_up_refresh(self):
        result = evaluate_runs(
            [run(UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES + 1, "in_progress", run_id=902)],
            NOW,
            artifact_generated_at=artifact(10),
            upstream_board_generated_at=NOW.isoformat().replace("+00:00", "Z"),
        )
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "upcoming_board_advanced_during_active_builder_run")
        self.assertEqual(result["active_run_id"], 902)

    def test_fresh_builder_artifact_still_skips_when_board_is_not_newer(self):
        result = evaluate_runs(
            [run(10)],
            NOW,
            artifact_generated_at=artifact(1),
            upstream_board_generated_at=artifact(2),
        )
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "builder_artifact_fresh")
        self.assertFalse(result["upcoming_board_newer_than_builder_artifact"])


if __name__ == "__main__":
    unittest.main()
