#!/usr/bin/env python3
"""Regression tests for current-value quote age and upcoming fixture scope."""
from datetime import datetime, timedelta, timezone
import runpy

GATE = runpy.run_path("scripts/selective_prediction_gate.py")
explicit_value_signal = GATE["explicit_value_signal"]
current_market_evidence = GATE["current_market_evidence"]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def row(*, quote_age_minutes=10, kickoff_minutes=60, model_age_minutes=30, edge=0.08, ev=0.12):
    quote_at = NOW - timedelta(minutes=quote_age_minutes)
    kickoff = NOW + timedelta(minutes=kickoff_minutes)
    calculated_at = NOW - timedelta(minutes=model_age_minutes)
    return {
        "sport": "tennis",
        "start_time": kickoff.isoformat(),
        "calculated_at": calculated_at.isoformat(),
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

stale_model = row(model_age_minutes=13 * 60)
ok, source, reason = explicit_value_signal(stale_model, now=NOW)
assert ok is False and source is None
assert reason == "model_prediction_older_than_12h"

missing_model_time = row()
missing_model_time.pop("calculated_at")
ok, source, reason = explicit_value_signal(missing_model_time, now=NOW)
assert ok is False and source is None
assert reason == "missing_or_invalid_model_prediction_time"

after_kickoff_model = row()
after_kickoff_model["calculated_at"] = (NOW + timedelta(hours=2)).isoformat()
ok, source, reason = explicit_value_signal(after_kickoff_model, now=NOW)
assert ok is False and source is None
assert reason == "model_prediction_after_kickoff"


print("Selective gate quote, model-age and kickoff-horizon regressions passed.")
