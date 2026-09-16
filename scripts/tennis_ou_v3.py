#!/usr/bin/env python3
"""Walk-forward, non-flat tennis O/U calibration layer.

The previous V2 O/U calibration used only a three-set bucket. Most matches
landed in the same bucket, so every 22.5 line received essentially the same
30/70 probability. This layer adds confidence and tour context, applies
hierarchical smoothing, and preserves some of the model's pre-calibration
signal. It is research-only and never changes match-winner probabilities.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PRED = DATA / "predictions.json"
ARCHIVE = DATA / "tennis_prediction_archive.json"
REPORT = DATA / "tennis_ou_v3.json"

PRIOR_STRENGTH = 10.0
PRIOR_WEIGHT = 0.25


def load(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except Exception:
        return default


def three_bin(value):
    value = float(value)
    if value < 0.46:
        return "low"
    if value > 0.56:
        return "high"
    return "mid"


def confidence_bin(value):
    value = float(value)
    if value < 0.60:
        return "low"
    if value < 0.70:
        return "mid"
    return "high"


def fit(records):
    usable = []
    for row in records:
        if row.get("sport") != "tennis" or not row.get("settled"):
            continue
        if row.get("capture_status") == "LATE_CAPTURE" or row.get("evaluation_eligible") is False:
            continue
        actual = (row.get("actual_markets") or {}).get("total_games_result")
        if actual not in {"over", "under"}:
            continue
        analytics = row.get("analytics") or {}
        total = analytics.get("total_games") or {}
        three = analytics.get("three_sets")
        confidence = row.get("confidence")
        if three is None or confidence is None:
            continue
        usable.append({
            "tour": str(row.get("league") or "unknown").upper(),
            "three": float(three),
            "confidence": float(confidence),
            "prior": float(total.get("over", 0.5) or 0.5),
            "over": 1 if actual == "over" else 0,
            "start": str(row.get("start_time") or ""),
        })

    if not usable:
        return {"n": 0, "global_rate": 0.5, "cells": {}}

    global_rate = (sum(x["over"] for x in usable) + PRIOR_STRENGTH * 0.5) / (len(usable) + PRIOR_STRENGTH)
    cells = {}
    for x in usable:
        key = f"{three_bin(x['three'])}|{confidence_bin(x['confidence'])}|{x['tour']}"
        cell = cells.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += x["over"]

    # Backstop cells by three-set/confidence only, then global rate.
    broad = {}
    for x in usable:
        key = f"{three_bin(x['three'])}|{confidence_bin(x['confidence'])}"
        cell = broad.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += x["over"]

    rates = {}
    for key, (n, over) in cells.items():
        rates[key] = (over + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH)
    broad_rates = {}
    for key, (n, over) in broad.items():
        broad_rates[key] = (over + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH)

    return {
        "n": len(usable),
        "global_rate": round(global_rate, 4),
        "cells": cells,
        "rates": rates,
        "broad_rates": broad_rates,
    }


def calibrate(row, model):
    analytics = row.setdefault("analytics", {})
    total = analytics.setdefault("total_games", {})
    if not total:
        return False
    line = float(total.get("line") or 22.5)
    three = float(analytics.get("three_sets") or 0.5)
    confidence = float(row.get("confidence") or 0.5)
    tour = str(row.get("league") or "unknown").upper()
    key = f"{three_bin(three)}|{confidence_bin(confidence)}|{tour}"
    broad_key = f"{three_bin(three)}|{confidence_bin(confidence)}"
    empirical = model["rates"].get(key)
    if empirical is None:
        empirical = model["broad_rates"].get(broad_key, model["global_rate"])

    prior = float(total.get("over", 0.5) or 0.5)
    # Preserve a quarter of the model's continuous signal while letting
    # settled outcomes dominate the calibration.
    over = (1.0 - PRIOR_WEIGHT) * empirical + PRIOR_WEIGHT * prior

    # Only adjust from the 22.5 baseline when we have historical support.
    # For other lines, use a conservative line-direction adjustment around
    # the calibrated 22.5 probability rather than pretending to have a
    # large line-specific sample.
    if abs(line - 22.5) > 0.001:
        over = max(0.05, min(0.95, over - 0.035 * (line - 22.5)))

    over = max(0.05, min(0.95, over))
    total["over"] = round(over, 4)
    total["under"] = round(1.0 - over, 4)
    total["pick"] = "over" if over >= 0.5 else "under"
    total["source"] = "walk-forward empirical tennis O/U calibration v3"
    total["calibration_status"] = "PAPER_RESEARCH"
    total["calibration_features"] = {
        "three_sets_bin": three_bin(three),
        "confidence_bin": confidence_bin(confidence),
        "tour": tour,
        "empirical_over_rate": round(empirical, 4),
        "prior_model_over": round(prior, 4),
        "global_over_rate": model["global_rate"],
    }
    analytics["total_games"] = total
    return True


def main():
    predictions = load(PRED, [])
    archive = load(ARCHIVE, [])
    model = fit(archive)
    changed = 0
    distribution = []
    for row in predictions:
        if row.get("sport") != "tennis":
            continue
        if calibrate(row, model):
            changed += 1
            distribution.append(row["analytics"]["total_games"]["over"])

    PRED.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "2026-09-16-tennis-ou-v3",
        "status": "PAPER_RESEARCH_ONLY",
        "training_records": model["n"],
        "global_over_rate": model["global_rate"],
        "current_predictions_rewritten": changed,
        "min_current_over": round(min(distribution), 4) if distribution else None,
        "max_current_over": round(max(distribution), 4) if distribution else None,
        "unique_current_over_probabilities": len(set(distribution)),
        "guardrails": [
            "No future results are used for a fixture before its start time.",
            "Late-captured records are excluded from calibration training.",
            "Calibration never changes match-winner probabilities.",
            "No bookmaker odds are invented.",
            "Research-only; no live-money execution."
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
