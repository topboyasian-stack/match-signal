#!/usr/bin/env python3
"""Regression tests for exact half-line SportyBet tennis totals alignment."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import enrich_sportybet_odds as sync  # noqa: E402
from tennis_total_model import recommend_total_line  # noqa: E402
from tennis_ou_v3 import calibrate as calibrate_tennis_ou  # noqa: E402

TARGET_TIME = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def synthetic_history():
    rows = []
    for i in range(40):
        start = TARGET_TIME - timedelta(days=2 + i)
        rows.append({
            "sport": "tennis",
            "league": "ATP",
            "event_id": f"history-{i}",
            "start_time": start.isoformat(),
            "player_1": f"ATP Player {i} A",
            "player_2": f"ATP Player {i} B",
            "probabilities": {"p1": 0.64, "p2": 0.36},
            "rankings": {"p1": 5, "p2": 75},
            "form": {"p1": 0.7, "p2": 0.35},
            "final_score": [6, 4],
            "settled": True,
        })
    return rows


def target_prediction():
    return {
        "sport": "tennis",
        "league": "ATP",
        "event_id": "current-1",
        "start_time": TARGET_TIME.isoformat(),
        "player_1": "Alexander Example",
        "player_2": "Player Example",
        "probabilities": {"p1": 0.64, "p2": 0.36},
        "rankings": {"p1": 5, "p2": 75},
        "form": {"p1": 0.7, "p2": 0.35},
        "analytics": {"total_games": {"line": 18.5, "over": 0.78, "under": 0.22, "pick": "over"}},
    }


def match_total_rows(lines):
    out = []
    for line in lines:
        for side, odds in (("over", 1.9), ("under", 1.9)):
            out.append({
                "line": line,
                "side": side,
                "odds": odds,
                "market_id": "189",
                "specifier": f"total={line}",
            })
    return out


class ExactTennisLineAlignmentTests(unittest.TestCase):
    def test_decimal_specifiers_preserve_half_lines(self):
        self.assertEqual(sync.line_from_specifier("total=19.5"), 19.5)
        self.assertEqual(sync.line_from_specifier("total=20.5"), 20.5)
        self.assertEqual(sync.line_from_specifier("setnr=1|total=6.5"), 6.5)
        self.assertEqual(sync.line_from_specifier("line=22.5"), 22.5)

    def test_only_full_match_lines_with_both_sides_are_available(self):
        rows = match_total_rows([19.5, 20.5])
        rows += [
            {"line": 7.5, "side": "over", "odds": 1.5, "market_id": "204", "specifier": "setnr=1|total=7.5"},
            {"line": 21.5, "side": "over", "odds": 1.8, "market_id": "189", "specifier": "total=21.5"},
        ]
        self.assertEqual(sync.available_tennis_total_lines(rows), [19.5, 20.5])

    def test_recommender_never_uses_line_outside_supplied_market_ladder(self):
        history = synthetic_history()
        target = target_prediction()
        selected = recommend_total_line(target, history, minimum_probability=0.60, available_lines=[20.5, 22.5])
        self.assertIsNotNone(selected)
        self.assertIn(selected["recommended_line"], [20.5, 22.5])
        self.assertNotEqual(selected["recommended_line"], 18.5)

    def test_alignment_recalculates_probability_at_exact_available_line(self):
        prediction = target_prediction()
        changed = sync.align_tennis_total_prediction(prediction, match_total_rows([20.5, 22.5]), synthetic_history(), updated_at="2026-10-13T05:00:00+00:00")
        total = prediction["analytics"]["total_games"]
        self.assertTrue(changed)
        self.assertIn(total["line"], [20.5, 22.5])
        self.assertNotEqual(total["line"], 18.5)
        self.assertEqual(total["model_line_before_market_alignment"], 18.5)
        self.assertEqual(total["market_alignment_status"], "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED")
        self.assertAlmostEqual(total["over"] + total["under"], 1.0, places=5)

    def test_missing_exact_market_hides_unavailable_line_and_pick(self):
        prediction = target_prediction()
        changed = sync.align_tennis_total_prediction(prediction, [], synthetic_history(), updated_at="2026-10-13T05:00:00+00:00")
        total = prediction["analytics"]["total_games"]
        self.assertFalse(changed)
        self.assertIsNone(total["line"])
        self.assertIsNone(total["pick"])
        self.assertIsNone(total["over"])
        self.assertIsNone(total["under"])
        self.assertEqual(total["market_alignment_status"], "NO_EXACT_SPORTYBET_TOTAL_LINE")

    def test_non_tennis_prediction_is_untouched(self):
        row = {"sport": "football", "analytics": {"total_games": {"line": 2.5}}}
        before = repr(row)
        self.assertFalse(sync.align_tennis_total_prediction(row, match_total_rows([2.5]), synthetic_history()))
        self.assertEqual(repr(row), before)

    def test_exact_line_probability_is_not_adjusted_again_by_legacy_line_offset(self):
        row = target_prediction()
        total = row["analytics"]["total_games"]
        total.update({
            "line": 20.5,
            "over": 0.70,
            "under": 0.30,
            "base_model_over": 0.70,
            "base_model_under": 0.30,
            "market_alignment_status": "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED",
        })
        model = {"n": 0, "global_rate": 0.5, "cells": {}, "rates": {}, "broad_rates": {}, "line_rates": {}, "line_counts": {}}
        self.assertTrue(calibrate_tennis_ou(row, model))
        self.assertAlmostEqual(row["analytics"]["total_games"]["over"], 0.70, places=4)

    def test_missing_exact_line_does_not_get_recreated_by_legacy_calibrator(self):
        row = target_prediction()
        total = row["analytics"]["total_games"]
        total.update({"line": None, "over": None, "under": None, "pick": None,
                      "market_alignment_status": "NO_EXACT_SPORTYBET_TOTAL_LINE"})
        model = {"n": 0, "global_rate": 0.5, "cells": {}, "rates": {}, "broad_rates": {}, "line_rates": {}, "line_counts": {}}
        self.assertFalse(calibrate_tennis_ou(row, model))
        self.assertIsNone(total["line"])
        self.assertIsNone(total["pick"])


if __name__ == "__main__":
    unittest.main()
