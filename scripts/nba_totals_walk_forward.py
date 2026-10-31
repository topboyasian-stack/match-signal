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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from expansion_pipeline import NBA_TOTALS_MODEL_VERSION, nba_total_components, dt as parse_time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "nba_history.json"
LEDGER = DATA / "nba_totals_ledger.json"
OUTPUT = DATA / "nba_totals_oos_value_test.json"
MIN_PRIOR_GAMES = 40
HOLDOUT_FRACTION = 0.20
BASELINE_DAYS = 90
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
    return sorted(
        [row for row in rows if _roi_grade_record(row)],
        key=lambda row: (str(row.get("start_time") or ""), str(row.get("event_id") or "")),
    )


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
    if n >= 2:
        variance = sum((value - roi) ** 2 for value in profits) / (n - 1)
        lower = roi - 1.96 * math.sqrt(variance / n)
    else:
        lower = None
    favorite_roi = sum(favorite_profits) / len(favorite_profits) if favorite_profits else None
    for side, values in by_pick.items():
        values["accuracy"] = round(values["wins"] / values["n"], 4) if values["n"] else None
    return {
        "n": n, "wins": wins, "losses": losses, "pushes": pushes,
        "win_rate": round(wins / n, 4) if n else None,
        "over_under_accuracy": round(wins / n, 4) if n else None,
        "by_pick": by_pick,
        "profit_units": round(sum(profits), 4) if n else 0.0,
        "roi": round(roi, 4) if roi is not None else None,
        "roi_ci95_lower": round(lower, 4) if lower is not None else None,
        "market_favorite_roi": round(favorite_roi, 4) if favorite_roi is not None else None,
        "roi_vs_market_favorite": round(roi - favorite_roi, 4) if roi is not None and favorite_roi is not None else None,
    }

def _blend_total(row, weight):
    base = float(row["base_total"])
    pace = row.get("pace_total")
    if row.get("pace_available") is not True or finite_number(pace) is None:
        return base
    return base + weight * (float(pace) - base)


def evaluate(history, ledger):
    forecasts = build_forecasts(history)
    split = int(len(forecasts) * (1.0 - HOLDOUT_FRACTION))
    development, holdout = forecasts[:split], forecasts[split:]

    # Choose the pace contribution and residual correction on development only.
    grid = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    candidates = []
    for weight in grid:
        predictions = [_blend_total(row, weight) for row in development]
        actuals = [float(row["actual_total"]) for row in development]
        errors = [prediction - actual for prediction, actual in zip(predictions, actuals)]
        mae = sum(abs(error) for error in errors) / len(errors) if errors else float("inf")
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else float("inf")
        candidates.append((mae, rmse, weight))
    selected_weight = min(candidates)[2] if candidates else 0.0
    development_errors = [
        _blend_total(row, selected_weight) - float(row["actual_total"])
        for row in development
    ]
    bias_correction = sum(development_errors) / len(development_errors) if development_errors else 0.0

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

    market_rows = verified_market_records(ledger)
    market_split = int(len(market_rows) * (1.0 - HOLDOUT_FRACTION))
    market_holdout = market_metrics(market_rows[market_split:])
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
        "evaluation_type": "NBA_TOTALS_WALK_FORWARD_V1",
        "market_id": "225",
        "market_definition": "full_game_total_including_overtime",
        "model_version": NBA_TOTALS_MODEL_VERSION,
        "history_games": len(clean_history(history)),
        "walk_forward": {
            "method": "expanding chronological forecasts; each game uses only strictly earlier completed games",
            "baseline": "mean NBA game total over the preceding 90 days (or all prior games when unavailable)",
            "development_games": len(development),
            "holdout": {
                **model_metrics,
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
            "selection_rule": "minimum development MAE across a predeclared pace blend grid; residual bias estimated on development only",
        },
        "verified_market_records": len(market_rows),
        "market_development_records": market_split,
        "market_overall": market_overall,
        "market_holdout": market_holdout,
        "release_decision": "QUALIFIED" if forecast_ok and market_ok else "RESEARCH_ONLY",
        "release_reason": (
            "Chronological calibrated score forecasts beat the rolling baseline and the untouched, model-version-specific SportyBet holdout passed the pre-registered ROI and confidence checks."
            if forecast_ok and market_ok else
            "Not qualified: require at least 100 unseen calibrated forecast games with lower MAE than baseline and absolute bias <=3 points, plus at least 100 settled, immutable, fresh SportyBet market-225 holdout bets with positive ROI, a positive 95% lower confidence bound, and ROI above the market-favourite baseline."
        ),
    }

def main():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    ledger_payload = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []
    ledger = ledger_payload.get("records", []) if isinstance(ledger_payload, dict) else ledger_payload
    result = evaluate(history, ledger if isinstance(ledger, list) else [])
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
