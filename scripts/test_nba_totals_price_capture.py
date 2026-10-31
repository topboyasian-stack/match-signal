#!/usr/bin/env python3
"""Regression tests for fresh immutable NBA market-225 price capture."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from expansion_pipeline import NBA_TOTALS_MODEL_VERSION
from capture_nba_totals_prices import attach_fresh_quote, capture, capture_timestamp


def make_prediction(now, **overrides):
    prediction = {
        "event_id": "espn-101",
        "start_time": (now + timedelta(hours=2)).isoformat(),
        "player_1": "Boston Celtics",
        "player_2": "New York Knicks",
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "expected_total": 224.5,
        "markets": {"moneyline": {"home": 0.55, "away": 0.45}},
    }
    prediction.update(overrides)
    return prediction


def make_quote(now, **overrides):
    quote = {
        "line": 220.5,
        "over_odds": 1.91,
        "under_odds": 1.89,
        "market_id": "225",
        "source": "SportyBet Nigeria",
        "sportybet_event_id": "sr:match:12345",
        "quote_timestamp": now.isoformat(),
        "quote_capture_basis": "SportyBet API response observed_at",
        "settlement": "Official final score including overtime",
    }
    quote.update(overrides)
    return quote


class PriceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def test_captures_exact_fresh_pair_and_calculates_direction(self):
        prediction = make_prediction(self.now)
        changed = attach_fresh_quote(prediction, make_quote(self.now), self.now)
        self.assertTrue(changed)
        market = prediction["markets"]["total_ou"]
        self.assertEqual(market["market_id"], "225")
        self.assertEqual(market["line"], 220.5)
        self.assertEqual(market["over_odds"], 1.91)
        self.assertEqual(market["under_odds"], 1.89)
        self.assertEqual(market["pick"], "over")
        self.assertEqual(market["projection_edge_points"], 4.0)
        self.assertTrue(prediction["signal_quality"]["total_market_available"])
        self.assertEqual(prediction["markets"]["moneyline"]["home"], 0.55)

    def test_freezes_both_prices_even_when_there_is_no_directional_lean(self):
        prediction = make_prediction(self.now, expected_total=221.0)
        self.assertTrue(attach_fresh_quote(prediction, make_quote(self.now), self.now))
        market = prediction["markets"]["total_ou"]
        self.assertIsNone(market["pick"])
        self.assertEqual(market["lean"], "NO_CLEAR_LEAN")
        self.assertEqual(market["over_odds"], 1.91)
        self.assertEqual(market["under_odds"], 1.89)

    def test_rejects_stale_future_started_wrong_source_and_incomplete_pairs(self):
        prediction = make_prediction(self.now)
        self.assertFalse(attach_fresh_quote(prediction, make_quote(self.now-timedelta(minutes=16)), self.now))
        self.assertFalse(attach_fresh_quote(prediction, make_quote(self.now+timedelta(minutes=3)), self.now))
        self.assertFalse(attach_fresh_quote(prediction, make_quote(self.now, source="Other bookmaker"), self.now))
        self.assertFalse(attach_fresh_quote(prediction, make_quote(self.now, under_odds=None), self.now))
        started = make_prediction(self.now, start_time=(self.now-timedelta(minutes=1)).isoformat())
        self.assertFalse(attach_fresh_quote(started, make_quote(self.now), self.now))

    def test_skips_old_model_predictions_and_counts_only_fresh_exact_matches(self):
        prediction = make_prediction(self.now)
        legacy = make_prediction(self.now, event_id="old", totals_model_version="nba-total-v3")
        quote = make_quote(self.now)
        with patch("capture_nba_totals_prices.sportybet_total_for_fixture", return_value=quote):
            candidates, stats = capture([prediction, legacy], [], self.now)
        self.assertEqual(stats["upcoming_v5_predictions"], 1)
        self.assertEqual(stats["exact_fresh_market_matches"], 1)
        self.assertEqual(stats["prediction_price_updates"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(legacy["totals_model_version"], "nba-total-v3")

    def test_capture_time_is_taken_after_feed_response_not_before(self):
        before_response = self.now
        fetched = before_response + timedelta(seconds=3)
        feed = [{"fetched_at": fetched.isoformat()}]
        self.assertEqual(capture_timestamp(feed, before_response), fetched)

    def test_capture_time_does_not_follow_unbounded_future_feed_clock(self):
        before_response = self.now
        feed = [{"fetched_at": (before_response + timedelta(minutes=3)).isoformat()}]
        self.assertEqual(capture_timestamp(feed, before_response), before_response)

    def test_does_not_overwrite_a_newer_price_snapshot(self):
        newer = make_quote(self.now)
        prediction = make_prediction(self.now, markets={"total_ou": dict(newer)})
        older = make_quote(self.now-timedelta(minutes=2), line=218.5, over_odds=1.8, under_odds=2.1)
        self.assertFalse(attach_fresh_quote(prediction, older, self.now))
        self.assertEqual(prediction["markets"]["total_ou"]["line"], 220.5)
        self.assertEqual(prediction["markets"]["total_ou"]["over_odds"], 1.91)


if __name__ == "__main__":
    unittest.main(verbosity=2)
