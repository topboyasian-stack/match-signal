#!/usr/bin/env python3
"""Offline tests for the paper-only eFootball performance report."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "efootball_performance_report", Path(__file__).with_name("efootball_performance_report.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def settled_ou(day, pick, line, win, p=0.7, odds=1.8, competition="GT"):
    return {
        "trace_id": f"{day}-{pick}-{line}-{competition}",
        "start_time": f"{day}T12:00:00+00:00",
        "pick": pick, "line": line, "win": win, "settled": True, "push": False,
        "model_probability": p, "bookmaker_odds": odds, "competition": competition,
        "validated_model_family": "test-model",
    }


def market_row(i, market_type="btts", product="efootball_gt", win=True, day="2026-10-01"):
    return {
        "sample_id": f"sample-{i}", "product": product, "market_type": market_type,
        "competition": "Test League", "start_time": f"{day}T12:00:00+00:00",
        "market_favourite": "yes" if market_type == "btts" else "home",
        "favourite_odds": 1.8, "favourite_correct": win,
        "favourite_net_units": 0.8 if win else -1,
        "market_brier": 0.2 if win else 0.5,
        "market_log_loss": 0.3 if win else 1.0,
        "settlement_status": "SETTLED",
    }


def test_ou_stats_and_confidence_grouping():
    rows = [
        settled_ou("2026-10-01", "under", 6.5, False, 0.65, 1.9),
        settled_ou("2026-10-02", "under", 6.5, False, 0.65, 1.9),
        settled_ou("2026-10-03", "under", 7.5, True, 0.75, 1.8),
        {"settled": False, "win": None, "start_time": "2026-10-04T12:00:00+00:00"},
        settled_ou("2026-10-05", "under", 7.5, True, 0.75, 1.8) | {"push": True},
    ]
    report = mod.build_ou_report(rows)
    assert report["metrics"]["settled"] == 3
    assert report["metrics"]["wins"] == 1
    assert report["metrics"]["losses"] == 2
    assert report["metrics"]["flat_stake_roi"] == round(((1.8 - 1) - 1 - 1) / 3, 4)
    by_line = {r["group"]: r for r in report["segments"]["by_line_and_side"]}
    assert by_line["under 6.5"]["settled"] == 2
    assert by_line["under 6.5"]["flat_stake_roi"] == -1.0
    assert any("overconfident" in x["finding"].lower() for x in report["findings"]) is False


def test_market_baseline_and_review_threshold_are_not_promotion():
    rows = [market_row(i, win=(i % 3 != 0)) for i in range(100)]
    archive = {"updated_at": "2026-10-05T00:00:00+00:00", "observations": rows,
               "last_run": {"captured_at": "2026-10-05T00:00:00+00:00"},
               "market_coverage": {"products": {}}}
    summary = mod.summarize_market_archive(archive)
    lane = summary["summary_by_product_market"]["efootball_gt|btts"]
    assert lane["settled"] == 100
    assert summary["promotion_review"]["efootball_gt|btts"]["status"] == "PRELIMINARY_REVIEW_DUE"
    assert summary["promotion_review"]["efootball_gt|btts"]["automatic_promotion"] is False
    report = mod.build_report([], archive, {}, {}, datetime(2026, 10, 5, 1, tzinfo=timezone.utc))
    assert report["live_trading_approved"] is False
    assert report["production_qualification_enabled"] is False
    assert report["odds_builder_eligible"] is False
    assert report["market_review_status"]["efootball_gt_gg_ng"]["status"] == "REVIEW_NOW_NOT_PROMOTED"


def test_market_lanes_do_not_mix_products_or_market_types():
    rows = [market_row(i, "btts", "efootball_gt", True) for i in range(12)]
    rows += [market_row(i, "match_winner", "efootball_adriatic", False) for i in range(12)]
    archive = {"observations": rows}
    data = mod.summarize_market_archive(archive)
    assert "efootball_gt|btts" in data["summary_by_product_market"]
    assert "efootball_adriatic|match_winner" in data["summary_by_product_market"]
    assert "efootball_adriatic|btts" not in data["summary_by_product_market"]


def test_ticket_dedup_and_efootball_scope():
    base = {
        "ticket_id": "t1", "status": "WON", "combined_odds": 3.0,
        "products": ["efootball_gt"], "primary_lane": "research", "leg_count": 2,
        "legs": [{"product": "efootball_gt"}],
    }
    tracker = {"updated_at": "2026-10-15T00:00:00Z",
               "tickets": [base], "archived_tickets": [base | {"status": "PENDING"}],
               "summary": {"tracked_tickets": 1}}
    report = mod.build_ticket_report(tracker)
    assert report["unique_ticket_count"] == 1
    assert report["efootball_related_ticket_count"] == 1
    assert report["metrics_by_efootball_scope"]["efootball_gt_only"]["settled"] == 1
    assert report["metrics_by_efootball_scope"]["efootball_gt_only"]["flat_stake_net_units"] == 2.0


def test_empty_archive_fails_closed_and_age_warning():
    report = mod.build_report(
        [], {"observations": [], "updated_at": None, "last_run": {}, "market_coverage": {}},
        {}, {}, datetime(2026, 10, 15, tzinfo=timezone.utc),
    )
    assert report["source_freshness"]["collector_stale_over_30_minutes"] is True
    assert report["mode"] == "PAPER_RESEARCH_ONLY"
    assert report["automatic_promotion"] if "automatic_promotion" in report else report["promotion_policy"]["automatic_promotion"] is False
