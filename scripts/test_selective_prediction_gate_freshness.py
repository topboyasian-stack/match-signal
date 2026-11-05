#!/usr/bin/env python3
"""Regression tests for current-value quote age and upcoming fixture scope."""
from datetime import datetime, timedelta, timezone
import runpy

GATE = runpy.run_path("scripts/selective_prediction_gate.py")
explicit_value_signal = GATE["explicit_value_signal"]
current_market_evidence = GATE["current_market_evidence"]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def row(*, quote_age_minutes=10, kickoff_minutes=60, edge=0.08, ev=0.12):
    quote_at = NOW - timedelta(minutes=quote_age_minutes)
    kickoff = NOW + timedelta(minutes=kickoff_minutes)
    return {
        "sport": "tennis",
        "start_time": kickoff.isoformat(),
        "odds_timestamp": quote_at.isoformat(),
        "market_insights": {
            "snapshot_at": quote_at.isoformat(),
            "winner_model_edge_vs_market": edge,
            "winner_expected_value": ev,
        },
    }


ok, source, reason = explicit_value_signal(row(), now=NOW)
assert ok is True
assert source == "current_sportybet_winner_edge_ev"
assert reason is None

ok, source, reason = explicit_value_signal(row(quote_age_minutes=16), now=NOW)
assert ok is False and source is None
assert reason == "sportybet_quote_older_than_15m"

ok, source, reason = explicit_value_signal(row(kickoff_minutes=13 * 60), now=NOW)
assert ok is False and source is None
assert reason == "fixture_outside_12h_builder_horizon"

ok, source, reason = explicit_value_signal(row(kickoff_minutes=-1), now=NOW)
assert ok is False and source is None
assert reason == "fixture_already_started"

future = row(quote_age_minutes=-5)
ok, source, reason = explicit_value_signal(future, now=NOW)
assert ok is False and source is None
assert reason == "sportybet_snapshot_timestamp_in_future"

no_value = row(edge=0.01, ev=-0.02)
ok, source, reason = explicit_value_signal(no_value, now=NOW)
assert ok is False and source is None
assert reason == "current_quote_has_no_qualifying_value"

legacy = row()
legacy["market_insights"] = {}
legacy["edge"] = 0.08
legacy["value"] = {"expected_value": 0.12}
legacy["sportybet_market_snapshot"] = {"fetched_at": legacy["odds_timestamp"]}
ok, source, reason = explicit_value_signal(legacy, now=NOW)
assert ok is True and source == "frozen_market_edge_ev"

print("Selective gate freshness and kickoff-horizon regressions passed.")
