#!/usr/bin/env python3
"""Chronological NBA full-game totals validation and price-audited ROI evidence.

Each historical forecast is generated using only games completed before tip-off.
Historical totals lines and odds are never reconstructed. ROI uses only settled,
immutable, contemporaneous SportyBet market-225 publication records from this
model version.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from expansion_pipeline import (NBA_TOTALS_MODEL_VERSION, NBA_TOTALS_PACE_BLEND_WEIGHT, NBA_TOTALS_BIAS_CORRECTION, nba_total_components, dt as parse_time)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "nba_history.json"
LEDGER = DATA / "nba_totals_ledger.json"
SNAPSHOTS = DATA / "nba_totals_publication_snapshots.json"
PREDICTIONS = DATA / "nba_predictions.json"
OUTPUT = DATA / "nba_totals_oos_value_test.json"
MIN_PRIOR_GAMES = 40
BASELINE_DAYS = 90
# Frozen once v5's prospective validation began. Never roll this date forward.
EVALUATION_CUTOFF_UTC = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
BOOTSTRAP_RESAMPLES = 4000
MIN_FORECAST_HOLDOUT = 100
MIN_MARKET_HOLDOUT = 100


def finite_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def clean_history(rows):
    clean = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        stamp = parse_time(row.get("date"))
        home, away = str(row.get("home") or "").strip(), str(row.get("away") or "").strip()
        hs, aws = finite_number(row.get("home_score")), finite_number(row.get("away_score"))
        if not stamp or not home or not away or hs is None or aws is None or hs < 0 or aws < 0:
            continue
        event_id = str(row.get("event_id") or f"{stamp.isoformat()}|{home}|{away}")
        clean_row = {
            "event_id": event_id, "date": stamp.isoformat(), "home": home, "away": away,
            "home_score": hs, "away_score": aws,
        }
        for key in (
            "home_pace", "away_pace", "home_off_rating", "away_off_rating",
            "home_def_rating", "away_def_rating", "home_possessions", "away_possessions",
        ):
            clean_row[key] = finite_number(row.get(key))
        clean[event_id] = clean_row
    return sorted(clean.values(), key=lambda row: (row["date"], row["event_id"]))


def build_forecasts(history, min_prior_games=MIN_PRIOR_GAMES):
    """Build expanding-window total components; every forecast uses only pre-tip games."""
    rows = clean_history(history)
    prior = []
    forecasts = []
    for game in rows:
        tip = parse_time(game["date"])
        if len(prior) >= min_prior_games:
            components = nba_total_components(game, prior)
            base_total = finite_number(components.get("base_total"))
            if base_total is not None:
                cutoff = tip - timedelta(days=BASELINE_DAYS)
                recent = [item for item in prior if cutoff <= parse_time(item["date"]) < tip]
                baseline_rows = recent or prior
                baseline_total = sum(
                    float(item["home_score"]) + float(item["away_score"]) for item in baseline_rows
                ) / len(baseline_rows)
                forecasts.append({
                    "event_id": game["event_id"], "date": game["date"],
                    "base_total": base_total,
                    "pace_total": finite_number(components.get("pace_total")),
                    "pace_available": components.get("pace_available") is True,
                    "model_total": base_total,
                    "baseline_total": baseline_total,
                    "actual_total": float(game["home_score"]) + float(game["away_score"]),
                    "prior_games": len(prior),
                })
        prior.append(game)
    return forecasts

def regression_metrics(rows, forecast_key):
    errors = [
        float(row[forecast_key]) - float(row["actual_total"])
        for row in rows
        if finite_number(row.get(forecast_key)) is not None and finite_number(row.get("actual_total")) is not None
    ]
    if not errors:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    n = len(errors)
    return {
        "n": n,
        "mae": round(sum(abs(error) for error in errors) / n, 4),
        "rmse": round(math.sqrt(sum(error * error for error in errors) / n), 4),
        "bias": round(sum(errors) / n, 4),
    }


def _roi_grade_record(row):
    if not isinstance(row, dict) or row.get("totals_model_version") != NBA_TOTALS_MODEL_VERSION:
        return False
    required_true = (
        "settled", "publication_snapshot_verified", "roi_eligible",
        "quote_fresh_at_publication", "price_pair_valid", "price_source_verified",
    )
    if any(row.get(key) is not True for key in required_true):
        return False
    if str(row.get("market_id") or "") != "225":
        return False
    if str(row.get("market_source") or "").strip().lower() != "sportybet nigeria":
        return False
    if not str(row.get("sportybet_event_id") or "").strip():
        return False
    if row.get("quote_capture_basis") != "SportyBet API response observed_at":
        return False
    if "ESPN official scoreboard event ID" not in str(row.get("settlement_source") or ""):
        return False
    published, start, quote = (
        parse_time(row.get("published_at")), parse_time(row.get("start_time")),
        parse_time(row.get("quote_timestamp")),
    )
    if not published or not start or not quote or not (quote <= published < start):
        return False
    age = (published - quote).total_seconds() / 60
    if not 0 <= age <= 15:
        return False
    line = finite_number(row.get("line"))
    over_odds, under_odds = finite_number(row.get("over_odds")), finite_number(row.get("under_odds"))
    final_total = finite_number(row.get("final_total"))
    score = row.get("final_score")
    if line is None or final_total is None or not isinstance(score, list) or len(score) != 2:
        return False
    score_values = [finite_number(value) for value in score]
    if any(value is None for value in score_values) or final_total != sum(score_values):
        return False
    if over_odds is None or under_odds is None or over_odds <= 1 or under_odds <= 1:
        return False
    expected_result = "over" if final_total > line else "under" if final_total < line else "push"
    if str(row.get("result") or "").lower() != expected_result:
        return False
    return str(row.get("pick") or "").lower() in {"over", "under"}


def verified_market_records(rows):
    """Return one independently settled, provenance-verified row per fixture."""
    eligible = [row for row in rows if _roi_grade_record(row)]
    eligible.sort(key=lambda row: (
        str(row.get("published_at") or ""),
        str(row.get("start_time") or ""),
        str(row.get("event_id") or ""),
    ))
    unique = []
    seen_events = set()
    for row in eligible:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id or event_id in seen_events:
            continue
        seen_events.add(event_id)
        unique.append(row)
    return unique


def split_at_fixed_cutoff(rows, timestamp_field):
    """Split immutable records at the one pre-registered UTC cutoff."""
    development, holdout = [], []
    for row in rows or []:
        stamp = parse_time(row.get(timestamp_field)) if isinstance(row, dict) else None
        if stamp is None:
            continue
        if stamp < EVALUATION_CUTOFF_UTC:
            development.append(row)
        else:
            holdout.append(row)
    return development, holdout


def market_record_audit(rows):
    """Expose the exact projection/line/side/price/result for every verified bet."""
    audit = []
    for row in rows:
        pick = str(row.get("pick") or "").lower()
        expected = finite_number(row.get("expected_total"))
        line = finite_number(row.get("line"))
        actual = finite_number(row.get("final_total"))
        over_odds = finite_number(row.get("over_odds"))
        under_odds = finite_number(row.get("under_odds"))
        selected_odds = over_odds if pick == "over" else under_odds
        published = parse_time(row.get("published_at"))
        quote = parse_time(row.get("quote_timestamp"))
        quote_age = (published - quote).total_seconds() / 60 if published and quote else None
        selected_implied = (1.0 / selected_odds) if selected_odds and selected_odds > 1 else None
        total_implied = (
            (1.0 / over_odds) + (1.0 / under_odds)
            if over_odds and under_odds and over_odds > 1 and under_odds > 1 else None
        )
        no_vig_probability = (
            selected_implied / total_implied
            if selected_implied is not None and total_implied else None
        )
        result = str(row.get("result") or "").lower()
        won = pick == result
        is_push = result == "push" or (actual is not None and line is not None and actual == line)
        favorite_side = "over" if over_odds <= under_odds else "under"
        favorite_odds = over_odds if favorite_side == "over" else under_odds
        favorite_won = favorite_side == result
        selected_profit = 0.0 if is_push else (selected_odds - 1.0 if won else -1.0)
        favorite_profit = 0.0 if is_push else (favorite_odds - 1.0 if favorite_won else -1.0)
        audit.append({
            "event_id": str(row.get("event_id") or ""),
            "start_time": row.get("start_time"),
            "matchup": f'{row.get("player_1") or ""} vs {row.get("player_2") or ""}',
            "model_projection": round(expected, 4) if expected is not None else None,
            "sportybet_market_225_line": line,
            "projection_edge_points": round(expected - line, 4) if expected is not None and line is not None else None,
            "selected_side": pick.upper(),
            "over_odds": over_odds,
            "under_odds": under_odds,
            "selected_side_odds": selected_odds,
            "selected_side_profit_units": round(selected_profit, 4),
            "market_favorite_side": favorite_side.upper(),
            "market_favorite_profit_units": round(favorite_profit, 4),
            "no_vig_market_probability_for_selected_side": round(no_vig_probability, 4) if no_vig_probability is not None else None,
            "final_total_including_overtime": actual,
            "actual_minus_market_line": round(actual - line, 4) if actual is not None and line is not None else None,
            "model_projection_error": round(expected - actual, 4) if expected is not None and actual is not None else None,
            "settled_result": result.upper(),
            "won": won,
            "diagnosis": "CORRECT" if won else f'{pick.upper()}_PICK_LOST',
            "quote_age_minutes_at_publication": round(quote_age, 4) if quote_age is not None else None,
            "published_at": row.get("published_at"),
            "quote_timestamp": row.get("quote_timestamp"),
            "publication_snapshot_id": row.get("publication_snapshot_id"),
        })
    return audit


def _bootstrap_roi_lower_bound(profits, resamples=BOOTSTRAP_RESAMPLES):
    """Deterministic fixture-level bootstrap lower 95% bound for mean unit ROI."""
    values = list(profits)
    n = len(values)
    if n < 2:
        return None
    rng = random.Random(20261102 + n)
    means = []
    for _ in range(resamples):
        sample_total = sum(values[rng.randrange(n)] for _ in range(n))
        means.append(sample_total / n)
    means.sort()
    index = max(0, min(len(means) - 1, int(0.025 * (len(means) - 1))))
    return means[index]


def publication_capture_metrics(snapshots, predictions=None, as_of=None):
    """Report immutable revision coverage separately from today's quote availability."""
    checked_at = parse_time(as_of) if as_of is not None else datetime.now(timezone.utc)
    if checked_at is None:
        checked_at = datetime.now(timezone.utc)

    current = [
        row for row in (snapshots or [])
        if isinstance(row, dict) and row.get("totals_model_version") == NBA_TOTALS_MODEL_VERSION
    ]
    valid = []
    for row in current:
        market = ((row.get("markets") or {}).get("total_ou") or {})
        published = parse_time(row.get("published_at"))
        start = parse_time(row.get("start_time"))
        quote = parse_time(market.get("quote_timestamp"))
        try:
            line = float(market.get("line"))
            over = float(market.get("over_odds"))
            under = float(market.get("under_odds"))
        except (TypeError, ValueError):
            continue
        age = (published - quote).total_seconds() / 60 if published and quote else None
        if not (
            row.get("publication_snapshot_verified") is True
            and str(row.get("publication_snapshot_id") or "").strip()
            and str(row.get("event_id") or "").strip()
            and str(market.get("market_id") or "") == "225"
            and str(market.get("source") or "").strip().lower() == "sportybet nigeria"
            and str(market.get("sportybet_event_id") or "").strip()
            and market.get("quote_capture_basis") == "SportyBet API response observed_at"
            and published is not None and start is not None and quote is not None
            and quote <= published < start and age is not None and 0 <= age <= 15
            and 100 <= line <= 300
            and math.isfinite(over) and over > 1 and math.isfinite(under) and under > 1
        ):
            continue
        valid.append(row)

    predictions_by_event = {
        str(row.get("event_id")): row
        for row in (predictions or [])
        if isinstance(row, dict)
        and row.get("totals_model_version") == NBA_TOTALS_MODEL_VERSION
        and row.get("event_id")
    }
    attached_event_ids = set()
    for event_id, row in predictions_by_event.items():
        market = ((row.get("markets") or {}).get("total_ou") or {})
        start = parse_time(row.get("start_time"))
        stamp = parse_time(market.get("quote_timestamp"))
        try:
            line = float(market.get("line"))
            over = float(market.get("over_odds"))
            under = float(market.get("under_odds"))
        except (TypeError, ValueError):
            continue
        age = (checked_at - stamp).total_seconds() / 60 if stamp else None
        if (
            str(market.get("market_id") or "") == "225"
            and str(market.get("source") or "").strip().lower() == "sportybet nigeria"
            and str(market.get("sportybet_event_id") or "").strip()
            and market.get("quote_capture_basis") == "SportyBet API response observed_at"
            and stamp is not None and start is not None
            and stamp <= checked_at < start and age is not None and 0 <= age <= 15
            and 100 <= line <= 300
            and math.isfinite(over) and over > 1 and math.isfinite(under) and under > 1
        ):
            attached_event_ids.add(event_id)

    snapshot_event_ids = {
        str(row.get("event_id")) for row in valid
        if str(row.get("event_id") or "") in predictions_by_event
    }
    predicted_event_ids = set(predictions_by_event)
    unpriced = len(predicted_event_ids - attached_event_ids)
    unmatched = len(attached_event_ids - snapshot_event_ids)
    coverage = round(len(snapshot_event_ids) / len(predicted_event_ids), 4) if predicted_event_ids else None
    picks = [
        row for row in valid
        if str(((row.get("markets") or {}).get("total_ou") or {}).get("pick") or "").lower() in {"over", "under"}
    ]
    no_lean = [
        row for row in valid
        if str(((row.get("markets") or {}).get("total_ou") or {}).get("pick") or "").lower() not in {"over", "under"}
    ]
    if not predicted_event_ids:
        status = "NO_CURRENT_MODEL_PREDICTIONS"
    elif predicted_event_ids <= snapshot_event_ids and unmatched == 0:
        status = "CAPTURED"
    elif valid or attached_event_ids:
        status = "PARTIAL"
    else:
        status = "AWAITING_FRESH_MARKET_225_QUOTES"
    return {
        "model_version": NBA_TOTALS_MODEL_VERSION,
        "model_predictions": len(predicted_event_ids),
        "predictions_with_fresh_sportybet_market_225_pair": len(attached_event_ids),
        "immutable_fresh_publication_snapshots": len(valid),
        "unique_events_with_immutable_snapshots": len(snapshot_event_ids),
        "snapshot_coverage": coverage,
        "directional_pick_snapshots": len(picks),
        "no_clear_lean_snapshots": len(no_lean),
        "unpriced_or_unavailable_prediction_count": unpriced,
        "unmatched_fresh_market_predictions": unmatched,
        "capture_status": status,
    }



