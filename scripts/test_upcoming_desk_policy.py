#!/usr/bin/env python3
"""Regression tests for Upcoming publication freshness and evidence gates."""
import runpy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ns = runpy.run_path(str(ROOT / "scripts" / "unified_upcoming.py"))
learning_ns = runpy.run_path(str(ROOT / "scripts" / "efootball_desk_learning.py"))
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

    def test_virtual_qualified_picks_wait_until_the_next_60_minute_window(self):
        gate = ns["apply_virtual_kickoff_window_gate"]
        self.assertEqual(ns["QUALIFIED_VIRTUAL_KICKOFF_WINDOW_MINUTES"], 60)
        now = self.now
        qualified = "BETTING_QUALIFIED_PAPER"
        self.assertEqual(gate(qualified, now + timedelta(hours=5), now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now + timedelta(minutes=61), now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now + timedelta(minutes=60), now), qualified)
        self.assertEqual(gate(qualified, now + timedelta(minutes=1), now), qualified)
        self.assertEqual(gate(qualified, now, now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now - timedelta(seconds=1), now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate("EDGE_BELOW_2PCT", now + timedelta(hours=5), now), "EDGE_BELOW_2PCT")
        self.assertEqual(ns["virtual_kickoff_window_minutes"](now + timedelta(hours=5), now), 300.0)

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

    def test_tennis_forward_watch_remains_unqualified_in_unified_desk(self):
        row = {
            "event_id": "desk-policy-test-tennis-watch",
            "sport": "tennis",
            "league": "ATP",
            "player_1": "Player Alpha",
            "player_2": "Player Beta",
            "start_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "pick": "p1",
            "confidence": 0.72,
            "probabilities": {"p1": 0.72, "p2": 0.28},
            "prediction_status": "watch_projection",
            "projection_tier": "baseline_plus_enrichment",
            "evidence_depth": "tennis_forward_window_ranking_form_watch",
            "qualification_status": "TENNIS_FORWARD_WATCH_NOT_QUALIFIED",
            "betting_qualified": False,
            "qualified_for_builder": False,
            "paper_only": True,
        }
        rows = []
        ns["core_rows"](rows, [row])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["projection_tier"], "baseline_plus_enrichment")
        self.assertEqual(rows[0]["qualification_status"], "TENNIS_FORWARD_WATCH_NOT_QUALIFIED")
        self.assertFalse(rows[0]["betting_qualified"])
        self.assertFalse(rows[0]["qualified_for_builder"])

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


    def test_exact_line_calibration_uses_raw_probability_as_its_adjustment_basis(self):
        forecasts = [
            {
                "product": "efootball_gt",
                "line": 6.5,
                "pick": "under",
                "model_probability": 0.60,
                "raw_model_probability": 0.80,
                "win": index < 15,
            }
            for index in range(20)
        ]
        profile = learning_ns["exact_profiles"](forecasts)["efootball_gt"]["6.5|under"]
        posterior = (15 + 4.0) / (20 + 8.0)
        self.assertAlmostEqual(profile["mean_model_probability"], 0.60)
        self.assertAlmostEqual(profile["mean_raw_model_probability"], 0.80)
        self.assertAlmostEqual(profile["calibration_offset"], posterior - 0.60)
        self.assertAlmostEqual(profile["raw_calibration_offset"], posterior - 0.80)

        report = {"exact_selection": {"6.5|under": profile}}
        actual, source, _ = ns["calibrate_desk_probability"](0.80, 6.5, "under", report)
        expected = ns["clamp"](0.80 + profile["raw_calibration_offset"] * profile["calibration_weight"])
        self.assertEqual(source, "EXACT_LINE_DIRECTION")
        self.assertAlmostEqual(actual, expected)
        self.assertLess(actual, 0.80, "raw estimate must be corrected using the raw-scale residual")

    def test_probability_bucket_fallback_is_keyed_and_calibrated_on_raw_scores(self):
        forecasts = [
            {
                "product": "efootball_gt",
                "line": 4.5,
                "pick": "over",
                "model_probability": 0.60,
                "raw_model_probability": 0.80,
                "win": index < 15,
            }
            for index in range(30)
        ]
        displayed_buckets = learning_ns["calibration"](forecasts)
        raw_buckets = learning_ns["calibration"](forecasts, probability_field="raw_model_probability")
        self.assertIn("0.6", displayed_buckets)
        self.assertIn("0.8", raw_buckets)
        self.assertAlmostEqual(displayed_buckets["0.6"]["mean_model_probability"], 0.60)
        self.assertAlmostEqual(raw_buckets["0.8"]["mean_model_probability"], 0.80)

        report = {
            "exact_selection": {},
            "raw_probability_calibration": {"active": True, "buckets": raw_buckets},
        }
        actual, source, _ = ns["calibrate_desk_probability"](0.80, 4.5, "over", report)
        expected = ns["clamp"](0.80 + raw_buckets["0.8"]["calibration_offset"] * raw_buckets["0.8"]["calibration_weight"])
        self.assertEqual(source, "PROBABILITY_BUCKET")
        self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(actual, 0.65)


if __name__ == "__main__":
    unittest.main(verbosity=2)
