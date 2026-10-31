#!/usr/bin/env python3
"""Offline contract tests for NBA live box-score projection."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from record_nba_live_behavior import fetch_scoreboard_window, live_total_projection


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


class LiveBoxscoreProjectionTests(unittest.TestCase):
    def test_uses_both_teams_live_boxscore_to_estimate_possessions(self):
        result = live_total_projection(sample_record(), {"expected_total": 224.5})
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
        result = live_total_projection(sample_record(False), {"expected_total": 224.5})
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertFalse(result["uses_live_boxscore_stats"])
        self.assertEqual(result["projection_source"], "ESPN_LIVE_SCORE_CLOCK_PACE_ONLY")
        self.assertIsNone(result["stat_adjusted_total"])

    def test_overtime_never_reuses_regulation_pace_projection(self):
        record = sample_record()
        record["period"] = 5
        result = live_total_projection(record, {"expected_total": 224.5})
        self.assertEqual(result["status"], "OVERTIME_CONTEXT_ONLY")

    def test_insufficient_elapsed_time_withholds_live_estimate(self):
        record = sample_record()
        record["period"] = 1
        record["clock"] = "08:00"
        result = live_total_projection(record, {"expected_total": 224.5})
        self.assertEqual(result["status"], "COLLECTING")

    def test_missing_pregame_baseline_fails_closed(self):
        result = live_total_projection(sample_record(), {})
        self.assertEqual(result["status"], "NO_PREGAME_BASELINE")


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
