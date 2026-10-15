#!/usr/bin/env python3
"""Offline tests for the paper-only eFootball performance report."""
import importlib.util
from datetime import datetime, timedelta, timezone
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
    assert report["independent_winner_ggng_shadow"]["mode"] == "PAPER_SHADOW_ONLY"
    assert report["independent_winner_ggng_shadow"]["production_qualification_enabled"] is False
    assert report["automatic_promotion"] if "automatic_promotion" in report else report["promotion_policy"]["automatic_promotion"] is False


def shadow_market_row(event_id, product, start, settle, p1, p2, score,
                      market_type="match_winner", capture_offset_minutes=-10):
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    captured_dt = start_dt + timedelta(minutes=capture_offset_minutes)
    settle_dt = datetime.fromisoformat(settle.replace("Z", "+00:00"))
    home, away = int(score[0]), int(score[1])
    if market_type == "match_winner":
        actual = "home" if home > away else "away" if home < away else "draw"
        probs = {"home": 0.40, "draw": 0.28, "away": 0.32}
        odds = {"home": 2.30, "draw": 3.50, "away": 2.80}
    else:
        actual = "yes" if home > 0 and away > 0 else "no"
        probs = {"yes": 0.57, "no": 0.43}
        odds = {"yes": 1.80, "no": 2.10}
    fave = max(probs, key=probs.get)
    return {
        "sample_id": f"{event_id}-{market_type}",
        "event_id": event_id,
        "product": product,
        "competition": "Synthetic Test League",
        "participant_1": p1,
        "participant_2": p2,
        "start_time": start_dt.isoformat(),
        "captured_at": captured_dt.isoformat(),
        "settled_at": settle_dt.isoformat(),
        "market_type": market_type,
        "market_id": "1" if market_type == "match_winner" else "29",
        "odds": odds,
        "market_probabilities_no_vig": probs,
        "market_favourite": fave,
        "favourite_odds": odds[fave],
        "favourite_correct": fave == actual,
        "favourite_net_units": odds[fave] - 1 if fave == actual else -1,
        "settlement_status": "SETTLED",
        "final_score": [float(home), float(away)],
        "actual_outcome": actual,
    }


def shadow_history(product="efootball_gt", extreme=False):
    teams = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
    rows = []
    base = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    for i in range(40):
        start = base + timedelta(hours=i)
        settle = start + timedelta(minutes=5)
        p1 = teams[i % len(teams)]
        p2 = teams[(i * 3 + 1) % len(teams)]
        score = (7, 0) if extreme else (i % 4, (i * 2 + 1) % 3)
        row = shadow_market_row(
            f"{product}-history-{i}", product, start.isoformat(), settle.isoformat(),
            p1, p2, score, "match_winner", capture_offset_minutes=1,
        )
        rows.append(row)
        # A second market row for some matches must not count as a second training game.
        if i % 5 == 0:
            rows.append(shadow_market_row(
                f"{product}-history-{i}", product, start.isoformat(), settle.isoformat(),
                p1, p2, score, "btts", capture_offset_minutes=1,
            ))
    return rows


def shadow_target_rows(product="efootball_gt"):
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    settle = start + timedelta(minutes=10)
    # Same event, two target markets: it must be one unique match in the score history.
    return [
        shadow_market_row("target-event", product, start.isoformat(), settle.isoformat(),
                          "Alpha", "Beta", (3, 1), "match_winner", -10),
        shadow_market_row("target-event", product, start.isoformat(), settle.isoformat(),
                          "Alpha", "Beta", (3, 1), "btts", -10),
    ]


