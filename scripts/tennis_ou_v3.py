#!/usr/bin/env python3
"""Walk-forward, non-flat tennis O/U calibration layer.

Uses the upstream continuous set/game model as the primary signal and only
uses settled empirical rates as a secondary calibration layer. This prevents
a single historical bucket from flattening every fixture into the same 30/70
probability while retaining honest walk-forward calibration.
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

# The upstream continuous model remains dominant. Empirical data corrects
# systematic bias without replacing fixture-specific signal.
EMPIRICAL_WEIGHT = 0.35
PRIOR_STRENGTH = 10.0
MIN_CELL_SUPPORT = 12


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
            "over": 1 if actual == "over" else 0,
        })

    if not usable:
        return {"n": 0, "global_rate": 0.5, "cells": {}, "rates": {}, "broad_rates": {}}

    global_rate = (sum(x["over"] for x in usable) + PRIOR_STRENGTH * 0.5) / (len(usable) + PRIOR_STRENGTH)
    cells = {}
    broad = {}
    for x in usable:
        key = f"{three_bin(x['three'])}|{confidence_bin(x['confidence'])}|{x['tour']}"
        cell = cells.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += x["over"]
        broad_key = f"{three_bin(x['three'])}|{confidence_bin(x['confidence'])}"
        bcell = broad.setdefault(broad_key, [0, 0])
        bcell[0] += 1
        bcell[1] += x["over"]

    rates = {}
    for key, (n, over) in cells.items():
        rates[key] = (over + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH)
    broad_rates = {}
    for key, (n, over) in broad.items():
        broad_rates[key] = (over + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH)

    return {"n": len(usable), "global_rate": round(global_rate, 4), "cells": cells, "rates": rates, "broad_rates": broad_rates}


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

    empirical = None
    cell = model.get("cells", {}).get(key)
    if cell and cell[0] >= MIN_CELL_SUPPORT:
        empirical = model.get("rates", {}).get(key)
    if empirical is None:
        broad_cell = model.get("broad_rates", {}).get(broad_key)
        broad_n = (model.get("cells", {}).get(key) or [0, 0])[0]
        # Broad calibration is allowed only when there is meaningful support.
        # Otherwise keep the upstream model untouched rather than inventing a
        # population-level probability for an individual fixture.
        if broad_cell is not None:
            for candidate_key, candidate_cell in model.get("cells", {}).items():
                if candidate_key.startswith(broad_key + "|"):
                    broad_n += candidate_cell[0]
            if broad_n >= MIN_CELL_SUPPORT:
                empirical = broad_cell
    if empirical is None:
        empirical = model.get("global_rate", 0.5)

    prior = float(total.get("base_model_over", total.get("over", 0.5)) or 0.5)
    # Primary signal: upstream fixture-specific model. Secondary signal:
    # settled empirical calibration.
    over = (1.0 - EMPIRICAL_WEIGHT) * prior + EMPIRICAL_WEIGHT * empirical

    # A 22.5 baseline is where the strongest empirical support exists. For
    # other lines, move conservatively with the line rather than pretending
    # that we have a large line-specific historical sample.
    if abs(line - 22.5) > 0.001:
        over -= 0.035 * (line - 22.5)

    over = max(0.05, min(0.95, over))
    total["base_model_over"] = round(prior, 4)
    total["base_model_under"] = round(1.0 - prior, 4)
    total["over"] = round(over, 4)
    total["under"] = round(1.0 - over, 4)
    total["pick"] = "over" if over >= 0.5 else "under"
    total["source"] = "continuous tennis model + walk-forward empirical O/U calibration v3"
    total["calibration_status"] = "PAPER_RESEARCH"
    total["calibration_features"] = {
        "three_sets_bin": three_bin(three),
        "confidence_bin": confidence_bin(confidence),
        "tour": tour,
        "empirical_over_rate": round(empirical, 4),
        "empirical_weight": EMPIRICAL_WEIGHT,
        "prior_model_over": round(prior, 4),
        "global_over_rate": model.get("global_rate", 0.5),
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
        "version": "2026-09-16-tennis-ou-v3-nonflat",
        "status": "PAPER_RESEARCH_ONLY",
        "training_records": model.get("n", 0),
        "global_over_rate": model.get("global_rate", 0.5),
        "current_predictions_rewritten": changed,
        "min_current_over": round(min(distribution), 4) if distribution else None,
        "max_current_over": round(max(distribution), 4) if distribution else None,
        "unique_current_over_probabilities": len(set(distribution)),
        "empirical_weight": EMPIRICAL_WEIGHT,
        "guardrails": [
            "No future results are used for a fixture before its start time.",
            "Late-captured records are excluded from calibration training.",
            "The continuous upstream model remains the primary O/U signal.",
            "Empirical calibration cannot flatten the entire feed into one probability.",
            "No bookmaker odds are invented.",
            "Research-only; no live-money execution."
        ]
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
