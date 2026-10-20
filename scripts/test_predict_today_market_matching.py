#!/usr/bin/env python3
"""Regression tests for competition-safe football market matching and probabilities."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import predict_today
import enrich_sportybet_odds
from football_competition_match import same_competition
from model_upgrade import _apply_independent_probability_fields


KICKOFF = "2026-10-20T16:45:00+00:00"
KICKOFF_MS = int(datetime.fromisoformat(KICKOFF).timestamp() * 1000)


def prediction():
    return {
        "sport": "football",
        "league": "Champions League",
        "event_id": "espn:match:senior",
        "start_time": KICKOFF,
        "player_1": "Fenerbahce",
        "player_2": "Slavia Prague",
    }


def sporty_event(*, tournament, start_ms=KICKOFF_MS, event_id="sr:match:fixture"):
    return {
        "event_id": event_id,
        "eventId": event_id,
        "tournament": tournament,
        "_league": tournament,
        "home": "Fenerbahce",
        "away": "Slavia Prague",
        "homeTeamName": "Fenerbahce",
        "awayTeamName": "Slavia Prague",
        "start_time_ms": start_ms,
        "estimateStartTime": start_ms,
        "markets": [],
    }


class CompetitionSafeFootballMarketTests(unittest.TestCase):
    def test_competition_aliases_match_but_youth_is_separate(self):
        self.assertTrue(same_competition("Champions League", "UEFA Champions League"))
        self.assertTrue(same_competition("EPL", "English Premier League"))
        self.assertFalse(same_competition("Champions League", "UEFA Youth League"))
        self.assertFalse(same_competition("Champions League", ""))

    def test_prediction_market_matcher_ignores_same_named_youth_fixture(self):
        youth = sporty_event(
            tournament="UEFA Youth League",
            start_ms=int(datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc).timestamp() * 1000),
            event_id="sr:match:youth",
        )
        senior = sporty_event(tournament="UEFA Champions League", event_id="sr:match:senior")
        event, match = predict_today._find_sportybet_match(prediction(), [youth, senior])
        self.assertIs(event, senior)
        self.assertIsNotNone(match)
        event, match = predict_today._find_sportybet_match(prediction(), [youth])
        self.assertIsNone(event)
        self.assertIsNone(match)

    def test_enrichment_matcher_fails_closed_for_wrong_or_missing_competition(self):
        pred = prediction()
        youth = sporty_event(
            tournament="UEFA Youth League",
            start_ms=int(datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc).timestamp() * 1000),
            event_id="sr:match:youth",
        )
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [youth]), (None, None))
        missing = sporty_event(tournament="", event_id="sr:match:unknown")
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [missing]), (None, None))
        senior = sporty_event(tournament="UEFA Champions League", event_id="sr:match:senior")
        found, method = enrich_sportybet_odds.find_event(pred, [youth, senior])
        self.assertIs(found, senior)
        self.assertEqual(method, "name_time")


    def test_enrichment_matcher_accepts_second_based_kickoff_timestamp(self):
        pred = prediction()
        senior = sporty_event(tournament="UEFA Champions League", event_id="sr:match:seconds")
        senior["estimateStartTime"] = int(KICKOFF_MS / 1000)
        found, method = enrich_sportybet_odds.find_event(pred, [senior])
        self.assertIs(found, senior)
        self.assertEqual(method, "name_time")

    def test_enrichment_matcher_fails_closed_when_kickoff_is_too_far_away(self):
        pred = prediction()
        tomorrow = sporty_event(
            tournament="UEFA Champions League",
            start_ms=int(datetime(2026, 10, 21, 16, 45, tzinfo=timezone.utc).timestamp() * 1000),
            event_id="sr:match:tomorrow",
        )
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [tomorrow]), (None, None))

    def test_model_upgrade_replaces_stale_confidence_metadata(self):
        row = {
            "raw_probabilities": {"p1": 0.90, "draw": 0.05, "p2": 0.05},
            "raw_confidence": 0.90,
            "calibrated_confidence": 0.88,
            "calibration": {"method": "recency_weighted_empirical_bayes"},
        }
        independent = {"p1": 0.65831, "draw": 0.20084, "p2": 0.14085}
        calibrated = [0.4954, 0.2235, 0.2811]
        _apply_independent_probability_fields(
            row, independent, calibrated, {"football": {"temperature": 1.1}, "version": "test-v1"}
        )
        self.assertEqual(row["raw_probabilities"], {"p1": 0.6583, "draw": 0.2008, "p2": 0.1409})
        self.assertEqual(row["raw_confidence"], max(row["raw_probabilities"].values()))
        self.assertEqual(row["calibrated_confidence"], max(row["probabilities"].values()))
        self.assertEqual(row["confidence"], row["calibrated_confidence"])
        self.assertEqual(row["calibration"]["method"], "softmax_temperature")
        self.assertEqual(row["calibration"]["temperature"], 1.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
