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
from football_competition_match import same_competition, football_market_identity_matches
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


def sporty_event(
    *,
    tournament,
    category="International Clubs",
    home="Fenerbahce",
    away="Slavia Prague",
    start_ms=KICKOFF_MS,
    event_id="sr:match:fixture",
):
    return {
        "event_id": event_id,
        "eventId": event_id,
        "tournament": tournament,
        "_league": tournament,
        "category": category,
        "_category": category,
        "home": home,
        "away": away,
        "homeTeamName": home,
        "awayTeamName": away,
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

    def test_youth_category_and_age_markers_override_a_mislabelled_tournament(self):
        pred = prediction()
        # Real provider pattern: same club names and kickoff, but the category
        # identifies this row as youth. A misleading senior tournament label
        # must not permit attachment.
        category_mislabeled = sporty_event(
            tournament="UEFA Champions League",
            category="International Youth",
            event_id="sr:match:category-mislabeled-youth",
        )
        self.assertIsNone(predict_today._find_sportybet_match(pred, [category_mislabeled])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [category_mislabeled]), (None, None))

        # A youth marker in either participant is also authoritative even when
        # the tournament/category text looks senior.
        age_marked = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            home="Fenerbahce U19",
            away="Slavia Prague U19",
            event_id="sr:match:age-marked-youth",
        )
        self.assertIsNone(predict_today._find_sportybet_match(pred, [age_marked])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [age_marked]), (None, None))

        senior = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            event_id="sr:match:senior",
        )
        found, _ = predict_today._find_sportybet_match(pred, [category_mislabeled, age_marked, senior])
        self.assertIs(found, senior)
        found, method = enrich_sportybet_odds.find_event(pred, [category_mislabeled, age_marked, senior])
        self.assertIs(found, senior)
        self.assertEqual(method, "name_time")

    def test_age_group_must_match_on_both_sides(self):
        self.assertFalse(football_market_identity_matches(
            "UEFA Youth League U19",
            "UEFA Youth League U17",
            market_category="International Youth",
            prediction_teams=("Fenerbahce U19", "Slavia Prague U19"),
            market_teams=("Fenerbahce U17", "Slavia Prague U17"),
        ))
        self.assertTrue(football_market_identity_matches(
            "UEFA Champions League",
            "UEFA Champions League",
            market_category="International Clubs",
            prediction_teams=("Fenerbahce", "Slavia Prague"),
            market_teams=("Fenerbahce Istanbul", "Slavia Prague"),
        ))

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
