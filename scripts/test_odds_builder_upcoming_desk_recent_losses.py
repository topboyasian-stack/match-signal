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

from odds_builder import _upcoming_desk_recent_result_guard


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
