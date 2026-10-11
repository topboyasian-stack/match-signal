#!/usr/bin/env python3
"""Regression tests for stale unresolved paper-ticket archiving.

These tests exercise only the lifecycle classification helper. They do not touch
or rewrite the real data/odds_ticket_tracker.json file.
"""
from __future__ import annotations

import sys
import unittest
import json
import urllib.parse
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.odds_ticket_tracker import backfill_virtual_results, settle_virtual_leg, ticket_is_stale_pending


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


class VirtualResultBackfillTests(unittest.TestCase):
    def ticket(self, product, event_id):
        start = datetime.now(timezone.utc).replace(microsecond=0)
        start = start.replace(year=start.year, month=start.month, day=start.day)
        from datetime import timedelta
        start -= timedelta(hours=2)
        return {
            "status": "PENDING",
            "legs": [{
                "status": "PENDING",
                "product": product,
                "event_id": event_id,
                "match": "Liverpool (PlayerA) vs Tottenham (PlayerB)",
                "market": "virtual_total",
                "builder_pick": "under",
                "pick": "Liverpool vs Tottenham — O/U under 5.5",
                "line": 5.5,
                "start_time": start.isoformat(),
            }],
        }

    def run_backfill_for_product(self, product, source, exact_scope=False):
        event_id = "sr:match:test-" + product
        tickets = [self.ticket(product, event_id)]
        def opener(request, timeout=60):
            class Response:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return json.dumps({
                        "ok": True,
                        "events": [{"eventId": event_id, "score": "5:2"}],
                        "errors": [],
                    }).encode("utf-8")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            self.assertEqual(query["source"], [source])
            if exact_scope:
                self.assertEqual(query["categoryId"], ["cat-test"])
                self.assertEqual(query["tournamentId"], ["tour-test"])
            return Response()
        scope_index = {
            event_id: {"source": source, "category_id": "cat-test", "tournament_id": "tour-test"}
        } if exact_scope else {}
        with patch("scripts.odds_ticket_tracker.urllib.request.urlopen", side_effect=opener):
            rows = backfill_virtual_results(tickets, datetime.now(timezone.utc).isoformat(), scope_index=scope_index)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product"], product)
        self.assertEqual(rows[0]["event_id"], event_id)
        self.assertEqual(rows[0]["result"], "O5.5")
        self.assertFalse(rows[0]["win"])
        self.assertEqual(rows[0]["backfill_match_mode"], "event_id")
        settled = settle_virtual_leg(tickets[0]["legs"][0], rows)
        self.assertEqual(settled["status"], "LOST")
        self.assertEqual(settled["final_score"], [5.0, 2.0])

    def test_efootball_pending_leg_uses_efootball_result_source(self):
        self.run_backfill_for_product("efootball_gt", "efootball")

    def test_efootball_adriatic_pending_leg_uses_efootball_result_source(self):
        self.run_backfill_for_product("efootball_adriatic", "efootball")

    def test_efootball_reuses_saved_exact_result_scope(self):
        self.run_backfill_for_product("efootball_gt", "efootball", exact_scope=True)

    def test_vfootball_pending_leg_keeps_vfootball_result_source(self):
        self.run_backfill_for_product("vfootball", "vfootball")

    def test_recent_pending_leg_is_not_sent_to_result_api(self):
        ticket = self.ticket("efootball_gt", "sr:match:too-recent")
        from datetime import timedelta
        ticket["legs"][0]["start_time"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        with patch("scripts.odds_ticket_tracker.urllib.request.urlopen") as mocked:
            self.assertEqual(backfill_virtual_results([ticket], datetime.now(timezone.utc).isoformat()), [])
        mocked.assert_not_called()
