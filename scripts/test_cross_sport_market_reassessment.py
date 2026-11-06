#!/usr/bin/env python3
"""Regression tests for cross-sport market reassessment."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_sport_market_reassessment as reassessment


class FakeCore:
    MIN_PROB = 0.60

    @staticmethod
    def within_builder_horizon(row, now):
        try:
            start = datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            minutes = (start.astimezone(timezone.utc) - now).total_seconds() / 60
            return 0 < minutes <= 720
        except (KeyError, TypeError, ValueError):
            return False


def sample_football(now, *, quote_age_seconds=0, include_btts=True, include_double_chance=True):
    fetched = (now - timedelta(seconds=quote_age_seconds)).isoformat()
    markets = [
        {
            "id": "1",
            "name": "1X2",
            "line": None,
            "outcomes": [
                {"id": "home-id", "name": "Home", "odds": 2.0},
                {"id": "draw-id", "name": "Draw", "odds": 3.2},
                {"id": "away-id", "name": "Away", "odds": 4.0},
            ],
        },
        {
            "id": "18",
            "name": "Total Goals",
            "line": 2.5,
            "outcomes": [
                {"id": "over-id", "name": "Over 2.5", "odds": 2.05},
                {"id": "under-id", "name": "Under 2.5", "odds": 1.75},
            ],
        },
    ]
    if include_btts:
        markets.append({
            "id": "29",
            "name": "Both Teams To Score",
            "line": None,
            "outcomes": [
                {"id": "btts-yes-id", "name": "Yes", "odds": 1.70},
                {"id": "btts-no-id", "name": "No", "odds": 2.10},
            ],
        })
    if include_double_chance:
        markets.append({
            "id": "26",
            "name": "Double Chance",
            "line": None,
            "outcomes": [
                {"id": "dc-1x-id", "name": "1X", "odds": 1.30},
                {"id": "dc-12-id", "name": "12", "odds": 1.38},
                {"id": "dc-x2-id", "name": "X2", "odds": 1.65},
            ],
        })
    return {
        "sport": "football",
        "event_id": "football-test-1",
        "start_time": (now + timedelta(hours=2)).isoformat(),
        "player_1": "Team Alpha",
        "player_2": "Team Beta",
        "league": "Test League",
        "pick": "p1",
        "probabilities": {"p1": 0.50, "draw": 0.20, "p2": 0.30},
        "expected_goals": {"p1": 1.8, "p2": 1.2, "total": 3.0},
        "markets": {
            "over_under": {"line": 2.5, "over": 0.58, "under": 0.42},
            "btts": {"yes": 0.62, "no": 0.38},
        },
        "sportybet_winner_odds": {"p1": 2.0, "draw": 3.2, "p2": 4.0, "market_id": "1"},
        "sportybet_total_games_odds": [
            {"line": 2.5, "over": 2.05, "under": 1.75, "market_id": "18"},
            {"line": 3.0, "over": 2.15, "under": 1.70, "market_id": "18"},
        ],
        "sportybet_market": {
            "available": True,
            "event_id": "sporty-event-1",
            "fetched_at": fetched,
            "winner": {"market_id": "1"},
            "markets": markets,
        },
        "market_odds_timestamp": fetched,
        "odds_timestamp": fetched,
        "data_quality": 0.9,
        "uncertainty": 0.1,
        "model": "test independent model",
    }


class CrossSportReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        reassessment._RUN_OPTIONS.clear()

    def test_poisson_recalculates_half_line_and_rejects_push_line(self):
        self.assertAlmostEqual(reassessment._poisson_over_probability(3.0, 2.5), 0.5768099, places=5)
        self.assertIsNone(reassessment._poisson_over_probability(3.0, 2.0))

    def test_football_evaluates_winner_totals_btts_and_double_chance_alternatives(self):
        row = sample_football(self.now)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        audit_markets = {candidate["builder_market"] for candidate in audit}
        self.assertTrue({"1X2", "total_goals", "btts", "double_chance"}.issubset(audit_markets))
        # The model is below the 0.60 floor on all winner outcomes and the 2.5 over line;
        # higher-probability BTTS/double-chance options are retained only with exact IDs.
        active_keys = {(x["builder_market"], x["builder_pick"]) for x in active}
        self.assertIn(("btts", "yes"), active_keys)
        self.assertIn(("double_chance", "1x"), active_keys)
        self.assertIn(("double_chance", "12"), active_keys)
        self.assertNotIn(("total_goals", "over"), active_keys)
        for candidate in active:
            self.assertTrue(candidate.get("sportybet_market_id"))
            self.assertTrue(candidate.get("sportybet_outcome_id"))
            self.assertTrue(candidate.get("reassessment_market_rows"))

    def test_partial_1x2_price_pair_is_not_promoted_as_an_alternative(self):
        row = sample_football(self.now, include_btts=False, include_double_chance=False)
        row["sportybet_winner_odds"].pop("draw")
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(any(x["builder_market"] == "1X2" for x in audit))
        self.assertFalse(any(x["builder_market"] == "1X2" for x in active))

    def test_integer_total_lines_are_never_substituted_for_half_lines(self):
        row = sample_football(self.now)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        total_candidates = [x for x in audit if x["builder_market"] == "total_goals"]
        self.assertTrue(total_candidates)
        self.assertTrue(all(abs(float(x["line"]) - round(float(x["line"]))) > 1e-9 for x in total_candidates))

    def test_stale_quotes_are_audited_but_never_enter_the_active_candidate_pool(self):
        row = sample_football(self.now, quote_age_seconds=901)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(audit)
        self.assertEqual(active, [])

    def test_missing_exact_outcome_identifier_blocks_booking_candidate(self):
        row = sample_football(self.now)
        for market in row["sportybet_market"]["markets"]:
            for outcome in market["outcomes"]:
                outcome["id"] = ""
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(audit)
        self.assertEqual(active, [])

    def test_market_discovery_requires_available_live_snapshot(self):
        row = sample_football(self.now)
        row["sportybet_market"]["available"] = False
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertEqual(active, [])
        self.assertEqual(audit, [])


    def test_future_quote_timestamp_fails_closed(self):
        row = sample_football(self.now, quote_age_seconds=0)
        future = self.now + timedelta(seconds=5)
        row["market_odds_timestamp"] = future.isoformat()
        fresh, age, stamp = reassessment._fresh_quote(row, self.now)
        self.assertFalse(fresh)
        self.assertLess(age, 0)
        self.assertEqual(stamp, future.isoformat())

    def test_nba_quote_timestamp_is_supported_by_common_freshness_check(self):
        row = {
            "quote_timestamp": (self.now - timedelta(seconds=30)).isoformat(),
            "sport": "basketball",
            "market_id": "225",
            "line": 226.5,
        }
        fresh, age, stamp = reassessment._fresh_quote(row, self.now)
        self.assertTrue(fresh)
        self.assertEqual(age, 30.0)
        self.assertEqual(stamp, row["quote_timestamp"])

    def test_virtual_wrapper_preserves_builder_signature_and_records_candidates(self):
        old = reassessment._ORIGINALS.get("virtual_candidates")
        try:
            candidate = {"sport": "virtual", "event_id": "virtual-1", "builder_market": "virtual_total"}
            reassessment._ORIGINALS["virtual_candidates"] = lambda now: [candidate]
            reassessment._RUN_OPTIONS.clear()
            result = reassessment._virtual_options(self.now)
            self.assertEqual(result, [candidate])
            self.assertEqual(reassessment._RUN_OPTIONS, [candidate])
        finally:
            if old is None:
                reassessment._ORIGINALS.pop("virtual_candidates", None)
            else:
                reassessment._ORIGINALS["virtual_candidates"] = old

    def test_fingerprint_changes_when_price_or_model_probability_changes(self):
        base = {
            "sport": "football", "event_id": "evt", "market": "total_goals", "line": 2.5,
            "pick": "over", "quote_timestamp": "2026-11-06T12:00:00+00:00",
            "bookmaker_odds": 1.9, "model_probability": 0.63, "model_source": "test",
            "sportybet_market_id": "18", "sportybet_outcome_id": "over-id",
        }
        changed_price = {**base, "bookmaker_odds": 2.0}
        changed_probability = {**base, "model_probability": 0.65}
        self.assertNotEqual(reassessment._fingerprint(base), reassessment._fingerprint(changed_price))
        self.assertNotEqual(reassessment._fingerprint(base), reassessment._fingerprint(changed_probability))
        self.assertEqual(reassessment._fingerprint(base), reassessment._fingerprint(dict(base)))

    def test_settlement_join_scores_double_chance_as_yes_or_no(self):
        base = {"sport": "football", "event_id": "evt", "market": "double_chance", "line": None, "pick": "1x"}
        by_event = {("football", "evt"): {"actual": "p1", "settled": True}}
        self.assertEqual(reassessment._settle_result(base, by_event)["settlement_result"], "yes")
        by_event = {("football", "evt"): {"actual": "p2", "settled": True}}
        self.assertEqual(reassessment._settle_result(base, by_event)["settlement_result"], "no")


if __name__ == "__main__":
    unittest.main(verbosity=2)
