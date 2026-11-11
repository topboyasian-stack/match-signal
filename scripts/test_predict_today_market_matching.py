#!/usr/bin/env python3
"""Regression tests for competition-safe football market matching and probabilities."""
from __future__ import annotations

import sys
import unittest
from unittest import mock
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
        # Keep kickoff identical so this test proves competition identity—not time—
        # excludes the Youth League event.
        youth = sporty_event(
            tournament="UEFA Youth League",
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
        # Same competition label, teams, and kickoff; provider category is youth.
        category_mislabeled = sporty_event(
            tournament="UEFA Champions League",
            category="International Youth",
            event_id="sr:match:category-mislabeled-youth",
        )
        self.assertIsNone(predict_today._find_sportybet_match(pred, [category_mislabeled])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [category_mislabeled]), (None, None))

        # A youth marker in either participant is authoritative even if tournament
        # and category text appear senior.
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

    def test_event_level_youth_competition_cannot_hide_behind_parent_league_label(self):
        pred = prediction()
        # Some provider payloads expose a generic parent tournament while the
        # individual event retains the true Youth League competition.
        hidden_youth = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            event_id="sr:match:hidden-youth-competition",
        )
        hidden_youth["competitionName"] = "UEFA Youth League"
        self.assertIsNone(predict_today._find_sportybet_match(pred, [hidden_youth])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [hidden_youth]), (None, None))

        nested_youth = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            event_id="sr:match:nested-youth-competition",
        )
        nested_youth["competition"] = {"name": "UEFA Youth League", "ageGroup": "U19"}
        self.assertIsNone(predict_today._find_sportybet_match(pred, [nested_youth])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [nested_youth]), (None, None))

        senior = sporty_event(tournament="UEFA Champions League", event_id="sr:match:senior")
        found, _ = predict_today._find_sportybet_match(pred, [hidden_youth, nested_youth, senior])
        self.assertIs(found, senior)
        found, method = enrich_sportybet_odds.find_event(pred, [hidden_youth, nested_youth, senior])
        self.assertIs(found, senior)
        self.assertEqual(method, "name_time")

    def test_normalized_sportybet_events_preserve_event_level_identity_metadata(self):
        raw_event = {
            "eventId": "sr:match:raw-youth-metadata",
            "homeTeamName": "Fenerbahce",
            "awayTeamName": "Slavia Prague",
            "estimateStartTime": KICKOFF_MS,
            "competitionName": "UEFA Youth League",
            "markets": [],
        }
        body = {
            "data": {
                "totalNum": 1,
                "tournaments": [{
                    "name": "UEFA Champions League",
                    "categoryName": "International Clubs",
                    "events": [raw_event],
                }],
            },
        }
        with mock.patch.object(predict_today, "_sportybet_get", return_value=body):
            events = predict_today.fetch_sportybet_events("sr:sport:1", "1")
        self.assertEqual(len(events), 1)
        self.assertIn("youth league", events[0]["identity_metadata"].lower())
        self.assertFalse(predict_today._football_market_fixture_valid(prediction(), events[0]))

    def test_age_group_must_match_on_both_sides(self):
        self.assertFalse(football_market_identity_matches(
            "UEFA Youth League",
            "UEFA Youth League",
            market_category="International Youth",
            prediction_teams=("Fenerbahce U19", "Slavia Prague U19"),
            market_teams=("Fenerbahce U17", "Slavia Prague U17"),
        ))
        self.assertTrue(football_market_identity_matches(
            "UEFA Champions League",
            "UEFA Champions League",
            market_category="International Clubs",
            prediction_teams=("Fenerbahce", "Slavia Prague"),
            market_teams=("Fenerbahce", "Slavia Prague"),
        ))

    def test_supported_senior_club_aliases_match_the_same_competition_and_kickoff(self):
        pred = prediction()
        pred.update({"league": "La Liga", "player_1": "Elche", "player_2": "Real Betis"})
        fixture = sporty_event(
            tournament="LaLiga", category="Spain", home="Elche CF", away="Betis",
            event_id="sr:match:elche-betis",
        )
        found, _ = predict_today._find_sportybet_match(pred, [fixture])
        self.assertIs(found, fixture)

        pred.update({"league": "Ligue 1", "player_1": "Stade Rennais", "player_2": "Lille"})
        fixture = sporty_event(
            tournament="Ligue 1", category="France", home="Rennes", away="Lille",
            event_id="sr:match:rennes-lille",
        )
        found, _ = predict_today._find_sportybet_match(pred, [fixture])
        self.assertIs(found, fixture)

    def test_club_aliases_do_not_strip_youth_or_gender_identity(self):
        pred = prediction()
        pred.update({"league": "La Liga", "player_1": "Real Betis", "player_2": "Sevilla"})
        youth = sporty_event(
            tournament="LaLiga", category="Spain Youth", home="Betis U19", away="Sevilla U19",
            event_id="sr:match:betis-youth",
        )
        self.assertIsNone(predict_today._find_sportybet_match(pred, [youth])[0])

    def test_both_participants_must_match_not_just_one_exact_club(self):
        pred = prediction()
        # This same-competition, same-kickoff row has one exact participant and a
        # merely partial opponent label. The old aggregate score could accept it.
        wrong_opponent = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            home="Fenerbahce",
            away="Slavia",
            event_id="sr:match:wrong-opponent",
        )
        self.assertIsNone(predict_today._find_sportybet_match(pred, [wrong_opponent])[0])
        self.assertEqual(enrich_sportybet_odds.find_event(pred, [wrong_opponent]), (None, None))

        real_fixture = sporty_event(
            tournament="UEFA Champions League",
            category="International Clubs",
            event_id="sr:match:real-fixture",
        )
        found, match = predict_today._find_sportybet_match(pred, [wrong_opponent, real_fixture])
        self.assertIs(found, real_fixture)
        self.assertIsNotNone(match)
        found, method = enrich_sportybet_odds.find_event(pred, [wrong_opponent, real_fixture])
        self.assertIs(found, real_fixture)
        self.assertEqual(method, "name_time")

    def test_identity_check_rejects_missing_or_wrong_participants(self):
        self.assertFalse(football_market_identity_matches(
            "UEFA Champions League",
            "UEFA Champions League",
            market_category="International Clubs",
            prediction_teams=("Fenerbahce", "Slavia Prague"),
            market_teams=("Fenerbahce", ""),
        ))
        self.assertFalse(football_market_identity_matches(
            "UEFA Champions League",
            "UEFA Champions League",
            market_category="International Clubs",
            prediction_teams=("Fenerbahce", "Slavia Prague"),
            market_teams=("Fenerbahce", "Club Brugge"),
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



class FuturePrematchFilterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    def event(self, start, *, state="pre", completed=False, name="STATUS_SCHEDULED"):
        return {
            "id": "fixture-1",
            "date": start,
            "status": {"type": {"state": state, "completed": completed, "name": name}},
        }

    def test_future_scheduled_fixture_is_allowed(self):
        self.assertTrue(predict_today.is_future_prematch_event(
            self.event("2026-11-01T12:05:00Z"), now=self.now
        ))

    def test_already_started_time_is_rejected_even_if_provider_says_pre(self):
        # Regression for a Basel final that remained in the provider's pre-match
        # date board after its scheduled 14:30 UTC start.
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event("2026-11-01T11:59:00Z"), now=self.now
        ))

    def test_near_kickoff_is_held_out_of_upcoming(self):
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event("2026-11-01T12:01:00Z"), now=self.now
        ))

    def test_live_and_completed_statuses_are_rejected(self):
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event("2026-11-01T13:00:00Z", state="in", name="STATUS_IN_PROGRESS"),
            now=self.now,
        ))
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event("2026-11-01T13:00:00Z", completed=True, state="post", name="STATUS_FINAL"),
            now=self.now,
        ))

    def test_missing_or_unparseable_start_time_is_rejected(self):
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event(None), now=self.now
        ))
        self.assertFalse(predict_today.is_future_prematch_event(
            self.event("not-a-time"), now=self.now
        ))




