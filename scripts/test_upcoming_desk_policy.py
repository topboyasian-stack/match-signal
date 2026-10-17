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


    def test_virtual_current_quote_ladder_deduplicates_and_requires_two_sided_totals(self):
        event = {"markets": [
            {"id": "18", "name": "Total Goals", "line": 2.5,
             "outcomes": [{"name": "Over 2.5", "odds": 1.8}, {"name": "Under 2.5", "odds": 2.0}]},
            {"id": "18", "name": "Total Goals", "specifier": "total=3.5",
             "outcomes": [{"name": "Over 3.5", "odds": 2.1}, {"name": "Under 3.5", "odds": 1.7}]},
            {"id": "18", "name": "Total Goals", "specifier": "total=4.5",
             "outcomes": [{"name": "Over 4.5", "odds": 3.2}, {"name": "Under 4.5", "odds": 1.3}]},
            {"id": "18", "name": "Total Goals", "line": 3.5,
             "outcomes": [{"name": "Over 3.5", "odds": 2.0}, {"name": "Under 3.5", "odds": 1.8}]},
            {"id": "1", "name": "Match Winner", "line": 0.5,
             "outcomes": [{"name": "Over", "odds": 1.8}, {"name": "Under", "odds": 2.0}]},
            {"id": "18", "name": "Total Goals", "line": 5.5,
             "outcomes": [{"name": "Over 5.5", "odds": 1.8}]},
        ]}
        points = ns["virtual_market_ladder_points"](event)
        self.assertEqual([line for line, _ in points], [2.5, 3.5, 4.5])
        self.assertEqual(len(points), len({line for line, _ in points}))
        self.assertAlmostEqual(points[0][1], (1 / 1.8) / ((1 / 1.8) + (1 / 2.0)))
        self.assertAlmostEqual(points[1][1], (
            (1 / 2.1) / ((1 / 2.1) + (1 / 1.7)) +
            (1 / 2.0) / ((1 / 2.0) + (1 / 1.8))
        ) / 2)

    def test_virtual_target_lambda_is_fit_without_the_target_market_line(self):
        calls = []
        def fake_fit(points):
            calls.append(list(points))
            return 3.25
        points = [(2.5, 0.70), (3.5, 0.51), (4.5, 0.29)]
        fitted, meta = ns["fit_virtual_target_lambda"](points, 3.5, fake_fit, 2.7)
        self.assertEqual(fitted, 3.25)
        self.assertEqual(calls, [[(2.5, 0.70), (4.5, 0.29)]])
        self.assertEqual(meta["source"], "current_market_ladder_leave_one_line_out")
        self.assertTrue(meta["target_line_excluded"])

    def test_virtual_target_lambda_uses_historical_fallback_when_ladder_is_too_thin(self):
        calls = []
        fitted, meta = ns["fit_virtual_target_lambda"](
            [(2.5, 0.70), (3.5, 0.50)],
            3.5,
            lambda points: calls.append(list(points)) or 9.0,
            2.8,
        )
        self.assertEqual(fitted, 2.8)
        self.assertEqual(calls, [])
        self.assertEqual(meta["source"], "historical_product_lambda_fallback")

    def test_efootball_model_variant_uses_product_holdout_and_does_not_force_participant_overlay(self):
        def metrics(n, brier, log_loss, ece, hit_rate=0.60):
            return {"n": n, "brier": brier, "log_loss": log_loss, "ece": ece, "hit_rate": hit_rate}
        report = {
            "by_product": {"efootball_gt": {
                "market": metrics(3432, .26075, .71526, .09980),
                "poisson": metrics(3432, .24022, .67320, .00526),
                "poisson_prior": metrics(3432, .24219, .67734, .01917),
                "efootball_shape": metrics(3432, .24647, .68641, .05849),
                "participant_model": metrics(3432, .24408, .68129, .04916),
            }},
            "holdout_metrics": {
                "market": metrics(5639, .32967, .93964, .22249),
                "poisson": metrics(5639, .19446, .56169, .00862),
                "poisson_prior": metrics(5639, .19582, .56438, .01937),
                "efootball_shape": metrics(5639, .19826, .56974, .03702),
            },
        }
        selector = ns["select_validated_virtual_model_variant"]
        self.assertEqual(selector(report, "efootball_gt", participant_enabled=False), "poisson")
        # Even if a stale artifact says the participant gate passed, the overlay
        # must not override a better product-specific base holdout.
        self.assertEqual(selector(report, "efootball_gt", participant_enabled=True), "poisson")

        report["by_product"]["efootball_gt"]["participant_model"] = metrics(3432, .230, .650, .020)
        self.assertEqual(selector(report, "efootball_gt", participant_enabled=True), "participant_model")

    def test_under_forecast_is_complement_of_the_selected_over_probability(self):
        result = (0.55, 0.31, 0.33, 0.32, 0.29, 20, 0.35, 30, 0.5)
        probability = ns["virtual_model_side_probability"]
        self.assertAlmostEqual(probability(result, "poisson", "over"), 0.31)
        self.assertAlmostEqual(probability(result, "poisson", "under"), 0.69)
        self.assertAlmostEqual(probability(result, "poisson_prior", "under"), 0.67)
        self.assertAlmostEqual(probability(result, "efootball_shape", "under"), 0.65)
        self.assertAlmostEqual(probability(result, "participant_model", "under"), 0.71)
        self.assertIsNone(probability(result, "unknown_variant", "under"))

    def test_exact_line_direction_lookup_reads_nested_product_selection_artifact(self):
        artifact = {"by_product_selection": {"efootball_gt": {
            "u7.5": {"7.5": {
                "poisson": {"n": 255, "hit_rate": .6039, "brier": .2361},
                "participant_model": {"n": 255, "hit_rate": .6039, "brier": .2337},
            }}
        }}}
        result = ns["exact_line_direction_oos"](artifact, "efootball_gt", 7.5, "under")
        self.assertEqual(result["n"], 255)
        self.assertAlmostEqual(result["hit_rate"], .6039)
        self.assertAlmostEqual(result["brier"], .2337)
        self.assertEqual(result["variant"], "participant_model")

if __name__ == "__main__":
    unittest.main(verbosity=2)
