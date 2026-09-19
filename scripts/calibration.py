"""Historical probability calibration for Match Signal.

Calibration is strictly pre-event: only settled predictions already present in
prediction_history.json are used to transform a new prediction.  It is
market-specific, recency-weighted, and shrunk toward the model probability so
small samples cannot create extreme probabilities.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


HALF_LIFE_DAYS = 45.0
MIN_OBS_FOR_STRONG_CALIBRATION = 25
SHRINKAGE_PRIOR = 30.0
BIN_WIDTH = 0.05
NEIGHBOR_RADIUS = 0.10

# V5 production refresh trigger: calibration changes must regenerate the live feed.


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_weight(settled_at, now):
    dt = _parse_date(settled_at)
    if not dt:
        return 0.65
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _market_key(prediction):
    sport = prediction.get("sport")
    if sport == "football":
        return "football:1x2"
    if sport == "tennis":
        total = (prediction.get("analytics") or {}).get("total_games") or {}
        if total.get("pick") in {"over", "under"}:
            return "tennis:total_games"
        return "tennis:winner"
    return f"{sport or 'unknown'}:winner"


def _outcome_for_market(prediction):
    if prediction.get("sport") == "tennis":
        total = (prediction.get("analytics") or {}).get("total_games") or {}
        if total.get("pick") in {"over", "under"}:
            actual = (prediction.get("actual_markets") or {}).get("total_games_result")
            return actual == total.get("pick")
    return prediction.get("correct") is True


def _bin_center(probability):
    p = max(0.01, min(0.99, float(probability)))
    return round((math.floor(p / BIN_WIDTH) + 0.5) * BIN_WIDTH, 3)


def _observations(history, market_key, now):
    rows = []
    for item in history:
        if not isinstance(item, dict) or not item.get("settled"):
            continue
        if _market_key(item) != market_key:
            continue
        probs = item.get("probabilities") or {}
        pick = item.get("pick")
        try:
            raw = float(probs.get(pick))
        except (TypeError, ValueError):
            continue
        if not 0.01 <= raw <= 0.99:
            continue
        rows.append((raw, 1.0 if _outcome_for_market(item) else 0.0, _age_weight(item.get("settled_at"), now)))
    return rows


def calibrate_probability(raw_probability, history, market_key, now=None):
    """Return (calibrated_probability, diagnostics).

    Uses nearby historical probabilities with recency weighting and empirical
    Bayes shrinkage.  The current prediction is never included in its own fit.
    """
    now = now or datetime.now(timezone.utc)
    raw = max(0.01, min(0.99, float(raw_probability)))
    observations = _observations(history, market_key, now)
    if not observations:
        return raw, {"method": "raw_no_history", "sample_size": 0, "empirical": raw}

    nearby = []
    for observed_p, outcome, recency in observations:
        distance = abs(observed_p - raw)
        if distance <= NEIGHBOR_RADIUS:
            proximity = max(0.0, 1.0 - distance / NEIGHBOR_RADIUS)
            nearby.append((outcome, recency * (0.25 + 0.75 * proximity)))

    # Fall back to all observations when a narrow confidence region is sparse.
    pool = nearby if sum(w for _, w in nearby) >= 8.0 else [
        (outcome, recency * math.exp(-abs(observed_p - raw) / 0.12))
        for observed_p, outcome, recency in observations
    ]

    weight_sum = sum(weight for _, weight in pool)
    success_weight = sum(outcome * weight for outcome, weight in pool)
    empirical = success_weight / weight_sum if weight_sum else raw
    effective_n = min(len(observations), weight_sum)

    # Strong evidence should move the probability; sparse evidence stays close
    # to the raw model. This prevents a handful of old matches from dominating.
    calibrated = (effective_n * empirical + SHRINKAGE_PRIOR * raw) / (effective_n + SHRINKAGE_PRIOR)
    calibrated = max(0.02, min(0.98, calibrated))

    return calibrated, {
        "method": "recency_weighted_empirical_bayes",
        "sample_size": len(observations),
        "effective_sample": round(effective_n, 2),
        "empirical": round(empirical, 4),
        "raw": round(raw, 4),
        "bin_center": _bin_center(raw),
    }


def calibrate_prediction(prediction, history, now=None):
    now = now or datetime.now(timezone.utc)
    market_key = _market_key(prediction)
    probs = dict(prediction.get("probabilities") or {})
    pick = prediction.get("pick")
    try:
        raw_pick = float(probs.get(pick))
    except (TypeError, ValueError):
        return prediction

    calibrated_pick, diagnostics = calibrate_probability(raw_pick, history, market_key, now)
    calibrated = dict(probs)

    # Calibration must never silently invert the selected outcome. The pick is
    # a deliberate model decision, so if historical calibration would move it
    # below another outcome, cap the downward adjustment at the strongest
    # non-selected raw probability (with a tiny margin for strict ordering).
    other_raw_max = max(
        (float(value) for key, value in probs.items() if key != pick),
        default=0.0,
    )
    selection_floor = min(0.98, other_raw_max + 0.001)
    if calibrated_pick < selection_floor:
        calibrated_pick = selection_floor
        diagnostics = {
            **diagnostics,
            "selection_identity_preserved": True,
            "selection_floor": round(selection_floor, 4),
        }

    # Preserve the relative probabilities of the non-selected outcomes while
    # moving the selected outcome to its empirically calibrated confidence.
    remainder_raw = max(1e-9, 1.0 - raw_pick)
    remainder_new = 1.0 - calibrated_pick
    for key, value in probs.items():
        if key == pick:
            calibrated[key] = round(calibrated_pick, 4)
        else:
            calibrated[key] = round(max(0.0, float(value)) / remainder_raw * remainder_new, 4)

    # Re-normalize after rounding.
    total = sum(calibrated.values())
    if total:
        calibrated = {key: round(value / total, 4) for key, value in calibrated.items()}

    prediction["raw_probabilities"] = {key: round(float(value), 4) for key, value in probs.items()}
    prediction["raw_confidence"] = round(raw_pick, 4)
    prediction["calibrated_probabilities"] = calibrated
    prediction["calibrated_confidence"] = round(calibrated_pick, 4)
    prediction["calibration"] = {
        "market": market_key,
        **diagnostics,
    }
    prediction["probabilities"] = calibrated
    prediction["confidence"] = round(calibrated_pick, 4)
    prediction["pick"] = pick
    prediction["model_version"] = "5.0 historical-calibrated"
    return prediction


def calibrate_binary_market(prediction, raw_probability, history, market_key, now=None):
    """Calibrate a binary market such as tennis Total Games."""
    now = now or datetime.now(timezone.utc)
    calibrated, diagnostics = calibrate_probability(raw_probability, history, market_key, now)
    return calibrated, diagnostics
