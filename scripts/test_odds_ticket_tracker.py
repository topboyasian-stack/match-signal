#!/usr/bin/env python3
"""Regression tests for stale unresolved paper-ticket archiving.

These tests exercise only the lifecycle classification helper. They do not touch
or rewrite the real data/odds_ticket_tracker.json file.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.odds_ticket_tracker import ticket_is_stale_pending


class StalePaperTicketArchiveTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    def ticket(self, starts, status="PENDING"):
        return {
            "ticket_id": "TEST-TICKET",
            "status": status,
            "legs": [{"start_time": start, "status": "PENDING"} for start in starts],
        }

    def test_old_pending_ticket_is_archived_after_six_hours(self):
        ticket = self.ticket(["2026-10-10T04:00:00Z", "2026-10-10T05:30:00Z"])
        self.assertTrue(ticket_is_stale_pending(ticket, self.now))

    def test_recent_pending_ticket_stays_in_current_track(self):
        ticket = self.ticket(["2026-10-10T07:00:00Z", "2026-10-10T10:00:00Z"])
        self.assertFalse(ticket_is_stale_pending(ticket, self.now))

    def test_latest_leg_controls_staleness(self):
        ticket = self.ticket(["2026-10-10T03:00:00Z", "2026-10-10T11:00:00Z"])
        self.assertFalse(ticket_is_stale_pending(ticket, self.now))

    def test_settled_ticket_is_never_archived_as_stale_pending(self):
        ticket = self.ticket(["2026-09-30T05:00:00Z"], status="LOST")
        self.assertFalse(ticket_is_stale_pending(ticket, self.now))

    def test_missing_or_invalid_kickoff_is_not_auto_archived(self):
        self.assertFalse(ticket_is_stale_pending(self.ticket([""]), self.now))
        self.assertFalse(ticket_is_stale_pending(self.ticket(["not-a-date"]), self.now))
        self.assertFalse(ticket_is_stale_pending({"status": "PENDING", "legs": []}, self.now))

    def test_timezone_naive_kickoff_is_interpreted_as_utc(self):
        ticket = self.ticket(["2026-10-10T03:00:00"])
        self.assertTrue(ticket_is_stale_pending(ticket, self.now))

    def test_classification_does_not_mutate_snapshot(self):
        ticket = self.ticket(["2026-09-30T05:00:00Z"])
        before = repr(ticket)
        self.assertTrue(ticket_is_stale_pending(ticket, self.now))
        self.assertEqual(repr(ticket), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
