#!/usr/bin/env python3
"""Regression tests for fresh immutable NBA market-225 price capture."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from expansion_pipeline import NBA_TOTALS_MODEL_VERSION
from live_expansion_pipeline import append_nba_totals_publication_snapshots
from capture_nba_totals_prices import attach_fresh_quote, capture, capture_timestamp, diagnose_fixture_quote, nearby_feed_events, sportybet_basketball_feed_paged


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
    def test_basketball_page_scopes_sportybet_feed_to_nba(self):
        root = Path(__file__).resolve().parents[1]
        page_script = (root / "basketball-live.js").read_text(encoding="utf-8")
        page_html = (root / "basketball.html").read_text(encoding="utf-8")
        proxy_script = (root / "functions" / "api" / "sportybet-basketball.js").read_text(encoding="utf-8")
        booking_script = (root / "functions" / "api" / "sportybet-booking.js").read_text(encoding="utf-8")
        self.assertIn("tournamentId=sr%3Atournament%3A132", page_script)
        self.assertIn("basketball-live.js?v=20261102-nba-feed-scope2", page_html)
        self.assertIn("u.searchParams.get('tournamentId')||NBA_TOURNAMENT_ID", proxy_script)
        self.assertIn("if(tournamentId!==NBA_TOURNAMENT_ID)", proxy_script)

        # Any slip containing NBA totals must fail closed instead of returning
        # a share code when either our validation or SportyBet accepts only
        # part of the requested set of legs.
        self.assertIn("const hasBasketballLeg = legs.some", booking_script)
        self.assertIn("if (hasBasketballLeg && preExcluded.length > 0)", booking_script)
        self.assertIn("BASKETBALL_SLIP_REJECTED_PARTIAL", booking_script)
        self.assertIn("booking_code_withheld: true", booking_script)
        self.assertLess(
            booking_script.index("if (hasBasketballLeg && preExcluded.length > 0)"),
            booking_script.index("const sharePayload = JSON.stringify"),
        )
        self.assertLess(
            booking_script.index("unavailable.length > 0 ||"),
            booking_script.index("const deadline = Number(data?.deadline || 0);"),
        )


    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def test_feed_paginates_seven_day_window_and_merges_duplicate_market_rows(self):
        first_page = [
            {"event_id": f"event-{i}", "home": f"Home {i}", "away": f"Away {i}",
             "fetched_at": self.now.isoformat(), "markets": []}
            for i in range(100)
        ]
        second_page = [
            {"event_id": "event-100", "home": "Home 100", "away": "Away 100",
             "fetched_at": self.now.isoformat(), "markets": [
                 {"id": "225", "specifier": "total=220.5", "outcomes": []}
             ]},
            {"event_id": "event-0", "home": "Home 0", "away": "Away 0",
             "fetched_at": (self.now + timedelta(seconds=1)).isoformat(), "markets": [
                 {"id": "225", "specifier": "total=221.5", "outcomes": []}
             ]},
        ]

        class Response:
            def __init__(self, events):
                self.events = events
            def raise_for_status(self):
                return None
            def json(self):
                return {"ok": True, "events": self.events}

        with patch("capture_nba_totals_prices.S.get", side_effect=[
            Response(first_page), Response(second_page)
        ]) as feed_get:
            events, error = sportybet_basketball_feed_paged(max_pages=5)

        self.assertIsNone(error)
        self.assertEqual([call.kwargs["params"]["pageNum"] for call in feed_get.call_args_list], [1, 2])
        self.assertTrue(all(call.kwargs["params"]["timeline"] == 168 for call in feed_get.call_args_list))
        self.assertTrue(all(call.kwargs["params"]["tournamentId"] == "sr:tournament:132" for call in feed_get.call_args_list))
        self.assertEqual(len(events), 101)
        duplicate = next(row for row in events if row["event_id"] == "event-0")
        self.assertEqual({market["specifier"] for market in duplicate["markets"]}, {"total=221.5"})

    def test_feed_returns_partial_pages_when_a_later_page_fails(self):
        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"ok": True, "events": [
                    {"event_id": f"event-{i}", "markets": []} for i in range(100)
                ]}

        with patch("capture_nba_totals_prices.S.get", side_effect=[
            Response(), RuntimeError("page two unavailable")
        ]):
            events, error = sportybet_basketball_feed_paged(max_pages=3)

        self.assertEqual(len(events), 100)
        self.assertIn("page 2", error)

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

    def test_new_quote_timestamp_gets_its_own_immutable_snapshot_not_a_new_bet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            prediction = make_prediction(self.now)
            prediction["generated_at"] = self.now.isoformat()
            self.assertTrue(attach_fresh_quote(prediction, make_quote(self.now), self.now))

            first_published = self.now + timedelta(seconds=3)
            first = append_nba_totals_publication_snapshots(
                [prediction], path, published_at=first_published.isoformat()
            )
            self.assertEqual(first["added"], 1)

            revised = copy.deepcopy(prediction)
            second_quote = self.now + timedelta(minutes=1)
            revised["markets"]["total_ou"]["quote_timestamp"] = second_quote.isoformat()
            second_published = second_quote + timedelta(seconds=3)
            second = append_nba_totals_publication_snapshots(
                [revised], path, published_at=second_published.isoformat()
            )
            self.assertEqual(second["added"], 1)

            duplicate = append_nba_totals_publication_snapshots(
                [revised], path, published_at=(second_quote + timedelta(seconds=6)).isoformat()
            )
            self.assertEqual(duplicate["added"], 0)

            snapshots = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(len({row["publication_snapshot_id"] for row in snapshots}), 2)
            self.assertEqual({row["event_id"] for row in snapshots}, {"espn-101"})
            self.assertEqual(
                {row["markets"]["total_ou"]["quote_timestamp"] for row in snapshots},
                {self.now.isoformat(), second_quote.isoformat()},
            )

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

    def test_fixture_diagnostics_separate_unopened_market_from_matching_errors(self):
        fixture = {
            "home": "Boston Celtics", "away": "New York Knicks",
            "date": (self.now + timedelta(hours=2)).isoformat(),
        }
        no_event = [{
            "event_id": "other", "home": "Chicago Bulls", "away": "Miami Heat",
            "start_time": fixture["date"], "fetched_at": self.now.isoformat(), "markets": [],
        }]
        self.assertEqual(
            diagnose_fixture_quote(fixture, no_event, self.now),
            "SPORTYBET_FIXTURE_NOT_LISTED_IN_FEED",
        )

        partial_identity = [{
            "event_id": "partial", "home": "Boston Celtics", "away": "Miami Heat",
            "start_time": fixture["date"], "fetched_at": self.now.isoformat(), "markets": [],
        }]
        self.assertEqual(
            diagnose_fixture_quote(fixture, partial_identity, self.now),
            "SPORTYBET_PARTIAL_TEAM_IDENTITY_MATCH",
        )

        wrong_time = [{
            "event_id": "same", "home": "Boston Celtics", "away": "New York Knicks",
            "start_time": (self.now + timedelta(hours=3)).isoformat(),
            "fetched_at": self.now.isoformat(), "markets": [],
        }]
        self.assertEqual(
            diagnose_fixture_quote(fixture, wrong_time, self.now),
            "SPORTYBET_START_TIME_MISMATCH_OVER_45_MIN",
        )

        no_market = [{
            "event_id": "same", "home": "Boston Celtics", "away": "New York Knicks",
            "start_time": fixture["date"], "fetched_at": self.now.isoformat(), "markets": [],
        }]
        self.assertEqual(
            diagnose_fixture_quote(fixture, no_market, self.now),
            "MARKET_225_NOT_OFFERED_FOR_MATCHED_FIXTURE",
        )

        incomplete = [{
            "event_id": "same", "home": "Boston Celtics", "away": "New York Knicks",
            "start_time": fixture["date"], "fetched_at": self.now.isoformat(),
            "markets": [{"id": "225", "specifier": "total=220.5", "outcomes": []}],
        }]
        self.assertEqual(
            diagnose_fixture_quote(fixture, incomplete, self.now),
            "MARKET_225_LINE_OR_BOTH_PRICES_UNUSABLE",
        )

        valid = [{
            "event_id": "same", "home": "Boston Celtics", "away": "New York Knicks",
            "start_time": fixture["date"], "fetched_at": self.now.isoformat(),
            "markets": [{
                "id": "225", "specifier": "total=220.5", "outcomes": [
                    {"name": "Over", "odds": 1.91, "active": True},
                    {"name": "Under", "odds": 1.89, "active": True},
                ],
            }],
        }]
        self.assertEqual(diagnose_fixture_quote(fixture, valid, self.now), "MATCHED")
        nearby = nearby_feed_events(fixture, valid)
        self.assertEqual(len(nearby), 1)
        self.assertEqual(nearby[0]["home"], "Boston Celtics")
        self.assertTrue(nearby[0]["market_225_present"])
        self.assertLessEqual(nearby[0]["minutes_from_fixture"], 180)

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
