#!/usr/bin/env python3
"""Regression tests for the Upcoming Desk exact line/side recent-loss hold."""
from __future__ import annotations

import json
import sys
import unittest
from unittest import mock
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import odds_builder as builder
from odds_builder import _upcoming_desk_recent_result_guard, _upcoming_desk_settled_performance_gate, _upcoming_desk_pending_event_ids, _exclude_pending_virtual_ticket_events, _settled_builder_lane_performance_gate


def settled_leg(event_id, status, settled_at, *, line=7.5, side="under", product="efootball_gt"):
    result = "PUSH" if status == "VOID" else ("U" if side == "under" else "O") + str(line)
    return {
        "event_id": event_id,
        "product": product,
        "sport": "virtual",
        "market": "virtual_total",
        "line": line,
        "builder_pick": side,
        "pick": f"Example A vs Example B — O/U {side} {line}",
        "status": status,
        "result": result,
        "settled_at": settled_at,
        "start_time": settled_at,
    }


def tracker_with(*legs):
    return {
        "tickets": [{
            "ticket_id": f"T-{i}",
            "status": leg["status"],
            "created_at": leg["settled_at"],
            "last_settled_at": leg["settled_at"],
            "legs": [leg],
        } for i, leg in enumerate(legs, 1)],
        "archived_tickets": [],
    }