class TennisSetWinnerMarketSpecifierTests(unittest.TestCase):
    def test_tennis_snapshot_preserves_distinct_set_winner_specifiers(self):
        event = {
            "event_id": "sr:match:tennis-set-specifier",
            "tournament": "ATP Stockholm, Sweden Men Singles",
            "category": "ATP",
            "start_time_ms": KICKOFF_MS,
            "markets": [
                {
                    "id": "202", "desc": "1st set - winner", "specifier": "setnr=1",
                    "outcomes": [
                        {"id": "4", "desc": "Home", "odds": "1.81", "isActive": 1},
                        {"id": "5", "desc": "Away", "odds": "2.00", "isActive": 1},
                    ],
                },
                {
                    "id": "202", "desc": "2nd set - winner", "specifier": "setnr=2",
                    "outcomes": [
                        {"id": "4", "desc": "Home", "odds": "1.82", "isActive": 1},
                        {"id": "5", "desc": "Away", "odds": "2.00", "isActive": 1},
                    ],
                },
            ],
        }
        snapshot = predict_today._sportybet_market_snapshot(event, "tennis")
        set_markets = [
            row for row in snapshot["markets"]
            if str(row.get("id")) == "202"
        ]
        self.assertEqual(len(set_markets), 2)
        self.assertEqual([row.get("specifier") for row in set_markets], ["setnr=1", "setnr=2"])
        self.assertEqual([row["name"] for row in set_markets], ["1st set - winner", "2nd set - winner"])
        self.assertEqual(
            [[outcome["id"] for outcome in row["outcomes"]] for row in set_markets],
            [["4", "5"], ["4", "5"]],
        )


