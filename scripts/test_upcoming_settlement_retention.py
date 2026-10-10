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




def check_learning_reconciliation_matches_cross_minute_kickoff_safely():
    kickoff = datetime(2026, 10, 8, 16, 42, 30, tzinfo=timezone.utc)
    history_kickoff = datetime(2026, 10, 8, 16, 43, 30, tzinfo=timezone.utc)
    settled_at = datetime(2026, 10, 8, 16, 50, tzinfo=timezone.utc)
    history_row = {
        "product": "efootball_gt",
        "event_id": "reused-session-id",
        "timestamp": iso(history_kickoff),
        "participant_1": "SPARTAN",
        "participant_2": "DART",
        "market": "ou",
        "line": 2.5,
        "selection": "over",
        "score": "2:1",
        "settled_at": iso(settled_at),
        # Missing win is acceptable only because score + settled_at are present.
    }
    forecast = {
        "event_id": "different-provider-id",
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
    stats = learning.reconcile([forecast], history_index)
    assert forecast.get("scored_forecast") is True, "Minute-boundary drift should reconcile by unique participants + kickoff proximity"
    assert forecast.get("win") is True and forecast.get("score") == "2:1"
    assert stats["matched_line_groups_near_time"] == 1
    assert stats["scored_forecasts"] == 1


def check_ambiguous_near_time_settlement_is_never_guessed():
    forecast_kickoff = datetime(2026, 10, 8, 16, 43, tzinfo=timezone.utc)
    rows = []
    for minute, score in ((42, "2:1"), (44, "1:0")):
        event_time = datetime(2026, 10, 8, 16, minute, tzinfo=timezone.utc)
        rows.append({
            "product": "efootball_gt",
            "event_id": "same-reused-id",
            "timestamp": iso(event_time),
            "participant_1": "SPARTAN",
            "participant_2": "DART",
            "market": "ou",
            "line": 2.5,
            "selection": "over",
            "win": True,
            "score": score,
            "settled_at": iso(event_time + timedelta(minutes=5)),
        })
    forecast = {
        "event_id": "another-reused-id",
        "product": "efootball_gt",
        "start_time": iso(forecast_kickoff),
        "participant_1": "Home (SPARTAN)",
        "participant_2": "Away (DART)",
        "line": 2.5,
        "pick": "over",
        "model_probability": 0.70,
        "observed_at": iso(forecast_kickoff - timedelta(minutes=5)),
        "settled": False,
    }
    stats = learning.reconcile([forecast], learning.settlement_index(rows))
    assert forecast.get("scored_forecast") is not True, "Two plausible recurring-participant fixtures must stay unmatched"
    assert stats["ambiguous_line_groups"] == 1
    assert stats["scored_forecasts"] == 0


def check_half_line_directional_gate_uses_unique_scores_and_excludes_conflicts():
    history = []
    for index in range(32):
        kickoff = datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=10 * index)
        settled_at = kickoff + timedelta(minutes=4)
        base = {
            "product": "efootball_gt",
            "event_id": f"directional-event-{index}",
            "timestamp": iso(kickoff),
            "participant_1": f"Home (HANDLE_A{index})",
            "participant_2": f"Away (HANDLE_B{index})",
            "market": "ou",
            "line": 7.5,
            "selection": "under",
            "win": True,
            "score": "2:1",
            "settled_at": iso(settled_at),
        }
        history.append(base)
        if index == 1:
            history.append(dict(base))  # duplicate market row must not add sample size
        if index == 2:
            conflict = dict(base)
            conflict["score"] = "5:5"
            conflict["win"] = False
            history.append(conflict)  # conflicting final score at same settlement time is excluded

    eval_art = {"efootball_gt_diagnostics": {"selection": {
        "u7.5": {"7.5": {"participant_model": {"n": 30, "hit_rate": 0.70}}}
    }}}
    gate = upcoming.build_efootball_directional_gate(eval_art, history)[(7.5, "under")]
    assert gate["recent_evidence_source"] == "UNIQUE_SETTLED_SCORE_REPLAY"
    assert gate["recent_n"] == 31, "32 unique events minus one conflicting event; duplicate rows must not count"
    assert gate["recent_hit_rate"] == 1.0
    assert gate["excluded_conflicting_score_fixtures"] == 1
    assert gate["pass"] is True, "Both unchanged >=30 and >=65% recent and holdout gates must pass"


