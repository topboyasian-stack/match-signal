"""Private-facing ML probability primitives for Match Signal.
No credentials, vendor payloads, raw odds, or frontend logic belong here.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Iterable, Sequence


def clamp_probability(p: float, eps: float = 1e-6) -> float:
    return max(eps, min(1.0 - eps, float(p)))


def brier_binary(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    if len(y_true) != len(probabilities):
        raise ValueError("y_true and probabilities must have the same length")
    if not y_true:
        return 0.0
    return sum((float(p) - int(y)) ** 2 for y, p in zip(y_true, probabilities)) / len(y_true)


def log_loss_binary(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    if len(y_true) != len(probabilities):
        raise ValueError("y_true and probabilities must have the same length")
    if not y_true:
        return 0.0
    total = 0.0
    for y, p in zip(y_true, probabilities):
        p = clamp_probability(p)
        total += -(int(y) * math.log(p) + (1 - int(y)) * math.log(1 - p))
    return total / len(y_true)


def brier_multiclass(rows: Sequence[dict], outcome_keys: Sequence[str] = ("p1", "draw", "p2")) -> float | None:
    """Multiclass Brier score using the complete probability vector.

    This avoids the old error of scoring only the probability of the outcome
    that happened, which always labels that probability as y=1 and is not a
    valid full-match evaluation.
    """
    scores = []
    keys = tuple(outcome_keys)
    for row in rows:
        if not row.get("settled"):
            continue
        actual = row.get("actual")
        probs = row.get("probabilities") or {}
        if actual not in keys or any(probs.get(k) is None for k in keys):
            continue
        try:
            vector = [float(probs[k]) for k in keys]
        except (TypeError, ValueError):
            continue
        if any(p < 0 or p > 1 for p in vector) or abs(sum(vector) - 1.0) > 0.02:
            continue
        scores.append(sum((p - (1.0 if k == actual else 0.0)) ** 2 for k, p in zip(keys, vector)))
    return sum(scores) / len(scores) if scores else None


def log_loss_multiclass(rows: Sequence[dict], outcome_keys: Sequence[str] = ("p1", "draw", "p2")) -> float | None:
    """Multiclass log loss from the probability assigned to the actual class."""
    losses = []
    keys = tuple(outcome_keys)
    for row in rows:
        if not row.get("settled"):
            continue
        actual = row.get("actual")
        probs = row.get("probabilities") or {}
        if actual not in keys or probs.get(actual) is None:
            continue
        try:
            losses.append(-math.log(clamp_probability(float(probs[actual]))))
        except (TypeError, ValueError):
            continue
    return sum(losses) / len(losses) if losses else None


def chronological_split(rows: Sequence[dict], holdout_fraction: float = 0.2):
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between 0 and 1")
    ordered = sorted(rows, key=lambda r: str(r.get("start_time") or r.get("calculated_at") or ""))
    cut = max(1, int(len(ordered) * (1 - holdout_fraction))) if ordered else 0
    return ordered[:cut], ordered[cut:]


@dataclass(frozen=True)
class ModelProbability:
    probability: float
    source: str
    sample_size: int = 0
    calibrated: bool = False


def ensemble_probability(models: Iterable[ModelProbability], weights: Iterable[float] | None = None) -> float:
    items = list(models)
    if not items:
        raise ValueError("at least one probability model is required")
    ws = list(weights) if weights is not None else [1.0] * len(items)
    if len(ws) != len(items):
        raise ValueError("weights must match models")
    total = sum(max(0.0, float(w)) for w in ws)
    if total <= 0:
        total = float(len(items))
        ws = [1.0] * len(items)
    return clamp_probability(sum(clamp_probability(m.probability) * max(0.0, float(w)) for m, w in zip(items, ws)) / total)


def disagreement(models: Iterable[ModelProbability]) -> float:
    values = [clamp_probability(m.probability) for m in models]
    return max(values) - min(values) if values else 0.0


def calibration_bucket(probability: float) -> str:
    p = clamp_probability(probability)
    return "low" if p < 0.55 else "moderate" if p < 0.65 else "strong" if p < 0.75 else "high"


def evaluate_binary(rows: Sequence[dict]) -> dict:
    """Backward-compatible binary evaluation for explicitly binary rows only.

    Football 1X2 rows must use evaluate_multiclass instead; treating every
    actual p1/p2 outcome as y=1 is mathematically invalid.
    """
    y = []
    p = []
    for row in rows:
        if not row.get("settled") or row.get("actual") not in {0, 1}:
            continue
        probs = row.get("probabilities") or {}
        probability = probs.get("positive") if isinstance(probs, dict) else None
        if probability is None:
            probability = row.get("probability")
        if probability is None:
            continue
        try:
            y.append(int(row["actual"]))
            p.append(float(probability))
        except (TypeError, ValueError):
            continue
    return {
        "sample_size": len(p),
        "brier": round(brier_binary(y, p), 6) if p else None,
        "log_loss": round(log_loss_binary(y, p), 6) if p else None,
    }


def evaluate_multiclass(rows: Sequence[dict], outcome_keys: Sequence[str] = ("p1", "draw", "p2")) -> dict:
    sample = sum(
        1
        for row in rows
        if row.get("settled")
        and row.get("actual") in outcome_keys
        and all((row.get("probabilities") or {}).get(k) is not None for k in outcome_keys)
    )
    brier = brier_multiclass(rows, outcome_keys)
    log_loss = log_loss_multiclass(rows, outcome_keys)
    return {
        "sample_size": sample,
        "outcomes": list(outcome_keys),
        "brier": round(brier, 6) if brier is not None else None,
        "log_loss": round(log_loss, 6) if log_loss is not None else None,
    }