class CurrentSportyBetQuoteTimestampTests(unittest.TestCase):
    def test_matched_live_snapshot_sets_builder_freshness_fields(self):
        prediction_row = prediction()
        prediction_row.update({
            "pick": "p1",
            "probabilities": {"p1": 0.70, "draw": 0.15, "p2": 0.15},
            "market_odds_timestamp": "2026-11-03T12:00:00+00:00",
            "odds_timestamp": "2026-11-03T12:00:00+00:00",
        })
        event = sporty_event(tournament="UEFA Champions League")
        fetched_at = "2026-11-03T16:00:00+00:00"
        snapshot = {
            "provider": "SportyBet NG",
            "event_id": "sr:match:fixture",
            "tournament": "UEFA Champions League",
            "category": "International Clubs",
            "winner": {
                "p1_book": 1.90, "draw_book": 3.40, "p2_book": 4.10,
                "p1_fair_prob": 0.50, "draw_fair_prob": 0.28, "p2_fair_prob": 0.22,
                "p1_fair_odds": 2.00, "draw_fair_odds": 3.57, "p2_fair_odds": 4.55,
                "market_id": "1", "overround": 0.04,
                "raw_outcomes": [
                    {"id": "4", "name": "Home"},
                    {"id": "X", "name": "Draw"},
                    {"id": "5", "name": "Away"},
                ],
            },
            "totals": [],
            "markets": [{"id": "1", "name": "1X2"}],
            "fetched_at": fetched_at,
        }
        with (
            mock.patch.object(
                predict_today,
                "fetch_sportybet_events",
                side_effect=lambda sport_id, markets: [event] if sport_id == "sr:sport:1" else [],
            ),
            mock.patch.object(
                predict_today, "_find_sportybet_match",
                return_value=(event, {"method": "direct", "score": 1.0}),
            ),
            mock.patch.object(predict_today, "_sportybet_market_snapshot", return_value=snapshot),
            mock.patch.object(predict_today, "_pick_sporty_total", return_value=None),
        ):
            stats = predict_today.attach_sportybet_market_layer([prediction_row])

        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["per_sport"]["football"]["predictions_seen"], 1)
        self.assertEqual(stats["per_sport"]["football"]["events_fetched"], 1)
        self.assertEqual(stats["per_sport"]["football"]["matched_events"], 1)
        self.assertEqual(stats["per_sport"]["football"]["winner_market_available"], 1)
        self.assertEqual(stats["per_sport"]["football"]["market_id_counts"], {"1": 1})
        self.assertEqual(prediction_row["market_odds_timestamp"], fetched_at)
        self.assertEqual(prediction_row["odds_timestamp"], fetched_at)
        self.assertEqual(prediction_row["sportybet_market"]["fetched_at"], fetched_at)
        self.assertEqual(prediction_row["market_insights"]["snapshot_at"], fetched_at)

    def test_unmatched_fixture_does_not_keep_old_quote_timestamp(self):
        prediction_row = prediction()
        prediction_row.update({
            "market_odds_timestamp": "2026-11-03T12:00:00+00:00",
            "odds_timestamp": "2026-11-03T12:00:00+00:00",
        })
        with mock.patch.object(predict_today, "fetch_sportybet_events", return_value=[]):
            stats = predict_today.attach_sportybet_market_layer([prediction_row])

        self.assertEqual(stats["matched"], 0)
        self.assertEqual(stats["per_sport"]["football"]["predictions_seen"], 1)
        self.assertEqual(stats["per_sport"]["football"]["unmatched_events"], 1)
        self.assertEqual(stats["per_sport"]["football"]["unmatched_reason_counts"], {"market_feed_empty": 1})
        self.assertNotIn("market_odds_timestamp", prediction_row)
        self.assertNotIn("odds_timestamp", prediction_row)


