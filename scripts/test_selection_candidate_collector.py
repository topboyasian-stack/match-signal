#!/usr/bin/env python3
"""Regression tests for preserving exact two-sided SportyBet quotes in Desk candidates."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import selection_candidate_collector as collector  # noqa: E402

NOW = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)


def base_row(**overrides):
    row = {
        "event_id": "event-1",
        "start_time": (NOW + timedelta(hours=1)).isoformat(),
        "sport": "virtual",
        "product": "efootball_gt",
        "league": "Recognized test league",
        "player_1": "Team One",
        "player_2": "Team Two",
        "market": "over_under",
        "line": 2.5,
        "pick": "over",
        "probability": 0.90,
        "bookmaker_odds": 2.05,
        "sportybet_odds_market": "total",
        "sportybet_odds_line": 2.5,
        "sportybet_odds_side": "over",
        "market_odds_timestamp": (NOW - timedelta(minutes=2)).isoformat(),
        "sportybet_over_odds": 2.05,
        "sportybet_under_odds": 1.85,
    }
    row.update(overrides)
    return row


class SelectionCandidateQuotePreservationTests(unittest.TestCase):
    def test_duplicate_event_prefers_newest_sportybet_snapshot(self):
        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=2)).isoformat()
        old_quote = (now - timedelta(hours=1)).isoformat()
        fresh_quote = (now - timedelta(minutes=2)).isoformat()
        old_row = base_row(
            sport="tennis",
            product=None,
            start_time=start,
            market="winner",
            line=None,
            pick="p1",
            probability=0.7933,
            bookmaker_odds=1.39,
            sportybet_odds_market="winner",
            sportybet_odds_line=None,
            sportybet_odds_side="p1",
            sportybet_winner_odds={"p1": 1.39, "draw": None, "p2": 3.15},
            sportybet_over_odds=None,
            sportybet_under_odds=None,
            market_odds_timestamp=old_quote,
        )
        fresh_row = dict(old_row)
        fresh_row.update({
            "bookmaker_odds": 1.45,
            "sportybet_winner_odds": {"p1": 1.45, "draw": None, "p2": 2.95},
            "market_odds_timestamp": fresh_quote,
        })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unified_path = root / "unified_upcoming.json"
            predictions_path = root / "predictions.json"
            output_path = root / "selection_candidates.json"
            status_path = root / "selection_candidate_status.json"
            unified_path.write_text(json.dumps({"events": [old_row]}), encoding="utf-8")
            predictions_path.write_text(json.dumps([fresh_row]), encoding="utf-8")

            with (
                mock.patch.object(collector, "UNIFIED", unified_path),
                mock.patch.object(collector, "PREDICTIONS", predictions_path),
                mock.patch.object(collector, "OUT", output_path),
                mock.patch.object(collector, "STATUS_OUT", status_path),
            ):
                collector.main()

            rows = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["market_odds_timestamp"], fresh_quote)
            self.assertEqual(rows[0]["bookmaker_odds"], 1.45)
            self.assertEqual(rows[0]["sportybet_winner_odds"]["p1"], 1.45)


    def test_preserves_participant_history_freshness_into_candidate_pool(self):
        row = base_row()
        row.update({
            "participant_history_fresh": False,
            "participant_history_age_minutes": 184.2,
            "participant_history_stale_reason": "input older than 30 minutes: collector_status",
        })
        result = collector.compact(row, NOW)
        self.assertIsNotNone(result)
        self.assertFalse(result["participant_history_fresh"])
        self.assertAlmostEqual(result["participant_history_age_minutes"], 184.2)
        self.assertEqual(
            result["participant_history_stale_reason"],
            "input older than 30 minutes: collector_status",
        )

        row["participant_history_fresh"] = True
        row["participant_history_age_minutes"] = 4.0
        row["participant_history_stale_reason"] = None
        result = collector.compact(row, NOW)
        self.assertTrue(result["participant_history_fresh"])
        self.assertEqual(result["participant_history_age_minutes"], 4.0)
        self.assertIsNone(result["participant_history_stale_reason"])

    def test_preserves_both_current_virtual_total_sides(self):
        result = collector.compact(base_row(), NOW)
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_odds_market"], "total")
        self.assertEqual(result["sportybet_odds_line"], 2.5)
        self.assertEqual(result["sportybet_odds_side"], "over")
        self.assertEqual(result["bookmaker_odds"], 2.05)
        self.assertEqual(result["sportybet_over_odds"], 2.05)
        self.assertEqual(result["sportybet_under_odds"], 1.85)

    def test_extracts_both_sides_from_tennis_total_games_snapshot(self):
        result = collector.compact(
            base_row(
                sport="tennis",
                product=None,
                market="over_under",
                line=21.5,
                sportybet_odds_line=21.5,
                sportybet_total_games_odds=[
                    {"line": 20.5, "over": 1.70, "under": 2.10},
                    {"line": 21.5, "over": 1.91, "under": 1.91},
                    {"line": 22.5, "over": 2.05, "under": 1.75},
                ],
                sportybet_over_odds=None,
                sportybet_under_odds=None,
                bookmaker_odds=1.91,
            ),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_over_odds"], 1.91)
        self.assertEqual(result["sportybet_under_odds"], 1.91)

    def test_supports_side_odds_rows_for_exact_line(self):
        result = collector.compact(
            base_row(
                line=7.5,
                sportybet_odds_line=7.5,
                sportybet_over_odds=None,
                sportybet_under_odds=None,
                sportybet_total_games_odds=[
                    {"line": 7.5, "side": "over", "odds": 2.10},
                    {"line": 7.5, "side": "under", "odds": 1.72},
                ],
                bookmaker_odds=1.72,
                pick="under",
                sportybet_odds_side="under",
            ),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_over_odds"], 2.10)
        self.assertEqual(result["sportybet_under_odds"], 1.72)

    def test_never_borrows_prices_from_a_different_line(self):
        result = collector.compact(
            base_row(
                line=21.5,
                sportybet_odds_line=21.5,
                sportybet_over_odds=None,
                sportybet_under_odds=None,
                sportybet_total_games_odds=[
                    {"line": 20.5, "over": 1.70, "under": 2.10},
                    {"line": 22.5, "over": 2.05, "under": 1.75},
                ],
            ),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertIsNone(result["sportybet_over_odds"])
        self.assertIsNone(result["sportybet_under_odds"])

    def test_one_missing_side_remains_missing(self):
        result = collector.compact(
            base_row(sportybet_over_odds=2.05, sportybet_under_odds=None),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_over_odds"], 2.05)
        self.assertIsNone(result["sportybet_under_odds"])

    def test_preserves_all_current_winner_outcomes_for_de_vigging(self):
        result = collector.compact(
            base_row(
                sport="football",
                product=None,
                market="winner",
                line=None,
                pick="p1",
                selection="Home",
                bookmaker_odds=2.10,
                sportybet_odds_market="winner",
                sportybet_odds_line=None,
                sportybet_odds_side="p1",
                sportybet_winner_odds={
                    "p1": 2.10,
                    "draw": 3.20,
                    "p2": 3.60,
                },
                sportybet_over_odds=None,
                sportybet_under_odds=None,
            ),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_winner_odds"], {
            "p1": 2.10,
            "draw": 3.20,
            "p2": 3.60,
        })

    def test_invalid_or_non_decimal_winner_prices_are_not_copied(self):
        result = collector.compact(
            base_row(
                sport="football",
                product=None,
                market="winner",
                line=None,
                pick="p1",
                bookmaker_odds=2.10,
                sportybet_odds_market="winner",
                sportybet_odds_side="p1",
                sportybet_winner_odds={"p1": 2.10, "draw": 1.0, "p2": None},
                sportybet_over_odds=None,
                sportybet_under_odds=None,
            ),
            NOW,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["sportybet_winner_odds"], {"p1": 2.10})


if __name__ == "__main__":
    unittest.main(verbosity=2)