def market_metrics(rows):
    profits, favorite_profits = [], []
    wins = losses = pushes = 0
    by_pick = {
        "over": {"n": 0, "wins": 0, "losses": 0, "accuracy": None},
        "under": {"n": 0, "wins": 0, "losses": 0, "accuracy": None},
    }
    for row in rows:
        final_total, line = float(row["final_total"]), float(row["line"])
        outcome = "over" if final_total > line else "under" if final_total < line else "push"
        if outcome == "push":
            pushes += 1
            continue
        pick = str(row["pick"]).lower()
        if pick not in by_pick:
            continue
        odds = float(row["over_odds"] if pick == "over" else row["under_odds"])
        won = pick == outcome
        wins += int(won)
        losses += int(not won)
        by_pick[pick]["n"] += 1
        by_pick[pick]["wins"] += int(won)
        by_pick[pick]["losses"] += int(not won)
        profits.append(odds - 1.0 if won else -1.0)
        favorite = "over" if float(row["over_odds"]) <= float(row["under_odds"]) else "under"
        fav_odds = float(row["over_odds"] if favorite == "over" else row["under_odds"])
        favorite_profits.append(fav_odds - 1.0 if favorite == outcome else -1.0)

    n = len(profits)
    roi = sum(profits) / n if n else None
    lower = _bootstrap_roi_lower_bound(profits)
    favorite_roi = sum(favorite_profits) / len(favorite_profits) if favorite_profits else None
    for values in by_pick.values():
        values["accuracy"] = round(values["wins"] / values["n"], 4) if values["n"] else None
    return {
        "n": n, "wins": wins, "losses": losses, "pushes": pushes,
        "win_rate": round(wins / n, 4) if n else None,
        "over_under_accuracy": round(wins / n, 4) if n else None,
        "by_pick": by_pick,
        "profit_units": round(sum(profits), 4) if n else 0.0,
        "roi": round(roi, 4) if roi is not None else None,
        "roi_ci95_lower": round(lower, 4) if lower is not None else None,
        "roi_ci_method": "deterministic fixture-level percentile bootstrap; 4,000 resamples",
        "market_favorite_roi": round(favorite_roi, 4) if favorite_roi is not None else None,
        "roi_vs_market_favorite": round(roi - favorite_roi, 4) if roi is not None and favorite_roi is not None else None,
    }


