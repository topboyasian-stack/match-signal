#!/usr/bin/env python3
"""Walk-forward, fixture-specific tennis O/U calibration.

The upstream continuous model is the primary signal. Historical settlement is
used only as a shrinkage/calibration layer, with enough support required for a
cell before it can influence a fixture. Unsupported fixtures retain their own
model probability instead of inheriting a single global 30/70-style rate.
PAPER ONLY.
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
EMPIRICAL_WEIGHT = 0.20
PRIOR_STRENGTH = 8.0
MIN_CELL_SUPPORT = 12
MIN_BROAD_SUPPORT = 20

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def three_bin(value):
    value = float(value)
    if value < 0.46: return "low"
    if value > 0.56: return "high"
    return "mid"

def confidence_bin(value):
    value = float(value)
    if value < 0.56: return "low"
    if value < 0.65: return "mid"
    if value < 0.75: return "high"
    return "very_high"

def fit(records):
    usable = []
    for row in records:
        if row.get("sport") != "tennis" or not row.get("settled"): continue
        if row.get("capture_status") == "LATE_CAPTURE" or row.get("evaluation_eligible") is False: continue
        actual = (row.get("actual_markets") or {}).get("total_games_result")
        if actual not in {"over", "under"}: continue
        total = (row.get("analytics") or {}).get("total_games") or {}
        three, confidence, line = (row.get("analytics") or {}).get("three_sets"), row.get("confidence"), total.get("line")
        if three is None or confidence is None or line is None: continue
        usable.append({"tour": str(row.get("league") or "unknown").upper(), "line": round(float(line) * 2) / 2, "three": float(three), "confidence": float(confidence), "over": 1 if actual == "over" else 0})
    if not usable:
        return {"n": 0, "global_rate": 0.5, "cells": {}, "rates": {}, "broad_rates": {}, "line_rates": {}, "line_counts": {}}
    global_rate = (sum(x["over"] for x in usable) + PRIOR_STRENGTH * 0.5) / (len(usable) + PRIOR_STRENGTH)
    cells, broad, lines = {}, {}, {}
    for x in usable:
        key = f"{x['line']:.1f}|{three_bin(x['three'])}|{confidence_bin(x['confidence'])}|{x['tour']}"
        cell = cells.setdefault(key, [0, 0]); cell[0] += 1; cell[1] += x["over"]
        broad_key = f"{x['line']:.1f}|{three_bin(x['three'])}|{confidence_bin(x['confidence'])}"
        bcell = broad.setdefault(broad_key, [0, 0]); bcell[0] += 1; bcell[1] += x["over"]
        lcell = lines.setdefault(x["line"], [0, 0]); lcell[0] += 1; lcell[1] += x["over"]
    rates = {k: (o + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH) for k, (n, o) in cells.items()}
    broad_rates = {k: (o + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH) for k, (n, o) in broad.items()}
    line_rates = {k: (o + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH) for k, (n, o) in lines.items()}
    return {"n": len(usable), "global_rate": round(global_rate, 4), "cells": cells, "rates": rates, "broad_rates": broad_rates, "line_rates": line_rates, "line_counts": {k: v[0] for k, v in lines.items()}}

def calibrate(row, model):
    analytics = row.setdefault("analytics", {})
    total = analytics.setdefault("total_games", {})
    if not total: return False
    line = round(float(total.get("line") or 22.5) * 2) / 2
    three = float(analytics.get("three_sets") or 0.5)
    confidence = float(row.get("confidence") or 0.5)
    tour = str(row.get("league") or "unknown").upper()
    key = f"{line:.1f}|{three_bin(three)}|{confidence_bin(confidence)}|{tour}"
    broad_key = f"{line:.1f}|{three_bin(three)}|{confidence_bin(confidence)}"
    empirical = None
    source = "upstream_only"
    cell = model.get("cells", {}).get(key)
    if cell and cell[0] >= MIN_CELL_SUPPORT:
        empirical = model.get("rates", {}).get(key); source = "line+three_sets+confidence+tour"
    if empirical is None:
        broad_cell = model.get("broad", {}).get(broad_key) if model.get("broad") else None
        # Reconstruct broad support from the fitted broad-rate table. Require
        # meaningful support before allowing it to influence a fixture.
        if broad_cell is None:
            raw = model.get("broad_rates", {}).get(broad_key)
            broad_n = sum(v[0] for k, v in model.get("cells", {}).items() if k.startswith(broad_key + "|"))
            if raw is not None and broad_n >= MIN_BROAD_SUPPORT:
                empirical = raw; source = "line+three_sets+confidence"
    if empirical is None:
        line_rate = model.get("line_rates", {}).get(line)
        if line_rate is not None and model.get("line_counts", {}).get(line, 0) >= MIN_BROAD_SUPPORT:
            empirical = line_rate; source = "line_only"
    # Never fall back to the global historical rate for an individual fixture.
    # That was what made the visible feed look like the same 30/70 everywhere.
    prior = float(total.get("base_model_over", total.get("over", 0.5)) or 0.5)
    over = prior if empirical is None else (1.0 - EMPIRICAL_WEIGHT) * prior + EMPIRICAL_WEIGHT * float(empirical)
    if abs(line - 22.5) > 0.001:
        over -= 0.025 * (line - 22.5)
    over = max(0.05, min(0.95, over))
    total["base_model_over"] = round(prior, 4)
    total["base_model_under"] = round(1.0 - prior, 4)
    total["over"] = round(over, 4)
    total["under"] = round(1.0 - over, 4)
    total["pick"] = "over" if over >= 0.5 else "under"
    total["source"] = "continuous tennis model + walk-forward O/U calibration v4"
    total["calibration_status"] = "PAPER_RESEARCH"
    total["calibration_features"] = {"line": line, "three_sets_bin": three_bin(three), "confidence_bin": confidence_bin(confidence), "tour": tour, "empirical_over_rate": round(float(empirical), 4) if empirical is not None else None, "calibration_source": source, "empirical_weight": EMPIRICAL_WEIGHT if empirical is not None else 0.0, "prior_model_over": round(prior, 4), "global_over_rate": model.get("global_rate", 0.5)}
    analytics["total_games"] = total
    return True

def main():
    predictions = load(PRED, [])
    archive = load(ARCHIVE, [])
    model = fit(archive)
    changed, distribution = 0, []
    for row in predictions:
        if row.get("sport") == "tennis" and calibrate(row, model):
            changed += 1; distribution.append(row["analytics"]["total_games"]["over"])
    PRED.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {"updated_at": datetime.now(timezone.utc).isoformat(), "version": "2026-09-16-tennis-ou-v4-fixture-specific", "status": "PAPER_RESEARCH_ONLY", "training_records": model.get("n", 0), "global_over_rate": model.get("global_rate", 0.5), "current_predictions_rewritten": changed, "min_current_over": round(min(distribution), 4) if distribution else None, "max_current_over": round(max(distribution), 4) if distribution else None, "unique_current_over_probabilities": len(set(distribution)), "empirical_weight": EMPIRICAL_WEIGHT, "guardrails": ["No future results are used for a fixture before its start time.", "Late-captured records are excluded from calibration training.", "Fixture-specific upstream probability remains primary.", "Calibration is line-aware and requires support before influencing a fixture.", "No global fallback is applied to individual fixtures.", "No bookmaker odds are invented.", "Research-only; no live-money execution."]}
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__": main()
