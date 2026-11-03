#!/usr/bin/env python3
"""Offline regression tests for the NBA totals walk-forward evaluator."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import nba_totals_walk_forward as evaluator
from nba_totals_walk_forward import (
    build_forecasts, clean_history, evaluate, market_metrics, publication_capture_metrics,
    verified_market_records, split_at_fixed_cutoff, market_record_audit,
    EVALUATION_CUTOFF_UTC,
)
from expansion_pipeline import (NBA_TOTALS_MODEL_VERSION, NBA_TOTALS_PACE_BLEND_WEIGHT, NBA_TOTALS_BIAS_CORRECTION)


def game(event_id, day, home, away, hs, aws):
    return {"event_id": event_id, "date": f"2026-01-{day:02d}T00:00:00+00:00",
            "home": home, "away": away, "home_score": hs, "away_score": aws}


def test_walk_forward_does_not_use_current_or_future_games():
    rows = [
        game("g1", 1, "A", "B", 100, 90),
        game("g2", 2, "C", "D", 110, 100),
        game("g3", 3, "A", "C", 105, 95),
        game("g4", 4, "B", "D", 99, 101),
        game("g5", 5, "A", "D", 102, 98),
    ]
    baseline = build_forecasts(rows, min_prior_games=2)
    with_future = build_forecasts(rows + [game("future", 6, "A", "B", 250, 240)], min_prior_games=2)
    assert baseline and with_future
    assert baseline[0]["event_id"] == with_future[0]["event_id"] == "g3"
    assert baseline[0]["model_total"] == with_future[0]["model_total"]
    assert baseline[0]["prior_games"] == 2



def test_same_date_games_share_a_prior_only_history_snapshot():
    rows = []
    base_day = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    for i in range(40):
        day = base_day + timedelta(days=i)
        rows.append({
            "event_id": f"prior-{i}",
            "date": day.isoformat(),
            "home": f"Home{i}", "away": f"Away{i}",
            "home_score": 100 + i % 8, "away_score": 95 + i % 7,
        })
    # Team-game logs contain the same end-of-day stamp for every game on a
    # local date. Their conservative evaluation timestamps therefore tie.
    same_day_date = "2026-02-11T04:59:59.999999+00:00"
    rows.extend([
        {"event_id":"same-day-a","date":same_day_date,"source":"nba_data_v2_team_game_logs",
         "home":"A","away":"B","home_score":250,"away_score":240},
        {"event_id":"same-day-b","date":same_day_date,"source":"nba_data_v2_team_game_logs",
         "home":"C","away":"D","home_score":80,"away_score":75},
    ])
    observed_prior = {}
    def capture_components(game_row, prior_rows):
        observed_prior[game_row["event_id"]] = [row["event_id"] for row in prior_rows]
        return {"base_total": 220.0, "pace_total": None, "pace_available": False}

    with patch.object(evaluator, "nba_total_components", side_effect=capture_components):
        forecasts = evaluator.build_forecasts(rows, min_prior_games=40)

    same_day_forecasts = {
        row["event_id"]: row for row in forecasts
        if row["event_id"] in {"same-day-a", "same-day-b"}
    }
    assert set(same_day_forecasts) == {"same-day-a", "same-day-b"}
    assert same_day_forecasts["same-day-a"]["prior_games"] == 40
    assert same_day_forecasts["same-day-b"]["prior_games"] == 40
    assert observed_prior["same-day-a"] == observed_prior["same-day-b"]
    assert "same-day-a" not in observed_prior["same-day-a"]
    assert "same-day-b" not in observed_prior["same-day-a"]
    assert "same-day-a" not in observed_prior["same-day-b"]
    assert "same-day-b" not in observed_prior["same-day-b"]



def test_date_only_nba_game_dates_cannot_cross_the_frozen_cutoff():
    # The upstream NBA team-game-log feed exposes a local game date, which is
    # normalized to end-of-day Eastern to avoid same-day score leakage. The
    # cutoff is 2026-11-02 02:00 UTC (21:00 ET on Nov 1), so treating that
    # end-of-day timestamp as the forecast timestamp wrongly promotes Nov 1
    # games that may have tipped before the cutoff.
    rows = [
        {
            "event_id": "nba-date-only-before-cutoff",
            "date": "2026-11-02T04:59:59.999999+00:00",
            "source": "nba_data_v2_team_game_logs",
            "home": "A", "away": "B", "home_score": 100, "away_score": 90,
        },
        {
            "event_id": "nba-exact-start-after-cutoff",
            "date": "2026-11-02T04:59:59.999999+00:00",
            "start_time": "2026-11-02T02:30:00+00:00",
            "source": "nba_data_v2_team_game_logs",
            "home": "C", "away": "D", "home_score": 105, "away_score": 95,
        },
        {
            "event_id": "nba-next-local-day",
            "date": "2026-11-03T04:59:59.999999+00:00",
            "source": "nba_data_v2_team_game_logs",
            "home": "E", "away": "F", "home_score": 110, "away_score": 100,
        },
    ]
    cleaned = clean_history(rows)
    development, holdout = split_at_fixed_cutoff(cleaned, "forecast_timestamp")
    assert [row["event_id"] for row in development] == ["nba-date-only-before-cutoff"]
    assert {row["event_id"] for row in holdout} == {
        "nba-exact-start-after-cutoff", "nba-next-local-day"
    }
    assert all(
        datetime.fromisoformat(row["forecast_timestamp"]) < EVALUATION_CUTOFF_UTC
        for row in development
    )
    assert all(
        datetime.fromisoformat(row["forecast_timestamp"]) >= EVALUATION_CUTOFF_UTC
        for row in holdout
    )


def test_evaluator_uses_the_same_frozen_v51_parameters_as_live_model():
    rows = [
        game(f"cal-{i}", (i % 28) + 1, f"Team {i % 4}", f"Team {(i + 1) % 4}", 105 + i % 7, 102 + i % 5)
        for i in range(1, 29)
    ]
    report = evaluate(rows, [])
    assert report["model_version"] == NBA_TOTALS_MODEL_VERSION
    assert report["model_calibration"]["selected_pace_blend_weight"] == NBA_TOTALS_PACE_BLEND_WEIGHT
    assert report["model_calibration"]["production_bias_correction"] == NBA_TOTALS_BIAS_CORRECTION
    assert NBA_TOTALS_MODEL_VERSION == "nba-total-v5.1-pace-efficiency-calibrated"


def test_market_evidence_rejects_unverified_and_old_model_records():
    published = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    good = {
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "settled": True, "publication_snapshot_verified": True, "roi_eligible": True,
        "quote_fresh_at_publication": True, "price_pair_valid": True, "price_source_verified": True,
        "market_id": "225", "market_source": "SportyBet Nigeria",
        "sportybet_event_id": "sr:match:test-001",
        "quote_capture_basis": "SportyBet API response observed_at",
        "settlement_source": "ESPN official scoreboard event ID",
        "published_at": published.isoformat(), "start_time": "2026-01-01T11:00:00+00:00",
        "quote_timestamp": "2026-01-01T09:55:00+00:00", "line": 200.5,
        "over_odds": 1.9, "under_odds": 1.9, "final_score": [110, 100],
        "final_total": 210, "result": "over", "pick": "over", "event_id": "g1",
    }
    invalid = dict(good, publication_snapshot_verified=False)
    old_model = dict(good, totals_model_version="old-model")
    untraceable = dict(good, sportybet_event_id=None)
    assert verified_market_records([good, invalid, old_model, untraceable]) == [good]
    metrics = market_metrics([good, dict(good, event_id="g2", pick="under")])
    assert metrics["by_pick"]["over"]["n"] == 1
    assert metrics["by_pick"]["over"]["accuracy"] == 1.0
    assert metrics["by_pick"]["under"]["n"] == 1
    assert metrics["by_pick"]["under"]["accuracy"] == 0.0



def test_publication_capture_is_separate_from_settlement_and_roi():
    published = "2026-10-31T20:45:00+00:00"
    snapshot = {
        "event_id": "espn-1",
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "published_at": published,
        "start_time": "2026-10-31T22:00:00+00:00",
        "publication_snapshot_id": "nba-total-pub:test-001",
        "publication_snapshot_verified": True,
        "markets": {"total_ou": {
            "market_id": "225", "source": "SportyBet Nigeria",
            "sportybet_event_id": "sr:match:test-001",
            "quote_capture_basis": "SportyBet API response observed_at",
            "quote_timestamp": "2026-10-31T20:44:30+00:00",
            "line": 212.5, "over_odds": 1.97, "under_odds": 1.88,
            "pick": None,
        }},
    }
    prediction = {
        "event_id": "espn-1", "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "start_time": "2026-10-31T22:00:00+00:00",
        "markets": {"total_ou": {
            "market_id": "225", "source": "SportyBet Nigeria",
            "sportybet_event_id": "sr:match:test-001",
            "quote_capture_basis": "SportyBet API response observed_at",
            "quote_timestamp": "2026-10-31T20:44:30+00:00",
            "line": 212.5, "over_odds": 1.97, "under_odds": 1.88,
        }},
        "generated_at": published,
    }
    result = publication_capture_metrics([snapshot], [prediction], as_of="2026-10-31T20:45:30+00:00")
    assert result["model_predictions"] == 1
    assert result["predictions_with_fresh_sportybet_market_225_pair"] == 1
    assert result["immutable_fresh_publication_snapshots"] == 1
    assert result["directional_pick_snapshots"] == 0
    assert result["no_clear_lean_snapshots"] == 1
    assert result["capture_status"] == "CAPTURED"



def test_capture_status_is_partial_until_every_v5_forecast_has_a_frozen_price_pair():
    from nba_totals_walk_forward import publication_capture_metrics
    published = "2026-10-31T20:45:00+00:00"
    snapshot = {
        "event_id": "g1",
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "published_at": published,
        "start_time": "2026-10-31T22:00:00+00:00",
        "publication_snapshot_id": "nba-total-pub:g1",
        "publication_snapshot_verified": True,
        "markets": {"total_ou": {
            "market_id": "225", "source": "SportyBet Nigeria",
            "sportybet_event_id": "sr:match:g1",
            "quote_capture_basis": "SportyBet API response observed_at",
            "quote_timestamp": "2026-10-31T20:44:30+00:00",
            "line": 212.5, "over_odds": 1.97, "under_odds": 1.88,
            "pick": None,
        }},
    }
    def prediction(event_id):
        return {
            "event_id": event_id,
            "totals_model_version": NBA_TOTALS_MODEL_VERSION,
            "generated_at": published,
            "start_time": "2026-10-31T22:00:00+00:00",
            "markets": {"total_ou": {
                "market_id": "225", "source": "SportyBet Nigeria",
                "sportybet_event_id": "sr:match:" + event_id,
                "quote_capture_basis": "SportyBet API response observed_at",
                "quote_timestamp": "2026-10-31T20:44:30+00:00",
                "line": 212.5, "over_odds": 1.97, "under_odds": 1.88,
            }},
        }
    as_of = "2026-10-31T20:45:30+00:00"
    partial = publication_capture_metrics([snapshot], [prediction("g1"), prediction("g2")], as_of=as_of)
    assert partial["capture_status"] == "PARTIAL"
    assert partial["snapshot_coverage"] == 0.5
    assert partial["immutable_fresh_publication_snapshots"] == 1
    assert partial["unmatched_fresh_market_predictions"] == 1

    second_snapshot = dict(snapshot, event_id="g2", publication_snapshot_id="nba-total-pub:g2")
    second_market = dict(snapshot["markets"]["total_ou"], sportybet_event_id="sr:match:g2")
    second_snapshot["markets"] = {"total_ou": second_market}
    complete = publication_capture_metrics(
        [snapshot, second_snapshot], [prediction("g1"), prediction("g2")], as_of=as_of
    )
    assert complete["capture_status"] == "CAPTURED"
    assert complete["snapshot_coverage"] == 1.0

    stale_prediction = prediction("g1")
    stale_prediction["markets"]["total_ou"]["quote_timestamp"] = "2026-10-31T20:20:00+00:00"
    waiting = publication_capture_metrics([], [stale_prediction], as_of=as_of)
    assert waiting["capture_status"] == "AWAITING_FRESH_MARKET_225_QUOTES"
    empty = publication_capture_metrics([], [])
    assert empty["capture_status"] == "NO_CURRENT_MODEL_PREDICTIONS"

    # The full evaluator must retain the supplied forecast rows; its internal
    # calibration candidates must not shadow the external prediction list.
    full_report = evaluate(
        [game("h1", 1, "A", "B", 100, 90), game("h2", 2, "C", "D", 101, 99)],
        [],
        [snapshot],
        [prediction("g1")],
        as_of=as_of,
    )
    assert full_report["publication_capture"]["model_predictions"] == 1
    assert full_report["publication_capture"]["immutable_fresh_publication_snapshots"] == 1


def test_fixed_holdout_cutoff_unique_fixture_and_market_audit():
    base = {
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "settled": True, "publication_snapshot_verified": True, "roi_eligible": True,
        "quote_fresh_at_publication": True, "price_pair_valid": True, "price_source_verified": True,
        "market_id": "225", "market_source": "SportyBet Nigeria",
        "sportybet_event_id": "sr:match:fixed-cutoff-test",
        "quote_capture_basis": "SportyBet API response observed_at",
        "settlement_source": "ESPN official scoreboard event ID",
        "published_at": "2026-01-01T10:00:00+00:00",
        "start_time": "2026-01-01T11:00:00+00:00",
        "quote_timestamp": "2026-01-01T09:55:00+00:00",
        "line": 200.5, "over_odds": 1.9, "under_odds": 1.9,
        "final_score": [110, 100], "final_total": 210,
        "result": "over", "pick": "over", "event_id": "fixed-past",
        "expected_total": 205.0, "player_1": "Team A", "player_2": "Team B",
        "publication_snapshot_id": "nba-total-pub:fixed-past",
    }
    duplicate = dict(
        base,
        published_at="2026-01-01T10:01:00+00:00",
        quote_timestamp="2026-01-01T10:00:00+00:00",
        publication_snapshot_id="nba-total-pub:fixed-past-revision",
    )
    future = dict(
        base,
        event_id="fixed-future",
        sportybet_event_id="sr:match:fixed-future",
        published_at="2026-11-03T10:00:00+00:00",
        start_time="2026-11-03T11:00:00+00:00",
        quote_timestamp="2026-11-03T09:55:00+00:00",
        pick="under",
        publication_snapshot_id="nba-total-pub:fixed-future",
    )

    eligible = verified_market_records([base, duplicate, future])
    assert [row["event_id"] for row in eligible] == ["fixed-past", "fixed-future"], (
        "multiple price revisions for one fixture must never become multiple settled bets"
    )
    development, holdout = split_at_fixed_cutoff(eligible, "published_at")
    assert EVALUATION_CUTOFF_UTC.isoformat() == "2026-11-02T02:00:00+00:00"
    assert [row["event_id"] for row in development] == ["fixed-past"]
    assert [row["event_id"] for row in holdout] == ["fixed-future"]

    result = evaluate([], [base, duplicate, future])
    assert result["market_development_records"] == 1
    assert result["market_holdout_publications"] == 1
    assert result["market_holdout"]["n"] == 1
    assert result["release_decision"] == "RESEARCH_ONLY"

    audit = market_record_audit(eligible)
    assert audit[0]["model_projection_error"] == -5.0
    assert audit[0]["projection_edge_points"] == 4.5
    assert audit[0]["over_odds"] == 1.9 and audit[0]["under_odds"] == 1.9
    assert audit[0]["selected_side_profit_units"] == 0.9
    assert audit[0]["market_favorite_profit_units"] == 0.9
    assert audit[0]["diagnosis"] == "CORRECT"
    metrics = market_metrics(eligible)
    assert metrics["roi_ci_method"].startswith("deterministic fixture-level percentile bootstrap")
    assert metrics["roi_ci95_lower"] is not None


def test_evaluator_never_promotes_without_market_holdout():
    rows = [game(f"g{i}", (i % 28) + 1, "A", "B", 100 + i % 5, 98 + i % 7) for i in range(1, 29)]
    result = evaluate(rows, [])
    assert result["market_holdout"]["n"] == 0
    assert result["release_decision"] == "RESEARCH_ONLY"


if __name__ == "__main__":
    test_walk_forward_does_not_use_current_or_future_games()
    test_same_date_games_share_a_prior_only_history_snapshot()
    test_evaluator_uses_the_same_frozen_v51_parameters_as_live_model()
    test_market_evidence_rejects_unverified_and_old_model_records()
    test_publication_capture_is_separate_from_settlement_and_roi()
    test_capture_status_is_partial_until_every_v5_forecast_has_a_frozen_price_pair()
    test_fixed_holdout_cutoff_unique_fixture_and_market_audit()
    test_evaluator_never_promotes_without_market_holdout()
    print("NBA totals walk-forward regression tests: PASS (8 groups)")
