#!/usr/bin/env python3
"""Regression tests for complete, time-safe ticket calibration history."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

import odds_builder as builder
import ticket_calibration_experiment as experiment
from ticket_history import merge_ticket_history, settled_ticket_history, independent_settled_ticket_history


def make_ticket(index, *, status=None, stamp=None, ticket_id=None, lane="efootball_exact_evidence_value"):
    return {
        "ticket_id": ticket_id or f"T-{index:03d}",
        "status": status or ("WON" if index % 5 == 0 else "LOST"),
        "created_at": f"2026-10-{min(index + 1, 28):02d}T10:00:00+00:00",
        "last_settled_at": stamp or f"2026-10-{min(index + 1, 28):02d}T12:00:00+00:00",
        "leg_count": 2,
        "combined_odds": 3.4,
        "combined_model_probability": 0.60,
        "raw_combined_model_probability": 0.80,
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
    def test_overlapping_event_tickets_are_excluded_from_independent_sample(self):
        first = make_ticket(1, status="LOST")
        overlapping = make_ticket(2, status="WON")
        third = make_ticket(3, status="WON")
        # Reusing just one leg event makes the whole accumulator dependent.
        overlapping["legs"][0]["event_id"] = first["legs"][0]["event_id"]
        raw = {"tickets": [first, overlapping, third], "archived_tickets": []}

        independent, diagnostics = independent_settled_ticket_history(raw)
        self.assertEqual([row["ticket_id"] for row in independent], ["T-001", "T-003"])
        self.assertEqual(diagnostics["settled_ticket_rows"], 3)
        self.assertEqual(diagnostics["independent_ticket_rows"], 2)
        self.assertEqual(diagnostics["overlapping_event_tickets_excluded"], 1)
        self.assertEqual(diagnostics["tickets_missing_complete_event_identity"], 0)

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
        self.assertAlmostEqual(predictions[0]["model_probability"], 0.80)
        self.assertEqual(experiment.calibrate(rows)[1]["naive"]["avg_probability"], 0.80)

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

    def test_legacy_rows_without_raw_joint_probability_do_not_train_gamma(self):
        raw = ledger_fixture()
        for ticket in raw["archived_tickets"]:
            ticket.pop("raw_combined_model_probability", None)
        old_cache = builder._TICKET_CALIBRATION_CACHE
        builder._TICKET_CALIBRATION_CACHE = None
        try:
            with patch.object(builder, "load", return_value=raw):
                result = builder._ticket_calibration_gamma()
        finally:
            builder._TICKET_CALIBRATION_CACHE = old_cache
        self.assertEqual(result["sample"], 4, "only current rows with raw joint probabilities may train")
        self.assertEqual(result["available_settled_tickets"], 12)
        self.assertEqual(result["missing_raw_joint_probability_count"], 8)
        self.assertFalse(result["trained"])

    def test_efootball_ticket_lane_does_not_inherit_unrelated_general_gamma(self):
        legs = [
            {"product": "efootball_gt", "qualification_lane": "efootball_exact_evidence_value",
             "model_probability": 0.70, "model_edge": 0.05},
            {"product": "efootball_gt", "qualification_lane": "efootball_exact_evidence_value",
             "model_probability": 0.70, "model_edge": 0.05},
        ]
        lane_calibration = {
            "gamma": 2.0, "sample": 40, "settled_lane_ticket_count": 40,
            "missing_raw_joint_probability_count": 0, "trained": True,
            "oos_sample": 20, "raw_oos_brier": 0.25, "calibrated_oos_brier": 0.23,
            "oos_brier_improved": True, "promotion_allowed": True
        }
        with patch.object(builder, "_ticket_calibration_gamma",
                          return_value={"gamma": 3.0, "sample": 200, "trained": True}), \
             patch.object(builder, "_efootball_exact_evidence_ticket_gamma",
                          return_value=lane_calibration):
            metrics = builder._batch_metrics(legs)
        self.assertEqual(metrics["ticket_calibration_mode"], "efootball_exact_evidence_chronological_gamma")
        self.assertEqual(metrics["ticket_calibration_gamma"], 2.0)
        self.assertAlmostEqual(metrics["raw_combined_model_probability"], 0.49)
        self.assertAlmostEqual(metrics["combined_model_probability"], 0.49 ** 2)
        self.assertTrue(metrics["ticket_calibration_ready"])


    def test_brier_improvement_does_not_promote_lane_with_negative_settled_roi(self):
        origin = datetime(2026, 10, 1, tzinfo=timezone.utc)
        lane_tickets = []
        for index in range(40):
            status = "WON" if index % 5 == 0 else "LOST"
            stamp = (origin + timedelta(days=index)).isoformat()
            row = make_ticket(index, status=status, stamp=stamp, ticket_id=f"ROI-{index:03d}")
            row["combined_odds"] = 3.4
            row["raw_combined_model_probability"] = 0.56
            lane_tickets.append(row)

        old_cache = builder._EFOOTBALL_TICKET_CALIBRATION_CACHE
        builder._EFOOTBALL_TICKET_CALIBRATION_CACHE = None
        try:
            with patch.object(builder, "load", return_value={"tickets": lane_tickets, "archived_tickets": []}):
                result = builder._efootball_exact_evidence_ticket_gamma()
        finally:
            builder._EFOOTBALL_TICKET_CALIBRATION_CACHE = old_cache

        self.assertTrue(result["brier_promotion_allowed"], "chronological calibration should improve against an overconfident raw score")
        self.assertFalse(result["profitability_promotion_allowed"], "8 wins at 3.4x and 32 losses are negative flat-stake ROI")
        self.assertFalse(result["promotion_allowed"], "calibration quality is not the same as ticket profitability")
        self.assertEqual(result["settled_lane_profit_ticket_count"], 40)
        self.assertAlmostEqual(result["settled_lane_flat_stake_roi"], -0.32)
        self.assertEqual(result["promotion_hold_reason"], "settled_lane_roi_not_positive")


if __name__ == "__main__":
    unittest.main(verbosity=2)