class SettledSideProbabilityCapTests(unittest.TestCase):
    def test_upcoming_desk_uses_its_walkforward_probability_and_lower_bound_policy(self):
        index = {"exact": {
            ("efootball_gt", "4.5", "over"): {"n": 22, "wins": 13, "losses": 9},
        }}
        with (
            mock.patch.object(builder, "_load_results_first_index", return_value=index),
            mock.patch.object(builder, "selected_price_and_devig", return_value=(2.75, 1/2.75, 0.35, True)),
            mock.patch.object(builder, "odds_age", return_value=10.0),
            mock.patch.object(builder, "data_quality", return_value=1.0),
            mock.patch.object(builder, "uncertainty", return_value=0.01),
            mock.patch.object(builder, "participant_history_signal", return_value={"available": False, "score": 0.5, "participants": []}),
            mock.patch.object(builder, "_phase2_cyclical_loop_signal", return_value={"enabled": False, "flagged": False, "confidence": 0.0, "reason": "test"}),
        ):
            leg = builder.make_leg({
                "sport": "virtual", "product": "efootball_gt", "league": "Test eComp",
                "line": 4.5, "builder_pick": "over", "builder_probability": 0.677,
                "desk_calibrated_probability": 0.677, "raw_model_probability": 0.7281,
                "walkforward_exact_line_n": 433, "walkforward_exact_line_hit_rate": 0.625866,
                "upcoming_desk_research_only": True,
                "qualification_lane": builder.UPCOMING_DESK_RESEARCH_LANE,
                "player_1": "France (Virtual_12)", "player_2": "Germany (Virtual_13)",
                "builder_market": "virtual_total", "event_id": "desk-walkforward-cap-test",
                "odds_timestamp": "2026-10-20T20:00:00+00:00",
            })
        # Desk research has its own calibrated probability + exact-line
        # chronological holdout. Preserve the prior selected-ticket cap as a
        # diagnostic, but do not let that legacy lane censor this independent lane.
        self.assertAlmostEqual(leg["model_probability"], 0.677, places=5)
        self.assertTrue(leg["builder_eligible"])
        cap = leg["settled_side_probability_cap"]
        self.assertFalse(cap["applied"])
        self.assertEqual(cap["reason"], "desk_probability_uses_exact_line_walkforward")
        self.assertEqual(cap["settled_sample_n"], 22)
        self.assertAlmostEqual(cap["effective_probability"], 0.677, places=5)
        self.assertAlmostEqual(cap["diagnostic_historical_probability"], 15 / 26, places=5)
        self.assertAlmostEqual(leg["expected_value"], 0.677 * 2.75 - 1, places=5)

        with mock.patch.object(builder, "_upcoming_desk_pending_event_ids", return_value=set()):
            selected, diagnostics = builder._construct_upcoming_desk_research_batches([leg], max_batches=1)
        # One candidate is not a ticket, but it must survive the leg-level gate.
        self.assertEqual(selected, [])
        self.assertEqual(diagnostics["candidate_count"], 1)
        self.assertNotIn("desk_or_raw_probability_floor", diagnostics["leg_rejections"])
        self.assertEqual(diagnostics["reason"], "no_desk_combination_reached_odds_and_conservative_roi_gates")

    def test_short_odds_raw_model_edge_is_capped_by_losing_exact_line_history(self):
        index = {"exact": {
            ("efootball_gt", "0.5", "over"): {"n": 35, "wins": 29, "losses": 6},
        }}
        with (
            mock.patch.object(builder, "_load_results_first_index", return_value=index),
            mock.patch.object(builder, "selected_price_and_devig", return_value=(1.11, 1/1.11, 0.89, True)),
            mock.patch.object(builder, "odds_age", return_value=10.0),
            mock.patch.object(builder, "data_quality", return_value=1.0),
            mock.patch.object(builder, "uncertainty", return_value=0.01),
            mock.patch.object(builder, "participant_history_signal", return_value={"available": False, "score": 0.5, "participants": []}),
            mock.patch.object(builder, "_phase2_cyclical_loop_signal", return_value={"enabled": False, "flagged": False, "confidence": 0.0, "reason": "test"}),
        ):
            leg = builder.make_leg({
                "sport": "virtual", "product": "efootball_gt",
                "line": 0.5, "builder_pick": "over", "builder_probability": 0.9887,
                "raw_model_probability": 0.9978, "player_1": "Paris SG (BULLFROG)",
                "player_2": "Manchester City (INSTINCT)", "builder_market": "virtual_total",
                "event_id": "event-short-price",
            })
        self.assertAlmostEqual(leg["model_probability"], 31/39, places=5)
        self.assertTrue(leg["settled_side_probability_cap"]["applied"])
        self.assertEqual(leg["settled_side_probability_cap"]["settled_sample_n"], 35)
        self.assertFalse(leg["builder_eligible"])
        self.assertLess(leg["expected_value"], 0)

    def test_supported_desk_line_remains_uncapped_when_settled_rate_is_stronger(self):
        index = {"exact": {
            ("efootball_gt", "4.5", "over"): {"n": 11, "wins": 7, "losses": 4},
        }}
        result = builder._settled_exact_line_probability_cap(
            "efootball_gt", 4.5, "over", 0.60, index=index
        )
        self.assertFalse(result["applied"])
        self.assertAlmostEqual(result["effective_probability"], 0.60, places=5)
        self.assertEqual(result["settled_sample_n"], 11)

    def test_missing_or_thin_history_does_not_invent_a_probability_cap(self):
        index = {"exact": {
            ("efootball_gt", "4.5", "over"): {"n": 3, "wins": 3, "losses": 0},
        }}
        result = builder._settled_exact_line_probability_cap(
            "efootball_gt", 4.5, "over", 0.677, index=index
        )
        self.assertFalse(result["applied"])
        self.assertAlmostEqual(result["effective_probability"], 0.677, places=5)
        self.assertEqual(result["reason"], "insufficient_settled_exact_line_side_sample")


