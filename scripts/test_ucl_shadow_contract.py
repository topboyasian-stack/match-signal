#!/usr/bin/env python3
"""A weak UCL research model must never overwrite the published prediction."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_upgrade import MODEL_VERSION, _record_ucl_shadow_fields


class UCLShadowContractTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "sport": "football",
            "league": "Champions League",
            "pick": "p2",
            "probabilities": {"p1": 0.30, "draw": 0.25, "p2": 0.45},
            "raw_probabilities": {"p1": 0.31, "draw": 0.24, "p2": 0.45},
            "calibrated_probabilities": {"p1": 0.30, "draw": 0.25, "p2": 0.45},
            "confidence": 0.45,
            "decision": "PAPER ONLY",
            "decision_reason": "published_model_reason",
            "market_probabilities": {"p1": 0.35, "draw": 0.30, "p2": 0.35},
            "market_odds": [2.8, 3.2, 2.9],
            "edge": 0.02,
            "value": {"expected_value": 0.01},
            "model": "published model",
            "model_version": "published-v1",
            "expected_goals": {"p1": 1.4, "p2": 1.1},
            "betting_qualified": False,
            "qualified_for_builder": False,
            "builder_eligible": False,
            "live_eligible": False,
        }
        self.original = copy.deepcopy(self.row)
        self.independent = {
            "p1": 0.62,
            "draw": 0.22,
            "p2": 0.16,
            "xg_home": 2.1,
            "xg_away": 0.8,
            "sample_home": 8.0,
            "sample_away": 7.0,
            "effective_sample": 6.0,
            "method": "domestic + Champions League form, venue-aware Poisson/Dixon-Coles",
            "competition_form": {
                "mode": "domestic_plus_champions_league",
                "home": {"domestic_competition": "Premier League"},
                "away": {"domestic_competition": "Bundesliga"},
            },
            "competition_form_status": "COMPLETE",
        }
        self.market = {
            "p1": 0.35,
            "draw": 0.30,
            "p2": 0.35,
            "odds": [2.8, 3.2, 2.9],
            "source": "SportyBet NG de-vig current market",
        }

    def assert_published_contract_unchanged(self):
        for key in (
            "pick",
            "probabilities",
            "raw_probabilities",
            "calibrated_probabilities",
            "confidence",
            "decision",
            "decision_reason",
            "market_probabilities",
            "market_odds",
            "edge",
            "value",
            "model",
            "model_version",
            "expected_goals",
            "betting_qualified",
            "qualified_for_builder",
            "builder_eligible",
        ):
            self.assertEqual(self.row.get(key), self.original.get(key), key)

    def test_complete_dual_competition_model_is_research_shadow_only(self):
        _record_ucl_shadow_fields(
            self.row, self.independent, [0.62, 0.22, 0.16], self.market, {"version": "test"}
        )
        self.assert_published_contract_unchanged()
        self.assertEqual(self.row["independent_shadow_model_version"], MODEL_VERSION)
        self.assertEqual(self.row["independent_shadow_pick"], "p1")
        self.assertEqual(self.row["independent_shadow_status"], "COMPLETE")
        self.assertTrue(self.row["independent_shadow_history_complete"])
        self.assertFalse(self.row["independent_shadow_use_for_tickets"])
        self.assertEqual(self.row["independent_shadow_promotion_status"], "NOT_PROMOTED")
        self.assertEqual(
            self.row["independent_competition_form"]["mode"],
            "domestic_plus_champions_league",
        )

    def test_partial_history_is_marked_without_changing_published_pick(self):
        self.independent["competition_form_status"] = "PARTIAL_HISTORY"
        self.independent["competition_form"]["status"] = "PARTIAL_HISTORY"
        _record_ucl_shadow_fields(
            self.row, self.independent, [0.62, 0.22, 0.16], None, {"version": "test"}
        )
        self.assert_published_contract_unchanged()
        self.assertEqual(self.row["independent_shadow_status"], "PARTIAL_HISTORY")
        self.assertFalse(self.row["independent_shadow_history_complete"])
        self.assertFalse(self.row["independent_shadow_use_for_tickets"])
        self.assertIsNone(self.row["independent_shadow_market"])

    def test_shadow_fields_do_not_set_active_ticket_eligibility(self):
        _record_ucl_shadow_fields(
            self.row, self.independent, [0.62, 0.22, 0.16], self.market, {"version": "test"}
        )
        self.assertFalse(self.row["betting_qualified"])
        self.assertFalse(self.row["qualified_for_builder"])
        self.assertFalse(self.row["builder_eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