def test_independent_shadow_is_time_safe_and_deduplicates_events():
    rows = shadow_history()
    # This game kicked off before the target, but its result was not settled when the target quote was captured.
    late_start = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
    late_settle = datetime(2026, 10, 4, 11, 55, tzinfo=timezone.utc)
    rows.append(shadow_market_row(
        "late-settlement-event", "efootball_gt", late_start.isoformat(), late_settle.isoformat(),
        "Alpha", "Beta", (0, 6), "match_winner", 1,
    ))
    rows.extend(shadow_target_rows())
    report = mod.build_independent_market_shadow({"observations": rows})
    winner = report["lanes"]["efootball_gt|match_winner"]
    btts = report["lanes"]["efootball_gt|btts"]

    assert report["mode"] == "PAPER_SHADOW_ONLY"
    assert report["automatic_promotion"] is False
    assert report["production_qualification_enabled"] is False
    assert report["conflicting_history_events_excluded"] == 0
    assert report["scored_unique_history_events"] == 42  # 40 history + late result + target game
    assert winner["forecasted_observations"] == 1
    assert btts["forecasted_observations"] == 1
    assert winner["mean_training_matches"] == 40  # duplicate markets and unsettled-at-capture game excluded
    assert btts["mean_training_matches"] == 40
    assert winner["model_mean_brier"] is not None
    assert winner["market_mean_brier_same_forecasts"] is not None
    assert winner["model_minus_market_brier"] is not None
    assert winner["promotion_review"]["automatic_promotion"] is False
    assert btts["promotion_review"]["production_qualification_enabled"] is False


def test_independent_shadow_keeps_gt_and_adriatic_histories_separate():
    gt_rows = shadow_history("efootball_gt")
    target = shadow_target_rows("efootball_gt")
    gt_only = mod.build_independent_market_shadow({"observations": gt_rows + target})
    mixed_products = mod.build_independent_market_shadow({
        "observations": gt_rows + target + shadow_history("efootball_adriatic", extreme=True)
    })
    a = gt_only["lanes"]["efootball_gt|match_winner"]
    b = mixed_products["lanes"]["efootball_gt|match_winner"]
    assert a["forecasted_observations"] == b["forecasted_observations"] == 1
    assert a["mean_training_matches"] == b["mean_training_matches"] == 40
    assert a["model_mean_brier"] == b["model_mean_brier"]
    assert "efootball_adriatic|match_winner" not in gt_only["lanes"]
    assert "efootball_gt|match_winner" in mixed_products["lanes"]


def test_independent_shadow_falls_back_for_unseen_participants_and_reports_tier():
    rows = shadow_history()
    # Same-product history exists, but neither target participant has appeared before.
    for row in rows:
        row["participant_1"] = "Historical " + row["participant_1"]
        row["participant_2"] = "Historical " + row["participant_2"]
    rows.extend(shadow_target_rows())
    report = mod.build_independent_market_shadow({"observations": rows})
    lane = report["lanes"]["efootball_gt|match_winner"]
    assert lane["forecasted_observations"] == 1
    assert lane["mean_training_matches"] == 40
    assert lane["by_participant_history_tier"][0]["tier"] == "neither_participant_seen"
    assert lane["by_participant_history_tier"][0]["model_mean_brier"] is not None
    assert "chronological_split" in lane["by_participant_history_tier"][0]
    assert "by_picked_side_value_picks" in lane
    assert "by_selected_odds_band_value_picks" in lane
    assert lane["diagnostic_findings"]
    assert report["forecasts_by_participant_history_tier"]["neither_participant_seen"] == 2
    assert report["skipped_target_counts"]["insufficient_global_history"] == 0


def test_shadow_review_rejects_a_configuration_that_loses_to_market_in_both_periods():
    assert mod._shadow_review_status(
        795, 621, 0.0291, 0.0367, 0.0331, 0.0417, -0.2190,
    ) == "REJECT_CURRENT_SHADOW_MODEL_VS_MARKET"
    # A positive latest flat-stake ROI cannot override worse probability scores in both periods.
    assert mod._shadow_review_status(
        119, 83, 0.0256, 0.0315, 0.0127, 0.0233, 0.0532,
    ) == "REJECT_CURRENT_SHADOW_MODEL_VS_MARKET"
    assert mod._shadow_review_status(
        120, 80, -0.02, -0.03, -0.01, -0.02, 0.03,
    ) == "ELIGIBLE_FOR_PAPER_PROMOTION_REVIEW"
    assert mod._shadow_review_status(
        99, 80, -0.02, -0.03, -0.01, -0.02, 0.03,
    ) == "COLLECT_AND_MONITOR"
