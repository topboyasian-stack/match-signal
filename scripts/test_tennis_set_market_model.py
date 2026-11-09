"""Tests for the tennis set-outcome simulation and its safety gates."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tennis_set_market_model as model


class TennisSetMarketModelTests(unittest.TestCase):
    def record(self, index=0, *, start=None, calculated=None, p1=0.65, won1=2, won2=0):
        kickoff = start or (datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=index))
        captured = calculated or (kickoff - timedelta(hours=2))
        return {
            "sport": "tennis",
            "league": "ATP",
            "event_id": f"event-{index}",
            "start_time": kickoff.isoformat(),
            "calculated_at": captured.isoformat(),
            "capture_status": "PRE_EVENT",
            "evaluation_eligible": True,
            "probabilities": {"p1": p1, "p2": 1.0 - p1},
            "actual_markets": {"sets_won_p1": won1, "sets_won_p2": won2},
            "settled": True,
        }

    def test_set_probability_inverts_best_of_three_and_five(self):
        for best_of in (3, 5):
            p_set = 0.63
            q = 1.0 - p_set
            expected = (
                p_set ** 2 * (1.0 + 2.0 * q)
                if best_of == 3
                else p_set ** 3 * (1.0 + 3.0 * q + 6.0 * q ** 2)
            )
            actual = model.set_win_probability_from_match(expected, best_of)
            self.assertAlmostEqual(actual, p_set, places=9)

    def test_any_set_probabilities_are_not_complements(self):
        markets = model.simulate_match_markets(0.5, 3)
        self.assertAlmostEqual(markets["player_to_win_at_least_one_set"]["p1"], 0.75, places=6)
        self.assertAlmostEqual(markets["player_to_win_at_least_one_set"]["p2"], 0.75, places=6)
        self.assertGreater(
            sum(markets["player_to_win_at_least_one_set"].values()),
            1.0,
        )

    def test_scoreline_and_set_count_distributions_sum_to_one(self):
        for best_of in (3, 5):
            markets = model.simulate_match_markets(0.61, best_of)
            self.assertAlmostEqual(sum(markets["correct_set_score"].values()), 1.0, places=5)
            self.assertAlmostEqual(sum(markets["total_sets"].values()), 1.0, places=5)

    def test_only_strict_pre_event_atp_settlement_records_are_valid(self):
        good = self.record()
        self.assertTrue(model.valid_record(good))
        late = dict(good, capture_status="LATE_CAPTURE")
        self.assertFalse(model.valid_record(late))
        unknown = dict(good, evaluation_eligible=None)
        self.assertFalse(model.valid_record(unknown))
        wta = dict(good, league="WTA")
        self.assertFalse(model.valid_record(wta))
        after_start = dict(good, calculated_at=good["start_time"])
        self.assertFalse(model.valid_record(after_start))

    def test_future_and_same_kickoff_records_do_not_enter_fixture_history(self):
        target_start = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        earlier = self.record(1, start=target_start - timedelta(days=1))
        same_time = self.record(2, start=target_start)
        future = self.record(3, start=target_start + timedelta(days=1))
        target = {
            "sport": "tennis",
            "league": "ATP",
            "start_time": target_start.isoformat(),
            "probabilities": {"p1": 0.65, "p2": 0.35},
        }
        result = model.predict_target(target, [earlier, same_time, future], {
            "promotion_gate": {"passed": False}
        })
        self.assertEqual(result["prior_matches"], 1)
        self.assertEqual(result["status"], "RESEARCH_ONLY_HOLD")
        self.assertIn("player_to_win_at_least_one_set", result)

    def test_walk_forward_is_held_when_sample_is_insufficient(self):
        report = model.build_report([self.record(i) for i in range(45)])
        self.assertFalse(report["promotion_gate"]["passed"])
        self.assertEqual(report["status"], "RESEARCH_ONLY_HOLD")
        self.assertGreaterEqual(report["promotion_gate"]["requirements"].__len__(), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