class CoreSportMarketBreakdownTests(unittest.TestCase):
    def test_atp_matching_and_winner_market_coverage_are_reported_separately(self):
        tennis_prediction = {
            "sport": "tennis",
            "league": "ATP",
            "event_id": "espn:atp:fixture",
            "start_time": KICKOFF,
            "player_1": "Ben Shelton",
            "player_2": "Arthur Rinderknech",
            "pick": "p1",
            "probabilities": {"p1": 0.68, "p2": 0.32},
        }
        event = sporty_event(
            tournament="ATP",
            category="ATP",
            home="Ben Shelton",
            away="Arthur Rinderknech",
            event_id="sr:match:atp-fixture",
        )
        snapshot = {
            "provider": "SportyBet NG",
            "event_id": "sr:match:atp-fixture",
            "tournament": "ATP",
            "category": "ATP",
            "winner": {
                "p1_book": 1.70, "p2_book": 2.20,
                "p1_fair_prob": 0.56, "p2_fair_prob": 0.44,
                "p1_fair_odds": 1.79, "p2_fair_odds": 2.27,
                "market_id": "186", "overround": 0.05,
                "raw_outcomes": [
                    {"id": "4", "name": "Ben Shelton"},
                    {"id": "5", "name": "Arthur Rinderknech"},
                ],
            },
            "totals": [],
            "markets": [{"id": "186", "name": "Winner"}],
            "fetched_at": "2026-11-03T16:00:00+00:00",
        }
        with (
            mock.patch.object(
                predict_today,
                "fetch_sportybet_events",
                side_effect=lambda sport_id, markets: [event] if sport_id == "sr:sport:5" else [],
            ),
            mock.patch.object(
                predict_today, "_find_sportybet_match",
                return_value=(event, {"method": "direct", "score": 1.0}),
            ),
            mock.patch.object(predict_today, "_sportybet_market_snapshot", return_value=snapshot),
            mock.patch.object(predict_today, "_pick_sporty_total", return_value=None),
        ):
            stats = predict_today.attach_sportybet_market_layer([tennis_prediction])

        tennis = stats["per_sport"]["tennis"]
        self.assertEqual(tennis["predictions_seen"], 1)
        self.assertEqual(tennis["events_fetched"], 1)
        self.assertEqual(tennis["matched_events"], 1)
        self.assertEqual(tennis["winner_market_available"], 1)
        self.assertEqual(tennis["market_id_counts"], {"186": 1})
        self.assertEqual(tennis["match_examples"][0]["match_score"], 1.0)
        self.assertEqual(tennis_prediction["sportybet_winner_odds"]["market_id"], "186")

    def test_unmatched_tennis_row_reports_nearest_fixture_candidates(self):
        tennis_prediction = {
            "sport": "tennis",
            "league": "ATP",
            "event_id": "espn:atp:missing",
            "start_time": KICKOFF,
            "player_1": "Ben Shelton",
            "player_2": "Arthur Rinderknech",
        }
        near = sporty_event(
            tournament="ATP",
            category="ATP",
            home="Ben Shelton",
            away="Arthur Rinderknech",
            event_id="sr:match:near",
        )
        with (
            mock.patch.object(
                predict_today,
                "fetch_sportybet_events",
                side_effect=lambda sport_id, markets: [near] if sport_id == "sr:sport:5" else [],
            ),
            mock.patch.object(predict_today, "_find_sportybet_match", return_value=(None, None)),
        ):
            stats = predict_today.attach_sportybet_market_layer([tennis_prediction])

        tennis = stats["per_sport"]["tennis"]
        self.assertEqual(tennis["unmatched_events"], 1)
        self.assertEqual(tennis["unmatched_reason_counts"], {"no_sufficient_fixture_match": 1})
        self.assertEqual(
            tennis["unmatched_examples"][0]["nearest_markets"][0]["event_id"],
            "sr:match:near",
        )
        self.assertEqual(
            tennis["unmatched_examples"][0]["nearest_markets"][0]["competition_identity_ok"],
            True,
        )

