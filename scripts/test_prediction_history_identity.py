#!/usr/bin/env python3
"""Regression tests for namespaced prediction identity and football result settlement."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import predict_today
from prediction_identity import (
    append_new_predictions,
    football_result_participants_match,
    prediction_identity_key,
)


def scoreboard_event(event_id, home, away, home_score, away_score):
    return {
        "id": event_id,
        "status": {"type": {"completed": True}},
        "competitors": [
            {"homeAway": "home", "score": str(home_score), "team": {"displayName": home}},
            {"homeAway": "away", "score": str(away_score), "team": {"displayName": away}},
        ],
    }


class PredictionIdentityTests(unittest.TestCase):
    def test_event_id_is_namespaced_by_sport_and_competition(self):
        ucl = {"sport": "football", "league": "Champions League", "event_id": "shared-espn-id"}
        bundesliga = {"sport": "football", "league": "Bundesliga", "event_id": "shared-espn-id"}
        tennis = {"sport": "tennis", "league": "ATP", "event_id": "shared-espn-id"}
        self.assertNotEqual(prediction_identity_key(ucl), prediction_identity_key(bundesliga))
        self.assertNotEqual(prediction_identity_key(ucl), prediction_identity_key(tennis))
        self.assertEqual(
            prediction_identity_key({**ucl, "league": "  champions   league "}),
            prediction_identity_key(ucl),
        )

    def test_append_deduplicates_only_the_same_canonical_fixture(self):
        history = [{"sport": "football", "league": "Bundesliga", "event_id": "same-id", "settled": True}]
        new_rows = [
            {"sport": "football", "league": "Champions League", "event_id": "same-id"},
            {"sport": "football", "league": "Bundesliga", "event_id": "same-id"},
            {"sport": "football", "league": "Champions League", "event_id": "same-id"},
        ]
        self.assertEqual(append_new_predictions(history, new_rows), 1)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["league"], "Champions League")

    def test_append_keeps_histories_longer_than_the_old_rolling_cap(self):
        history = [
            {"sport": "football", "league": "Bundesliga", "event_id": f"event-{index}", "settled": True}
            for index in range(2705)
        ]
        self.assertEqual(append_new_predictions(history, [
            {"sport": "football", "league": "Champions League", "event_id": "ucl-new"}
        ]), 1)
        self.assertEqual(len(history), 2706)
        self.assertEqual(history[0]["event_id"], "event-0")

    def test_football_result_participants_must_match_saved_home_away_order(self):
        prediction = {"player_1": "Borussia Dortmund", "player_2": "Real Betis"}
        matching = scoreboard_event("e1", "Borussia Dortmund", "Real Betis", 2, 1)
        wrong = scoreboard_event("e1", "Real Betis", "Borussia Dortmund", 2, 1)
        self.assertTrue(football_result_participants_match(prediction, matching))
        self.assertFalse(football_result_participants_match(prediction, wrong))
        self.assertFalse(football_result_participants_match(prediction, scoreboard_event("e1", "Other FC", "Real Betis", 2, 1)))

    def test_same_provider_event_id_in_two_competitions_settles_independently(self):
        today = datetime.now(timezone.utc).date().isoformat()
        event_id = "same-provider-event-id"
        ucl_event = scoreboard_event(event_id, "Borussia Dortmund", "Real Betis", 2, 1)
        domestic_event = scoreboard_event(event_id, "Bayern Munich", "RB Leipzig", 0, 3)
        rows = [
            {
                "sport": "football", "league": "Champions League", "event_id": event_id,
                "start_time": today + "T18:00:00Z", "player_1": "Borussia Dortmund",
                "player_2": "Real Betis", "pick": "p1",
                "probabilities": {"p1": 0.60, "draw": 0.25, "p2": 0.15},
                "markets": {"over_under": {"line": 2.5}},
            },
            {
                "sport": "football", "league": "Bundesliga", "event_id": event_id,
                "start_time": today + "T18:00:00Z", "player_1": "Bayern Munich",
                "player_2": "RB Leipzig", "pick": "p2",
                "probabilities": {"p1": 0.25, "draw": 0.25, "p2": 0.50},
                "markets": {"over_under": {"line": 2.5}},
            },
        ]

        def fake_scoreboard(sport, league, date):
            if sport != "soccer":
                return {"events": []}
            if league == "uefa.champions":
                return {"events": [ucl_event]}
            if league == "ger.1":
                return {"events": [domestic_event]}
            return {"events": []}

        with patch.object(predict_today, "fetch_scoreboard", side_effect=fake_scoreboard):
            settled = predict_today.settle_predictions(rows)

        self.assertTrue(all(row.get("settled") is True for row in settled))
        self.assertEqual(settled[0]["final_score"], [2.0, 1.0])
        self.assertEqual(settled[0]["actual"], "p1")
        self.assertTrue(settled[0]["correct"])
        self.assertEqual(settled[1]["final_score"], [0.0, 3.0])
        self.assertEqual(settled[1]["actual"], "p2")
        self.assertTrue(settled[1]["correct"])

    def test_prediction_and_settlement_writers_do_not_truncate_history(self):
        prediction_source = (SCRIPTS / "predict_today.py").read_text(encoding="utf-8")
        settlement_source = (SCRIPTS / "settle_same_day.py").read_text(encoding="utf-8")
        self.assertNotIn("history = history[-2500:]", prediction_source)
        self.assertNotIn("history[-2500:]", settlement_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
