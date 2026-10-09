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


if __name__ == "__main__":
    check_settled_fixture_is_shown_during_grace_then_hidden()
    check_reused_event_id_does_not_hide_a_different_fixture()
    check_past_unsettled_fixtures_are_hidden_but_live_fixtures_remain()
    check_desk_forecast_reconciles_by_fixture_and_score()
    print("PASS: settled grace/expiry, stale kickoff removal, live retention, reused-ID isolation, and time-safe reconciliation")
