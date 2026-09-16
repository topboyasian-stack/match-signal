#!/usr/bin/env python3
"""Build match-specific tennis O/U probabilities from the current model state.

The previous tennis O/U layer could collapse many fixtures onto one empirical
30/70-style prior. This layer restores fixture-level variation using the
model's set probability, competitiveness and expected-set count, then applies
a conservative historical calibration. It never uses future results for a
fixture that has not started.
PAPER ONLY.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS = DATA / "predictions.json"
ARCHIVE = DATA / "tennis_prediction_archive.json"


def load(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, (list, dict)) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def clamp(value, lo=0.05, hi=0.95):
    return max(lo, min(hi, float(value)))


def logit(p):
    p = clamp(p, 0.001, 0.999)
    return math.log(p / (1.0 - p))


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


def historical_over_rate(archive):
    over = total = 0
    for row in archive:
        if row.get("sport") != "tennis":
            continue
        actual = row.get("actual_markets") or {}
        result = str(actual.get("total_games_result") or "").lower()
        eligible = row.get("evaluation_eligible") is True
        if eligible and result in {"over", "under"}:
            total += 1
            over += result == "over"
    # Weak prior only; fixture-specific model remains dominant.
    return (over / total) if total >= 20 else 0.5


def fixture_raw_probability(row):
    analytics = row.get("analytics") or {}
    games = analytics.get("total_games") or {}
    line = float(games.get("line") or 22.5)
    set_probs = analytics.get("set_win_prob") or {}
    p1_set = float(set_probs.get("p1") or 0.5)
    p1_set = clamp(p1_set, 0.05, 0.95)
    expected_sets = float(analytics.get("expected_sets") or 2.5)

    # A close set probability implies longer sets/more games; a strong
    # favourite implies a greater chance of a shorter two-set match.
    competitiveness = 1.0 - 2.0 * abs(p1_set - 0.5)
    expected_games_per_set = 9.0 + 2.2 * competitiveness
    expected_total = expected_games_per_set * expected_sets

    # Logistic distance from the actual market line gives each fixture a
    # distinct O/U probability instead of reusing one global prior.
    scale = 2.15
    raw = sigmoid((expected_total - line) / scale)
    return raw, line, expected_total, competitiveness


def main():
    predictions = load(PREDICTIONS, [])
    archive = load(ARCHIVE, [])
    if not isinstance(predictions, list):
        raise SystemExit("predictions.json is not a list")
    if not isinstance(archive, list):
        archive = []

    prior = historical_over_rate(archive)
    changed = 0
    varied = set()

    for row in predictions:
        if row.get("sport") != "tennis":
            continue
        analytics = row.setdefault("analytics", {})
        games = analytics.setdefault("total_games", {})
        if not games:
            continue

        raw, line, expected_total, competitiveness = fixture_raw_probability(row)

        # Conservative calibration toward the historical prior. Keep enough
        # fixture signal to avoid the old 30/70 collapse.
        calibrated = sigmoid(0.78 * logit(raw) + 0.22 * logit(prior))
        calibrated = round(clamp(calibrated), 4)
        games["line"] = line
        games["expected_total_games"] = round(expected_total, 2)
        games["over"] = calibrated
        games["under"] = round(1.0 - calibrated, 4)
        games["pick"] = "over" if calibrated >= 0.5 else "under"
        games["source"] = "fixture-specific competitiveness + expected sets + historical calibration"
        games["calibration_status"] = "PAPER_RESEARCH"
        games["calibration_version"] = "tennis-ou-v2"
        games["competitiveness"] = round(competitiveness, 4)
        varied.add(calibrated)
        changed += 1

    PREDICTIONS.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "status": "ok",
        "version": "tennis-ou-v2",
        "predictions_updated": changed,
        "historical_over_prior": round(prior, 4),
        "distinct_over_probabilities": len(varied),
        "paper_only": True,
        "note": "Fixture-specific O/U probabilities replace the collapsed empirical prior; no future results are used.",
    }
    (DATA / "tennis_ou_calibration.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
