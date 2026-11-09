"""Settlement regression tests for tennis Player-to-Win-a-Set ticket legs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import odds_ticket_tracker


class TennisSetMarketSettlementTests(unittest.TestCase):
    def row(self, *, p1_sets=2, p2_sets=1):
        return {
            "event_id": "atp-event-1",
            "sport": "tennis",
            "settled": True,
            "settled_at": "2026-11-10T18:00:00Z",
            "final_score": "6-4 3-6 6-2",
            "actual_markets": {
                "sets_won_p1": p1_sets,
                "sets_won_p2": p2_sets,
            },
        }

    def leg(self, side):
        return {
            "event_id": "atp-event-1",
            "sport": "tennis",
            "market": "player_to_win_set",
            "pick": side,
            "builder_pick": "yes",
            "selection_label": "Player " + side + " to win at least one set",
        }

    def test_player_who_loses_match_but_wins_a_set_is_settled_won(self):
        result = odds_ticket_tracker.settle_core_leg(self.leg("p2"), [self.row()])
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "WON")
        self.assertTrue(result["correct"])
        self.assertIn("1 sets won", result["result"])

    def test_player_who_wins_no_sets_is_settled_lost(self):
        result = odds_ticket_tracker.settle_core_leg(
            self.leg("p2"),
            [self.row(p1_sets=2, p2_sets=0)],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "LOST")
        self.assertFalse(result["correct"])

    def test_both_players_may_win_a_set(self):
        rows = [self.row(p1_sets=2, p2_sets=1)]
        self.assertEqual(odds_ticket_tracker.settle_core_leg(self.leg("p1"), rows)["status"], "WON")
        self.assertEqual(odds_ticket_tracker.settle_core_leg(self.leg("p2"), rows)["status"], "WON")

    def test_missing_or_invalid_set_counts_remain_unsettled(self):
        missing = {"event_id": "atp-event-1", "sport": "tennis", "actual_markets": {}}
        self.assertIsNone(odds_ticket_tracker.settle_core_leg(self.leg("p1"), [missing]))
        invalid = self.row(p1_sets="unknown", p2_sets=0)
        self.assertIsNone(odds_ticket_tracker.settle_core_leg(self.leg("p1"), [invalid]))

    def test_other_fixture_set_result_is_not_reused(self):
        other = self.row()
        other["event_id"] = "different-event"
        self.assertIsNone(odds_ticket_tracker.settle_core_leg(self.leg("p1"), [other]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