def _blend_total(row, weight):
    base = float(row["base_total"])
    pace = row.get("pace_total")
    if row.get("pace_available") is not True or finite_number(pace) is None:
        return base
    return base + weight * (float(pace) - base)


def evaluate(history, ledger, snapshots=None, predictions=None, as_of=None):
    forecasts = build_forecasts(history)
    development, holdout = split_at_fixed_cutoff(forecasts, "date")

    # v5.1 is a frozen model specification shared with live publication and
    # residual-probability calibration. Re-fitting these parameters on the full
    # development window here would evaluate a different model from production.
    selected_weight = NBA_TOTALS_PACE_BLEND_WEIGHT
    bias_correction = NBA_TOTALS_BIAS_CORRECTION
    development_errors = [
        _blend_total(row, selected_weight) - float(row["actual_total"])
        for row in development
    ]

    raw_holdout = [
        {**row, "forecast_total": _blend_total(row, selected_weight)}
        for row in holdout
    ]
    calibrated_holdout = [
        {**row, "forecast_total": row["forecast_total"] - bias_correction}
        for row in raw_holdout
    ]
    model_metrics = regression_metrics(calibrated_holdout, "forecast_total")
    raw_model_metrics = regression_metrics(raw_holdout, "forecast_total")
    baseline_metrics = regression_metrics(holdout, "baseline_total")
    improvement = (
        round(baseline_metrics["mae"] - model_metrics["mae"], 4)
        if model_metrics["mae"] is not None and baseline_metrics["mae"] is not None else None
    )

    publication_capture = publication_capture_metrics(snapshots, predictions, as_of=as_of)
    market_rows = verified_market_records(ledger)
    market_development, market_holdout_rows = split_at_fixed_cutoff(market_rows, "published_at")
    market_holdout = market_metrics(market_holdout_rows)
    market_development_metrics = market_metrics(market_development)
    market_overall = market_metrics(market_rows)
    pace_development_n = sum(row.get("pace_available") is True for row in development)
    pace_holdout_n = sum(row.get("pace_available") is True for row in holdout)
    forecast_ok = (
        model_metrics["n"] >= MIN_FORECAST_HOLDOUT and improvement is not None and improvement > 0
        and model_metrics["bias"] is not None and abs(model_metrics["bias"]) <= 3.0
    )
    market_ok = (
        market_holdout["n"] >= MIN_MARKET_HOLDOUT
        and market_holdout["roi"] is not None and market_holdout["roi"] > 0
        and market_holdout["roi_ci95_lower"] is not None and market_holdout["roi_ci95_lower"] > 0
        and market_holdout["roi_vs_market_favorite"] is not None
        and market_holdout["roi_vs_market_favorite"] > 0
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
        "evaluation_type": "NBA_TOTALS_FIXED_CUTOFF_V2",
        "market_id": "225",
        "market_definition": "full_game_total_including_overtime",
        "model_version": NBA_TOTALS_MODEL_VERSION,
        "history_games": len(clean_history(history)),
        "holdout_protocol": {
            "fixed_cutoff_utc": EVALUATION_CUTOFF_UTC.isoformat(),
            "forecast_timestamp_field": "date",
            "market_timestamp_field": "published_at",
            "rule": "Records before the fixed cutoff are development; records at or after it are prospective holdout. The cutoff never rolls forward.",
            "market_sample_unit": "one verified settled record per unique ESPN fixture ID",
        },
        "walk_forward": {
            "method": "expanding chronological forecasts; every game uses only strictly earlier completed games; prospective holdout begins at the fixed cutoff",
            "baseline": "mean NBA game total over the preceding 90 days (or all prior games when unavailable)",
            "development_games": len(development),
            "holdout": {
                **model_metrics,
                "start_utc": EVALUATION_CUTOFF_UTC.isoformat(),
                "uncalibrated": raw_model_metrics,
                "baseline_mae": baseline_metrics["mae"],
                "baseline_rmse": baseline_metrics["rmse"],
                "baseline_bias": baseline_metrics["bias"],
                "mae_improvement_vs_baseline": improvement,
                "beats_baseline": bool(improvement is not None and improvement > 0),
                "pace_feature_games": pace_holdout_n,
            },
        },
        "model_calibration": {
            "selected_pace_blend_weight": round(selected_weight, 4),
            "production_bias_correction": round(bias_correction, 4),
            "development_n": len(development),
            "development_raw_bias": round(sum(development_errors) / len(development_errors), 4) if development_errors else None,
            "pace_feature_development_games": pace_development_n,
            "pace_feature_coverage": round(pace_development_n / len(development), 4) if development else 0.0,
            "selection_rule": "frozen v5.1 production calibration selected on the pre-registered training window; applied identically to live forecasts and holdout evaluation",
        },
        "publication_capture": publication_capture,
        "verified_market_records": len(market_rows),
        "market_development_records": len(market_development),
        "market_development": market_development_metrics,
        "market_holdout_publications": len(market_holdout_rows),
        "market_overall": market_overall,
        "market_holdout": market_holdout,
        "market_record_audit": market_record_audit(market_rows),
        "release_decision": "QUALIFIED" if forecast_ok and market_ok else "RESEARCH_ONLY",
        "release_reason": (
            "The fixed-cutoff prospective forecast holdout beat the rolling baseline and the untouched, model-version-specific SportyBet market-225 holdout passed the pre-registered ROI and bootstrap confidence checks."
            if forecast_ok and market_ok else
            "Not qualified: require at least 100 forecast games after the frozen cutoff with lower MAE than baseline and absolute bias <=3 points, plus at least 100 unique settled, immutable, fresh SportyBet market-225 bets published after that same cutoff with positive ROI, a positive bootstrap 95% lower bound, and ROI above the market-favourite baseline."
        ),
    }
