"""Explicit, format-aware odds and value calculations.

The legacy default remains American odds for existing callers.
SportyBet prices are decimal and must pass odds_format="decimal".
"""
from __future__ import annotations


def american_to_decimal(odds):
    try:
        value = float(odds)
        if value == 0:
            return None
        return 1 + value / 100 if value > 0 else 1 + 100 / abs(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def decimal_odds(odds):
    """Validate and return decimal odds (> 1.0)."""
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


def to_decimal_odds(odds, odds_format="american"):
    """Convert a declared input price; never infer a format from its magnitude."""
    if odds_format == "decimal":
        return decimal_odds(odds)
    if odds_format == "american":
        return american_to_decimal(odds)
    return None


def edge_and_ev(model_prob, odds, *, odds_format="american"):
    """Return probability edge and expected return per unit for one selection."""
    try:
        probability = float(model_prob)
    except (TypeError, ValueError):
        return None, None
    if not 0.0 <= probability <= 1.0:
        return None, None
    decimal = to_decimal_odds(odds, odds_format=odds_format)
    if decimal is None:
        return None, None
    implied = 1.0 / decimal
    return round(probability - implied, 6), round(probability * decimal - 1.0, 6)


def decision(
    model_prob,
    odds=None,
    *,
    odds_format="american",
    min_edge=0.035,
    min_ev=0.05,
    min_confidence=0.55,
    sample_ok=True,
    data_ok=True,
):
    """Value-first decision layer. Live eligibility remains separately gated."""
    try:
        probability = float(model_prob)
    except (TypeError, ValueError):
        return {"decision": "NO BET", "reason": "invalid_probability"}
    if not 0.0 <= probability <= 1.0:
        return {"decision": "NO BET", "reason": "invalid_probability"}
    if not data_ok:
        return {"decision": "NO BET", "reason": "data_quality_gate"}
    if odds is None:
        return {"decision": "PAPER ONLY", "reason": "no_contemporaneous_odds"}
    edge, expected_value = edge_and_ev(probability, odds, odds_format=odds_format)
    if edge is None or expected_value is None:
        return {"decision": "NO BET", "reason": "invalid_market_price"}
    if probability < min_confidence:
        return {"decision": "NO BET", "reason": "low_probability", "edge": edge, "ev": expected_value}
    if edge < min_edge or expected_value < min_ev:
        return {"decision": "NO BET", "reason": "insufficient_value", "edge": edge, "ev": expected_value}
    return {
        "decision": "PAPER ONLY",
        "reason": "value_detected_but_live_gate_closed",
        "edge": edge,
        "ev": expected_value,
    }
