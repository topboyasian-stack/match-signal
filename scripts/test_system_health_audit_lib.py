#!/usr/bin/env python3
"""Unit tests for exposing stale PDL source status without publishing stale picks."""
import unittest

from system_health_audit_lib import pdl_health_summary, virtual_live_health_summary, nba_live_observation_health_summary


class PDLHealthSummaryTests(unittest.TestCase):
    def test_stale_source_is_visible_but_nonblocking_when_stale_rows_are_withheld(self):
        lane, issues = pdl_health_summary({
            "status": "STALE_SOURCE_UNAVAILABLE",
            "paper_only": True,
            "historical_rows": 61,
            "current_upcoming": 3,
            "last_attempt_at": "2026-10-27T20:28:40+00:00",
            "last_successful_update_at": "2026-10-24T09:41:33+00:00",
            "last_error": "HTTP 403 upstream provider blocked",
        }, published_rows=0)
        self.assertEqual(lane["status"], "STALE_SOURCE_UNAVAILABLE")
        self.assertEqual(lane["published_prediction_rows"], 0)
        self.assertIn("last_successful_update_at", lane)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "PDL_EXPERIMENTAL_FEED_STALE")
        self.assertEqual(issues[0]["severity"], "info")

    def test_stale_pdl_rows_in_prediction_feed_are_critical(self):
        lane, issues = pdl_health_summary({
            "status": "STALE_SOURCE_UNAVAILABLE",
            "paper_only": True,
            "last_successful_update_at": "2026-10-24T09:41:33+00:00",
        }, published_rows=2)
        self.assertEqual(lane["published_prediction_rows"], 2)
        self.assertEqual(issues[0]["code"], "PDL_STALE_PREDICTIONS_STILL_PUBLISHED")
        self.assertEqual(issues[0]["severity"], "critical")

    def test_current_pdl_feed_has_no_stale_source_issue(self):
        lane, issues = pdl_health_summary({
            "status": "CURRENT",
            "paper_only": True,
            "historical_rows": 70,
            "current_upcoming": 4,
            "last_successful_update_at": "2026-10-27T20:30:00+00:00",
        }, published_rows=4)
        self.assertEqual(lane["status"], "CURRENT")
        self.assertEqual(issues, [])

    def test_unknown_status_is_not_silently_reported_as_current(self):
        lane, issues = pdl_health_summary({}, published_rows=0)
        self.assertEqual(lane["status"], "UNKNOWN")
        self.assertEqual(issues[0]["code"], "PDL_EXPERIMENTAL_FEED_STATUS_UNKNOWN")
        self.assertEqual(issues[0]["severity"], "warning")


class VirtualLiveHealthSummaryTests(unittest.TestCase):
    def test_fresh_nonempty_live_snapshot_passes(self):
        check, issues = virtual_live_health_summary(
            {"status": "LIVE", "events_count": 12}, 0.2
        )
        self.assertEqual(check["status"], "PASS")
        self.assertEqual(check["heartbeat_source"], "virtual_lab_live.json")
        self.assertEqual(issues, [])

    def test_stale_snapshot_is_degraded_even_if_a_downstream_board_refreshed(self):
        check, issues = virtual_live_health_summary(
            {"status": "LIVE", "events_count": 12}, 3.82
        )
        self.assertEqual(check["status"], "STALE")
        self.assertEqual(issues[0]["code"], "VIRTUAL_LIVE_FEED_STALE")
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertIn("cannot substitute", issues[0]["detail"])

    def test_empty_or_invalid_live_snapshot_is_critical(self):
        check, issues = virtual_live_health_summary(
            {"status": "UPSTREAM_EMPTY", "events_count": 0}, 0.1
        )
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(issues[0]["code"], "VIRTUAL_LIVE_FEED_INVALID")
        self.assertEqual(issues[0]["severity"], "critical")


class NbaLiveObservationHealthSummaryTests(unittest.TestCase):
    def test_recent_recorder_heartbeat_passes_even_without_active_games(self):
        check, issues = nba_live_observation_health_summary(
            {"updated_at": "2026-10-31T06:00:00Z", "games": {}}, 0.1
        )
        self.assertEqual(check["status"], "PASS")
        self.assertEqual(check["games_tracked"], 0)
        self.assertEqual(issues, [])

    def test_stale_recorder_is_visible_as_warning(self):
        check, issues = nba_live_observation_health_summary(
            {"games": {"event-1": {"snapshots": [{}, {}]}}}, 4.0
        )
        self.assertEqual(check["status"], "STALE")
        self.assertEqual(check["snapshots_recorded"], 2)
        self.assertEqual(issues[0]["code"], "NBA_LIVE_OBSERVATION_STALE")
        self.assertEqual(issues[0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main(verbosity=2)
