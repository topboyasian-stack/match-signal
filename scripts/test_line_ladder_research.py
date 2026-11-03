#!/usr/bin/env python3
"""Regression tests for Upcoming Desk anchor identity in shadow line-ladder research."""
import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("line_ladder_research.py")
SPEC = importlib.util.spec_from_file_location("line_ladder_research", MODULE_PATH)
line_ladder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(line_ladder)


class CurrentAnchorIdentityTests(unittest.TestCase):
    def test_desk_schema_maps_league_and_participants(self):
        event = {
            "sport": "virtual",
            "market": "over_under",
            "product": "efootball_gt",
            "event_id": "sr:match:D001031126",
            "start_time": "2026-11-03T00:01:00+00:00",
            "league": "Esoccer H2H GG League",
            "player_1": "Liverpool (PILLAR)",
            "player_2": "Napoli (DECIMATOR)",
            "line": 4.5,
            "pick": "under 4.5",
            "probability": 0.8413,
            "odds": 1.24,
        }

        anchors = line_ladder.current_anchors({}, {"events": [event]})

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["competition"], "Esoccer H2H GG League")
        self.assertEqual(
            anchors[0]["match"],
            "Liverpool (PILLAR) vs Napoli (DECIMATOR)",
        )
        self.assertEqual(anchors[0]["event_id"], "sr:match:D001031126")
        self.assertEqual(anchors[0]["anchor_line"], 4.5)
        self.assertEqual(anchors[0]["anchor_side"], "under")

    def test_existing_builder_identity_fields_are_preserved(self):
        leg = {
            "product": "efootball_adriatic",
            "event_id": "event-2",
            "competition": "Adriatic League",
            "match": "Player A vs Player B",
            "line": 3.5,
            "pick": "over 3.5",
            "model_probability": 0.9,
        }

        anchors = line_ladder.current_anchors({"best_available_legs": [leg]})

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["competition"], "Adriatic League")
        self.assertEqual(anchors[0]["match"], "Player A vs Player B")
        self.assertEqual(anchors[0]["anchor_side"], "over")


if __name__ == "__main__":
    unittest.main()
