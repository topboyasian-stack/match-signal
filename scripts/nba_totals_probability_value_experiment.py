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
MIN_PROSPECTIVE_PROBABILITY_SCORE = 30
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


def historical_probability_validation(validation_rows, calibration_residuals):
    """Score residual-derived O/U probabilities on untouched historical validation games.

    Lines are synthetic offsets around each model forecast, not invented bookmaker quotes.
    This is probability validation of the score model only, never a historical betting ROI test.
    """
    offsets = (-7.5, -5.0, -2.5, 0.0, 2.5, 5.0, 7.5)
    observations = []
    for row in validation_rows:
        forecast = float(row["forecast_total"])
        actual = float(row["actual_total"])
        for offset in offsets:
            line = round((forecast + offset) * 2.0) / 2.0
            model = _settlement_probabilities(forecast, line, calibration_residuals)
            outcome = (
                "over" if actual > line
                else "under" if actual < line
                else "push"
            )
            if outcome == "push":
                continue
            total_probability = model["over"] + model["under"]
            if total_probability <= 0:
                continue
            model_over = model["over"] / total_probability
            actual_over = 1.0 if outcome == "over" else 0.0
            observations.append({
                "event_id": row.get("event_id"),
                "offset_from_forecast": offset,
                "line": line,
                "model_over_probability": model_over,
                "outcome": outcome,
                "actual_over": actual_over,
                "model_brier": (model_over - actual_over) ** 2,
                "coinflip_brier": (0.5 - actual_over) ** 2,
                "model_log_loss": -math.log(max(1e-12, model_over if actual_over else 1.0 - model_over)),
                "coinflip_log_loss": -math.log(0.5),
            })

    def summarize(rows):
        n = len(rows)
        if not n:
            return {"n": 0, "brier": None, "log_loss": None}
        return {
            "n": n,
            "brier": round(sum(row["model_brier"] for row in rows) / n, 6),
            "log_loss": round(sum(row["model_log_loss"] for row in rows) / n, 6),
        }

    offset_results = []
    for offset in offsets:
        rows = [row for row in observations if row["offset_from_forecast"] == offset]
        model = summarize(rows)
        n = len(rows)
        offset_results.append({
            "offset_from_model_forecast_points": offset,
            "n": n,
            "model_brier": model["brier"],
            "coinflip_brier": round(sum(row["coinflip_brier"] for row in rows) / n, 6) if n else None,
            "model_log_loss": model["log_loss"],
            "coinflip_log_loss": round(sum(row["coinflip_log_loss"] for row in rows) / n, 6) if n else None,
            "model_brier_improves_on_coinflip": (
                model["brier"] < sum(row["coinflip_brier"] for row in rows) / n
                if n else False
            ),
        })

    n = len(observations)
    # Seven synthetic offsets from one game are repeated measurements, not seven
    # independent fixtures. Bootstrap score differences at the unique-game level.
    scores_by_event = {}
    for index, row in enumerate(observations):
        event_key = str(row.get("event_id") or f"row-{index}")
        scores_by_event.setdefault(event_key, []).append(row)
    event_score_rows = []
    for event_key, rows in sorted(scores_by_event.items()):
        event_score_rows.append({
            "event_id": event_key,
            "brier_delta": sum(r["model_brier"] - r["coinflip_brier"] for r in rows) / len(rows),
            "log_loss_delta": sum(r["model_log_loss"] - r["coinflip_log_loss"] for r in rows) / len(rows),
        })
    event_n = len(event_score_rows)
    clustered_diagnostics = {
        "independent_unit": "unique NBA game; mean over its non-push synthetic lines",
        "unique_validation_games_scored": event_n,
        "synthetic_lines_treated_as_independent_games": False,
    }
    if event_n:
        brier_deltas = [row["brier_delta"] for row in event_score_rows]
        log_deltas = [row["log_loss_delta"] for row in event_score_rows]
        mean_brier_delta = sum(brier_deltas) / event_n
        mean_log_delta = sum(log_deltas) / event_n
        rng = random.Random(20261102 + event_n)
        brier_bootstrap, log_bootstrap = [], []
        for _ in range(BOOTSTRAP_RESAMPLES):
            indices = [rng.randrange(event_n) for _ in range(event_n)]
            brier_bootstrap.append(sum(brier_deltas[i] for i in indices) / event_n)
            log_bootstrap.append(sum(log_deltas[i] for i in indices) / event_n)
        brier_low, brier_high = _quantile(brier_bootstrap, 0.025), _quantile(brier_bootstrap, 0.975)
        log_low, log_high = _quantile(log_bootstrap, 0.025), _quantile(log_bootstrap, 0.975)
        clustered_diagnostics.update({
            "brier_model_minus_coinflip_mean_per_game": round(mean_brier_delta, 6),
            "brier_difference_cluster_bootstrap_95_ci": [round(brier_low, 6), round(brier_high, 6)],
            "brier_model_improves_with_95pct_clustered_support": bool(brier_high < 0),
            "log_loss_model_minus_coinflip_mean_per_game": round(mean_log_delta, 6),
            "log_loss_difference_cluster_bootstrap_95_ci": [round(log_low, 6), round(log_high, 6)],
            "log_loss_model_improves_with_95pct_clustered_support": bool(log_high < 0),
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        })
    else:
        clustered_diagnostics.update({
            "brier_model_minus_coinflip_mean_per_game": None,
            "brier_difference_cluster_bootstrap_95_ci": None,
            "brier_model_improves_with_95pct_clustered_support": False,
            "log_loss_model_minus_coinflip_mean_per_game": None,
            "log_loss_difference_cluster_bootstrap_95_ci": None,
            "log_loss_model_improves_with_95pct_clustered_support": False,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        })

    if n:
        bins = []
        for bucket in range(10):
            lower, upper = bucket / 10.0, (bucket + 1) / 10.0
            selected = [
                row for row in observations
                if lower <= row["model_over_probability"] < upper
                or (bucket == 9 and row["model_over_probability"] == 1.0)
            ]
            if not selected:
                continue
            bins.append({
                "range": f"{lower:.1f}-{upper:.1f}",
                "n": len(selected),
                "mean_predicted_over_probability": round(
                    sum(row["model_over_probability"] for row in selected) / len(selected), 4
                ),
                "observed_over_rate": round(
                    sum(row["actual_over"] for row in selected) / len(selected), 4
                ),
            })
        model_brier = sum(row["model_brier"] for row in observations) / n
        coinflip_brier = sum(row["coinflip_brier"] for row in observations) / n
        model_log = sum(row["model_log_loss"] for row in observations) / n
        coinflip_log = sum(row["coinflip_log_loss"] for row in observations) / n
    else:
        bins = []
        model_brier = coinflip_brier = model_log = coinflip_log = None
    return {
        "protocol": "Empirical calibration residuals evaluated on later historical forecast games at seven synthetic half-point line offsets around each forecast. No historical SportyBet lines or odds are assumed.",
        "unique_validation_games": len(validation_rows),
        "synthetic_game_line_observations": n,
        "pushes_excluded": len(validation_rows) * len(offsets) - n,
        "model_brier": round(model_brier, 6) if model_brier is not None else None,
        "coinflip_baseline_brier": round(coinflip_brier, 6) if coinflip_brier is not None else None,
        "model_log_loss": round(model_log, 6) if model_log is not None else None,
        "coinflip_baseline_log_loss": round(coinflip_log, 6) if coinflip_log is not None else None,
        "model_brier_improves_on_coinflip": (
            bool(model_brier < coinflip_brier) if model_brier is not None and coinflip_brier is not None else False
        ),
        "model_log_loss_improves_on_coinflip": (
            bool(model_log < coinflip_log) if model_log is not None and coinflip_log is not None else False
        ),
        "probability_reliability_bins": bins,
        "event_clustered_score_diagnostics": clustered_diagnostics,
        "by_line_offset": offset_results,
        "not_a_sportybet_market_backtest": True,
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
        "historical_probability_validation": historical_probability_validation(
            [{**row, "forecast_total": _prediction(row, weight, bias)} for row in validation],
            calibration_residuals,
        ),
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
    non_push_mass = probabilities["over"] + probabilities["under"]
    # Market prices are conditional on a decisive outcome if the total can push.
    model_over_no_push = probabilities["over"] / non_push_mass if non_push_mass > 0 else 0.5
    model_under_no_push = probabilities["under"] / non_push_mass if non_push_mass > 0 else 0.5

    over_ev = _ev({"win": probabilities["over"], "loss": probabilities["under"]}, over_odds)
    under_ev = _ev({"win": probabilities["under"], "loss": probabilities["over"]}, under_odds)

    rng = random.Random(20261102 + sum(ord(ch) for ch in str(seed_key)))
    over_edge_samples, under_edge_samples = [], []
    over_ev_samples, under_ev_samples = [], []
    count = len(residuals)
    for _ in range(max(100, int(resamples))):
        sample = [residuals[rng.randrange(count)] for _ in range(count)]
        p = _settlement_probabilities(forecast, line, sample)
        sample_non_push_mass = p["over"] + p["under"]
        sample_over_no_push = p["over"] / sample_non_push_mass if sample_non_push_mass > 0 else 0.5
        sample_under_no_push = p["under"] / sample_non_push_mass if sample_non_push_mass > 0 else 0.5
        over_edge_samples.append(sample_over_no_push - no_vig_over)
        under_edge_samples.append(sample_under_no_push - no_vig_under)
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
        "model_probability_conditional_on_no_push": {
            "over": round(model_over_no_push, 4),
            "under": round(model_under_no_push, 4),
        },
        "model_probability_edge": {
            "over": round(model_over_no_push - no_vig_over, 4),
            "under": round(model_under_no_push - no_vig_under, 4),
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


def _snapshot_market(snapshot):
    if not isinstance(snapshot, dict):
        return None
    market = ((snapshot.get("markets") or {}).get("total_ou") or {})
    if (
        str(market.get("market_id") or "") != "225"
        or str(market.get("source") or "").strip().lower() != "sportybet nigeria"
        or market.get("quote_capture_basis") != "SportyBet API response observed_at"
        or not str(market.get("sportybet_event_id") or "").strip()
    ):
        return None
    quote_time = parse_time(market.get("quote_timestamp"))
    published = parse_time(snapshot.get("published_at"))
    start = parse_time(snapshot.get("start_time"))
    if not quote_time or not published or not start or quote_time >= start or published >= start:
        return None
    age = (published - quote_time).total_seconds()
    if age < -120 or age > 15 * 60:
        return None
    try:
        line = float(market["line"])
        over = float(market["over_odds"])
        under = float(market["under_odds"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (line, over, under)) or over <= 1 or under <= 1:
        return None
    return {
        "quote_time": quote_time,
        "published": published,
        "start": start,
        "line": line,
        "over_odds": over,
        "under_odds": under,
        "sportybet_event_id": str(market.get("sportybet_event_id")),
        "snapshot_id": str(snapshot.get("publication_snapshot_id") or ""),
    }


def _no_vig_probability(side, over_odds, under_odds):
    over_implied = 1.0 / float(over_odds)
    under_implied = 1.0 / float(under_odds)
    total = over_implied + under_implied
    if side == "over":
        return over_implied / total
    return under_implied / total


def snapshot_clv_audit(settled_rows, snapshots, close_window_minutes=45):
    """Compare original immutable v5 quote with the latest captured pre-tip revision.

    'Near-close' is explicitly only the latest captured pregame observation within
    the configured window. It is not represented as SportyBet's official closing line.
    """
    by_id = {
        str(row.get("publication_snapshot_id")): row
        for row in (snapshots or [])
        if isinstance(row, dict) and row.get("publication_snapshot_id")
    }
    by_event = {}
    for snapshot in snapshots or []:
        if not isinstance(snapshot, dict):
            continue
        event_id = str(snapshot.get("event_id") or "")
        if event_id:
            by_event.setdefault(event_id, []).append(snapshot)

    audit = []
    for bet in settled_rows:
        event_id = str(bet.get("event_id") or "")
        side = str(bet.get("pick") or "").lower()
        if side not in ("over", "under"):
            continue
        initial = by_id.get(str(bet.get("publication_snapshot_id") or ""))
        opening = _snapshot_market(initial)
        if not opening or str(initial.get("event_id") or "") != event_id:
            audit.append({
                "event_id": event_id,
                "clv_status": "MISSING_VERIFIED_OPENING_SNAPSHOT",
            })
            continue
        candidates = []
        for snapshot in by_event.get(event_id, []):
            market = _snapshot_market(snapshot)
            if not market:
                continue
            if market["sportybet_event_id"] != opening["sportybet_event_id"]:
                continue
            if market["quote_time"] <= opening["quote_time"]:
                continue
            if market["quote_time"] >= opening["start"]:
                continue
            candidates.append((market["quote_time"], market, snapshot))
        if not candidates:
            audit.append({
                "event_id": event_id,
                "clv_status": "NO_LATER_VERIFIED_PREGAME_QUOTE",
                "opening_line": opening["line"],
                "opening_snapshot_id": opening["snapshot_id"],
            })
            continue

        _, latest, latest_snapshot = max(candidates, key=lambda item: (item[0], item[1]["published"]))
        minutes_to_start = (latest["start"] - latest["quote_time"]).total_seconds() / 60.0
        opening_no_vig = _no_vig_probability(
            side, opening["over_odds"], opening["under_odds"]
        )
        latest_no_vig = _no_vig_probability(
            side, latest["over_odds"], latest["under_odds"]
        )
        probability_clv = latest_no_vig - opening_no_vig
        line_clv = (
            opening["line"] - latest["line"]
            if side == "over" else latest["line"] - opening["line"]
        )
        near_close = minutes_to_start <= float(close_window_minutes)
        audit.append({
            "event_id": event_id,
            "matchup": f'{bet.get("player_1") or ""} vs {bet.get("player_2") or ""}',
            "selected_side": side.upper(),
            "clv_status": (
                "NEAR_CLOSE_CAPTURED"
                if near_close else "LATER_PREGAME_CAPTURE_OUTSIDE_CLOSE_WINDOW"
            ),
            "opening": {
                "snapshot_id": opening["snapshot_id"],
                "quote_timestamp": opening["quote_time"].isoformat(),
                "line": opening["line"],
                "over_odds": opening["over_odds"],
                "under_odds": opening["under_odds"],
                "selected_side_no_vig_probability": round(opening_no_vig, 6),
            },
            "latest_pregame": {
                "snapshot_id": latest["snapshot_id"],
                "quote_timestamp": latest["quote_time"].isoformat(),
                "minutes_before_start": round(minutes_to_start, 3),
                "line": latest["line"],
                "over_odds": latest["over_odds"],
                "under_odds": latest["under_odds"],
                "selected_side_no_vig_probability": round(latest_no_vig, 6),
            },
            "selected_side_no_vig_probability_clv": round(probability_clv, 6),
            "selected_side_line_clv_points": round(line_clv, 4),
            "positive_probability_clv": probability_clv > 0,
            "positive_line_clv": line_clv > 0,
            "is_official_bookmaker_close": False,
        })
    near_close_rows = [row for row in audit if row.get("clv_status") == "NEAR_CLOSE_CAPTURED"]
    return {
        "definition": "Opening immutable v5 publication quote vs latest captured exact SportyBet market-225 pregame quote; near-close counts only if quote was observed within 45 minutes of tip. This is not an official bookmaker close.",
        "close_window_minutes": close_window_minutes,
        "settled_v5_fixtures_audited": len(audit),
        "near_close_observations": len(near_close_rows),
        "positive_probability_clv_n": sum(row["positive_probability_clv"] for row in near_close_rows),
        "positive_line_clv_n": sum(row["positive_line_clv"] for row in near_close_rows),
        "mean_probability_clv": (
            round(sum(row["selected_side_no_vig_probability_clv"] for row in near_close_rows) / len(near_close_rows), 6)
            if near_close_rows else None
        ),
        "mean_line_clv_points": (
            round(sum(row["selected_side_line_clv_points"] for row in near_close_rows) / len(near_close_rows), 4)
            if near_close_rows else None
        ),
        "fixtures": audit,
        "sample_is_sufficient_for_release": False,
    }


def prospective_snapshot_coverage(settled_rows, snapshots, cutoff=EVALUATION_CUTOFF_UTC):
    """Measure post-cutoff coverage and require exact linkage to immutable snapshots."""
    all_snapshots = [row for row in (snapshots or []) if isinstance(row, dict)]
    snapshot_by_id = {}
    duplicate_ids = set()
    for snapshot in all_snapshots:
        snapshot_id = str(snapshot.get("publication_snapshot_id") or "").strip()
        if not snapshot_id:
            continue
        if snapshot_id in snapshot_by_id:
            duplicate_ids.add(snapshot_id)
        else:
            snapshot_by_id[snapshot_id] = snapshot

    after_cutoff = []
    verified_fresh = []
    for snapshot in all_snapshots:
        if snapshot.get("totals_model_version") != "nba-total-v5-pace-efficiency-calibrated":
            continue
        published = parse_time(snapshot.get("published_at"))
        if not published or published < cutoff:
            continue
        after_cutoff.append(snapshot)
        market = _snapshot_market(snapshot)
        snapshot_id = str(snapshot.get("publication_snapshot_id") or "").strip()
        if (
            snapshot.get("publication_snapshot_verified") is True
            and snapshot.get("publication_snapshot_kind") == "immutable_sportybet_market_225_revision"
            and snapshot_id
            and snapshot_id not in duplicate_ids
            and str(snapshot.get("event_id") or "").strip()
            and market is not None
        ):
            verified_fresh.append(snapshot)

    settled_prospective = []
    for row in (settled_rows or []):
        published = parse_time(row.get("published_at")) if isinstance(row, dict) else None
        if published and published >= cutoff:
            settled_prospective.append(row)

    matched_events = set()
    failures = []
    for row in settled_prospective:
        event_id = str(row.get("event_id") or "").strip()
        snapshot_id = str(row.get("publication_snapshot_id") or "").strip()
        snapshot = snapshot_by_id.get(snapshot_id)
        reason = None
        if not snapshot_id or snapshot is None:
            reason = "SNAPSHOT_REFERENCE_NOT_FOUND"
        elif snapshot_id in duplicate_ids:
            reason = "SNAPSHOT_ID_NOT_UNIQUE"
        else:
            market = _snapshot_market(snapshot)
            row_published = parse_time(row.get("published_at"))
            row_start = parse_time(row.get("start_time"))
            snap_published = parse_time(snapshot.get("published_at"))
            snap_start = parse_time(snapshot.get("start_time"))
            snap_market = ((snapshot.get("markets") or {}).get("total_ou") or {})
            row_quote = parse_time(row.get("quote_timestamp"))
            checks = [
                row.get("totals_model_version") == "nba-total-v5-pace-efficiency-calibrated",
                snapshot.get("totals_model_version") == "nba-total-v5-pace-efficiency-calibrated",
                snapshot.get("publication_snapshot_verified") is True,
                snapshot.get("publication_snapshot_kind") == "immutable_sportybet_market_225_revision",
                str(snapshot.get("event_id") or "").strip() == event_id,
                row_published is not None and snap_published == row_published and row_published >= cutoff,
                row_start is not None and snap_start == row_start,
                market is not None,
                str(row.get("market_id") or "") == "225",
                str(row.get("market_source") or "").strip().lower() == "sportybet nigeria",
                str(row.get("quote_capture_basis") or "") == "SportyBet API response observed_at",
                str(row.get("sportybet_event_id") or "").strip() == str(snap_market.get("sportybet_event_id") or "").strip(),
                str(row.get("pick") or "").strip().lower() == str(snap_market.get("pick") or "").strip().lower(),
                row_quote is not None and market is not None and market["quote_time"] == row_quote,
            ]
            # The model projection is present on both the immutable prediction
            # and its market-attached audit record; require both to match settlement.
            for frozen_forecast in (snapshot.get("expected_total"), snap_market.get("expected_total")):
                try:
                    same = math.isclose(
                        float(row.get("expected_total")), float(frozen_forecast),
                        rel_tol=0.0, abs_tol=1e-9,
                    )
                except (TypeError, ValueError):
                    same = False
                checks.append(same)
            for field in ("line", "over_odds", "under_odds"):
                try:
                    same = math.isclose(float(row.get(field)), float(snap_market.get(field)), rel_tol=0.0, abs_tol=1e-9)
                except (TypeError, ValueError):
                    same = False
                checks.append(same)
            if not all(checks):
                reason = "SNAPSHOT_FIELDS_DO_NOT_MATCH_SETTLEMENT_RECORD"
        if reason:
            failures.append({"event_id": event_id, "reason": reason})
        elif event_id:
            matched_events.add(event_id)

    prospective_event_ids = {
        str(row.get("event_id") or "").strip()
        for row in after_cutoff
        if str(row.get("event_id") or "").strip()
    }
    verified_event_ids = {
        str(row.get("event_id") or "").strip()
        for row in verified_fresh
        if str(row.get("event_id") or "").strip()
    }
    report = {
        "cutoff_utc": cutoff.isoformat(),
        "snapshot_source": "data/nba_totals_publication_snapshots.json",
        "prospective_v5_snapshot_records": len(after_cutoff),
        "prospective_unique_fixtures_with_any_snapshot": len(prospective_event_ids),
        "prospective_verified_fresh_market_225_snapshot_records": len(verified_fresh),
        "prospective_unique_fixtures_with_verified_fresh_market_225_snapshot": len(verified_event_ids),
        "prospective_settled_unique_market_selections": len(settled_prospective),
        "prospective_settled_selections_with_exact_snapshot_match": len(matched_events),
        "prospective_settled_selections_missing_or_mismatched_snapshot": len(settled_prospective) - len(matched_events),
        "snapshot_linkage_failures": failures[:10],
        "target_unique_settled_probability_observations": MIN_PROSPECTIVE_PROBABILITY_SCORE,
        "snapshot_linked_sample_threshold_met": len(matched_events) >= MIN_PROSPECTIVE_PROBABILITY_SCORE,
    }
    return report, matched_events


def probability_score_summary(settled_audit, minimum_descriptive_sample=30, cohort_label="selected-v5 historical cohort"):
    """Descriptive Brier/log-loss comparison; never a release gate at tiny n."""
    binary = []
    for row in settled_audit:
        outcome = str(row.get("settled_result") or "").lower()
        if outcome not in ("over", "under"):
            continue
        model = row.get("model_probability") or {}
        market = row.get("market_no_vig_probability") or {}
        try:
            model_over_raw = float(model["over"])
            model_under_raw = float(model["under"])
            non_push_mass = model_over_raw + model_under_raw
            if (
                not math.isfinite(model_over_raw)
                or not math.isfinite(model_under_raw)
                or non_push_mass <= 0
            ):
                continue
            market_over = float(market["over"])
            if not math.isfinite(market_over) or not 0 <= market_over <= 1:
                continue
            binary.append({
                "event_id": row.get("event_id"),
                "outcome": outcome,
                "model_over": model_over_raw / non_push_mass,
                "market_over": market_over,
            })
        except (KeyError, TypeError, ValueError):
            continue

    n = len(binary)
    if not n:
        return {
            "n": 0, "model_brier": None, "market_no_vig_brier": None,
            "model_log_loss": None, "market_no_vig_log_loss": None,
            "over_probability_buckets": [],
            "sufficient_for_probability_validation": False,
        }

    model_brier = market_brier = model_log = market_log = 0.0
    bucket_map = {}
    epsilon = 1e-12
    for row in binary:
        actual = 1.0 if row["outcome"] == "over" else 0.0
        for prefix, probability in (
            ("model", row["model_over"]),
            ("market", row["market_over"]),
        ):
            clipped = min(1.0 - epsilon, max(epsilon, probability))
            brier = (clipped - actual) ** 2
            log_loss = -(
                actual * math.log(clipped) + (1.0 - actual) * math.log(1.0 - clipped)
            )
            if prefix == "model":
                model_brier += brier
                model_log += log_loss
            else:
                market_brier += brier
                market_log += log_loss

        bucket = min(9, max(0, int(row["model_over"] * 10)))
        bucket_map.setdefault(bucket, []).append(row)

    buckets = []
    for bucket, values in sorted(bucket_map.items()):
        buckets.append({
            "range": f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}",
            "n": len(values),
            "mean_model_over_probability": round(
                sum(row["model_over"] for row in values) / len(values), 4
            ),
            "observed_over_rate": round(
                sum(row["outcome"] == "over" for row in values) / len(values), 4
            ),
        })

    return {
        "n": n,
        "pushes_excluded_from_binary_metrics": len(settled_audit) - n,
        "model_brier": round(model_brier / n, 6),
        "market_no_vig_brier": round(market_brier / n, 6),
        "model_log_loss": round(model_log / n, 6),
        "market_no_vig_log_loss": round(market_log / n, 6),
        "over_probability_buckets": buckets,
        "sufficient_for_probability_validation": n >= minimum_descriptive_sample,
        "minimum_descriptive_sample": minimum_descriptive_sample,
        "warning": (
            f"Descriptive only. This comparison is based on {cohort_label} and does not establish release readiness or betting value."
            if n < minimum_descriptive_sample else
            "Descriptive score only; prospective market validation and release gates still apply."
        ),
    }


def run_experiment(history, ledger, predictions, now=None, snapshots=None):
    now = now or datetime.now(timezone.utc)
    fitted = fit_residual_distribution(history)
    residuals = fitted.pop("calibration_residuals")
    historical_probability_scores = fitted.pop("historical_probability_validation")
    calibration_ok = (
        fitted["coverage_check"] == "PASS"
        and fitted["calibration_n"] >= MIN_CALIBRATION_RESIDUALS
    )

    settled = verified_market_records(ledger)
    v5_settled = [row for row in settled if row.get("totals_model_version") == "nba-total-v5-pace-efficiency-calibrated"]
    clv_audit = snapshot_clv_audit(v5_settled, snapshots or [])
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

    # The immutable snapshot file is passed separately from current prediction data
    # by main(); for this intermediate call, a dedicated keyword-free run argument below
    # is populated from the ledger rows' exact publication snapshot references.
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

    snapshot_coverage, snapshot_linked_event_ids = prospective_snapshot_coverage(
        v5_settled, snapshots or []
    )
    prospective_settled_audit = [
        row for row in settled_audit
        if row.get("event_id") in snapshot_linked_event_ids
        and parse_time(row.get("published_at")) is not None
        and parse_time(row.get("published_at")) >= EVALUATION_CUTOFF_UTC
    ]
    probability_scores = probability_score_summary(settled_audit)
    prospective_probability_scores = probability_score_summary(
        prospective_settled_audit,
        minimum_descriptive_sample=MIN_PROSPECTIVE_PROBABILITY_SCORE,
        cohort_label="post-cutoff prospective cohort with exact linked pregame snapshots",
    )
    prospective_bets = [
        row for row in settled
        if parse_time(row.get("published_at")) is not None
        and parse_time(row.get("published_at")) >= EVALUATION_CUTOFF_UTC
    ]
    prospective_minimum_sample_reached = (
        len(prospective_bets) >= MIN_PROSPECTIVE_SETTLED_BETS
    )
    prospective_clv_rows = [
        row for row in v5_settled
        if row.get("event_id") in snapshot_linked_event_ids
        and parse_time(row.get("published_at")) is not None
        and parse_time(row.get("published_at")) >= EVALUATION_CUTOFF_UTC
    ]
    prospective_snapshots = [
        row for row in (snapshots or [])
        if isinstance(row, dict)
        and row.get("totals_model_version") == "nba-total-v5-pace-efficiency-calibrated"
        and parse_time(row.get("published_at")) is not None
        and parse_time(row.get("published_at")) >= EVALUATION_CUTOFF_UTC
    ]
    prospective_clv = snapshot_clv_audit(prospective_clv_rows, prospective_snapshots)
    prospective_clv["cohort"] = "post-cutoff prospective v5 selections with exact immutable snapshot linkage"
    prospective_clv["positive_clv_release_check_passed"] = bool(
        int(prospective_clv.get("near_close_observations") or 0) > 0
        and prospective_clv.get("mean_probability_clv") is not None
        and float(prospective_clv["mean_probability_clv"]) > 0
        and prospective_clv.get("mean_line_clv_points") is not None
        and float(prospective_clv["mean_line_clv_points"]) > 0
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
        "experiment": "NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V3",
        "model_version": "nba-total-v5-pace-efficiency-calibrated",
        "model_projection_market_blind": True,
        "prospective_holdout_cutoff_utc": EVALUATION_CUTOFF_UTC.isoformat(),
        "prospective_holdout_used_for_calibration": False,
        "historical_probability_validation": historical_probability_scores,
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
        "settled_v5_clv_diagnostics": clv_audit,
        "settled_v5_probability_score_summary": probability_scores,
        "prospective_pregame_snapshot_coverage": snapshot_coverage,
        "prospective_probability_score_summary": prospective_probability_scores,
        "prospective_clv_diagnostics": prospective_clv,
        "prospective_clv_release_check_passed": prospective_clv["positive_clv_release_check_passed"],
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
        "prospective_probability_scored_unique_fixtures": prospective_probability_scores["n"],
        "prospective_probability_validation_sample_met": prospective_probability_scores["sufficient_for_probability_validation"],
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
    snapshots = json.loads((DATA / "nba_totals_publication_snapshots.json").read_text(encoding="utf-8"))
    records = ledger.get("records", []) if isinstance(ledger, dict) else []
    report = run_experiment(history, records, predictions, snapshots=snapshots)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": report["experiment"],
        "calibration": report["calibration_protocol"],
        "settled_v5_market_count": report["settled_v5_market_count"],
        "upcoming_exact_fresh_market_225_value_diagnostics": report["upcoming_value_diagnostics_count"],
        "upcoming_predictions_without_exact_fresh_pair": report["upcoming_predictions_without_exact_fresh_pair"],
        "prospective_settled_market_bets_after_cutoff": report["prospective_settled_market_bets_after_cutoff"],
        "prospective_probability_scored_unique_fixtures": report["prospective_probability_scored_unique_fixtures"],
        "prospective_clv_release_check_passed": report["prospective_clv_release_check_passed"],
        "prospective_snapshot_coverage": report["prospective_pregame_snapshot_coverage"],
        "release_decision": report["release_decision"],
        "output": str(OUTPUT.relative_to(ROOT)),
    }, indent=2))


if __name__ == "__main__":
    main()
