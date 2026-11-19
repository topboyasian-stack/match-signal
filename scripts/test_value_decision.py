#!/usr/bin/env python3
"""Regression for American versus decimal odds in Match Signal value math."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from value_decision import edge_and_ev, decision  # noqa: E402
from model_upgrade import valid_market  # noqa: E402


def close(actual, expected, tolerance=1e-6):
    assert actual is not None and abs(actual - expected) <= tolerance, (actual, expected)


def test_decimal_prices_are_not_treated_as_american():
    edge, ev = edge_and_ev(0.55, 2.0, odds_format="decimal")
    close(edge, 0.05)
    close(ev, 0.10)
    result = decision(0.55, 2.0, odds_format="decimal")
    assert result["decision"] == "PAPER ONLY"
    assert result["reason"] == "value_detected_but_live_gate_closed"
    close(result["edge"], 0.05)
    close(result["ev"], 0.10)


def test_american_default_remains_backward_compatible():
    assert edge_and_ev(0.55, 100) == edge_and_ev(0.55, 2.0, odds_format="decimal")
    edge, ev = edge_and_ev(0.55, -110)
    close(edge, 0.026190, 1e-5)
    close(ev, 0.05, 1e-5)


def test_decimal_sportybet_source_is_tagged_as_decimal():
    row = {
        "sport": "football",
        "sportybet_winner_odds": {"p1": 1.10, "draw": 11.79, "p2": 22.27},
    }
    market = valid_market(row)
    assert market is not None
    assert market["odds_format"] == "decimal"
    assert market["odds"] == [1.10, 11.79, 22.27]
    edge, ev = edge_and_ev(0.799181, market["odds"][0], odds_format=market["odds_format"])
    close(edge, 0.799181 - (1 / 1.10))
    close(ev, 0.799181 * 1.10 - 1)
    assert ev < 0


def test_legacy_espn_market_source_is_tagged_as_american():
    row = {
        "market_probabilities": {"p1": 0.55, "draw": 0.25, "p2": 0.20},
        "market_odds": [100, 250, 400],
        "market_source": "ESPN core bookmaker odds",
    }
    market = valid_market(row)
    assert market is not None
    assert market["odds_format"] == "american"
    assert edge_and_ev(0.55, market["odds"][0], odds_format=market["odds_format"]) == edge_and_ev(0.55, 100)


def test_unknown_or_invalid_decimal_prices_fail_closed():
    assert edge_and_ev(0.70, 1.0, odds_format="decimal") == (None, None)
    assert edge_and_ev(0.70, 2.0, odds_format="unknown") == (None, None)
    assert decision(0.70, 1.0, odds_format="decimal")["decision"] == "NO BET"


if __name__ == "__main__":
    test_decimal_prices_are_not_treated_as_american()
    test_american_default_remains_backward_compatible()
    test_decimal_sportybet_source_is_tagged_as_decimal()
    test_legacy_espn_market_source_is_tagged_as_american()
    test_unknown_or_invalid_decimal_prices_fail_closed()
    print("Explicit odds-format value math regressions passed.")
