#!/usr/bin/env python3
"""Regression tests for the Upcoming Desk exact line/side recent-loss hold."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from odds_builder import _upcoming_desk_recent_result_guard, _upcoming_desk_settled_performance_gate, _upcoming_desk_pending_event_ids, _settled_builder_lane_performance_gate


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




def desk_ticket(ticket_id, status, odds=3.5, lane="upcoming_desk_research"):
    return {
        "ticket_id": ticket_id,
        "primary_lane": lane,
        "status": status,
        "combined_odds": odds,
        "created_at": f"2026-10-20T04:00:00+00:00",
        "last_settled_at": f"2026-10-20T05:00:00+00:00",
        "legs": [],
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
        self.assertEqual(result["reason"], "insufficient_settled_desk_ticket_sample")

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
        self.assertEqual(result["reason"], "settled_desk_ticket_roi_below_promotion_floor")

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
        self.assertIsNone(result["reason"])

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
        self.assertEqual(pending, {"still-open-event", "archived-open-event"})
        self.assertNotIn("finished-event", pending)
        self.assertNotIn("research-only-event", pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
