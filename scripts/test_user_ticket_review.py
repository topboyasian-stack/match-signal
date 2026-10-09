"""Dependency-free regression tests for private user-ticket evidence review."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_user_ticket_review import (  # noqa: E402
    analyze_leg,
    evaluate_pick,
    summarize_document,
    validate_document,
)


def make_leg(actual_pick="over", actual_line=1.5, desk_pick="over", desk_line=2.5, score=(1, 1)):
    return {
        "leg_ref": "leg_1",
        "product": "vfootball",
        "match": "Sample A vs Sample B",
        "actual_selection": {
            "market": "total_goals_over_under",
            "pick": actual_pick,
            "line": actual_line,
            "odds": 1.5,
        },
        "desk_snapshot": {
            "market": "total_goals_over_under",
            "pick": desk_pick,
            "line": desk_line,
            "odds": 1.8,
            "model_probability": 0.72,
            "captured_at": "2026-10-09T10:00:00Z",
        },
        "final_score": {"home": score[0], "away": score[1]},
        "settled_at": "2026-10-09T10:10:00Z",
    }


def make_document(leg):
    return {
        "schema_version": 1,
        "record_type": "private_user_ticket_review",
        "mode": "PRIVATE_USER_EVIDENCE",
        "updated_at": "2026-10-09T10:12:00Z",
        "tickets": [{
            "ticket_ref": "private_ticket_1",
            "captured_at": "2026-10-09T10:00:00Z",
            "reported_ticket_outcome": "LOST",
            "stake": 300,
            "total_odds": 3.17,
            "total_return": 0,
            "currency": "NGN",
            "legs": [leg],
        }],
    }


class UserTicketReviewTests(unittest.TestCase):
    def test_over_line_reduction_can_change_outcome(self):
        leg = make_leg(actual_pick="over", actual_line=1.5, desk_pick="over", desk_line=2.5, score=(1, 1))
        result = analyze_leg(leg)
        self.assertEqual(result["line_adjustment"], "user_line_easier")
        self.assertEqual(result["desk_result"], "LOST")
        self.assertEqual(result["actual_result"], "WON")
        self.assertEqual(result["counterfactual"], "actual_selection_won_desk_did_not")

    def test_under_line_increase_is_easier_but_can_still_lose(self):
        leg = make_leg(actual_pick="under", actual_line=9.5, desk_pick="under", desk_line=8.5, score=(7, 6))
        result = analyze_leg(leg)
        self.assertEqual(result["line_adjustment"], "user_line_easier")
        self.assertEqual(result["desk_result"], "LOST")
        self.assertEqual(result["actual_result"], "LOST")
        self.assertEqual(result["counterfactual"], "neither_won")

    def test_under_line_reduction_is_harder(self):
        leg = make_leg(actual_pick="under", actual_line=7.5, desk_pick="under", desk_line=8.5, score=(3, 3))
        self.assertEqual(analyze_leg(leg)["line_adjustment"], "user_line_harder")

    def test_side_change_is_not_misclassified_as_line_safety(self):
        leg = make_leg(actual_pick="under", actual_line=2.5, desk_pick="over", desk_line=2.5, score=(2, 1))
        self.assertEqual(analyze_leg(leg)["line_adjustment"], "side_changed")

    def test_integer_line_push_is_not_a_win_or_loss(self):
        self.assertEqual(evaluate_pick("over", 2, {"home": 1, "away": 1}), "PUSH")
        self.assertEqual(evaluate_pick("under", 2, {"home": 1, "away": 1}), "PUSH")

    def test_missing_desk_snapshot_keeps_actual_result(self):
        leg = make_leg()
        leg.pop("desk_snapshot")
        result = analyze_leg(leg)
        self.assertEqual(result["actual_result"], "WON")
        self.assertEqual(result["desk_result"], None)
        self.assertEqual(result["line_adjustment"], "desk_snapshot_missing")
        self.assertEqual(result["counterfactual"], "not_comparable")

    def test_validation_rejects_invalid_odds(self):
        document = make_document(make_leg())
        document["tickets"][0]["legs"][0]["actual_selection"]["odds"] = 1
        self.assertTrue(any("actual_selection.odds" in error for error in validate_document(document)))

    def test_summary_keeps_leg_hit_rate_separate_from_ticket_result(self):
        document = make_document(make_leg())
        summary = summarize_document(document)
        self.assertEqual(summary["ticket_count"], 1)
        self.assertEqual(summary["leg_count"], 1)
        self.assertEqual(summary["actual_selection_outcomes"]["WON"], 1)
        self.assertAlmostEqual(summary["actual_leg_hit_rate_excluding_pushes"], 1.0)
        # The reported accumulator outcome is not replaced by its single leg.
        self.assertEqual(document["tickets"][0]["reported_ticket_outcome"], "LOST")

    def test_desk_snapshot_time_remains_unverified_and_flags_after_kickoff(self):
        leg = make_leg()
        leg["kickoff_at"] = "2026-10-09T10:30:00Z"
        result = analyze_leg(leg)
        self.assertEqual(result["desk_snapshot_timing"], "user_reported_pre_kickoff_time_unverified")
        leg["desk_snapshot"]["captured_at"] = "2026-10-09T10:45:00Z"
        self.assertEqual(analyze_leg(leg)["desk_snapshot_timing"], "captured_after_kickoff")

    def test_user_reported_provenance_is_validated(self):
        document = make_document(make_leg())
        document["tickets"][0]["legs"][0]["desk_snapshot"]["provenance"] = "captured_live"
        self.assertTrue(any("provenance must be user_reported" in error for error in validate_document(document)))


if __name__ == "__main__":
    unittest.main()