if __name__ == "__main__":
    unittest.main(verbosity=2)

if __name__ == "__main__":
    unittest.main(verbosity=2)

if __name__ == "__main__":
    unittest.main(verbosity=2)

if __name__ == "__main__":
    unittest.main(verbosity=2)


class CurrentSportyBetQuoteTimestampTests(unittest.TestCase):
    def test_matched_live_snapshot_sets_builder_freshness_fields(self):
        prediction_row = prediction()
        prediction_row.update({
            "pick": "p1",
            "probabilities": {"p1": 0.70, "draw": 0.15, "p2": 0.15},
            "market_odds_timestamp": "2026-11-03T12:00:00+00:00",
            "odds_timestamp": "2026-11-03T12:00:00+00:00",
        })
        event = sporty_event(tournament="UEFA Champions League")
        fetched_at = "2026-11-03T16:00:00+00:00"
        snapshot = {
            "provider": "SportyBet NG",
            "event_id": "sr:match:fixture",
            "tournament": "UEFA Champions League",
            "category": "International Clubs",
            "winner": {
                "p1_book": 1.90,
                "draw_book": 3.40,
                "p2_book": 4.10,
                "p1_fair_prob": 0.50,
                "draw_fair_prob": 0.28,
                "p2_fair_prob": 0.22,
                "p1_fair_odds": 2.00,
                "draw_fair_odds": 3.57,
                "p2_fair_odds": 4.55,
                "market_id": "1",
                "overround": 0.04,
                "raw_outcomes": [
                    {"id": "4", "name": "Home"},
                    {"id": "X", "name": "Draw"},
                    {"id": "5", "name": "Away"},
                ],
            },
            "totals": [],
            "fetched_at": fetched_at,
        }
        with (
            mock.patch.object(
                predict_today,
                "fetch_sportybet_events",
                side_effect=lambda sport_id, markets: [event] if sport_id == "sr:sport:1" else [],
            ),
            mock.patch.object(
                predict_today,
                "_find_sportybet_match",
                return_value=(event, {"method": "direct", "score": 1.0}),
            ),
            mock.patch.object(
                predict_today,
                "_sportybet_market_snapshot",
                return_value=snapshot,
            ),
            mock.patch.object(predict_today, "_pick_sporty_total", return_value=None),
        ):
            stats = predict_today.attach_sportybet_market_layer([prediction_row])

        self.assertEqual(stats["matched"], 1)
        self.assertEqual(prediction_row["market_odds_timestamp"], fetched_at)
        self.assertEqual(prediction_row["odds_timestamp"], fetched_at)
        self.assertEqual(prediction_row["sportybet_market"]["fetched_at"], fetched_at)
        self.assertEqual(prediction_row["market_insights"]["snapshot_at"], fetched_at)

    def test_unmatched_fixture_does_not_keep_old_quote_timestamp(self):
        prediction_row = prediction()
        prediction_row.update({
            "market_odds_timestamp": "2026-11-03T12:00:00+00:00",
            "odds_timestamp": "2026-11-03T12:00:00+00:00",
        })
        with mock.patch.object(predict_today, "fetch_sportybet_events", return_value=[]):
            stats = predict_today.attach_sportybet_market_layer([prediction_row])

        self.assertEqual(stats["matched"], 0)
        self.assertNotIn("market_odds_timestamp", prediction_row)
        self.assertNotIn("odds_timestamp", prediction_row)


