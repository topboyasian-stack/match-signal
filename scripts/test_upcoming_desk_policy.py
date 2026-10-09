#!/usr/bin/env python3
"""Regression tests for Upcoming publication freshness and evidence gates."""
import runpy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ns = runpy.run_path(str(ROOT / "scripts" / "unified_upcoming.py"))
tennis_ns = runpy.run_path(str(ROOT / "scripts" / "predict_today.py"))
UTC = timezone.utc


class UpcomingDeskPolicyTests(unittest.TestCase):
    def setUp(self):
        for key in ns["DESK_FILTER_STATS"]:
            ns["DESK_FILTER_STATS"][key] = 0
        self.now = datetime(2026, 10, 9, 13, 0, tzinfo=UTC)
        self.horizon = self.now + timedelta(days=7)

    def row(self, event_id, start, **extra):
        row = {
            "event_id": event_id,
            "sport": "football",
            "league": "Test League",
            "player_1": "Example Home",
            "player_2": "Example Away",
            "start_time": start.isoformat(),
        }
        row.update(extra)
        return row

    def test_stale_live_flags_are_capped_per_sport_family(self):
        stale_live_flag = ns["stale_live_flag"]
        limit_hours = ns["live_age_limit_hours"]
        self.assertEqual(limit_hours({"sport": "virtual", "product": "vfootball"}), 2.0)
        self.assertEqual(limit_hours({"sport": "tennis"}), 8.0)
        self.assertEqual(limit_hours({"sport": "football"}), 4.0)

        row = {"sport": "virtual", "product": "vfootball", "live": True,
               "start_time": (self.now - timedelta(hours=3)).isoformat()}
        self.assertTrue(stale_live_flag(row, self.now))
        row["start_time"] = (self.now - timedelta(minutes=30)).isoformat()
        self.assertFalse(stale_live_flag(row, self.now))
        future = {"sport": "football", "live": True,
                  "start_time": (self.now + timedelta(minutes=5)).isoformat()}
        self.assertFalse(stale_live_flag(future, self.now))

    def test_old_live_row_is_removed_from_upcoming_but_filter_is_audited(self):
        rows = []
        old_live = self.row(
            "desk-policy-test-old-live",
            self.now - timedelta(hours=3),
            sport="virtual",
            product="vfootball",
            live=True,
            event_state="LIVE",
        )
        ns["add"](rows, old_live, now=self.now, horizon=self.horizon)
        self.assertEqual(rows, [])
        self.assertEqual(ns["DESK_FILTER_STATS"]["stale_live_flags_hidden"], 1)

    def test_past_kickoff_non_live_row_is_hidden_but_future_row_remains(self):
        rows = []
        past = self.row("desk-policy-test-past", self.now - timedelta(minutes=1))
        ns["add"](rows, past, now=self.now, horizon=self.horizon)
        self.assertEqual(rows, [])
        self.assertEqual(ns["DESK_FILTER_STATS"]["past_kickoff_rows_hidden"], 1)

        future = self.row("desk-policy-test-future", self.now + timedelta(hours=1))
        ns["add"](rows, future, now=self.now, horizon=self.horizon)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], "desk-policy-test-future")

    def test_tennis_discovery_accepts_person_id_on_competitor_record(self):
        quality = tennis_ns["tennis_fixture_quality"]
        event = {
            "draw_type": "Men's Singles",
            "competitors": [
                {"id": "person-101", "displayName": "Player Alpha"},
                {"id": "person-202", "displayName": "Player Beta"},
            ],
        }
        self.assertEqual(quality(event), (True, None))

        missing_identity = {
            "draw_type": "Men's Singles",
            "competitors": [
                {"displayName": "Player Alpha"},
                {"displayName": "Player Beta"},
            ],
        }
        self.assertEqual(quality(missing_identity), (False, "missing athlete id"))

        doubles = dict(event, draw_type="Men's Doubles")
        self.assertEqual(quality(doubles), (False, "non-singles draw"))

        paired_name = {
            "draw_type": "Singles",
            "competitors": [
                {"id": "pair-101", "displayName": "Player Alpha / Player Gamma"},
                {"id": "person-202", "displayName": "Player Beta"},
            ],
        }
        self.assertEqual(quality(paired_name), (False, "non-singles competitor"))

    def test_exact_line_walk_forward_evidence_is_not_inferred_from_neighboring_lines(self):
        evaluation = {
            "by_product_selection": {
                "vfootball": {
                    "u7.5": {
                        "participant_model": {
                            "n": 10,
                            "hit_rate": 1.0,
                            "brier": 0.0006,
                        }
                    }
                }
            }
        }
        evidence = ns["exact_line_direction_oos"](evaluation, "vfootball", 7.5, "under")
        self.assertEqual(evidence["n"], 10)
        self.assertEqual(evidence["hit_rate"], 1.0)
        missing = ns["exact_line_direction_oos"](evaluation, "vfootball", 8.5, "under")
        self.assertEqual(missing["n"], 0)
        self.assertIsNone(missing["hit_rate"])

    def test_high_vfootball_under_requires_30_exact_line_rows_and_65_percent(self):
        requires = ns["high_vfootball_under_requires_research"]
        self.assertTrue(requires("vfootball", 7.5, "under", {"n": 10, "hit_rate": 1.0}))
        self.assertTrue(requires("vfootball", 8.5, "under", {"n": 0, "hit_rate": None}))
        self.assertTrue(requires("vfootball", 7.5, "under", {"n": 30, "hit_rate": 0.64}))
        self.assertFalse(requires("vfootball", 7.5, "under", {"n": 30, "hit_rate": 0.65}))
        self.assertFalse(requires("vfootball", 6.5, "under", {"n": 0, "hit_rate": None}))
        self.assertFalse(requires("efootball_gt", 8.5, "under", {"n": 0, "hit_rate": None}))
        self.assertFalse(requires("vfootball", 8.5, "over", {"n": 0, "hit_rate": None}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
