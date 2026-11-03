#!/usr/bin/env python3
"""Regression tests for fixture-independent recent eFootball performance."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.efootball_desk_learning import (
    TRACE_CAP, bound_trace, merge_settled_observations,
    market_research_score_rows, recent_fixture_window, reconcile, settlement_index,
)


def row(product, start, home, away, win, settled, probability=0.6, line=2.5):
    return {
        "product": product,
        "start_time": start,
        "timestamp": start,
        "participant_1": home,
        "participant_2": away,
        "win": win,
        "settled_at": settled,
        "model_probability": probability,
        "line": line,
    }



def test_trace_is_bounded_and_scored_settlements_remain_in_durable_ledger():
    assert TRACE_CAP == 20000
    now_text = "2026-11-03T20:00:00+00:00"
    from datetime import datetime
    trace = [
        {
            "event_id": f"pending-{i}",
            "product": "efootball_gt",
            "start_time": "2026-11-04T00:00:00+00:00",
            "participant_1": f"home-{i}",
            "participant_2": f"away-{i}",
            "observed_at": now_text,
            "settled": False,
        }
        for i in range(TRACE_CAP + 25)
    ]
    assert len(bound_trace(trace, now=datetime.fromisoformat(now_text))) <= TRACE_CAP

    scored = {
        "event_id": "settled-ledger-row",
        "product": "efootball_gt",
        "participant_1": "home",
        "participant_2": "away",
        "start_time": "2026-11-03T10:00:00+00:00",
        "settled_at": "2026-11-03T10:05:00+00:00",
        "settled": True,
        "scored_forecast": True,
        "actual_result": "WON",
    }
    ledger, added = merge_settled_observations([], [scored])
    assert added == 1
    assert len(ledger) == 1
    assert ledger[0]["event_id"] == "settled-ledger-row"


def test_adriatic_totals_forecast_reconciles_to_exact_settled_market_score():
    start = "2026-11-01T10:00:00+00:00"
    settled = "2026-11-01T10:08:00+00:00"
    archived = {
        "observations": [
            {
                "event_id": "adriatic-100", "product": "efootball_adriatic",
                "participant_1": "Adriano", "participant_2": "Maverick",
                "start_time": start, "settled_at": settled,
                "market_type": "match_winner", "settlement_status": "SETTLED",
                "final_score": [3, 1],
            },
            {
                "event_id": "adriatic-100", "product": "efootball_adriatic",
                "participant_1": "Adriano", "participant_2": "Maverick",
                "start_time": start, "settled_at": settled,
                "market_type": "btts", "settlement_status": "SETTLED",
                "final_score": [3, 1],
            },
            {
                "event_id": "adriatic-pending", "product": "efootball_adriatic",
                "participant_1": "Cleo", "participant_2": "Logan",
                "start_time": "2026-11-01T10:10:00+00:00",
                "settled_at": None, "market_type": "match_winner",
                "settlement_status": "PENDING", "final_score": None,
            },
        ]
    }
    supplemental = market_research_score_rows(archived)
    assert len(supplemental) == 2, supplemental
    index = settlement_index(supplemental)
    assert len(index) == 1, index

    # Same participants/kickoff in different products must never share scores.
    trace = [
        {
            "product": "efootball_adriatic", "event_id": "desk-adriatic-100",
            "start_time": start, "timestamp": start,
            "participant_1": "Adriano", "participant_2": "Maverick",
            "line": 2.5, "pick": "over", "model_probability": 0.65,
            "observed_at": "2026-11-01T09:55:00+00:00", "settled": False,
        },
        {
            "product": "efootball_gt", "event_id": "desk-gt-100",
            "start_time": start, "timestamp": start,
            "participant_1": "Adriano", "participant_2": "Maverick",
            "line": 2.5, "pick": "under", "model_probability": 0.61,
            "observed_at": "2026-11-01T09:55:00+00:00", "settled": False,
        },
    ]
    diagnostics = reconcile(trace, index)
    assert trace[0].get("scored_forecast") is True, trace[0]
    assert trace[0].get("win") is True, trace[0]
    assert trace[0].get("score") == "3:1", trace[0]
    assert trace[1].get("scored_forecast") is not True, trace[1]
    assert diagnostics["match_counts_by_product"]["efootball_adriatic"]["matched_exact"] == 1
    assert diagnostics["match_counts_by_product"]["efootball_gt"]["unmatched"] == 1


def test_untrusted_market_rows_do_not_enter_the_score_index():
    row = {
        "product": "efootball_adriatic", "event_id": "untrusted",
        "participant_1": "Alpha", "participant_2": "Beta",
        "start_time": "2026-11-01T10:00:00+00:00",
        "timestamp": "2026-11-01T10:00:00+00:00",
        "settled_at": "2026-11-01T10:05:00+00:00",
        "market": "match_winner", "score": "5:0", "win": True,
    }
    assert settlement_index([row]) == {}


def main():
    rows = []
    # An older fixture has ten line decisions and is outside the selected window.
    for i in range(10):
        rows.append(row(
            "efootball_gt", "2026-11-01T10:00:00+00:00", "Home A", "Away A",
            False, f"2026-11-01T11:{i:02d}:00+00:00", probability=0.4, line=1.5+i,
        ))

    # Two latest fixtures have very different numbers of line decisions.
    # The second row reverses participants intentionally: fixture identity is order-independent.
    for i in range(3):
        rows.append(row(
            "efootball_gt", "2026-11-01T10:10:00+00:00",
            "Home B" if i != 1 else "Away B", "Away B" if i != 1 else "Home B",
            True, f"2026-11-01T12:1{i}:00+00:00", probability=0.7, line=2.5+i,
        ))
    rows.append(row(
        "efootball_gt", "2026-11-01T10:20:00+00:00", "Home C", "Away C",
        False, "2026-11-01T12:30:00+00:00", probability=0.3,
    ))

    # Same names/time in another product must be kept in a separate cluster.
    rows.append(row(
        "efootball_adriatic", "2026-11-01T10:20:00+00:00", "Home C", "Away C",
        True, "2026-11-01T12:31:00+00:00", probability=0.8,
    ))

    gt_rows = [item for item in rows if item["product"] == "efootball_gt"]
    result = recent_fixture_window(gt_rows, window=2)
    assert result["n"] == 2, result
    assert result["unique_fixtures"] == 2, result
    assert result["decision_count"] == 4, result
    # Each fixture contributes one cluster score: (3/3 + 0/1) / 2 = 0.50.
    assert abs(result["accuracy"] - 0.50) < 1e-12, result
    # Decision-weighted accuracy is retained only as a diagnostic: 3/4 = 0.75.
    assert abs(result["decision_accuracy"] - 0.75) < 1e-12, result
    assert result["window_unit"] == "unique_product_fixture_clusters", result
    assert result["first_settled_at"] == "2026-11-01T12:10:00+00:00", result
    assert result["last_settled_at"] == "2026-11-01T12:30:00+00:00", result

    adriatic = recent_fixture_window(
        [item for item in rows if item["product"] == "efootball_adriatic"], window=50
    )
    assert adriatic["n"] == 1 and adriatic["decision_count"] == 1, adriatic
    mixed = recent_fixture_window(rows, window=50)
    assert mixed["n"] == 4, mixed  # same names/time in distinct products remain distinct

    empty = recent_fixture_window([], window=50)
    assert empty["n"] == 0 and empty["decision_count"] == 0, empty
    test_adriatic_totals_forecast_reconciles_to_exact_settled_market_score()
    test_untrusted_market_rows_do_not_enter_the_score_index()
    print("eFootball desk fixture windows and cross-market score reconciliation tests passed.")


if __name__ == "__main__":
    main()
