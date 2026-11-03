#!/usr/bin/env python3
"""Contract tests for alternative domestic-history coverage."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_football_team_history import (
    SOFASCORE_TEAM_FALLBACKS,
    normalize_sofascore_domestic_event,
)


CUTOFF = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def event(event_id, home, away, home_score, away_score, country, league, day=20):
    dt = datetime(2026, 10, day, 12, 0, tzinfo=timezone.utc)
    return {
        "id": event_id,
        "startTimestamp": dt.timestamp(),
        "status": {"code": 100, "type": "finished"},
        "tournament": {"name": league, "category": {"name": country}},
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "homeScore": {"current": home_score},
        "awayScore": {"current": away_score},
    }


class DomesticFallbackTests(unittest.TestCase):
    def test_ukrainian_premier_league_event_is_normalized_with_provenance(self):
        row = normalize_sofascore_domestic_event(
            event(1, "Shakhtar Donetsk", "Dynamo Kyiv", 2, 1, "Ukraine", "Premier League"),
            "Shakhtar Donetsk",
            SOFASCORE_TEAM_FALLBACKS["Shakhtar Donetsk"],
            CUTOFF,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["league"], "Ukrainian Premier League")
        self.assertEqual(row["final_score"], [2.0, 1.0])
        self.assertIn("SofaScore", row["source"])

    def test_slovak_domestic_match_is_accepted_for_slovan(self):
        row = normalize_sofascore_domestic_event(
            event(2, "AS Trenčín", "ŠK Slovan Bratislava", 0, 2, "Slovakia", "Niké Liga"),
            "Slovan Bratislava",
            SOFASCORE_TEAM_FALLBACKS["Slovan Bratislava"],
            CUTOFF,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["league"], "Slovak Super Liga")

    def test_czech_domestic_match_is_accepted_for_slavia(self):
        row = normalize_sofascore_domestic_event(
            event(3, "SK Slavia Praha", "FK Jablonec", 5, 0, "Czechia", "Czech First League"),
            "Slavia Prague",
            SOFASCORE_TEAM_FALLBACKS["Slavia Prague"],
            CUTOFF,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["league"], "Czech First League")

    def test_azerbaijan_domestic_match_is_accepted_for_sabah(self):
        row = normalize_sofascore_domestic_event(
            event(4, "Turan Tovuz", "Sabah FK", 0, 2, "Azerbaijan", "Misli Premier League"),
            "Sabah FK",
            SOFASCORE_TEAM_FALLBACKS["Sabah FK"],
            CUTOFF,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["league"], "Azerbaijan Premier League")

    def test_champions_league_result_cannot_be_mislabelled_domestic(self):
        row = normalize_sofascore_domestic_event(
            event(5, "Shakhtar Donetsk", "Sporting CP", 1, 0, "Europe", "UEFA Champions League"),
            "Shakhtar Donetsk",
            SOFASCORE_TEAM_FALLBACKS["Shakhtar Donetsk"],
            CUTOFF,
        )
        self.assertIsNone(row)



    def test_curated_overrides_cover_all_missing_domestic_leagues_without_mixing_competitions(self):
        rows = json.loads((ROOT / "data" / "football_team_history_overrides.json").read_text(encoding="utf-8"))
        expected = {
            "Ukrainian Premier League": ("Shakhtar Donetsk",),
            "Slovak Super Liga": ("Slovan Bratislava",),
            "Czech First League": ("Slavia Prague",),
            "Azerbaijan Premier League": ("Sabah FK",),
        }
        for league, teams in expected.items():
            selected = [row for row in rows if row["league"] == league]
            self.assertGreaterEqual(len(selected), 4, f"insufficient {league} rows")
            self.assertTrue(all(row["settled"] is True and row["final_score"] for row in selected))
            self.assertTrue(all(row.get("source_url", "").startswith("https://") for row in selected))
            for team in teams:
                self.assertTrue(
                    any(team.casefold() in (r["player_1"] + " " + r["player_2"]).casefold() for r in selected),
                    f"{team} has no domestic result in {league}",
                )
            self.assertFalse(any("champions league" in row["league"].casefold() for row in selected))
            self.assertFalse(any("cup" in row["source"].casefold() for row in selected))
        keys = [(row["league"], row["event_id"]) for row in rows]
        self.assertEqual(len(keys), len(set(keys)), "override rows must have unique competition/event IDs")

    def test_unfinished_or_future_rows_are_rejected(self):
        unfinished = event(6, "Shakhtar Donetsk", "Dynamo Kyiv", 1, 0, "Ukraine", "Premier League")
        unfinished["status"] = {"code": 0, "type": "inprogress"}
        future = event(7, "Shakhtar Donetsk", "Dynamo Kyiv", 1, 0, "Ukraine", "Premier League", day=3)
        future["startTimestamp"] = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(normalize_sofascore_domestic_event(unfinished, "Shakhtar Donetsk", SOFASCORE_TEAM_FALLBACKS["Shakhtar Donetsk"], CUTOFF))
        self.assertIsNone(normalize_sofascore_domestic_event(future, "Shakhtar Donetsk", SOFASCORE_TEAM_FALLBACKS["Shakhtar Donetsk"], CUTOFF))


if __name__ == "__main__":
    unittest.main(verbosity=2)
