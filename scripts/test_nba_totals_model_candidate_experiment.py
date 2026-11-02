#!/usr/bin/env python3
"""Unit tests for the frozen NBA nonlinear model-candidate experiment."""
import unittest
from datetime import datetime, timedelta, timezone

from nba_totals_model_candidate_experiment import FEATURES, split_by_cutoff


class NonlinearCandidateTests(unittest.TestCase):
    def test_model_features_do_not_include_bookmaker_prices_or_outcomes(self):
        forbidden = {"markets", "line", "over_odds", "under_odds", "pick", "result"}
        self.assertFalse(forbidden.intersection(FEATURES))
        self.assertNotIn("actual_total", FEATURES)

    def test_frozen_chronological_split_puts_cutoff_equality_in_holdout(self):
        cutoff = datetime(2026, 3, 26, tzinfo=timezone.utc)
        rows = [
            {"date": (cutoff - timedelta(seconds=1)).isoformat(), "event_id": "before"},
            {"date": cutoff.isoformat(), "event_id": "at-cutoff"},
            {"date": (cutoff + timedelta(seconds=1)).isoformat(), "event_id": "after"},
        ]
        before, after = split_by_cutoff(rows, cutoff)
        self.assertEqual([row["event_id"] for row in before], ["before"])
        self.assertEqual([row["event_id"] for row in after], ["at-cutoff", "after"])

    def test_v5_model_name_is_not_part_of_the_candidate_feature_columns(self):
        self.assertEqual(len(FEATURES), len(set(FEATURES)))
        self.assertIn("v5_prediction", FEATURES)
        self.assertIn("recent10_matchup_total", FEATURES)
        self.assertIn("recent10_pace_efficiency_total", FEATURES)


if __name__ == "__main__":
    unittest.main()
