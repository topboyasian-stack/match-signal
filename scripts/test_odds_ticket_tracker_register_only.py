#!/usr/bin/env python3
"""Regression tests for fast, idempotent Builder batch reservation."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.odds_ticket_tracker as tracker


class RegisterOnlyTicketTrackerTests(unittest.TestCase):
    def make_batch(self, starts_at):
        return {
            "batch_id": "DESK-BATCH-01",
            "primary_lane": "upcoming_desk_research",
            "combined_odds": 3.275,
            "combined_model_rating": 32.11,
            "combined_model_probability": 0.321147,
            "raw_combined_model_probability": 0.370511,
            "products": ["efootball_gt"],
            "legs": [
                {
                    "sport": "virtual",
                    "product": "efootball_gt",
                    "event_id": "event-desk-1",
                    "market": "virtual_total",
                    "line": 4.5,
                    "builder_pick": "over",
                    "pick": "Team A vs Team B — O/U over 4.5",
                    "match": "Team A vs Team B",
                    "start_time": starts_at,
                    "bookmaker_odds": 1.77,
                    "model_probability": 0.608696,
                },
                {
                    "sport": "virtual",
                    "product": "efootball_gt",
                    "event_id": "event-desk-2",
                    "market": "virtual_total",
                    "line": 4.5,
                    "builder_pick": "over",
                    "pick": "Team C vs Team D — O/U over 4.5",
                    "match": "Team C vs Team D",
                    "start_time": starts_at,
                    "bookmaker_odds": 1.85,
                    "model_probability": 0.608696,
                },
            ],
        }

    def test_register_only_persists_pending_event_reservations_without_network_settlement(self):
        start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder_path = root / "odds_builder.json"
            tracker_path = root / "odds_ticket_tracker.json"
            builder_path.write_text(json.dumps({"mode": "PAPER_ONLY", "batches": [self.make_batch(start)]}))
            tracker_path.write_text(json.dumps({
                "version": 4, "mode": "PAPER_ONLY", "updated_at": "2026-10-20T00:00:00+00:00",
                "summary": {}, "tickets": [], "archived_tickets": [],
            }))

            with (
                patch.object(tracker, "BUILDER", builder_path),
                patch.object(tracker, "TRACKER", tracker_path),
                patch.object(tracker, "flatten_history", side_effect=AssertionError("register-only must not load settlement history")),
                patch.object(tracker, "backfill_virtual_results", side_effect=AssertionError("register-only must not call result APIs")),
                patch.object(tracker, "refresh_ticket", side_effect=AssertionError("register-only must preserve existing settlement states")),
            ):
                tracker.main(register_only=True)
                first = json.loads(tracker_path.read_text())
                self.assertEqual(len(first["tickets"]), 1)
                ticket = first["tickets"][0]
                self.assertEqual(ticket["status"], "PENDING")
                self.assertEqual(ticket["leg_count"], 2)
                self.assertEqual({leg["event_id"] for leg in ticket["legs"]}, {"event-desk-1", "event-desk-2"})
                self.assertEqual(first["summary"]["pending"], 1)
                self.assertEqual(first["summary"]["legs_pending"], 2)

                first_id = ticket["ticket_id"]
                tracker.main(register_only=True)
                second = json.loads(tracker_path.read_text())
                self.assertEqual(len(second["tickets"]), 1, "the identical Builder batch must not register twice")
                self.assertEqual(second["tickets"][0]["ticket_id"], first_id)

    def test_register_only_retains_prior_settlements_and_archived_event_reservations(self):
        start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        prior = {
            "ticket_id": "T-OLD", "snapshot_fingerprint": "OLD",
            "batch_id": "OLD-BATCH", "status": "LOST", "created_at": "2026-10-19T00:00:00+00:00",
            "last_settled_at": "2026-10-19T01:00:00+00:00", "combined_odds": 3.2,
            "primary_lane": "upcoming_desk_research", "leg_count": 2,
            "settled_leg_count": 2, "pending_leg_count": 0,
            "leg_counts": {"won": 1, "lost": 1, "void": 0, "pending": 0},
            "legs": [
                {"status": "WON", "event_id": "old-1", "product": "efootball_gt", "sport": "virtual"},
                {"status": "LOST", "event_id": "old-2", "product": "efootball_gt", "sport": "virtual"},
            ],
            "paper_only": True, "real_money_execution": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder_path = root / "odds_builder.json"
            tracker_path = root / "odds_ticket_tracker.json"
            builder_path.write_text(json.dumps({"mode": "PAPER_ONLY", "batches": [self.make_batch(start)]}))
            tracker_path.write_text(json.dumps({
                "version": 4, "mode": "PAPER_ONLY", "updated_at": "2026-10-20T00:00:00+00:00",
                "summary": {}, "tickets": [], "archived_tickets": [prior],
            }))

            with (
                patch.object(tracker, "BUILDER", builder_path),
                patch.object(tracker, "TRACKER", tracker_path),
                patch.object(tracker, "flatten_history", side_effect=AssertionError("settlement history must not be refreshed")),
                patch.object(tracker, "backfill_virtual_results", side_effect=AssertionError("result API must not be called")),
                patch.object(tracker, "refresh_ticket", side_effect=AssertionError("saved results must not be overwritten")),
            ):
                tracker.main(register_only=True)

            current = json.loads(tracker_path.read_text())
            all_rows = current["tickets"] + current["archived_tickets"]
            preserved = next(row for row in all_rows if row["ticket_id"] == "T-OLD")
            self.assertEqual(preserved["status"], "LOST")
            self.assertEqual(preserved["legs"][0]["status"], "WON")
            self.assertEqual(preserved["legs"][1]["status"], "LOST")
            self.assertEqual(len([row for row in all_rows if row["status"] == "PENDING"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
