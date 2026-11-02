#!/usr/bin/env python3
"""Research-only NBA totals probabilities and SportyBet market-value diagnostics.

The score model is market-blind. Exact fresh market-225 prices are joined only
after the predictive residual distribution has been calibrated. No betting or
ticket release is authorized by this report.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from expansion_pipeline import dt as parse_time
from nba_totals_walk_forward import (
    EVALUATION_CUTOFF_UTC,
    HISTORY,
    LEDGER,
    PREDICTIONS,
    build_forecasts,
    clean_history,
    verified_market_records,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "nba_totals_probability_value_experiment.json"
CALIBRATION_TRAIN_CUTOFF_UTC = datetime(
    2026, 2, 10, 4, 59, 59, 999999, tzinfo=timezone.utc
)
HISTORICAL_VALIDATION_CUTOFF_UTC = datetime(
    2026, 3, 26, 3, 59, 59, 999999, tzinfo=timezone.utc
)
MIN_CALIBRATION_RESIDUALS = 150
MIN_PROSPECTIVE_SETTLED_BETS = 100
MIN_PROBABILITY_EDGE = 0.04
MIN_EXPECTED_VALUE = 0.03
BOOTSTRAP_RESAMPLES = 4000


def _blend(row, weight):
    base = float(row["base_total"])
    pace = row.get("pace_total")
    if row.get("pace_available") is not True or pace is None:
        return base
    return base + weight * (float(pace) - base)


def _tune_v5(training_rows):
    grid = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    candidates = []
    for weight in grid:
        errors = [
            _blend(row, weight) - float(row["actual_total"])
            for row in training_rows
        ]
        mae = sum(abs(error) for error in errors) / len(errors) if errors else float("inf")
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else float("inf")
        candidates.append((mae, rmse, weight))
    selected = min(candidates)[2] if candidates else 0.0
    errors = [_blend(row, selected) - float(row["actual_total"]) for row in training_rows]
    bias = sum(errors) / len(errors) if errors else 0.0
    return selected, bias


def _prediction(row, weight, bias):
    return _blend(row, weight) - bias


def _quantile(values, probability):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = max(0.0, min(1.0, float(probability))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _interval_coverage(calibration_residuals, validation_residuals, confidence):
    tail = (1.0 - confidence) / 2.0
    low = _quantile(calibration_residuals, tail)
    high = _quantile(calibration_residuals, 1.0 - tail)
    covered = sum(low <= value <= high for value in validation_residuals)
    return {
        "nominal": confidence,
        "lower_residual": round(low, 4),
        "upper_residual": round(high, 4),
        "observed_coverage": round(covered / len(validation_residuals), 4) if validation_residuals else None,
        "validation_n": len(validation_residuals),
    }


def fit_residual_distribution(history):
    forecasts = [
        row for row in build_forecasts(clean_history(history))
        if parse_time(row["date"]) < EVALUATION_CUTOFF_UTC
    ]
    training = [
        row for row in forecasts
        if parse_time(row["date"]) < CALIBRATION_TRAIN_CUTOFF_UTC
    ]
    calibration = [
        row for row in forecasts
        if CALIBRATION_TRAIN_CUTOFF_UTC <= parse_time(row["date"]) < HISTORICAL_VALIDATION_CUTOFF_UTC
    ]
    validation = [
        row for row in forecasts
        if HISTORICAL_VALIDATION_CUTOFF_UTC <= parse_time(row["date"]) < EVALUATION_CUTOFF_UTC
    ]
    if len(training) < 300 or len(calibration) < MIN_CALIBRATION_RESIDUALS or len(validation) < 100:
        raise RuntimeError(
            "Insufficient data for residual calibration: "
            f"training={len(training)}, calibration={len(calibration)}, validation={len(validation)}"
        )

    weight, bias = _tune_v5(training)
    calibration_residuals = [
        float(row["actual_total"]) - _prediction(row, weight, bias)
        for row in calibration
    ]
    validation_residuals = [
        float(row["actual_total"]) - _prediction(row, weight, bias)
        for row in validation
    ]
    intervals = [
        _interval_coverage(calibration_residuals, validation_residuals, confidence)
        for confidence in (0.50, 0.80, 0.90)
    ]
    coverage_ok = (
        0.35 <= intervals[0]["observed_coverage"] <= 0.65
        and 0.68 <= intervals[1]["observed_coverage"] <= 0.92
        and 0.78 <= intervals[2]["observed_coverage"] <= 0.98
    )
    return {
        "weight": weight,
        "bias": bias,
        "training_n": len(training),
        "calibration_n": len(calibration),
        "validation_n": len(validation),
        "calibration_residuals": calibration_residuals,
        "training_period": {
            "start_utc": training[0]["date"],
            "end_utc": training[-1]["date"],
            "n": len(training),
        },
        "calibration_period": {
            "start_utc": calibration[0]["date"],
            "end_utc": calibration[-1]["date"],
            "n": len(calibration),
        },
        "validation_period": {
            "start_utc": validation[0]["date"],
            "end_utc": validation[-1]["date"],
            "n": len(validation),
        },
        "validation_interval_coverage": intervals,
        "coverage_check": "PASS" if coverage_ok else "FAIL",
    }


def _settlement_probabilities(forecast, line, residuals):
    over = under = push = 0
    count = len(residuals)
    for residual in residuals:
        # NBA final totals are integer-valued; this handles whole-number pushes.
        projected_actual = int(math.floor(float(forecast) + float(residual) + 0.5))
        if projected_actual > float(line):
            over += 1
        elif projected_actual < float(line):
            under += 1
        else:
            push += 1
    return {
        "over": over / count if count else 0.0,
        "under": under / count if count else 0.0,
        "push": push / count if count else 0.0,
    }


def _ev(probability, odds):
    return probability["win"] * (odds - 1.0) - probability["loss"]


def _value_decision(forecast, line, over_odds, under_odds, residuals,
                    calibration_ok, resamples=BOOTSTRAP_RESAMPLES, seed_key=""):
    probabilities = _settlement_probabilities(forecast, line, residuals)
    implied_over = 1.0 / over_odds
    implied_under = 1.0 / under_odds
    normalizer = implied_over + implied_under
    no_vig_over = implied_over / normalizer
    no_vig_under = implied_under / normalizer

    over_ev = _ev({"win": probabilities["over"], "loss": probabilities["under"]}, over_odds)
    under_ev = _ev({"win": probabilities["under"], "loss": probabilities["over"]}, under_odds)

    rng = random.Random(20261102 + sum(ord(ch) for ch in str(seed_key)))
    over_edge_samples, under_edge_samples = [], []
    over_ev_samples, under_ev_samples = [], []
    count = len(residuals)
    for _ in range(max(100, int(resamples))):
        sample = [residuals[rng.randrange(count)] for _ in range(count)]
        p = _settlement_probabilities(forecast, line, sample)
        over_edge_samples.append(p["over"] - no_vig_over)
        under_edge_samples.append(p["under"] - no_vig_under)
        over_ev_samples.append(_ev({"win": p["over"], "loss": p["under"]}, over_odds))
        under_ev_samples.append(_ev({"win": p["under"], "loss": p["over"]}, under_odds))

    def lower(values):
        return _quantile(values, 0.025)

    over_edge_lower = lower(over_edge_samples)
    under_edge_lower = lower(under_edge_samples)
    over_ev_lower = lower(over_ev_samples)
    under_ev_lower = lower(under_ev_samples)

    decision = "NO BET"
    if calibration_ok:
        if over_edge_lower >= MIN_PROBABILITY_EDGE and over_ev_lower >= MIN_EXPECTED_VALUE:
            decision = "OVER VALUE"
        elif under_edge_lower >= MIN_PROBABILITY_EDGE and under_ev_lower >= MIN_EXPECTED_VALUE:
            decision = "UNDER VALUE"

    return {
        "forecast_total": round(float(forecast), 4),
        "sportybet_line": float(line),
        "over_odds": float(over_odds),
        "under_odds": float(under_odds),
        "model_probability": {
            "over": round(probabilities["over"], 4),
            "under": round(probabilities["under"], 4),
            "push": round(probabilities["push"], 4),
        },
        "market_no_vig_probability": {
            "over": round(no_vig_over, 4),
            "under": round(no_vig_under, 4),
        },
        "model_probability_edge": {
            "over": round(probabilities["over"] - no_vig_over, 4),
            "under": round(probabilities["under"] - no_vig_under, 4),
        },
        "expected_value_per_unit": {
            "over": round(over_ev, 4),
            "under": round(under_ev, 4),
        },
        "bootstrap_95_lower_bound": {
            "over_probability_edge": round(over_edge_lower, 4),
            "under_probability_edge": round(under_edge_lower, 4),
            "over_expected_value": round(over_ev_lower, 4),
            "under_expected_value": round(under_ev_lower, 4),
            "method": "deterministic paired empirical-residual bootstrap; 4,000 resamples",
        },
        "calibration_check": "PASS" if calibration_ok else "FAIL",
        "decision": decision,
        "decision_is_authorized_for_betting": False,
    }


def _valid_sportybet_market(prediction, now):
    if not isinstance(prediction, dict):
        return None
    start = parse_time(prediction.get("start_time"))
    if not start or start <= now:
        return None
    market = ((prediction.get("markets") or {}).get("total_ou") or {})
    quote_time = parse_time(market.get("quote_timestamp"))
    if not quote_time:
        return None
    age = (now - quote_time).total_seconds()
    if age < -120 or age > 15 * 60 or quote_time >= start:
        return None
    if str(market.get("market_id") or "") != "225":
        return None
    if str(market.get("source") or "").strip().lower() != "sportybet nigeria":
        return None
    if market.get("quote_capture_basis") != "SportyBet API response observed_at":
        return None
    try:
        line = float(market["line"])
        over_odds = float(market["over_odds"])
        under_odds = float(market["under_odds"])
        forecast = float(prediction["expected_total"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (line, over_odds, under_odds, forecast)):
        return None
    if not (100 <= line <= 300 and over_odds > 1 and under_odds > 1):
        return None
    return market, line, over_odds, under_odds, forecast, age / 60.0


def run_experiment(history, ledger, predictions, now=None):
    now = now or datetime.now(timezone.utc)
    fitted = fit_residual_distribution(history)
    residuals = fitted.pop("calibration_residuals")
    calibration_ok = (
        fitted["coverage_check"] == "PASS"
        and fitted["calibration_n"] >= MIN_CALIBRATION_RESIDUALS
    )

    settled = verified_market_records(ledger)
    v5_settled = [row for row in settled if row.get("totals_model_version") == "nba-total-v5-pace-efficiency-calibrated"]
    settled_audit = []
    for row in v5_settled:
        try:
            result = _value_decision(
                float(row["expected_total"]), float(row["line"]),
                float(row["over_odds"]), float(row["under_odds"]),
                residuals, calibration_ok, seed_key=row.get("event_id"),
            )
        except (KeyError, TypeError, ValueError):
            continue
        settled_result = str(row.get("result") or "").lower()
        value_side = (
            "over" if result["decision"] == "OVER VALUE"
            else "under" if result["decision"] == "UNDER VALUE" else None
        )
        value_signal_outcome = (
            "NOT_A_SIGNAL" if value_side is None
            else "WIN" if value_side == settled_result
            else "PUSH" if settled_result == "push"
            else "LOSS"
        )
        settled_audit.append({
            "event_id": str(row.get("event_id") or ""),
            "matchup": f'{row.get("player_1") or ""} vs {row.get("player_2") or ""}',
            "published_at": row.get("published_at"),
            "settled_result": settled_result,
            "won_by_original_point_edge_pick": (
                str(row.get("pick") or "").lower() == settled_result
            ),
            "research_value_signal_outcome": value_signal_outcome,
            **result,
        })

    upcoming = []
    skipped_without_fresh_pair = 0
    for prediction in predictions or []:
        if not isinstance(prediction, dict):
            continue
        if prediction.get("totals_model_version") != "nba-total-v5-pace-efficiency-calibrated":
            continue
        match = _valid_sportybet_market(prediction, now)
        if not match:
            if (parse_time(prediction.get("start_time")) or now) > now:
                skipped_without_fresh_pair += 1
            continue
        market, line, over_odds, under_odds, forecast, age_minutes = match
        decision = _value_decision(
            forecast, line, over_odds, under_odds, residuals,
            calibration_ok, seed_key=prediction.get("event_id"),
        )
        upcoming.append({
            "event_id": str(prediction.get("event_id") or ""),
            "matchup": f'{prediction.get("player_1") or ""} vs {prediction.get("player_2") or ""}',
            "start_time": prediction.get("start_time"),
            "quote_timestamp": market.get("quote_timestamp"),
            "quote_age_minutes": round(age_minutes, 4),
            **decision,
        })

    prospective_bets = [
        row for row in settled
        if parse_time(row.get("published_at")) is not None
        and parse_time(row.get("published_at")) >= EVALUATION_CUTOFF_UTC
    ]
    prospective_minimum_sample_reached = (
        len(prospective_bets) >= MIN_PROSPECTIVE_SETTLED_BETS
    )
    historical_value_signals = [
        row for row in settled_audit
        if row["research_value_signal_outcome"] != "NOT_A_SIGNAL"
    ]
    historical_value_signal_wins = sum(
        row["research_value_signal_outcome"] == "WIN" for row in historical_value_signals
    )
    historical_value_signal_losses = sum(
        row["research_value_signal_outcome"] == "LOSS" for row in historical_value_signals
    )
    archived_market_line_records = sum(
        bool(row.get("markets")) for row in (history or []) if isinstance(row, dict)
    )
    return {
        "generated_at": now.isoformat(),
        "paper_only": True,
        "experiment": "NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V1",
        "model_version": "nba-total-v5-pace-efficiency-calibrated",
        "model_projection_market_blind": True,
        "prospective_holdout_cutoff_utc": EVALUATION_CUTOFF_UTC.isoformat(),
        "prospective_holdout_used_for_calibration": False,
        "calibration_protocol": {
            "train_cutoff_utc": CALIBRATION_TRAIN_CUTOFF_UTC.isoformat(),
            "validation_cutoff_utc": HISTORICAL_VALIDATION_CUTOFF_UTC.isoformat(),
            "training_n": fitted["training_n"],
            "calibration_residuals_n": fitted["calibration_n"],
            "validation_n": fitted["validation_n"],
            "pace_blend_weight": fitted["weight"],
            "bias_correction_points": round(fitted["bias"], 4),
            "training_period": fitted["training_period"],
            "calibration_period": fitted["calibration_period"],
            "validation_period": fitted["validation_period"],
            "validation_interval_coverage": fitted["validation_interval_coverage"],
            "coverage_check": fitted["coverage_check"],
            "calibration_scope": "Historical score-residual interval coverage only; this does not establish SportyBet market-probability or betting-value calibration.",
            "probability_edge_threshold": MIN_PROBABILITY_EDGE,
            "expected_value_threshold": MIN_EXPECTED_VALUE,
        },
        "settled_v5_market_audit": settled_audit,
        "settled_v5_market_count": len(settled_audit),
        "historical_value_signal_summary": {
            "n": len(historical_value_signals),
            "wins": historical_value_signal_wins,
            "losses": historical_value_signal_losses,
            "insufficient_sample": len(historical_value_signals) < MIN_PROSPECTIVE_SETTLED_BETS,
        },
        "archived_history_rows_with_any_market_data": archived_market_line_records,
        "historical_market_line_backtest_available": archived_market_line_records > 0,
        "upcoming_exact_fresh_market_225_value_diagnostics": upcoming,
        "upcoming_value_diagnostics_count": len(upcoming),
        "upcoming_predictions_without_exact_fresh_pair": skipped_without_fresh_pair,
        "prospective_settled_market_bets_after_cutoff": len(prospective_bets),
        "prospective_minimum_sample_reached": prospective_minimum_sample_reached,
        "live_value_decisions_authorized": False,
        "release_decision": "RESEARCH_ONLY",
        "release_reason": (
            "This research experiment never authorizes betting or ticket generation; historical score-interval coverage does not calibrate market probabilities, the archived game log contains no historical odds, and the separate prospective model and market release gates must all pass first. "
            "This report is diagnostic only; the shared Basketball ticket gate remains locked."
        ),
        "market_prices_used_as_model_inputs": False,
    }


def main():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    predictions = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    records = ledger.get("records", []) if isinstance(ledger, dict) else []
    report = run_experiment(history, records, predictions)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": report["experiment"],
        "calibration": report["calibration_protocol"],
        "settled_v5_market_count": report["settled_v5_market_count"],
        "upcoming_exact_fresh_market_225_value_diagnostics": report["upcoming_value_diagnostics_count"],
        "upcoming_predictions_without_exact_fresh_pair": report["upcoming_predictions_without_exact_fresh_pair"],
        "prospective_settled_market_bets_after_cutoff": report["prospective_settled_market_bets_after_cutoff"],
        "release_decision": report["release_decision"],
        "output": str(OUTPUT.relative_to(ROOT)),
    }, indent=2))


if __name__ == "__main__":
    main()
