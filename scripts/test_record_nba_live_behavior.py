#!/usr/bin/env python3
"""Offline contract tests for NBA live box-score projection."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from record_nba_live_behavior import fetch_scoreboard_window, live_total_projection, load_observation_history, should_append_observation, write_observation_history


def stat(name, value, abbreviation=None):
    row = {"name": name, "displayValue": value}
    if abbreviation:
        row["abbreviation"] = abbreviation
    return row


def sample_record(with_stats=True):
    record = {
        "period": 2, "clock": "06:00",
        "home": {"id": "1", "name": "Home", "score": 45},
        "away": {"id": "2", "name": "Away", "score": 42},
    }
    if with_stats:
        record["team_statistics"] = [
            {"team": {"id": "1", "displayName": "Home"}, "statistics": [
                stat("fieldGoalsMade-fieldGoalsAttempted", "18-40", "FG"),
                stat("freeThrowsMade-freeThrowsAttempted", "7-10", "FT"),
                stat("offensiveRebounds", "5", "OREB"),
                stat("totalTurnovers", "8", "TO"),
            ]},
            {"team": {"id": "2", "displayName": "Away"}, "statistics": [
                stat("fieldGoalsMade-fieldGoalsAttempted", "17-39", "FG"),
                stat("freeThrowsMade-freeThrowsAttempted", "6-8", "FT"),
                stat("offensiveRebounds", "4", "OREB"),
                stat("totalTurnovers", "7", "TO"),
            ]},
        ]
    return record


def fresh_prediction(now=None, **overrides):
    now = now or datetime.now(timezone.utc)
    prediction = {"expected_total": 224.5, "generated_at": now.isoformat()}
    prediction.update(overrides)
    return prediction


class LiveBoxscoreProjectionTests(unittest.TestCase):
    def test_uses_both_teams_live_boxscore_to_estimate_possessions(self):
        result = live_total_projection(sample_record(), fresh_prediction())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertTrue(result["uses_live_boxscore_stats"])
        self.assertEqual(result["projection_source"], "ESPN_LIVE_BOXSCORE_POSSESSIONS_AND_SCORE_PACE")
        self.assertEqual(result["stats_summary"]["fields_used"], [
            "FGA", "FTA", "offensive rebounds", "turnovers", "score", "game clock"
        ])
        self.assertGreater(result["stats_summary"]["home_possessions"], 0)
        self.assertGreater(result["stats_summary"]["away_possessions"], 0)
        self.assertNotEqual(result["stat_adjusted_total"], result["score_pace_total"])
        self.assertTrue(206.5 <= result["live_total_estimate"] <= 242.5)

    def test_falls_back_explicitly_when_boxscore_fields_are_missing(self):
        result = live_total_projection(sample_record(False), fresh_prediction())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertFalse(result["uses_live_boxscore_stats"])
        self.assertEqual(result["projection_source"], "ESPN_LIVE_SCORE_CLOCK_PACE_ONLY")
        self.assertIsNone(result["stat_adjusted_total"])

    def test_overtime_never_reuses_regulation_pace_projection(self):
        record = sample_record()
        record["period"] = 5
        result = live_total_projection(record, fresh_prediction())
        self.assertEqual(result["status"], "OVERTIME_CONTEXT_ONLY")

    def test_decimal_seconds_only_clock_from_espn_final_minute_is_supported(self):
        record = sample_record()
        record["period"] = 2
        record["clock"] = "30.6"
        result = live_total_projection(record, fresh_prediction())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertAlmostEqual(result["elapsed_minutes"], 23.5, places=1)
        self.assertIn(result["projection_source"], {
            "ESPN_LIVE_BOXSCORE_POSSESSIONS_AND_SCORE_PACE",
            "ESPN_LIVE_SCORE_CLOCK_PACE_ONLY",
        })

    def test_decimal_seconds_in_minute_second_clock_is_supported(self):
        record = sample_record()
        record["period"] = 3
        record["clock"] = "0:30.6"
        result = live_total_projection(record, fresh_prediction())
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertAlmostEqual(result["elapsed_minutes"], 35.5, places=1)

    def test_insufficient_elapsed_time_withholds_live_estimate(self):
        record = sample_record()
        record["period"] = 1
        record["clock"] = "08:00"
        result = live_total_projection(record, fresh_prediction())
        self.assertEqual(result["status"], "COLLECTING")

    def test_missing_or_stale_timestamp_is_withheld_like_the_live_desk(self):
        now = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)
        missing = live_total_projection(sample_record(), {"expected_total": 224.5}, now=now)
        self.assertEqual(missing["status"], "STALE_PREGAME_BASELINE")
        old = live_total_projection(
            sample_record(), fresh_prediction(now - timedelta(hours=6, seconds=1)), now=now
        )
        self.assertEqual(old["status"], "STALE_PREGAME_BASELINE")
        future = live_total_projection(
            sample_record(), fresh_prediction(now + timedelta(minutes=3)), now=now
        )
        self.assertEqual(future["status"], "STALE_PREGAME_BASELINE")

    def test_live_projection_reports_eligible_baseline_age(self):
        now = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)
        result = live_total_projection(
            sample_record(), fresh_prediction(now - timedelta(minutes=30)), now=now
        )
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["pregame_baseline_age_minutes"], 30)

    def test_missing_pregame_baseline_fails_closed(self):
        result = live_total_projection(sample_record(), {})
        self.assertEqual(result["status"], "NO_PREGAME_BASELINE")


    def test_same_minute_final_transition_is_not_deduplicated(self):
        observed = "2026-10-31T23:59:30+00:00"
        live = {
            "observed_at": observed, "game_state": "live", "status": "0:00 - 4th",
            "period": 4, "clock": "0:00",
            "home": {"score": "110"}, "away": {"score": "105"},
        }
        duplicate = dict(live, observed_at="2026-10-31T23:59:55+00:00")
        final = {
            **live, "observed_at": "2026-10-31T23:59:55+00:00",
            "game_state": "final", "status": "Final",
        }
        changed_score = {
            **live, "observed_at": "2026-10-31T23:59:55+00:00",
            "home": {"score": "112"},
        }
        self.assertFalse(should_append_observation(live, duplicate))
        self.assertTrue(should_append_observation(live, final))
        self.assertTrue(should_append_observation(live, changed_score))

    def test_next_minute_observation_is_kept_even_without_score_change(self):
        live = {
            "observed_at": "2026-10-31T23:59:30+00:00", "game_state": "live",
            "status": "1:00 - 4th", "period": 4, "clock": "1:00",
            "home": {"score": "110"}, "away": {"score": "105"},
        }
        next_minute = {**live, "observed_at": "2026-11-01T00:00:10+00:00"}
        self.assertTrue(should_append_observation(live, next_minute))

    def test_legacy_json_archive_migrates_to_gzip_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compressed = root / "nba_live_observations.json.gz"
            legacy = root / "nba_live_observations.json"
            expected = {
                "updated_at": "2026-10-31T21:00:00+00:00",
                "games": {"event-1": {"event_id": "event-1", "snapshots": [{"observed_at": "2026-10-31T21:00:00+00:00"}]}},
            }
            legacy.write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(load_observation_history(compressed, legacy), expected)
            write_observation_history(expected, compressed, legacy)
            self.assertTrue(compressed.exists())
            self.assertFalse(legacy.exists(), "the raw legacy archive must be removed after compression")
            self.assertEqual(load_observation_history(compressed, legacy), expected)

    def test_scoreboard_window_uses_eastern_adjacent_days_after_utc_rollover(self):
        now = datetime(2026, 10, 31, 10, 10, tzinfo=timezone.utc)
        calls = []
        def fake_get(url, params=None):
            calls.append(params["dates"])
            return {"events": [{"id": "game-" + params["dates"]}]}
        with patch("record_nba_live_behavior.get", side_effect=fake_get):
            events, dates, errors = fetch_scoreboard_window(now)
        self.assertEqual(dates, ["20261030", "20261031", "20261101"])
        self.assertEqual(calls, dates)
        self.assertEqual({row["id"] for row in events}, {"game-20261030", "game-20261031", "game-20261101"})
        self.assertEqual(errors, [])

    def test_scoreboard_window_deduplicates_events_and_records_partial_source_errors(self):
        now = datetime(2026, 10, 31, 10, 10, tzinfo=timezone.utc)
        def fake_get(url, params=None):
            if params["dates"] == "20261030":
                raise RuntimeError("temporary provider error")
            return {"events": [{"id": "same-game"}, {"id": "same-game", "status": "latest"}]}
        with patch("record_nba_live_behavior.get", side_effect=fake_get):
            events, dates, errors = fetch_scoreboard_window(now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "latest")
        self.assertEqual(errors[0]["date"], "20261030")


if __name__ == "__main__":
    unittest.main(verbosity=2)
