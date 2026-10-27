#!/usr/bin/env python3
"""Unit tests for exposing stale PDL source status without publishing stale picks."""
import unittest

from system_health_audit_lib import pdl_health_summary


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
