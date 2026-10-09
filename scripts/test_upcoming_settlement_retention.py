#!/usr/bin/env python3
"""Regression tests for Upcoming settlement expiry and eFootball desk learning."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import unified_upcoming as upcoming
import efootball_desk_learning as learning


def iso(value):
    return value.isoformat()


def check_settled_fixture_is_shown_during_grace_then_hidden():
    original_now = upcoming.NOW
    original_horizon = upcoming.HORIZON
    original_details = upcoming.SETTLED_DETAILS
    try:
        kickoff = datetime(2026, 10, 8, 16, 42, tzinfo=timezone.utc)
        settled_at = datetime(2026, 10, 8, 17, 15, tzinfo=timezone.utc)
        now = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc)
        history = {
            "product": "efootball_gt",
            "event_id": "reused-session-id",
            "timestamp": iso(kickoff),
            "participant_1": "SPARTAN",
            "participant_2": "DART",
            "settled_at": iso(settled_at),
            "score": "2:1",
            "win": True,
        }
        key = upcoming.virtual_fixture_key(history)
        upcoming.SETTLED_DETAILS = {key: history}
        upcoming.NOW = now
        upcoming.HORIZON = now + timedelta(days=7)
        row = {
            "sport": "virtual",
            "product": "efootball_gt",
            "event_id": "reused-session-id",
            "start_time": iso(kickoff),
            "player_1": "Manchester City (SPARTAN)",
            "player_2": "FC Bayern (DART)",
            "market": "over_under",
            "line": 2.5,
            "pick": "over",
        }
        kept = []
        upcoming.add(kept, dict(row))
        assert len(kept) == 1, "Settled result should remain briefly visible"
        assert kept[0].get("event_state") == "SETTLED"
        assert kept[0].get("settlement_result") == "over"
        assert kept[0].get("final_score") == "2:1"

        upcoming.NOW = datetime(2026, 10, 8, 19, 30, tzinfo=timezone.utc)
        upcoming.HORIZON = upcoming.NOW + timedelta(days=7)
        expired = []
        upcoming.add(expired, dict(row))
        assert expired == [], "Settled result should disappear after two-hour grace"
        assert history["score"] == "2:1", "Archival source must remain untouched"
    finally:
        upcoming.NOW = original_now
        upcoming.HORIZON = original_horizon
        upcoming.SETTLED_DETAILS = original_details


def check_reused_event_id_does_not_hide_a_different_fixture():
    original_now = upcoming.NOW
    original_horizon = upcoming.HORIZON
    original_details = upcoming.SETTLED_DETAILS
    try:
        old_kickoff = datetime(2026, 10, 8, 16, 42, tzinfo=timezone.utc)
        new_kickoff = datetime(2026, 10, 8, 16, 46, tzinfo=timezone.utc)
        settled_at = datetime(2026, 10, 8, 16, 44, tzinfo=timezone.utc)
        now = datetime(2026, 10, 8, 16, 45, tzinfo=timezone.utc)
        history = {
            "product": "efootball_gt",
            "event_id": "reused-session-id",
            "timestamp": iso(old_kickoff),
            "participant_1": "SPARTAN",
            "participant_2": "DART",
            "settled_at": iso(settled_at),
            "score": "2:1",
            "win": True,
        }
        upcoming.SETTLED_DETAILS = {upcoming.virtual_fixture_key(history): history}
        upcoming.NOW = now
        upcoming.HORIZON = now + timedelta(days=7)
        new_row = {
            "sport": "virtual",
            "product": "efootball_gt",
            "event_id": "reused-session-id",
            "start_time": iso(new_kickoff),
            "player_1": "England (CLINICAL)",
            "player_2": "Spain (BULLFROG)",
            "market": "over_under",
            "line": 2.5,
            "pick": "over",
        }
        rows = []
        upcoming.add(rows, new_row)
        assert len(rows) == 1, "A reused provider ID must not falsely settle a different match"
        assert rows[0].get("event_state") != "SETTLED"
    finally:
        upcoming.NOW = original_now
        upcoming.HORIZON = original_horizon
        upcoming.SETTLED_DETAILS = original_details


def check_desk_forecast_reconciles_by_fixture_and_score():
    kickoff = datetime(2026, 10, 8, 16, 42, tzinfo=timezone.utc)
    settled_at = datetime(2026, 10, 8, 16, 50, tzinfo=timezone.utc)
    history_row = {
        "product": "efootball_gt",
        "event_id": "reused-session-id",
        "timestamp": iso(kickoff),
        "participant_1": "SPARTAN",
        "participant_2": "DART",
        "market": "ou",
        "line": 2.5,
        "selection": "over",
        "win": True,
        "score": "2:1",
        "settled_at": iso(settled_at),
    }
    forecast = {
        "event_id": "reused-session-id",
        "product": "efootball_gt",
        "start_time": iso(kickoff),
        "participant_1": "Manchester City (SPARTAN)",
        "participant_2": "FC Bayern (DART)",
        "line": 2.5,
        "pick": "over",
        "model_probability": 0.70,
        "observed_at": iso(kickoff - timedelta(minutes=5)),
        "settled": False,
    }
    history_index = learning.settlement_index([history_row])
    learning.reconcile([forecast], history_index)
    assert forecast.get("scored_forecast") is True, "Pre-kickoff forecast must reconcile to settlement"
    assert forecast.get("win") is True
    assert forecast.get("actual_result") == "over"
    assert forecast.get("score") == "2:1"


def check_past_unsettled_fixtures_are_hidden_but_live_fixtures_remain():
    original_now = upcoming.NOW
    original_horizon = upcoming.HORIZON
    original_details = upcoming.SETTLED_DETAILS
    original_event_ids = upcoming.SETTLED_EVENT_IDS
    original_match_keys = upcoming.SETTLED_MATCH_KEYS
    try:
        now = datetime(2026, 10, 9, 13, 55, tzinfo=timezone.utc)
        kickoff = now - timedelta(hours=3)
        upcoming.NOW = now
        upcoming.HORIZON = now + timedelta(days=7)
        upcoming.SETTLED_DETAILS = {}
        upcoming.SETTLED_EVENT_IDS = set()
        upcoming.SETTLED_MATCH_KEYS = set()
        stale = {
            "sport": "football",
            "event_id": "past-unsettled-fixture-test",
            "start_time": iso(kickoff),
            "player_1": "Home FC",
            "player_2": "Away FC",
        }
        rows = []
        upcoming.add(rows, dict(stale))
        assert rows == [], "A past-kickoff non-live fixture must not remain on Upcoming"

        live = {
            **stale,
            "event_id": "active-live-fixture-test",
            "live": True,
            "match_status": "LIVE",
        }
        live_rows = []
        upcoming.add(live_rows, live)
        assert len(live_rows) == 1, "An explicitly live fixture must remain visible"
        assert live_rows[0].get("event_state") == "LIVE"
    finally:
        upcoming.NOW = original_now
        upcoming.HORIZON = original_horizon
        upcoming.SETTLED_DETAILS = original_details
        upcoming.SETTLED_EVENT_IDS = original_event_ids
        upcoming.SETTLED_MATCH_KEYS = original_match_keys


def check_learning_capture_covers_each_virtual_product():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    products = {"efootball_gt", "efootball_adriatic", "vfootball", "zoom"}
    rows = [
        {
            "product": product,
            "sport": "virtual",
            "event_id": "capture-" + product,
            "start_time": iso(future),
            "player_1": "Home (HANDLE_A)",
            "player_2": "Away (HANDLE_B)",
            "market": "over_under",
            "line": 7.5,
            "pick": "under",
            "probability": 0.80,
        }
        for product in products
    ]
    captured = learning.eligible_current_rows({"events": rows})
    assert {row["product"] for row in captured} == products, "Each virtual product must be captured independently"


def check_each_totals_line_is_scored_independently():
    kickoff = datetime(2026, 10, 8, 16, 42, tzinfo=timezone.utc)
    settled_at = datetime(2026, 10, 8, 16, 50, tzinfo=timezone.utc)
    history_row = {
        "product": "efootball_gt",
        "event_id": "same-fixture-many-lines",
        "timestamp": iso(kickoff),
        "participant_1": "SPARTAN",
        "participant_2": "DART",
        "market": "ou",
        "line": 7.5,
        "selection": "under",
        "win": False,
        "score": "4:5",
        "settled_at": iso(settled_at),
    }
    forecasts = []
    for line, pick, p in ((4.5, "over", 0.82), (7.5, "under", 0.90), (8.5, "under", 0.88)):
        forecasts.append({
            "product": "efootball_gt",
            "event_id": "same-fixture-many-lines",
            "start_time": iso(kickoff),
            "participant_1": "Home (SPARTAN)",
            "participant_2": "Away (DART)",
            "line": line,
            "pick": pick,
            "model_probability": p,
            "observed_at": iso(kickoff - timedelta(minutes=5)),
            "settled": False,
        })
    index = learning.settlement_index([history_row])
    learning.reconcile(forecasts, index)
    results = {(row["line"], row["pick"]): row for row in forecasts}
    assert results[(4.5, "over")].get("scored_forecast") is True
    assert results[(4.5, "over")].get("win") is True
    assert results[(7.5, "under")].get("scored_forecast") is True
    assert results[(7.5, "under")].get("win") is False
    assert results[(8.5, "under")].get("scored_forecast") is True
    assert results[(8.5, "under")].get("win") is False
    profiles = learning.exact_profiles(learning.settled_forecasts(forecasts))
    gt = profiles["efootball_gt"]
    assert gt["7.5|under"]["n"] == 1 and gt["7.5|under"]["wins"] == 0
    assert gt["8.5|under"]["n"] == 1 and gt["8.5|under"]["wins"] == 0


def check_exact_profiles_do_not_pool_products_and_calibration_requires_evidence():
    source = (ROOT / "scripts" / "unified_upcoming.py").read_text(encoding="utf-8")
    assert "desk_learning_calibration" not in source, "Virtual event builder must not use the removed global calibration variable"
    forecasts = [
        {"product": "efootball_gt", "line": 7.5, "pick": "under", "win": False, "model_probability": 0.90},
        {"product": "vfootball", "line": 7.5, "pick": "under", "win": True, "model_probability": 0.82},
    ]
    profiles = learning.exact_profiles(forecasts)
    assert profiles["efootball_gt"]["7.5|under"]["n"] == 1
    assert profiles["efootball_gt"]["7.5|under"]["wins"] == 0
    assert profiles["vfootball"]["7.5|under"]["n"] == 1
    assert profiles["vfootball"]["7.5|under"]["wins"] == 1

    # A real sample size of 15 still gets only a one-third shrinkage toward
    # the observed calibration offset; this is a confidence correction, not
    # permission to qualify a line for betting.
    observed_offset = -0.20522608695652178
    exact_weight = 15 / (15 + 30)
    exact_report = {"exact_selection": {
        "8.5|under": {
            "n": 15, "calibration_offset": observed_offset,
            "calibration_weight": exact_weight, "accuracy": 11 / 15,
        }
    }, "calibration": {"active": False, "buckets": {}}}
    raw_probability = 0.8574
    p, source, detail = upcoming.calibrate_desk_probability(raw_probability, 8.5, "under", exact_report)
    assert abs(p - (raw_probability + observed_offset * exact_weight)) < 1e-9
    assert p < raw_probability, "Observed underperformance must lower the U8.5 Under estimate"
    assert source == "EXACT_LINE_DIRECTION"
    assert detail["n"] == 15

    immature_report = {"exact_selection": {
        "7.5|under": {
            "n": 11, "calibration_offset": -0.25,
            "calibration_weight": 11 / (11 + 30), "accuracy": 0.50,
        }
    }, "calibration": {"active": True, "buckets": {
        "0.9": {"n": 29, "calibration_offset": -0.20, "calibration_weight": 0.49}
    }}}
    p, source, _ = upcoming.calibrate_desk_probability(0.90, 7.5, "under", immature_report)
    assert abs(p - 0.90) < 1e-9
    assert source == "NONE", "A global active flag must not bypass exact and bucket sample gates"


if __name__ == "__main__":
    check_settled_fixture_is_shown_during_grace_then_hidden()
    check_reused_event_id_does_not_hide_a_different_fixture()
    check_past_unsettled_fixtures_are_hidden_but_live_fixtures_remain()
    check_desk_forecast_reconciles_by_fixture_and_score()
    check_learning_capture_covers_each_virtual_product()
    check_each_totals_line_is_scored_independently()
    check_exact_profiles_do_not_pool_products_and_calibration_requires_evidence()
    print("PASS: settled expiry, stale kickoff removal, per-line scoring, product-isolated profiles, evidence-gated calibration, and live retention")
