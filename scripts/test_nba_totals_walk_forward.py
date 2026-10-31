#!/usr/bin/env python3
"""Offline regression tests for the NBA totals walk-forward evaluator."""
from datetime import datetime, timezone
from nba_totals_walk_forward import build_forecasts, evaluate, verified_market_records
from expansion_pipeline import NBA_TOTALS_MODEL_VERSION


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


def test_market_evidence_rejects_unverified_and_old_model_records():
    published = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    good = {
        "totals_model_version": NBA_TOTALS_MODEL_VERSION,
        "settled": True, "publication_snapshot_verified": True, "roi_eligible": True,
        "quote_fresh_at_publication": True, "price_pair_valid": True, "price_source_verified": True,
        "market_id": "225", "market_source": "SportyBet Nigeria",
        "settlement_source": "ESPN official scoreboard event ID",
        "published_at": published.isoformat(), "start_time": "2026-01-01T11:00:00+00:00",
        "quote_timestamp": "2026-01-01T09:55:00+00:00", "line": 200.5,
        "over_odds": 1.9, "under_odds": 1.9, "final_score": [110, 100],
        "final_total": 210, "result": "over", "pick": "over", "event_id": "g1",
    }
    invalid = dict(good, publication_snapshot_verified=False)
    old_model = dict(good, totals_model_version="old-model")
    assert verified_market_records([good, invalid, old_model]) == [good]


def test_evaluator_never_promotes_without_market_holdout():
    rows = [game(f"g{i}", (i % 28) + 1, "A", "B", 100 + i % 5, 98 + i % 7) for i in range(1, 29)]
    result = evaluate(rows, [])
    assert result["market_holdout"]["n"] == 0
    assert result["release_decision"] == "RESEARCH_ONLY"


if __name__ == "__main__":
    test_walk_forward_does_not_use_current_or_future_games()
    test_market_evidence_rejects_unverified_and_old_model_records()
    test_evaluator_never_promotes_without_market_holdout()
    print("NBA totals walk-forward regression tests: PASS (3 groups)")
