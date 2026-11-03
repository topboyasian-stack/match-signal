#!/usr/bin/env python3
"""Regression tests for separate domestic and Champions League form."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from independent_football_model import (
    _team_key,
    independent_prediction,
)


CUTOFF = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def game(comp, event_id, home, away, home_score, away_score, days_ago):
    dt = CUTOFF - timedelta(days=days_ago)
    return {
        "sport": "football",
        "league": comp,
        "event_id": str(event_id),
        "start_time": dt.isoformat(),
        "calculated_at": dt.isoformat(),
        "player_1": home,
        "player_2": away,
        "final_score": [home_score, away_score],
        "settled": True,
    }


def fixture(home="Arsenal", away="Bayern Munich"):
    return {
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home}},
                {"homeAway": "away", "team": {"displayName": away}},
            ]
        }]
    }


def sample_history():
    rows = []
    # League baselines are populated independently of the two target clubs.
    for i in range(12):
        rows.append(game("Premier League", f"pl-base-{i}", f"PL Home {i}", f"PL Away {i}", 2, 1, 8 + i))
        rows.append(game("Bundesliga", f"de-base-{i}", f"DE Home {i}", f"DE Away {i}", 2, 1, 8 + i))
        rows.append(game("Champions League", f"ucl-base-{i}", f"UCL Home {i}", f"UCL Away {i}", 1, 1, 8 + i))
    # Domestic home/away form for the two clubs, from their own leagues.
    for i in range(6):
        rows.append(game("Premier League", f"ars-pl-{i}", "Arsenal", f"PL Opponent {i}", 3, 0, 12 + i * 8))
        rows.append(game("Bundesliga", f"bay-de-{i}", f"DE Opponent {i}", "Bayern Munich", 1, 2, 14 + i * 8))
    # Separate Champions League venue records.
    for i in range(3):
        rows.append(game("Champions League", f"ars-ucl-{i}", "Arsenal", f"UCL Rival A{i}", 3, 0, 22 + i * 10))
        rows.append(game("Champions League", f"bay-ucl-{i}", f"UCL Rival B{i}", "Bayern Munich", 2, 1, 24 + i * 10))
    return rows


class UCLDualCompetitionModelTests(unittest.TestCase):
    def predict(self, history, league="Champions League"):
        return independent_prediction(
            fixture(),
            league,
            history,
            cutoff=CUTOFF.isoformat(),
        )

    def test_ucl_prediction_reports_both_competitions_and_venue_samples(self):
        result = self.predict(sample_history())
        form = result["competition_form"]
        self.assertEqual(form["mode"], "domestic_plus_champions_league")
        self.assertEqual(form["status"], "COMPLETE")
        self.assertTrue(form["release_eligible"])
        self.assertEqual(form["home"]["domestic_competition"], "Premier League")
        self.assertEqual(form["away"]["domestic_competition"], "Bundesliga")
        self.assertGreater(form["home"]["domestic_venue_sample"], 2)
        self.assertGreater(form["away"]["domestic_venue_sample"], 2)
        self.assertGreater(form["home"]["champions_league_venue_sample"], 1)
        self.assertGreater(form["away"]["champions_league_venue_sample"], 1)
        self.assertGreater(form["home"]["champions_league_blend_weight"], 0)
        self.assertGreater(form["away"]["champions_league_blend_weight"], 0)
        self.assertLessEqual(form["home"]["champions_league_blend_weight"], 0.30)
        self.assertLessEqual(form["away"]["champions_league_blend_weight"], 0.30)
        self.assertAlmostEqual(result["p1"] + result["draw"] + result["p2"], 1.0, places=5)

    def test_ucl_results_change_ucl_prediction(self):
        history = sample_history()
        base = self.predict(history)
        changed = []
        for row in history:
            item = dict(row)
            if item["league"] == "Champions League" and item["player_1"] == "Arsenal":
                item["final_score"] = [0, 3]
            if item["league"] == "Champions League" and item["player_2"] == "Bayern Munich":
                item["final_score"] = [0, 3]
            changed.append(item)
        altered = self.predict(changed)
        self.assertNotAlmostEqual(base["xg_home"], altered["xg_home"], places=3)
        self.assertNotAlmostEqual(base["xg_away"], altered["xg_away"], places=3)

    def test_domestic_results_change_ucl_prediction(self):
        history = sample_history()
        base = self.predict(history)
        changed = []
        for row in history:
            item = dict(row)
            if item["league"] == "Premier League" and item["player_1"] == "Arsenal":
                item["final_score"] = [0, 3]
            if item["league"] == "Bundesliga" and item["player_2"] == "Bayern Munich":
                item["final_score"] = [3, 0]
            changed.append(item)
        altered = self.predict(changed)
        self.assertNotAlmostEqual(base["xg_home"], altered["xg_home"], places=3)
        self.assertNotAlmostEqual(base["xg_away"], altered["xg_away"], places=3)

    def test_domestic_prediction_does_not_mix_in_champions_league_results(self):
        history = sample_history()
        with_ucl = independent_prediction(
            fixture(), "Premier League", history, cutoff=CUTOFF.isoformat()
        )
        domestic_only = independent_prediction(
            fixture(), "Premier League",
            [row for row in history if row["league"] == "Premier League"],
            cutoff=CUTOFF.isoformat(),
        )
        self.assertAlmostEqual(with_ucl["xg_home"], domestic_only["xg_home"], places=6)
        self.assertAlmostEqual(with_ucl["xg_away"], domestic_only["xg_away"], places=6)

    def test_future_and_cutoff_time_results_are_never_used(self):
        history = sample_history()
        baseline = self.predict(history)
        future = game("Champions League", "ucl-future", "Arsenal", "Bayern Munich", 9, 0, -1)
        exact_cutoff = {
            **game("Champions League", "ucl-at-cutoff", "Arsenal", "Bayern Munich", 9, 0, 0),
            "start_time": CUTOFF.isoformat(),
            "calculated_at": CUTOFF.isoformat(),
        }
        extended = self.predict(history + [future, exact_cutoff])
        self.assertEqual(baseline["competition_form"], extended["competition_form"])
        self.assertAlmostEqual(baseline["xg_home"], extended["xg_home"], places=6)
        self.assertAlmostEqual(baseline["xg_away"], extended["xg_away"], places=6)

    def test_club_aliases_join_the_same_domestic_and_ucl_history(self):
        self.assertEqual(_team_key("Internazionale"), _team_key("Inter Milano"))
        self.assertEqual(_team_key("FC Barcelona"), _team_key("Barcelona"))
        self.assertEqual(_team_key("Villarreal CF"), _team_key("Villarreal"))

    def test_missing_domestic_or_ucl_history_is_marked_partial(self):
        history = [
            row for row in sample_history()
            if not (row["league"] == "Premier League" and row["player_1"] == "Arsenal")
        ]
        result = self.predict(history)
        self.assertEqual(result["competition_form_status"], "PARTIAL_HISTORY")
        self.assertFalse(result["competition_form"]["release_eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
