"""Private-facing EV calculation primitives.

This module deliberately contains no provider credentials and emits only derived
signal data. Keep provider adapters, credentials, feature stores, and calibrated
model weights out of the public frontend.
"""
from __future__ import annotations

import math
from typing import Dict, Optional


def clamp(p: float, lo: float = 1e-6, hi: float = 1 - 1e-6) -> float:
    return max(lo, min(hi, float(p)))


def devig(probabilities: Dict[str, float]) -> Dict[str, float]:
    vals = {k: max(1e-9, float(v)) for k, v in probabilities.items()}
    total = sum(vals.values())
    return {k: v / total for k, v in vals.items()}


def decimal_to_implied(decimal_odds: float) -> float:
    odds = float(decimal_odds)
    if odds <= 1.0:
        raise ValueError("decimal odds must be > 1")
    return 1.0 / odds


def fair_odds(probability: float) -> Optional[float]:
    p = clamp(probability)
    return round(1.0 / p, 4)


def expected_value(probability: float, decimal_odds: float) -> float:
    """Unit-stake expected return: P(win)*odds - 1."""
    return clamp(probability) * float(decimal_odds) - 1.0


def signal(probability: float, decimal_odds: float, min_ev: float = 0.05,
           min_edge: float = 0.03) -> dict:
    p = clamp(probability)
    odds = float(decimal_odds)
    implied = decimal_to_implied(odds)
    ev = expected_value(p, odds)
    edge = p - implied
    return {
        "model_probability": round(p, 6),
        "market_implied_probability": round(implied, 6),
        "fair_odds": fair_odds(p),
        "decimal_odds": round(odds, 4),
        "edge": round(edge, 6),
        "ev": round(ev, 6),
        "ev_percent": round(ev * 100.0, 3),
        "qualifies": bool(ev >= min_ev and edge >= min_edge),
        "status": "PAPER_VALUE" if ev >= min_ev and edge >= min_edge else "NO_VALUE",
    }


def build_market_signal(event_id: str, sport: str, league: str, market: str,
                        selection: str, model_probability: float,
                        decimal_odds: Optional[float], source: str,
                        model_version: str = "ms-ev-v1") -> dict:
    base = {
        "event_id": str(event_id),
        "sport": sport,
        "league": league,
        "market": market,
        "selection": selection,
        "source": source,
        "model_version": model_version,
        "paper_only": True,
    }
    if decimal_odds is None:
        base.update({
            "status": "NO_CURRENT_ODDS",
            "qualifies": False,
            "model_probability": round(clamp(model_probability), 6),
        })
        return base
    base.update(signal(model_probability, decimal_odds))
    return base