def check_prediction_desk_copy_and_quote_matching_contract():
    source = (ROOT / "sport-hubs.js").read_text(encoding="utf-8")
    assert "exact-line calibration only (" in source
    assert "qualification is separate" in source
    learning_source = (ROOT / "scripts" / "efootball_desk_learning.py").read_text(encoding="utf-8")
    assert "unmatched_samples_by_product" in learning_source, "Settlement diagnostics must retain GT samples separately from VFootball"
    assert "for r in trace if isinstance(r, dict)" in learning_source, "Products with pending forecasts must remain visible before the first scored result"
    assert "kickoff_and_history_gap_by_product" in learning_source, "Diagnostics must separate future fixtures from already-played unmatched fixtures"
    assert "line-calibration warm-up (" not in source
    assert "for(let page=1;page<=5;page++)" in source
    assert "if(!required.length)return byEvent;" in source
    assert "if(events.length<100)break;" in source
    assert "sameVirtualEvent(row,event)" in source
    assert "exact_event_not_found_in_live_snapshot" in source
    assert "exact_line_or_side_not_found_in_live_snapshot" in source, "Missing current line/side must invalidate quote freshness"
    assert "QUOTE_STALE" in source and "FRESH_TWO_SIDED_MARKET_REQUIRED" in source




def check_unmatched_diagnostics_separate_past_and_future_kickoffs():
    now = datetime.now(timezone.utc)
    forecasts = []
    for label, kickoff in (
        ("past-diagnostic", now - timedelta(hours=1)),
        ("future-diagnostic", now + timedelta(hours=1)),
    ):
        forecasts.append({
            "product": "efootball_gt",
            "event_id": label,
            "start_time": iso(kickoff),
            "participant_1": f"Home ({label}-HANDLE-A)",
            "participant_2": f"Away ({label}-HANDLE-B)",
            "line": 2.5,
            "pick": "over",
            "model_probability": 0.80,
            "observed_at": iso(kickoff - timedelta(minutes=5)),
            "settled": False,
        })
    stats = learning.reconcile(forecasts, {})
    gt = stats["kickoff_and_history_gap_by_product"]["efootball_gt"]
    assert gt["groups_with_kickoff"] == 2
    assert gt["past_kickoff_0_to_2h_groups"] == 1
    assert gt["future_kickoff_groups"] == 1
    assert gt["groups_with_pre_kickoff_observation"] == 2
    assert gt["nearest_same_product_history_missing"] == 2
    assert stats["scored_forecasts"] == 0, "Diagnostic counts must not create settlement outcomes"


if __name__ == "__main__":
    check_settled_fixture_is_shown_during_grace_then_hidden()
    check_reused_event_id_does_not_hide_a_different_fixture()
    check_past_unsettled_fixtures_are_hidden_but_live_fixtures_remain()
    check_desk_forecast_reconciles_by_fixture_and_score()
    check_learning_capture_covers_each_virtual_product()
    check_each_totals_line_is_scored_independently()
    check_exact_profiles_do_not_pool_products_and_calibration_requires_evidence()
    check_learning_reconciliation_matches_cross_minute_kickoff_safely()
    check_ambiguous_near_time_settlement_is_never_guessed()
    check_half_line_directional_gate_uses_unique_scores_and_excludes_conflicts()
    check_prediction_desk_copy_and_quote_matching_contract()
    check_unmatched_diagnostics_separate_past_and_future_kickoffs()
    print("PASS: settlement retention, conservative reconciliation, unique score replay, kickoff-gap diagnostics, line gates, calibration, and exact live quote contract")
