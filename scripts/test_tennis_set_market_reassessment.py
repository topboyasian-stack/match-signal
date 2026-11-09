"""Regression tests for exact SportyBet tennis Player-to-Win-a-Set mapping."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tennis_set_market_model as set_model
import tennis_set_market_reassessment as reassessment
import predict_today


NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def fixture():
    return {
        "sport": "tennis",
        "league": "ATP",
        "event_id": "espn-100",
        "start_time": (NOW + timedelta(hours=3)).isoformat(),
        "player_1": "Alex Example",
        "player_2": "Juan Example",
        "probabilities": {"p1": 0.68, "p2": 0.32},
        "sportybet_market": {
            "available": True,
            "event_id": "sr:match:100",
            "home": "Alex Example",
            "away": "Juan Example",
            "match": {"method": "direct"},
            "fetched_at": (NOW - timedelta(minutes=2)).isoformat(),
            "markets": [
                {
                    "id": "777",
                    "name": "Player to win at least one set",
                    "specifier": "player=home",
                    "outcomes": [
                        {"id": "77701", "name": "Yes", "book_odds": 1.22},
                        {"id": "77702", "name": "No", "book_odds": 3.70},
                    ],
                },
                {
                    "id": "777",
                    "name": "Player to win at least one set",
                    "specifier": "player=away",
                    "outcomes": [
                        {"id": "77703", "name": "Yes", "book_odds": 1.45},
                        {"id": "77704", "name": "No", "book_odds": 2.55},
                    ],
                },
            ],
        },
    }


class FakeCore:
    PREDICTIONS = Path("unused-predictions.json")

    @staticmethod
    def load(_path, default):
        return default

    @staticmethod
    def within_builder_horizon(_row, _now):
        return True


class TennisSetMarketReassessmentTests(unittest.TestCase):
    def test_live_sportybet_snapshot_preserves_set_market_identity_and_specifier(self):
        event = {
            "event_id": "sr:match:101",
            "home": "Alex Example",
            "away": "Juan Example",
            "tournament": "ATP Example Open",
            "category": "Tennis",
            "start_time_ms": int((NOW + timedelta(hours=2)).timestamp() * 1000),
            "markets": [
                {
                    "id": "777",
                    "desc": "Player to win at least one set",
                    "specifier": "player=home",
                    "outcomes": [
                        {"id": "77701", "desc": "Yes", "odds": 1.22},
                        {"id": "77702", "desc": "No", "odds": 3.70},
                    ],
                }
            ],
        }
        self.assertIn("203", predict_today.SPORTYBET_MARKETS["tennis"].split(","))
        snapshot = predict_today._sportybet_market_snapshot(event, "tennis")
        self.assertEqual(snapshot["home"], "Alex Example")
        self.assertEqual(snapshot["away"], "Juan Example")
        self.assertEqual(snapshot["markets"][0]["specifier"], "player=home")
        self.assertEqual(snapshot["markets"][0]["outcomes"][0]["id"], "77701")

    def test_home_and_away_yes_no_markets_map_to_prediction_sides(self):
        row = fixture()
        prediction = {
            "player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}
        }
        candidates, counts = reassessment._market_candidates(row, prediction, NOW)
        self.assertEqual(len(candidates), 2)
        by_side = {item["tennis_set_market"]["player_side"]: item for item in candidates}
        self.assertEqual(set(by_side), {"p1", "p2"})
        self.assertEqual(by_side["p1"]["sportybet_outcome_id"], "77701")
        self.assertEqual(by_side["p2"]["sportybet_outcome_id"], "77703")
        self.assertAlmostEqual(by_side["p1"]["builder_probability"], 0.86)
        self.assertEqual(by_side["p1"]["tennis_set_market_quotes"][1]["outcome_id"], "77702")
        self.assertEqual(by_side["p2"]["sportybet_event_id"], "sr:match:100")
        self.assertEqual(counts["candidates"], 2)

    def test_reverse_market_identity_flips_home_and_away(self):
        row = fixture()
        row["sportybet_market"]["match"]["method"] = "reverse"
        row["sportybet_market"]["markets"] = [row["sportybet_market"]["markets"][0]]
        prediction = {"player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}}
        candidates, _ = reassessment._market_candidates(row, prediction, NOW)
        self.assertEqual(candidates[0]["tennis_set_market"]["player_side"], "p2")
        self.assertAlmostEqual(candidates[0]["builder_probability"], 0.81)

    def test_ambiguous_subject_is_not_guessed(self):
        row = fixture()
        row["sportybet_market"]["markets"] = [dict(
            row["sportybet_market"]["markets"][0],
            specifier="",
        )]
        candidates, _ = reassessment._market_candidates(
            row,
            {"player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}},
            NOW,
        )
        self.assertEqual(candidates, [])

    def test_first_set_and_set_winner_markets_are_excluded(self):
        row = fixture()
        row["sportybet_market"]["markets"] = [
            {
                "id": "778",
                "name": "First Set Winner",
                "specifier": "player=home",
                "outcomes": [
                    {"id": "77801", "name": "Yes", "book_odds": 1.5},
                    {"id": "77802", "name": "No", "book_odds": 2.4},
                ],
            }
        ]
        candidates, _ = reassessment._market_candidates(
            row,
            {"player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}},
            NOW,
        )
        self.assertEqual(candidates, [])

    def test_stale_quotes_and_missing_outcome_ids_fail_closed(self):
        row = fixture()
        row["sportybet_market"]["fetched_at"] = (NOW - timedelta(minutes=16)).isoformat()
        candidates, counts = reassessment._market_candidates(
            row,
            {"player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}},
            NOW,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(counts["last_rejection"], "quote_older_than_15_minutes")

        row = fixture()
        row["sportybet_market"]["markets"][0]["outcomes"][0].pop("id")
        candidates, _ = reassessment._market_candidates(
            row,
            {"player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81}},
            NOW,
        )
        self.assertEqual(candidates, [])

    def test_builder_lane_waits_for_independent_walk_forward_promotion(self):
        row = fixture()
        report = {"status": "RESEARCH_ONLY_HOLD", "promotion_gate": {"passed": False}}
        candidates = reassessment.build_set_market_candidates(
            FakeCore(),
            NOW,
            prediction_rows=[row],
            history=[],
            report=report,
            baseline_fn=lambda _now: [],
        )
        self.assertEqual(candidates, [])
        self.assertEqual(
            reassessment.diagnostics()["rejected"]["independent_set_market_validation_not_passed"],
            1,
        )

    def test_builder_lane_emits_only_after_validation_and_prior_match_gates(self):
        row = fixture()
        report = {
            "status": "QUALIFIED_PAPER_RESEARCH",
            "validation": {"evaluated_matches": 70},
            "promotion_gate": {"passed": True},
        }
        predicted = {
            "status": "QUALIFIED_PAPER_RESEARCH",
            "promotion_gate_passed": True,
            "prior_matches": 50,
            "player_to_win_at_least_one_set": {"p1": 0.86, "p2": 0.81},
        }
        with mock.patch.object(set_model, "predict_target", return_value=predicted):
            candidates = reassessment.build_set_market_candidates(
                FakeCore(),
                NOW,
                prediction_rows=[row],
                history=[],
                report=report,
                baseline_fn=lambda _now: [],
            )
        self.assertEqual(len(candidates), 2)
        for candidate in candidates:
            self.assertEqual(candidate["builder_market"], "player_to_win_set")
            self.assertEqual(candidate["builder_pick"], "yes")
            self.assertEqual(candidate["market_source"], "SportyBet NG")
            self.assertEqual(candidate["sportybet_market_id"], "777")
            self.assertTrue(candidate["sportybet_outcome_id"])
            self.assertEqual(candidate["market_odds_timestamp"], row["sportybet_market"]["fetched_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