class UpcomingDeskRecentLossGateTests(unittest.TestCase):
    def test_two_distinct_latest_losses_do_not_hold_a_tiny_sample(self):
        tracker = tracker_with(
            settled_leg("event-old-loss", "LOST", "2026-10-20T05:08:00+00:00"),
            settled_leg("event-latest-loss", "LOST", "2026-10-20T05:09:00+00:00"),
        )
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["consecutive_losses"], 2)
        self.assertEqual(result["sample_n"], 2)
        self.assertIsNone(result["reason"])

    def test_duplicate_ticket_for_same_event_counts_once(self):
        first = settled_leg("event-same", "LOST", "2026-10-20T05:08:00+00:00")
        duplicate = settled_leg("event-same", "LOST", "2026-10-20T05:09:00+00:00")
        result = _upcoming_desk_recent_result_guard(
            "efootball_gt", 7.5, "under", tracker=tracker_with(first, duplicate)
        )
        self.assertFalse(result["blocked"])
        self.assertEqual(result["sample_n"], 1)

    def test_a_win_between_losses_does_not_trigger_a_tiny_sample_block(self):
        tracker = tracker_with(
            settled_leg("event-loss-1", "LOST", "2026-10-20T05:07:00+00:00"),
            settled_leg("event-loss-2", "LOST", "2026-10-20T05:08:00+00:00"),
            settled_leg("event-win", "WON", "2026-10-20T05:10:00+00:00"),
        )
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["consecutive_losses"], 0)
        self.assertEqual(result["latest_three_losses"], 2)
        self.assertIsNone(result["reason"])

    def test_interleaved_losses_in_last_five_do_not_block_without_a_mature_window(self):
        tracker = tracker_with(
            settled_leg("event-loss-1", "LOST", "2026-10-20T05:06:00+00:00"),
            settled_leg("event-loss-2", "LOST", "2026-10-20T05:07:00+00:00"),
            settled_leg("event-win-1", "WON", "2026-10-20T05:08:00+00:00"),
            settled_leg("event-loss-3", "LOST", "2026-10-20T05:09:00+00:00"),
            settled_leg("event-win-2", "WON", "2026-10-20T05:10:00+00:00"),
        )
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["latest_five_losses"], 3)
        self.assertEqual(result["decisive_sample_n"], 5)

    def test_four_consecutive_losses_hold_exact_selection(self):
        tracker = tracker_with(*[
            settled_leg(f"event-loss-{i}", "LOST", f"2026-10-20T05:{i:02d}:00+00:00")
            for i in range(5, 9)
        ])
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["consecutive_losses"], 4)
        self.assertEqual(result["reason"], "recent_settled_line_side_loss_streak")

    def test_recent_last_ten_hit_rate_below_fifty_percent_holds(self):
        # Four wins in the latest ten, with wins most recent so the rate test
        # (not the streak guard) must explain the hold.
        outcomes = ["LOST"] * 6 + ["WON"] * 4
        tracker = tracker_with(*[
            settled_leg(f"event-{i}", status, f"2026-10-20T05:{i:02d}:00+00:00")
            for i, status in enumerate(outcomes)
        ])
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["latest10_n"], 10)
        self.assertEqual(result["latest10_wins"], 4)
        self.assertEqual(result["latest10_hit_rate"], 0.4)
        self.assertEqual(result["reason"], "recent_settled_line_side_last10_below_0_50")

    def test_recent_last_twenty_hit_rate_below_fifty_five_blocks_when_last_ten_passes(self):
        outcomes = (["LOST"] * 5 + ["WON"] * 5) * 2
        tracker = tracker_with(*[
            settled_leg(f"event-{i}", status, f"2026-10-20T05:{i:02d}:00+00:00")
            for i, status in enumerate(outcomes)
        ])
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["latest10_hit_rate"], 0.5)
        self.assertEqual(result["latest20_hit_rate"], 0.5)
        self.assertEqual(result["reason"], "recent_settled_line_side_last20_below_0_55")

    def test_exactly_fifty_percent_in_latest_ten_passes_floor(self):
        outcomes = ["LOST"] * 5 + ["WON"] * 5
        tracker = tracker_with(*[
            settled_leg(f"event-{i}", status, f"2026-10-20T05:{i:02d}:00+00:00")
            for i, status in enumerate(outcomes)
        ])
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=tracker)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["latest10_hit_rate"], 0.5)
        self.assertIsNone(result["reason"])

    def test_guard_is_scoped_to_product_line_and_side(self):
        tracker = tracker_with(
            settled_leg("event-loss-1", "LOST", "2026-10-20T05:07:00+00:00"),
            settled_leg("event-loss-2", "LOST", "2026-10-20T05:08:00+00:00"),
        )
        self.assertFalse(_upcoming_desk_recent_result_guard("efootball_gt", 7.5, "over", tracker=tracker)["blocked"])
        self.assertFalse(_upcoming_desk_recent_result_guard("efootball_gt", 4.5, "under", tracker=tracker)["blocked"])
        self.assertFalse(_upcoming_desk_recent_result_guard("efootball_adriatic", 7.5, "under", tracker=tracker)["blocked"])

    def test_live_ledger_smoke_reports_current_under_75_guard(self):
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under")
        self.assertIsInstance(result.get("blocked"), bool)
        self.assertGreaterEqual(int(result.get("sample_n", 0)), int(result.get("consecutive_losses", 0)))
        print("Live ledger eFootball GT Under 7.5 guard:", json.dumps({
            "blocked": result.get("blocked"),
            "consecutive_losses": result.get("consecutive_losses"),
            "sample_n": result.get("sample_n"),
            "latest10_hit_rate": result.get("latest10_hit_rate"),
            "latest20_hit_rate": result.get("latest20_hit_rate"),
            "recent_results": result.get("recent_results", []),
        }, sort_keys=True))

    def test_pending_legs_are_not_results(self):
        pending = settled_leg("future-event", "PENDING", "2026-10-20T06:00:00+00:00")
        losses = tracker_with(
            settled_leg("event-loss-1", "LOST", "2026-10-20T05:07:00+00:00"),
            pending,
        )
        result = _upcoming_desk_recent_result_guard("efootball_gt", 7.5, "under", tracker=losses)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["sample_n"], 1)




