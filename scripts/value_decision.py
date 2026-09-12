import math


def american_to_decimal(odds):
    try:
        odds = float(odds)
        return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def edge_and_ev(model_prob, american_odds):
    try:
        p = float(model_prob)
    except (TypeError, ValueError):
        return None, None
    decimal = american_to_decimal(american_odds)
    if decimal is None:
        return None, None
    implied = 1.0 / decimal
    edge = p - implied
    ev = p * decimal - 1.0
    return round(edge, 6), round(ev, 6)


def decision(model_prob, american_odds=None, *, min_edge=0.035, min_ev=0.05, min_confidence=0.55, sample_ok=True, data_ok=True):
    """Conservative decision layer. Missing odds can never produce a live bet."""
    try:
        p = float(model_prob)
    except (TypeError, ValueError):
        return {"decision": "NO BET", "reason": "invalid_probability"}
    if not sample_ok:
        return {"decision": "PAPER ONLY", "reason": "insufficient_historical_support"}
    if not data_ok:
        return {"decision": "NO BET", "reason": "data_quality_gate"}
    if american_odds is None:
        return {"decision": "PAPER ONLY", "reason": "no_contemporaneous_odds"}
    edge, ev = edge_and_ev(p, american_odds)
    if edge is None or ev is None:
        return {"decision": "NO BET", "reason": "invalid_market_price"}
    if p < min_confidence:
        return {"decision": "NO BET", "reason": "low_probability", "edge": edge, "ev": ev}
    if edge < min_edge or ev < min_ev:
        return {"decision": "NO BET", "reason": "insufficient_value", "edge": edge, "ev": ev}
    return {"decision": "PAPER ONLY", "reason": "value_detected_but_live_gate_closed", "edge": edge, "ev": ev}
