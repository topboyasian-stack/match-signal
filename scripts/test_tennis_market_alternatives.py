#!/usr/bin/env python3
"""Regression tests for continuous exact-line tennis market reassessment."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import odds_builder as builder
import tennis_market_reassessment as reassessment


NOW = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)


def synthetic_history(count=40):
    rows = []
    for index in range(count):
        start = START - timedelta(days=index + 1)
        rows.append({
            "sport": "tennis",
            "league": "ATP",
            "event_id": f"history-{index}",
            "start_time": start.isoformat(),
            "player_1": f"ATP Player {index} A",
            "player_2": f"ATP Player {index} B",
            "probabilities": {"p1": 0.64, "p2": 0.36},
            "rankings": {"p1": 5, "p2": 75},
            "form": {"p1": 0.70, "p2": 0.35},
            "final_score": [6, 4],
            "settled": True,
        })
    return rows


def current_fixture():
    return {
        "sport": "tennis",
        "league": "ATP",
        "event_id": "current-1",
        "start_time": START.isoformat(),
        "player_1": "Alexander Example",
        "player_2": "Player Example",
        "probabilities": {"p1": 0.64, "p2": 0.36},
        "rankings": {"p1": 5, "p2": 75},
        "form": {"p1": 0.70, "p2": 0.35},
        "analytics": {
            "total_games": {
                "line": 22.5,
                "over": 0.65,
                "under": 0.35,
                "pick": "over",
                "market_alignment_status": "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED",
            }
        },
        "sportybet_total_games_odds": [
            {"line": 18.5, "over": 1.86, "under": 1.94, "market_id": "189", "specifier": "total=18.5"},
            {"line": 20.5, "over": 1.92, "under": 1.84, "market_id": "189", "specifier": "total=20.5"},
            {"line": 22.5, "over": 1.88, "under": 1.90, "market_id": "189", "specifier": "total=22.5"},
            # A set total is not a full-match total and must never leak in.
            {"line": 7.5, "over": 1.80, "under": 2.00, "market_id": "204", "specifier": "setnr=1|total=7.5"},
        ],
        "market_odds_timestamp": "2026-11-06T09:58:00+00:00",
        "odds_timestamp": "2026-11-06T09:58:00+00:00",
        "model": "Published ATP winner + legacy total model",
        "signal_quality": {"components": 4},
    }


class TennisExactMarketReassessmentTests(unittest.TestCase):
    def test_only_current_two_sided_full_match_market_189_lines_are_used(self):
        quotes = reassessment.exact_full_match_total_quotes(current_fixture())
        self.assertEqual(sorted(quotes), [18.5, 20.5, 22.5])
        self.assertNotIn(7.5, quotes)
        self.assertEqual(quotes[20.5]["under"], 1.84)

    def test_builder_de_vigs_the_exact_selected_line_and_side(self):
        row = current_fixture()
        row.update({
            "line": 20.5,
            "builder_market": "total_games",
            "builder_pick": "under",
        })
        row["analytics"]["total_games"]["line"] = 20.5
        rows = builder.market_rows(row)
        self.assertEqual(rows, [
            {"side": "over", "odds": 1.92},
            {"side": "under", "odds": 1.84},
        ])
        selected, implied, devig, complete = builder.selected_price_and_devig(row)
        self.assertAlmostEqual(selected, 1.84, places=6)
        self.assertGreater(implied, 0)
        self.assertGreater(devig, 0)
        self.assertTrue(complete)

    def test_every_available_line_is_recalculated_and_can_flip_the_side(self):
        fixture = current_fixture()
        candidates = reassessment.build_tennis_candidates(
            builder,
            NOW,
            prediction_rows=[fixture],
            history=synthetic_history(),
            baseline_fn=lambda _now: [],
        )
        total_candidates = [
            row for row in candidates
            if row.get("sport") == "tennis" and row.get("builder_market") == "total_games"
        ]
        self.assertTrue(total_candidates)
        self.assertEqual({row["line"] for row in total_candidates}, {18.5, 20.5, 22.5})
        self.assertTrue(all(row["builder_pick"] == "under" for row in total_candidates))
        self.assertTrue(all(row["market_reassessment"]["status"] == "RECALCULATED_EXACT_CURRENT_MARKET_LINE" for row in total_candidates))
        self.assertTrue(all(row["market_reassessment"]["history_neighbors"] >= 30 for row in total_candidates))
        self.assertTrue(all(row["market_reassessment"]["quote_line_exact"] for row in total_candidates))
        # The model is not copying the old Over pick or the old line probability.
        self.assertTrue(all(row["builder_probability"] > 0.60 for row in total_candidates))
        self.assertTrue(all(row["analytics"]["total_games"]["line"] == row["line"] for row in total_candidates))

    def test_insufficient_history_does_not_reuse_an_unavailable_or_unrecalculated_line(self):
        fixture = current_fixture()
        fixture["analytics"]["total_games"]["market_alignment_status"] = "LEGACY_MODEL_ONLY"
        candidates = reassessment.build_tennis_candidates(
            builder,
            NOW,
            prediction_rows=[fixture],
            history=synthetic_history(12),
            baseline_fn=lambda _now: [],
        )
        self.assertEqual(candidates, [])
        self.assertEqual(reassessment.diagnostics()["events_held_for_history"], 1)

    def test_recalculated_leg_keeps_exact_line_price_and_audit_metadata(self):
        fixture = current_fixture()
        candidates = reassessment.build_tennis_candidates(
            builder,
            NOW,
            prediction_rows=[fixture],
            history=synthetic_history(),
            baseline_fn=lambda _now: [],
        )
        candidate = next(row for row in candidates if row["line"] == 20.5 and row["builder_pick"] == "under")
        with (
            mock.patch.object(builder, "odds_age", return_value=10.0),
            mock.patch.object(builder, "data_quality", return_value=1.0),
            mock.patch.object(builder, "uncertainty", return_value=0.01),
        ):
            leg = builder.make_leg(candidate)
        self.assertEqual(leg["line"], 20.5)
        self.assertAlmostEqual(leg["bookmaker_odds"], 1.84, places=6)
        self.assertTrue(leg["market_complete"])
        self.assertTrue(leg["builder_eligible"])
        self.assertEqual(leg["market_reassessment"]["line"], 20.5)
        self.assertEqual(leg["market_reassessment"]["side"], "under")


if __name__ == "__main__":
    unittest.main(verbosity=2)
