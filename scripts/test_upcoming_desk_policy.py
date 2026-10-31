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

    def test_under_65_is_included_in_weak_line_diagnostics_without_changing_qualification(self):
        summarize = ns["build_under_line_evidence"]
        rows = [
            {"sport": "virtual", "product": "efootball_gt", "pick": "under", "line": 6.5,
             "walkforward_exact_line_n": 12, "qualification_status": "MODEL_PROBABILITY_BELOW_0_65"},
            {"sport": "virtual", "product": "efootball_gt", "pick": "under", "line": 6.5,
             "walkforward_exact_line_n": 12, "qualification_status": "MODEL_PROBABILITY_BELOW_0_65",
             "betting_qualified": False},
            {"sport": "virtual", "product": "efootball_gt", "pick": "under", "line": 6.0},
            {"sport": "virtual", "product": "efootball_gt", "pick": "over", "line": 6.5},
            {"sport": "football", "product": "efootball_gt", "pick": "under", "line": 6.5},
        ]
        report = summarize(rows)
        self.assertEqual(list(report), ["efootball_gt|6.5|under"])
        self.assertEqual(report["efootball_gt|6.5|under"]["event_rows"], 2)
        self.assertEqual(report["efootball_gt|6.5|under"]["walkforward_n"], 12)
        self.assertFalse(report["efootball_gt|6.5|under"]["betting_qualified"])
        self.assertEqual(report["efootball_gt|6.5|under"]["qualification_status"], "MODEL_PROBABILITY_BELOW_0_65")

    def test_timestamp_helper_supports_chronological_walk_forward_filtering(self):
        stamp = "2026-10-09T13:00:00+00:00"
        self.assertEqual(ns["ts"](stamp), datetime(2026, 10, 9, 13, 0, tzinfo=UTC).timestamp())
        self.assertGreater(ns["ts"]("not-a-timestamp"), ns["ts"](stamp))

    def test_participant_history_and_model_inputs_must_be_fresh_before_efootball_qualification(self):
        check = ns["virtual_participant_data_freshness"]
        gate = ns["apply_virtual_participant_history_freshness_gate"]
        now = self.now
        fresh_stamp = (now - timedelta(minutes=12)).isoformat()
        fresh = {"generated_at": fresh_stamp}
        status = {"updated_at": fresh_stamp}
        evaluation = {"generated_at": fresh_stamp}
        is_fresh, meta = check(fresh, status, evaluation, now)
        self.assertTrue(is_fresh)
        self.assertEqual(meta["max_age_minutes_allowed"], 30)
        self.assertEqual(gate("BETTING_QUALIFIED_PAPER", is_fresh), "BETTING_QUALIFIED_PAPER")

        old_stamp = (now - timedelta(minutes=31)).isoformat()
        is_fresh, meta = check(
            {"generated_at": old_stamp}, status, evaluation, now
        )
        self.assertFalse(is_fresh)
        self.assertIn("participant_lifecycle", meta["reason"])
        self.assertEqual(
            gate("BETTING_QUALIFIED_PAPER", is_fresh),
            "PARTICIPANT_HISTORY_STALE",
        )

        is_fresh, meta = check(fresh, status, {}, now)
        self.assertFalse(is_fresh, "missing model evaluation timestamp must fail closed")
        self.assertIn("model_evaluation", meta["reason"])
        self.assertEqual(
            gate("EDGE_BELOW_2PCT", is_fresh),
            "PARTICIPANT_HISTORY_STALE",
        )

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

    def test_exact_line_walk_forward_evidence_uses_selected_model_and_not_neighboring_lines(self):
        def metric(n, brier, log_loss, ece):
            return {"n": n, "brier": brier, "log_loss": log_loss, "ece": ece}
        evaluation = {
            "by_product": {"vfootball": {
                "market": metric(1000, .40, .90, .20),
                "poisson": metric(1000, .20, .50, .02),
                "poisson_prior": metric(1000, .22, .55, .03),
                "efootball_shape": metric(1000, .21, .53, .04),
                "participant_model": metric(1000, .25, .62, .06),
            }},
            "by_product_selection": {
                "vfootball": {
                    "u7.5": {
                        "poisson": {"n": 10, "hit_rate": .70, "brier": .10},
                        "participant_model": {"n": 10, "hit_rate": 1.0, "brier": .0006},
                    }
                }
            }
        }
        evidence = ns["exact_line_direction_oos"](evaluation, "vfootball", 7.5, "under")
        self.assertEqual(evidence["n"], 10)
        self.assertAlmostEqual(evidence["hit_rate"], .70)
        self.assertEqual(evidence["variant"], "poisson")
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

    def test_live_virtual_event_context_has_no_undefined_market_rows(self):
        start = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
        context = ns["virtual_live_event_context"](
            {"event_id": "live-event-1"},
            start,
            "efootball_gt",
            "Test League",
            "Alpha",
            "Beta",
            3.5,
            4.2,
        )
        self.assertEqual(context["event_id"], "live-event-1")
        self.assertEqual(context["timestamp"], start.isoformat())
        self.assertEqual(context["product"], "efootball_gt")
        self.assertEqual(context["home"], "Alpha")
        self.assertEqual(context["away"], "Beta")
        self.assertEqual(context["rows"], [])
        self.assertIsNone(context["total"])
        self.assertEqual(context["lambda"], 4.2)

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
        def metric(n, brier, log_loss, ece):
            return {"n": n, "brier": brier, "log_loss": log_loss, "ece": ece}
        artifact = {
            "by_product": {"efootball_gt": {
                "market": metric(1000, .30, .80, .10),
                "poisson": metric(1000, .20, .50, .02),
                "poisson_prior": metric(1000, .22, .55, .03),
                "efootball_shape": metric(1000, .23, .57, .04),
                "participant_model": metric(1000, .24, .59, .05),
            }},
            "by_product_selection": {"efootball_gt": {
                "u7.5": {"7.5": {
                    "poisson": {"n": 255, "hit_rate": .6039, "brier": .2361},
                    "participant_model": {"n": 255, "hit_rate": .6039, "brier": .2337},
                }}
            }}
        }
        result = ns["exact_line_direction_oos"](artifact, "efootball_gt", 7.5, "under")
        self.assertEqual(result["n"], 255)
        self.assertAlmostEqual(result["hit_rate"], .6039)
        self.assertAlmostEqual(result["brier"], .2361)
        self.assertEqual(result["variant"], "poisson")

    def test_directional_gate_uses_the_same_model_variant_as_live_forecast(self):
        def metric(n, brier, log_loss, ece):
            return {"n": n, "brier": brier, "log_loss": log_loss, "ece": ece}
        artifact = {
            "participant_feature_gate": {"pass": True},
            "by_product": {"efootball_gt": {
                "market": metric(1000, .30, .80, .10),
                "poisson": metric(1000, .20, .50, .02),
                "poisson_prior": metric(1000, .22, .55, .03),
                "efootball_shape": metric(1000, .23, .57, .04),
                "participant_model": metric(1000, .24, .59, .05),
            }},
            "holdout_metrics": {
                "market": metric(1000, .30, .80, .10),
                "poisson": metric(1000, .20, .50, .02),
                "poisson_prior": metric(1000, .22, .55, .03),
                "efootball_shape": metric(1000, .23, .57, .04),
                "participant_model": metric(1000, .24, .59, .05),
            },
            "efootball_gt_diagnostics": {"selection": {"u7.5": {"7.5": {
                "poisson": {"n": 100, "hit_rate": .60, "brier": .24},
                "participant_model": {"n": 100, "hit_rate": .99, "brier": .10},
            }}}}
        }
        history = []
        for i in range(40):
            stamp = self.now - timedelta(minutes=40-i)
            history.append({
                "product": "efootball_gt",
                "market": "ou",
                "line": 7.5,
                "selection": "under",
                "win": True,
                "score": "2:2",
                "timestamp": stamp.isoformat(),
                "settled_at": stamp.isoformat(),
                "start_time": stamp.isoformat(),
                "participant_1": f"Alpha{i} (player-a{i})",
                "participant_2": f"Beta{i} (player-b{i})",
            })
        result = ns["build_efootball_directional_gate"](artifact, history)[(7.5, "under")]
        self.assertEqual(result["holdout_n"], 100)
        self.assertAlmostEqual(result["holdout_hit_rate"], .60)
        self.assertFalse(result["pass"])


    def test_product_bootstrap_cannot_bypass_exact_line_direction_validation(self):
        resolve = ns["resolve_efootball_qualification_status"]
        common = {
            "base_model_gate": True,
            "model_line": True,
            "edge": 0.466,
            "model_probability": 0.6803,
            "active_comp": False,
            "model_comp": False,
            "product_bootstrap": True,
            "directional_pass": False,
        }
        # A product-wide bootstrap is not evidence that this exact line and
        # side passed its own chronological holdout and recent-settlement gates.
        self.assertEqual(
            resolve(**common),
            "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING",
        )
        # With the unchanged exact line/side gate passing, new competitions may
        # still use the validated product bootstrap lane.
        self.assertEqual(
            resolve(**{**common, "directional_pass": True}),
            "BETTING_QUALIFIED_PAPER_BOOTSTRAP",
        )
        self.assertEqual(
            resolve(**{**common, "product_bootstrap": False, "directional_pass": True}),
            "BETTING_QUALIFIED_PAPER_DIRECTIONAL",
        )
        # Preserve the existing validated competition + line route.
        self.assertEqual(
            resolve(**{**common, "active_comp": True, "model_comp": True}),
            "BETTING_QUALIFIED_PAPER",
        )
        # The configured 65% floor is strict; the 64.97% O3.5 holdout must not
        # pass merely because a UI rounds its displayed percentage to 65%.
        self.assertEqual(
            resolve(**{**common, "model_probability": 0.649717}),
            "MODEL_PROBABILITY_BELOW_0_65",
        )

    def test_qualified_best_displays_exact_line_hit_rate_without_rounding_up_to_gate(self):
        hub_script = (ROOT / "sport-hubs.js").read_text(encoding="utf-8")
        self.assertIn(
            "(calibration.hitRate*100).toFixed(2)",
            hub_script,
            "Do not display 64.97% as 65% when the qualification floor is 65%.",
        )


    def test_exact_line_calibration_waits_for_declared_sample_minimum(self):
        calibrate = ns["calibrate_desk_probability"]
        make_forecasts = lambda n: [
            {
                "product": "efootball_gt", "line": 4.5, "pick": "over",
                "model_probability": 0.62, "raw_model_probability": 0.80,
                "win": index < int(n * 0.6),
            }
            for index in range(n)
        ]
        profile_19 = learning_ns["exact_profiles"](make_forecasts(19))["efootball_gt"]["4.5|over"]
        report_19 = {"exact_selection": {"4.5|over": profile_19}}
        probability, source, _ = calibrate(0.80, 4.5, "over", report_19)
        self.assertEqual(source, "NONE", "19 observations must not activate a 20-row calibration policy")
        self.assertAlmostEqual(probability, 0.80)

        profile_20 = learning_ns["exact_profiles"](make_forecasts(20))["efootball_gt"]["4.5|over"]
        report_20 = {"exact_selection": {"4.5|over": profile_20}}
        probability, source, _ = calibrate(0.80, 4.5, "over", report_20)
        self.assertEqual(source, "EXACT_LINE_DIRECTION")
        self.assertLess(probability, 0.80)

    def test_expired_unmatched_forecasts_are_not_counted_as_active_pending(self):
        now = datetime.now(UTC)
        row = {
            "trace_id": "test-expired-unmatched",
            "product": "efootball_gt",
            "start_time": (now - timedelta(hours=3)).isoformat(),
            "observed_at": (now - timedelta(hours=4)).isoformat(),
            "participant_1": "Alpha",
            "participant_2": "Beta",
            "line": 4.5,
            "pick": "over",
            "model_probability": 0.70,
        }
        diagnostics = learning_ns["reconcile"]([row], {})
        self.assertEqual(row.get("settlement_reconciliation_status"), "UNMATCHED_EXPIRED")
        self.assertEqual(diagnostics["expired_unmatched_forecasts"], 1)
        self.assertFalse(learning_ns["is_pending_forecast"](row))

    def test_trace_capacity_prioritizes_recent_and_upcoming_fixtures(self):
        now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        def row(trace_id, kickoff, observed):
            return {
                "trace_id": trace_id,
                "start_time": kickoff.isoformat(),
                "observed_at": observed.isoformat(),
                "product": "efootball_gt",
                "line": 4.5,
                "pick": "over",
            }
        rows = [
            row("expired", now - timedelta(hours=4), now - timedelta(hours=5)),
            row("recently-kicked-off", now - timedelta(minutes=20), now - timedelta(minutes=25)),
            row("next-kickoff", now + timedelta(minutes=10), now - timedelta(minutes=1)),
            row("later-kickoff", now + timedelta(hours=2), now - timedelta(minutes=2)),
        ]
        retained = learning_ns["bound_trace"](rows, now=now, cap=3)
        retained_ids = {item["trace_id"] for item in retained}
        self.assertNotIn("expired", retained_ids)
        self.assertEqual(retained_ids, {"recently-kicked-off", "next-kickoff", "later-kickoff"})


    def test_poisson_shadow_probability_requires_leave_one_line_out_live_ladder_fit(self):
        shadow = ns["prospective_poisson_shadow_probability"]
        components = {
            "over": {
                "poisson_over_probability": 0.62,
                "lambda_fit": {
                    "source": "current_market_ladder_leave_one_line_out",
                    "target_line_excluded": True,
                },
            },
            "under": {
                "poisson_over_probability": 0.62,
                "lambda_fit": {
                    "source": "current_market_ladder_leave_one_line_out",
                    "target_line_excluded": True,
                },
            },
        }
        over, source = shadow(components, "efootball_gt", "over")
        under, under_source = shadow(components, "efootball_gt", "under")
        self.assertAlmostEqual(over, 0.62)
        self.assertAlmostEqual(under, 0.38)
        self.assertEqual(source, "current_market_ladder_leave_one_line_out")
        self.assertEqual(under_source, source)
        self.assertEqual(shadow(components, "vfootball", "over"), (None, None))
        included_line = {
            "over": {
                "poisson_over_probability": 0.62,
                "lambda_fit": {
                    "source": "current_market_ladder_leave_one_line_out",
                    "target_line_excluded": False,
                },
            },
        }
        self.assertEqual(shadow(included_line, "efootball_gt", "over"), (None, None))
        fallback = {
            "over": {
                "poisson_over_probability": 0.62,
                "lambda_fit": {
                    "source": "historical_product_lambda_fallback",
                    "target_line_excluded": True,
                },
            },
        }
        self.assertEqual(shadow(fallback, "efootball_gt", "over"), (None, None))
        decision = ns["prospective_poisson_shadow_decision"]
        self.assertEqual(
            decision(fallback, "efootball_gt", "over")[2],
            "historical_product_fallback_rejected",
        )
        self.assertEqual(
            decision(included_line, "efootball_gt", "over")[2],
            "target_line_not_excluded",
        )
        self.assertEqual(
            decision({}, "efootball_gt", "over")[2],
            "missing_side_components",
        )


    def test_prospective_shadow_coverage_diagnostics_explain_missing_rows(self):
        coverage = ns["prospective_poisson_shadow_coverage"]
        rows = [
            {
                "product": "efootball_gt", "event_id": "shadow-good",
                "poisson_shadow_probability": 0.61,
                "poisson_shadow_source": "current_market_ladder_leave_one_line_out",
                "poisson_shadow_reason": "eligible_leave_one_line_out_fit",
                "validated_model_components": {
                    "over": {"lambda_fit": {"source": "current_market_ladder_leave_one_line_out"}},
                    "under": {"lambda_fit": {"source": "current_market_ladder_leave_one_line_out"}},
                },
            },
            {
                "product": "efootball_gt", "event_id": "shadow-fallback",
                "poisson_shadow_probability": None,
                "poisson_shadow_source": None,
                "poisson_shadow_reason": "historical_product_fallback_rejected",
                "validated_model_components": {
                    "over": {"lambda_fit": {"source": "historical_product_lambda_fallback"}},
                    "under": {"lambda_fit": {"source": "historical_product_lambda_fallback"}},
                },
            },
            {
                "product": "efootball_adriatic", "event_id": "shadow-no-ladder",
                "poisson_shadow_probability": None,
                "poisson_shadow_reason": "insufficient_independent_ladder_fit",
                "validated_model_components": {},
            },
            {"product": "vfootball", "event_id": "out-of-scope"},
        ]
        result = coverage(rows)
        gt = result["efootball_gt"]
        self.assertEqual(gt["efootball_rows"], 2)
        self.assertEqual(gt["unique_events"], 2)
        self.assertEqual(gt["rows_with_valid_shadow"], 1)
        self.assertEqual(gt["unique_events_with_valid_shadow"], 1)
        self.assertEqual(gt["rejection_reason_counts"]["eligible_leave_one_line_out_fit"], 1)
        self.assertEqual(gt["rejection_reason_counts"]["historical_product_fallback_rejected"], 1)
        self.assertEqual(
            gt["lambda_fit_source_counts_by_side"]["over"]["historical_product_lambda_fallback"],
            1,
        )
        self.assertFalse(gt["qualification_or_prediction_changes_applied"])
        self.assertEqual(result["efootball_adriatic"]["rows_with_valid_shadow"], 0)


    def test_desk_capture_tracks_prospective_poisson_shadow_and_refreshes_when_it_changes(self):
        now = datetime.now(UTC)
        row = {
            "event_id": "prospective-shadow-capture-test",
            "product": "efootball_gt",
            "league": "Test League",
            "player_1": "Alpha (shadow-player-a)",
            "player_2": "Beta (shadow-player-b)",
            "line": 4.5,
            "pick": "over",
            "market": "over_under",
            "start_time": (now + timedelta(minutes=30)).isoformat(),
            "probability": 0.65,
            "raw_model_probability": 0.67,
            "model_version": "shadow-test-v1",
            "validated_model_family": "walk_forward_efootball_poisson",
            "poisson_shadow_probability": 0.61,
            "poisson_shadow_source": "current_market_ladder_leave_one_line_out",
            "poisson_shadow_reason": "eligible_leave_one_line_out_fit",
            "desk_observed_at": now.isoformat(),
        }
        trace = []
        captured = learning_ns["capture"](
            trace, {"generated_at": now.isoformat(), "events": [row]}
        )
        self.assertEqual(captured, 1)
        self.assertAlmostEqual(trace[0]["poisson_shadow_probability"], 0.61)
        self.assertEqual(
            trace[0]["poisson_shadow_source"],
            "current_market_ladder_leave_one_line_out",
        )
        self.assertEqual(trace[0]["poisson_shadow_reason"], "eligible_leave_one_line_out_fit")
        changed = dict(row)
        changed["poisson_shadow_probability"] = 0.58
        changed["desk_observed_at"] = (now + timedelta(minutes=5)).isoformat()
        self.assertFalse(learning_ns["materially_same_forecast"](trace[0], {
            **trace[0], "poisson_shadow_probability": 0.58,
        }))
        self.assertFalse(learning_ns["materially_same_forecast"](trace[0], {
            **trace[0], "poisson_shadow_source": "historical_product_lambda_fallback",
        }))
        self.assertFalse(learning_ns["materially_same_forecast"](trace[0], {
            **trace[0], "poisson_shadow_reason": "historical_product_fallback_rejected",
        }))
        self.assertTrue(learning_ns["materially_same_forecast"](trace[0], trace[0]))


    def test_prospective_poisson_shadow_uses_identical_settled_forecasts_and_cluster_uncertainty(self):
        start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
        rows = []
        # Forecast probability is overconfident (0.85) while the shadow assigns
        # 0.60; 72/120 wins give a deterministic synthetic 60% observed rate.
        for i in range(120):
            kickoff = start + timedelta(minutes=i * 3)
            rows.append({
                "trace_id": f"prospective-shadow-{i}",
                "event_id": f"shadow-event-{i}",
                "event_key": f"efootball_gt|{i}|alpha{i}|beta{i}|4.5",
                "product": "efootball_gt",
                "participant_1": f"Alpha{i} (alpha{i})",
                "participant_2": f"Beta{i} (beta{i})",
                "start_time": kickoff.isoformat(),
                "observed_at": (kickoff - timedelta(minutes=2)).isoformat(),
                "line": 4.5,
                "pick": "over",
                "model_probability": 0.85,
                "poisson_shadow_probability": 0.60,
                "poisson_shadow_source": "current_market_ladder_leave_one_line_out",
                "scored_forecast": True,
                "settled": True,
                "push": False,
                "win": i < 72,
            })
        result = learning_ns["prospective_poisson_shadow_comparison"](
            rows, min_sample=100, replicates=250, seed=123
        )
        repeated = learning_ns["prospective_poisson_shadow_comparison"](
            rows, min_sample=100, replicates=250, seed=123
        )
        self.assertEqual(result, repeated)
        self.assertEqual(result["mode"], "PAPER_SHADOW_ONLY")
        self.assertEqual(result["matched_settled_forecasts"], 120)
        self.assertEqual(result["unique_event_clusters"], 120)
        self.assertEqual(result["status"], "POISSON_SHADOW_BETTER_WITH_CLUSTER_BOOTSTRAP_SUPPORT")
        self.assertGreater(result["brier_difference_desk_minus_poisson"], 0)
        self.assertGreater(result["log_loss_difference_desk_minus_poisson"], 0)
        self.assertGreater(result["brier_difference_95_cluster_bootstrap_ci"][0], 0)
        self.assertGreater(result["log_loss_difference_95_cluster_bootstrap_ci"][0], 0)
        self.assertFalse(result["qualification_or_prediction_changes_applied"])
        self.assertFalse(result["production_qualification_enabled"])

    def test_shadow_capture_diagnostics_separate_pending_valid_rows_from_rejections(self):
        now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
        pending = {
            "trace_id": "pending-shadow-1", "event_id": "event-a",
            "product": "efootball_gt", "start_time": (now + timedelta(minutes=20)).isoformat(),
            "observed_at": now.isoformat(), "settled": False, "scored_forecast": False,
            "poisson_shadow_probability": 0.61,
            "poisson_shadow_source": "current_market_ladder_leave_one_line_out",
            "poisson_shadow_reason": "eligible_leave_one_line_out_fit",
        }
        rejected = {
            "trace_id": "rejected-shadow-1", "event_id": "event-b",
            "product": "efootball_gt", "start_time": (now + timedelta(minutes=25)).isoformat(),
            "observed_at": now.isoformat(), "settled": False, "scored_forecast": False,
            "poisson_shadow_probability": None, "poisson_shadow_source": None,
            "poisson_shadow_reason": "historical_product_fallback_rejected",
        }
        result = learning_ns["prospective_poisson_shadow_capture_diagnostics"](
            [pending, rejected, {**pending, "product": "vfootball", "trace_id": "other"}],
            "efootball_gt",
        )
        self.assertEqual(result["captured_forecast_revisions"], 2)
        self.assertEqual(result["rows_with_valid_poisson_shadow"], 1)
        self.assertEqual(result["pending_rows_with_valid_poisson_shadow"], 1)
        self.assertEqual(result["settled_scored_rows_with_valid_poisson_shadow"], 0)
        self.assertEqual(result["rejection_reason_counts"]["historical_product_fallback_rejected"], 1)
        self.assertFalse(result["production_qualification_enabled"])


    def test_exact_line_direction_oos_uses_exact_product_side_line_metrics(self):
        metrics = {"n": 100, "brier": 0.18, "log_loss": 0.55, "ece": 0.03}
        market = {"n": 100, "brier": 0.23, "log_loss": 0.66, "ece": 0.04}
        eval_art = {
            "holdout_metrics": {"market": market, "poisson": metrics},
            "by_product": {"efootball_gt": {"market": market, "poisson": metrics}},
            "by_product_selection_line": {
                "efootball_gt": {
                    "u4.5": {"poisson": {"n": 42, "hit_rate": 0.69, "brier": 0.19}},
                    "o4.5": {"poisson": {"n": 37, "hit_rate": 0.67, "brier": 0.20}},
                    "u7.5": {"poisson": {"n": 11, "hit_rate": 0.91, "brier": 0.08}},
                }
            },
        }
        result = ns["exact_line_direction_oos"](eval_art, "efootball_gt", 4.5, "under")
        self.assertEqual(result, {"n": 42, "hit_rate": 0.69, "brier": 0.19, "variant": "poisson"})
        self.assertEqual(ns["exact_line_direction_oos"](eval_art, "efootball_gt", 7.5, "under")["n"], 11)
        self.assertEqual(ns["exact_line_direction_oos"](eval_art, "efootball_gt", 4.5, "over")["n"], 37)

        # A legacy side-only aggregate is not exact-line evidence and must not be borrowed.
        legacy = {
            "holdout_metrics": {"market": market, "poisson": metrics},
            "by_product": {"efootball_gt": {"market": market, "poisson": metrics}},
            "by_product_selection": {
                "efootball_gt": {"under": {"poisson": {"n": 900, "hit_rate": 0.99}}}
            },
        }
        no_borrow = ns["exact_line_direction_oos"](legacy, "efootball_gt", 4.5, "under")
        self.assertEqual(no_borrow["n"], 0)


    def test_efootball_recent_product_drawdown_pauses_qualification(self):
        gate = ns["efootball_recent_performance_gate"]
        drawdown = {"by_product": {"efootball_gt": {"recent_window": {
            "n": 50, "accuracy": 0.44, "brier": 0.2516978982
        }}}}
        paused = gate(drawdown, "efootball_gt")
        self.assertFalse(paused["pass"])
        self.assertEqual(paused["status"], "RECENT_PRODUCT_DRAWDOWN_PAUSE")
        self.assertEqual(paused["recent_n"], 50)
        recovered = {"by_product": {"efootball_gt": {"recent_window": {
            "n": 50, "accuracy": 0.56, "brier": 0.24
        }}}}
        self.assertTrue(gate(recovered, "efootball_gt")["pass"])
        immature = {"by_product": {"efootball_gt": {"recent_window": {
            "n": 49, "accuracy": 0.70, "brier": 0.18
        }}}}
        pending = gate(immature, "efootball_gt")
        self.assertFalse(pending["pass"])
        self.assertEqual(pending["status"], "RECENT_PRODUCT_EVIDENCE_PENDING")
        self.assertEqual(gate({}, "efootball_gt")["status"], "RECENT_PRODUCT_EVIDENCE_PENDING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
