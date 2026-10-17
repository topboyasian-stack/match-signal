#!/usr/bin/env python3
"""Regression tests for the board-to-Builder fallback trigger."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ensure_odds_builder_refresh import BUILDER_RUN_MAX_AGE_MINUTES, evaluate_runs

NOW = datetime(2026, 10, 17, 9, 30, tzinfo=timezone.utc)


def run(age_minutes: int, status: str = "completed", run_id: int = 123, conclusion: str = "success") -> dict:
    stamp = NOW - timedelta(minutes=age_minutes)
    return {
        "databaseId": run_id,
        "status": status,
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
        "conclusion": conclusion if status == "completed" else None,
    }


class BuilderRefreshDecisionTests(unittest.TestCase):
    def test_fresh_completed_run_does_not_dispatch(self):
        result = evaluate_runs([run(BUILDER_RUN_MAX_AGE_MINUTES - 1)], NOW)
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "builder_run_recent")

    def test_stale_completed_run_dispatches(self):
        result = evaluate_runs([run(BUILDER_RUN_MAX_AGE_MINUTES)], NOW)
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "builder_run_stale")

    def test_missing_history_dispatches(self):
        result = evaluate_runs([], NOW)
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"], "no_valid_builder_run_history")

    def test_invalid_timestamp_history_dispatches(self):
        result = evaluate_runs([{"databaseId": 1, "status": "completed", "createdAt": "not-a-date"}], NOW)
        self.assertTrue(result["dispatch"])

    def test_active_run_suppresses_duplicate_even_when_old(self):
        result = evaluate_runs([run(90, "in_progress", 900)], NOW)
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["reason"], "active_builder_run")
        self.assertEqual(result["active_run_id"], 900)

    def test_clock_skew_cannot_make_a_recent_run_look_stale(self):
        result = evaluate_runs([{
            "databaseId": 7,
            "status": "completed",
            "createdAt": (NOW + timedelta(minutes=2)).isoformat(),
        }], NOW)
        self.assertFalse(result["dispatch"])
        self.assertEqual(result["age_minutes"], 0.0)

    def test_failed_recent_run_still_obeys_cooldown(self):
        result = evaluate_runs([run(5, "completed", conclusion="failure")], NOW)
        self.assertFalse(result["dispatch"])


if __name__ == "__main__":
    unittest.main()