def desk_ticket(ticket_id, status, odds=3.5, lane="upcoming_desk_research", events=None):
    event_ids = list(events) if events is not None else [f"{ticket_id}-event-a", f"{ticket_id}-event-b"]
    leg_status = str(status or "PENDING").upper()
    legs = [{
        "product": "efootball_gt",
        "sport": "virtual",
        "event_id": event_id,
        "status": leg_status,
        "market": "virtual_total",
        "line": 4.5,
        "builder_pick": "over",
        "pick": f"Example {index} vs Opponent {index} — O/U over 4.5",
        "start_time": "2026-10-20T03:00:00+00:00",
        "qualification_lane": lane,
    } for index, event_id in enumerate(event_ids, 1)]
    return {
        "ticket_id": ticket_id,
        "primary_lane": lane,
        "status": status,
        "combined_odds": odds,
        "created_at": "2026-10-20T04:00:00+00:00",
        "last_settled_at": "2026-10-20T05:00:00+00:00",
        "leg_count": len(legs),
        "legs": legs,
    }


class UpcomingDeskSettledPromotionGateTests(unittest.TestCase):
    def test_nine_settled_desk_tickets_cannot_promote_research_lane(self):
        tracker = {
            "tickets": [
                desk_ticket("desk-win-1", "WON"),
                desk_ticket("desk-win-2", "WON"),
                *[desk_ticket(f"desk-loss-{i}", "LOST") for i in range(7)],
            ],
            "archived_tickets": [],
        }
        result = _upcoming_desk_settled_performance_gate(tracker=tracker)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 9)
        self.assertEqual(result["flat_stake_roi"], round((2 * 2.5 - 7) / 9, 6))
        self.assertEqual(result["reason"], "insufficient_settled_lane_ticket_sample")

    def test_sufficient_sample_still_fails_when_realized_roi_is_negative(self):
        tracker = {
            "tickets": [
                desk_ticket("desk-win-1", "WON"),
                desk_ticket("desk-win-2", "WON"),
                *[desk_ticket(f"desk-loss-{i}", "LOST") for i in range(10)],
            ],
            "archived_tickets": [],
        }
        result = _upcoming_desk_settled_performance_gate(tracker=tracker)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 12)
        self.assertLess(result["flat_stake_roi"], 0)
        self.assertEqual(result["reason"], "settled_lane_ticket_roi_below_promotion_floor")

    def test_desk_promotes_only_after_sample_and_positive_roi_floor_both_pass(self):
        tracker = {
            "tickets": [
                *[desk_ticket(f"desk-win-{i}", "WON", odds=3.5) for i in range(3)],
                *[desk_ticket(f"desk-loss-{i}", "LOST", odds=3.5) for i in range(7)],
            ],
            "archived_tickets": [],
        }
        result = _upcoming_desk_settled_performance_gate(tracker=tracker)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 10)
        self.assertEqual(result["flat_stake_roi"], 0.05)
        self.assertEqual(result["event_independent_settled_ticket_n"], 10)
        self.assertEqual(result["event_independent_flat_stake_roi"], 0.05)
        self.assertIsNone(result["reason"])

    def test_repeated_fixtures_do_not_inflate_the_independent_promotion_sample(self):
        shared = "repeat-the-same-fixture"
        tickets = [
            desk_ticket(f"overlap-win-{i}", "WON", odds=3.5, events=[shared, f"unique-{i}"])
            for i in range(5)
        ]
        tickets += [
            desk_ticket(f"overlap-loss-{i}", "LOST", odds=3.5, events=[shared, f"loss-{i}"])
            for i in range(7)
        ]
        result = _upcoming_desk_settled_performance_gate(
            tracker={"tickets": tickets, "archived_tickets": []}
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 12)
        self.assertGreater(result["flat_stake_roi"], 0.02)
        self.assertEqual(result["event_independent_settled_ticket_n"], 0)
        self.assertEqual(result["overlapping_or_incomplete_ticket_n"], 12)
        self.assertEqual(result["reason"], "insufficient_event_independent_settled_lane_sample")

    def test_held_desk_lane_can_collect_only_qualified_paper_research(self):
        held_gate = {
            "lane": "upcoming_desk_research",
            "eligible": False,
            "reason": "insufficient_event_independent_settled_lane_sample",
            "settled_ticket_n": 16,
            "event_independent_settled_ticket_n": 7,
            "flat_stake_roi": 0.376,
            "event_independent_flat_stake_roi": 0.039,
        }
        row_a = {
            "sport": "virtual", "product": "efootball_gt", "event_id": "future-a",
            "start_time": "2026-10-20T17:00:00+00:00",
            "player_1": "Alpha", "player_2": "Bravo", "match": "Alpha vs Bravo",
            "builder_pick": "over", "line": 4.5, "bookmaker_odds": 1.75,
            "model_probability": 0.61, "model_edge": 0.08,
            "qualification_lane": "upcoming_desk_research_only",
            "upcoming_desk_research_only": True,
        }
        row_b = {
            "sport": "virtual", "product": "efootball_gt", "event_id": "future-b",
            "start_time": "2026-10-20T17:10:00+00:00",
            "player_1": "Charlie", "player_2": "Delta", "match": "Charlie vs Delta",
            "builder_pick": "over", "line": 4.5, "bookmaker_odds": 1.85,
            "model_probability": 0.61, "model_edge": 0.09,
            "qualification_lane": "upcoming_desk_research_only",
            "upcoming_desk_research_only": True,
        }
        metrics = {
            "model_rating": 32.0, "raw_model_rating": 37.0,
            "combined_model_probability": 0.32, "raw_combined_model_probability": 0.37,
            "ticket_calibration_gamma": 1.0,
            "ticket_calibration_mode": "upcoming_desk_exact_line_wilson_lower_bound_independence_proxy",
            "ticket_calibration_ready": False,
            "leg_strength_rating": 61.0, "avg_model_probability": 61.0,
            "avg_model_edge_percent": 8.5,
        }
        desk_diag = {"enabled": True, "ticket_probability_method": "Wilson lower-bound product"}
        option = {
            "rows": [row_a, row_b], "metrics": metrics, "odds": 3.2375,
            "span": 10.0, "roi": 0.035, "score": (0.32,),
        }
        with (
            mock.patch.object(builder, "make_leg", side_effect=lambda x: dict(x)),
            mock.patch.object(builder, "_exclude_pending_virtual_ticket_events", return_value=([], 0)),
            mock.patch.object(builder, "construction_shape_diagnostics", return_value=[]),
            mock.patch.object(builder, "_construct_upcoming_desk_research_batches", return_value=([option], desk_diag)),
            mock.patch.object(builder, "_upcoming_desk_settled_performance_gate", return_value=held_gate),
        ):
            batches, built, diagnostics = builder.build_value_batches([])
        self.assertEqual(len(batches), 1, "the held lane must keep gathering valid paper-only research outcomes")
        self.assertIs(batches[0]["promotion_allowed"], False)
        self.assertTrue(batches[0]["research_only_promotion_held"])
        self.assertEqual(diagnostics["construction_priority"], "upcoming_desk_research_observation_only")
        self.assertTrue(diagnostics["upcoming_desk_research_diagnostics"]["primary_lane_held"])
        self.assertEqual(
            diagnostics["upcoming_desk_research_diagnostics"]["primary_lane_hold_reason"],
            "insufficient_event_independent_settled_lane_sample",
        )

    def test_pending_and_unrelated_tickets_are_not_settled_promotion_evidence(self):
        tracker = {
            "tickets": [
                desk_ticket("desk-win-1", "WON"),
                desk_ticket("desk-win-2", "WON"),
                desk_ticket("pending", "PENDING"),
                desk_ticket("other-lane", "WON", lane="high_confidence_research"),
            ],
            "archived_tickets": [
                desk_ticket("desk-win-1", "WON"),  # archived/current duplicate counts once
            ],
        }
        result = _upcoming_desk_settled_performance_gate(tracker=tracker)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 2)
        self.assertEqual(result["wins"], 2)

    def test_negative_vfootball_lane_roi_is_not_overridden_by_old_event_holdout(self):
        tracker = {
            "tickets": [
                *[desk_ticket(f"vf-win-{i}", "WON", odds=3.05, lane="vfootball_event_holdout_value") for i in range(3)],
                *[desk_ticket(f"vf-loss-{i}", "LOST", odds=3.05, lane="vfootball_event_holdout_value") for i in range(17)],
            ],
            "archived_tickets": [],
        }
        result = _settled_builder_lane_performance_gate("vfootball_event_holdout_value", tracker=tracker)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 20)
        self.assertLess(result["flat_stake_roi"], 0)
        self.assertEqual(result["reason"], "settled_lane_ticket_roi_below_promotion_floor")

    def test_high_confidence_lane_needs_non_overlapping_fixtures_too(self):
        repeated = [desk_ticket(f"same-event-{i}", "WON", odds=4.7,
                                 lane="high_confidence_research",
                                 events=["one-reused-event", f"other-{i}"])
                    for i in range(12)]
        result = _settled_builder_lane_performance_gate(
            "high_confidence_research",
            tracker={"tickets": repeated, "archived_tickets": []}
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["event_independent_settled_ticket_n"], 0)
        self.assertEqual(result["reason"], "insufficient_event_independent_settled_lane_sample")

    def test_high_confidence_lane_can_pass_its_own_settled_return_gate(self):
        tracker = {
            "tickets": [
                *[desk_ticket(f"hc-win-{i}", "WON", odds=4.7, lane="high_confidence_research") for i in range(21)],
                *[desk_ticket(f"hc-loss-{i}", "LOST", odds=4.7, lane="high_confidence_research") for i in range(32)],
            ],
            "archived_tickets": [],
        }
        result = _settled_builder_lane_performance_gate("high_confidence_research", tracker=tracker)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["settled_ticket_n"], 53)
        self.assertGreaterEqual(result["flat_stake_roi"], 0.02)

    def test_open_ticket_event_is_removed_from_every_virtual_construction_pool(self):
        rows = [
            {"sport": "virtual", "product": "efootball_gt", "event_id": "still-open-event", "builder_eligible": True, "status": "ELIGIBLE"},
            {"sport": "virtual", "product": "efootball_gt", "event_id": "new-event", "builder_eligible": True, "status": "ELIGIBLE"},
            {"sport": "football", "product": "premier-league", "event_id": "still-open-event", "builder_eligible": True, "status": "ELIGIBLE"},
        ]
        filtered, rejected = _exclude_pending_virtual_ticket_events(rows, {"still-open-event"})
        self.assertEqual(rejected, 1)
        self.assertFalse(filtered[0]["builder_eligible"])
        self.assertEqual(filtered[0]["status"], "REJECTED")
        self.assertEqual(filtered[0]["builder_rejection_reason"], "event_already_in_pending_ticket")
        self.assertTrue(filtered[1]["builder_eligible"])
        self.assertTrue(filtered[2]["builder_eligible"])

    def test_stale_archived_pending_events_expire_as_live_holds_without_fabricating_results(self):
        now = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
        tracker = {
            "tickets": [],
            "archived_tickets": [
                {
                    "ticket_id": "stale-pending",
                    "status": "PENDING",
                    "legs": [{
                        "product": "efootball_gt", "event_id": "old-unresolved-event",
                        "status": "PENDING", "start_time": "2026-10-19T08:00:00+00:00",
                    }],
                },
                {
                    "ticket_id": "parent-lost-live-leg",
                    "status": "LOST",
                    "legs": [{
                        "product": "efootball_gt", "event_id": "still-live-event",
                        "status": "PENDING", "start_time": "2026-10-20T17:00:00+00:00",
                    }],
                },
                {
                    "ticket_id": "missing-start-fail-closed",
                    "status": "PENDING",
                    "legs": [{
                        "product": "efootball_gt", "event_id": "unknown-time-event",
                        "status": "PENDING",
                    }],
                },
            ],
        }
        pending = _upcoming_desk_pending_event_ids(tracker=tracker, now=now)
        self.assertEqual(pending, {"still-live-event", "unknown-time-event"})
        # Expiring a hold never changes the underlying unknown settlement.
        self.assertEqual(tracker["archived_tickets"][0]["legs"][0]["status"], "PENDING")

    def test_open_events_are_excluded_even_when_parent_ticket_already_lost(self):
        tracker = {
            "tickets": [
                {
                    "ticket_id": "ticket-already-lost",
                    "status": "LOST",
                    "legs": [
                        {"product": "efootball_gt", "event_id": "finished-event", "status": "WON"},
                        {"product": "efootball_gt", "event_id": "still-open-event", "status": "PENDING"},
                    ],
                }
            ],
            "archived_tickets": [
                {
                    "ticket_id": "archived-ticket",
                    "status": "PENDING",
                    "legs": [
                        {"product": "efootball_gt", "event_id": "archived-open-event", "status": "PENDING"},
                        {"product": "vfootball", "event_id": "research-only-event", "status": "PENDING"},
                    ],
                }
            ],
        }
        pending = _upcoming_desk_pending_event_ids(tracker=tracker)
        self.assertEqual(pending, {
            "event:efootball_gt:still-open-event",
            "event:efootball_gt:archived-open-event",
        })
        self.assertNotIn("event:efootball_gt:finished-event", pending)
        self.assertNotIn("event:vfootball:research-only-event", pending)




    def test_reused_provider_id_only_holds_the_same_identified_fixture(self):
        pending_leg = {
            "product": "efootball_gt", "event_id": "reused-provider-id",
            "status": "PENDING", "start_time": "2026-10-20T08:00:00+00:00",
            "participant_1": "Boca Juniors (zaha)", "participant_2": "Chelsea (mika)",
        }
        tracker = {"tickets": [{
            "ticket_id": "pending-same-session", "status": "PENDING",
            "legs": [pending_leg],
        }], "archived_tickets": []}
        pending = builder._upcoming_desk_pending_event_ids(tracker=tracker)
        rows = [
            {"sport": "virtual", "product": "efootball_gt", "event_id": "reused-provider-id",
             "start_time": "2026-10-20T08:00:00+00:00",
             "participant_1": "Boca Juniors (zaha)", "participant_2": "Chelsea (mika)",
             "builder_eligible": True, "status": "ELIGIBLE"},
            {"sport": "virtual", "product": "efootball_gt", "event_id": "reused-provider-id",
             "start_time": "2026-10-20T10:00:00+00:00",
             "participant_1": "Real Madrid (cira)", "participant_2": "Juventus (cappo)",
             "builder_eligible": True, "status": "ELIGIBLE"},
        ]
        filtered, rejected = _exclude_pending_virtual_ticket_events(rows, pending)
        self.assertEqual(rejected, 1)
        self.assertFalse(filtered[0]["builder_eligible"])
        self.assertTrue(filtered[1]["builder_eligible"])

    def test_reused_provider_id_does_not_merge_settled_ticket_outcomes(self):
        def leg(status, kickoff, left, right):
            return {
                "product": "efootball_gt", "event_id": "reused-provider-id",
                "status": status, "line": 4.5, "builder_pick": "over", "pick": "Over 4.5",
                "start_time": kickoff, "participant_1": left, "participant_2": right,
            }
        tracker = {"tickets": [
            {"ticket_id": "session-a", "status": "WON", "combined_odds": 3.2,
             "legs": [leg("WON", "2026-10-20T08:00:00+00:00", "Boca (zaha)", "Chelsea (mika)")],
             "created_at": "2026-10-20T08:00:00+00:00"},
            {"ticket_id": "session-b", "status": "LOST", "combined_odds": 3.2,
             "legs": [leg("LOST", "2026-10-20T10:00:00+00:00", "Real Madrid (cira)", "Juventus (cappo)")],
             "created_at": "2026-10-20T10:00:00+00:00"},
        ], "archived_tickets": []}
        old_spoiler, old_results = builder._TICKET_SPOILER_CACHE, builder._RESULTS_FIRST_CACHE
        try:
            builder._TICKET_SPOILER_CACHE = None
            builder._RESULTS_FIRST_CACHE = None
            with mock.patch.object(builder, "load", return_value=tracker):
                performance = builder._load_ticket_performance_index()
                results = builder._load_results_first_index()
            self.assertEqual(performance[("efootball_gt", "4.5", "over")], {"n": 2, "wins": 1, "losses": 1})
            self.assertEqual(results["exact"][("efootball_gt", "4.5", "over")], {"n": 2, "wins": 1, "losses": 1})
        finally:
            builder._TICKET_SPOILER_CACHE, builder._RESULTS_FIRST_CACHE = old_spoiler, old_results


