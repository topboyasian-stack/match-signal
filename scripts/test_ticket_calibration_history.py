#!/usr/bin/env python3
"""Regression tests for complete, time-safe ticket calibration history."""
from datetime import datetime, timezone
from unittest.mock import patch
import unittest

import odds_builder as builder
import ticket_calibration_experiment as experiment
from ticket_history import merge_ticket_history, settled_ticket_history


def make_ticket(index, *, status=None, stamp=None, ticket_id=None, lane="efootball_exact_evidence_value"):
    return {
        "ticket_id": ticket_id or f"T-{index:03d}",
        "status": status or ("WON" if index % 5 == 0 else "LOST"),
        "created_at": f"2026-10-{min(index + 1, 28):02d}T10:00:00+00:00",
        "last_settled_at": stamp or f"2026-10-{min(index + 1, 28):02d}T12:00:00+00:00",
        "leg_count": 2,
        "combined_odds": 3.4,
        "combined_model_probability": 0.80,
        "primary_lane": lane,
        "products": ["efootball_gt"],
        "legs": [
            {"event_id": f"event-{index}-a", "product": "efootball_gt", "market": "over_under", "line": 2.5, "builder_pick": "over"},
            {"event_id": f"event-{index}-b", "product": "efootball_gt", "market": "over_under", "line": 2.5, "builder_pick": "over"},
        ],
    }


def ledger_fixture():
    archived = [make_ticket(i) for i in range(9)]
    archived.append(make_ticket(99, status="PENDING", stamp=None, ticket_id="T-PENDING"))
    current = [make_ticket(0, status="WON", stamp="2026-10-20T12:00:00+00:00")]
    current.extend(make_ticket(i) for i in range(9, 12))
    return {"tickets": current, "archived_tickets": archived}


class TicketCalibrationHistoryTests(unittest.TestCase):
    def test_archived_and_current_records_are_combined_and_deduplicated(self):
        raw = ledger_fixture()
        unique, diagnostics = merge_ticket_history(raw)
        self.assertEqual(diagnostics["current_rows"], 4)
        self.assertEqual(diagnostics["archived_rows"], 10)
        self.assertEqual(diagnostics["duplicate_rows_collapsed"], 1)
        self.assertEqual(diagnostics["unique_rows"], 13)
        self.assertEqual(diagnostics["settled_unique_rows"], 12)
        self.assertEqual(diagnostics["pending_unique_rows"], 1)
        settled = settled_ticket_history(raw)
        self.assertEqual(len(settled), 12)
        winner = next(row for row in settled if row["ticket_id"] == "T-000")
        self.assertEqual(winner["status"], "WON", "active ticket record should replace archived duplicate")

    def test_experiment_uses_last_settled_at_and_scores_only_later_tickets(self):
        rows = settled_ticket_history(ledger_fixture())
        stamps = [row["_calibration_stamp"] for row in rows]
        self.assertEqual(stamps, sorted(stamps))
        self.assertTrue(all(stamp for stamp in stamps))
        predictions, metrics = experiment.calibrate(rows)
        self.assertEqual(metrics["n"], 4, "12 unique settled rows with an 8-ticket warmup yields four forward scores")
        self.assertEqual(len(predictions), 4)
        self.assertTrue(all(row["settled_at"] for row in predictions))
        self.assertEqual(predictions[0]["ticket_id"], rows[8]["ticket_id"])

    def test_builder_gamma_uses_archived_settlements_and_deduplicates(self):
        old_cache = builder._TICKET_CALIBRATION_CACHE
        builder._TICKET_CALIBRATION_CACHE = None
        try:
            with patch.object(builder, "load", return_value=ledger_fixture()):
                result = builder._ticket_calibration_gamma()
        finally:
            builder._TICKET_CALIBRATION_CACHE = old_cache
        self.assertEqual(result["sample"], 12)
        self.assertTrue(result["trained"])
        self.assertEqual(result["gamma_observations"], 4)

    def test_efootball_ticket_lane_does_not_inherit_unrelated_general_gamma(self):
        legs = [
            {"product": "efootball_gt", "qualification_lane": "efootball_exact_evidence_value",
             "model_probability": 0.70, "model_edge": 0.05},
            {"product": "efootball_gt", "qualification_lane": "efootball_exact_evidence_value",
             "model_probability": 0.70, "model_edge": 0.05},
        ]
        with patch.object(builder, "_ticket_calibration_gamma",
                          return_value={"gamma": 3.0, "sample": 200, "trained": True}):
            metrics = builder._batch_metrics(legs)
        self.assertEqual(metrics["ticket_calibration_mode"], "efootball_exact_evidence_independence_proxy")
        self.assertEqual(metrics["ticket_calibration_gamma"], 1.0)
        self.assertAlmostEqual(metrics["raw_combined_model_probability"], 0.49)
        self.assertAlmostEqual(metrics["combined_model_probability"], 0.49)


if __name__ == "__main__":
    unittest.main(verbosity=2)