class CompleteSettledLedgerIntegrityTests(unittest.TestCase):
    def make_ticket(self, ticket_id, ticket_status, leg_status, event_id, *, stamp="2026-10-20T10:00:00+00:00"):
        return {
            "ticket_id": ticket_id,
            "status": ticket_status,
            "created_at": stamp,
            "last_settled_at": stamp,
            "primary_lane": "efootball_exact_evidence_value",
            "leg_count": 2,
            "combined_odds": 3.2,
            "products": ["efootball_gt"],
            "legs": [
                {
                    "product": "efootball_gt", "sport": "virtual", "line": 4.5,
                    "builder_pick": "over", "pick": "Team A vs Team B — O/U over 4.5",
                    "status": leg_status, "event_id": event_id,
                    "qualification_lane": "efootball_exact_evidence_value",
                },
                {
                    "product": "efootball_gt", "sport": "virtual", "line": 3.5,
                    "builder_pick": "under", "pick": "Team C vs Team D — O/U under 3.5",
                    "status": leg_status, "event_id": event_id + "-b",
                    "qualification_lane": "efootball_exact_evidence_value",
                },
            ],
        }

    def test_archived_losses_feed_exact_performance_and_results_first_indexes_once(self):
        archived = [
            self.make_ticket(f"T-{i}", "LOST", "LOST", f"event-{i}")
            for i in range(50)
        ]
        # The active copy is canonical and replaces its stale archived duplicate.
        current = [self.make_ticket("T-0", "WON", "WON", "event-0")]
        tracker = {"tickets": current, "archived_tickets": archived}

        old_spoiler = builder._TICKET_SPOILER_CACHE
        old_results = builder._RESULTS_FIRST_CACHE
        builder._TICKET_SPOILER_CACHE = None
        builder._RESULTS_FIRST_CACHE = None
        try:
            with mock.patch.object(builder, "load", return_value=tracker):
                eligible, details = builder.ticket_performance_gate("efootball_gt", 4.5, "over")
                results = builder._load_results_first_index()
            self.assertFalse(eligible)
            self.assertTrue(details["available"])
            self.assertEqual(details["n"], 50)
            self.assertEqual(details["wins"], 1)
            self.assertEqual(details["losses"], 49)
            exact = results["exact"][("efootball_gt", "4.5", "over")]
            self.assertEqual(exact, {"n": 50, "wins": 1, "losses": 49})
            self.assertEqual(results["product_tickets"]["efootball_gt"]["tickets"], 50)
        finally:
            builder._TICKET_SPOILER_CACHE = old_spoiler
            builder._RESULTS_FIRST_CACHE = old_results

    def test_current_ticket_result_overrides_stale_archived_copy_in_recent_guard(self):
        current = self.make_ticket("DUP", "WON", "WON", "same-event")
        archived = self.make_ticket("DUP", "LOST", "LOST", "same-event")
        tracker = {"tickets": [current], "archived_tickets": [archived]}
        old_cache = builder._UPCOMING_DESK_SETTLED_RESULT_INDEX_CACHE
        builder._UPCOMING_DESK_SETTLED_RESULT_INDEX_CACHE = None
        try:
            index = builder._upcoming_desk_settled_result_index(tracker=tracker)
            rows = index[("efootball_gt", "4.5", "over")]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "WON")
            self.assertEqual(rows[0]["event_id"], "same-event")
        finally:
            builder._UPCOMING_DESK_SETTLED_RESULT_INDEX_CACHE = old_cache

    def test_current_settlement_removes_stale_archived_pending_event_hold(self):
        current = self.make_ticket("DUP", "WON", "WON", "already-settled")
        archived = self.make_ticket("DUP", "PENDING", "PENDING", "already-settled")
        tracker = {"tickets": [current], "archived_tickets": [archived]}
        pending = builder._upcoming_desk_pending_event_ids(tracker=tracker)
        self.assertNotIn("already-settled", pending)
        self.assertNotIn("already-settled-b", pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
