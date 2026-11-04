"""Regression tests for the NBA market-225 capture freshness watchdog."""

from datetime import datetime, timezone
from pathlib import Path

from nba_totals_capture_watchdog import (
    capture_age_minutes, should_dispatch_capture,
    stale_upcoming_prediction_count, should_dispatch_model_refresh,
    should_dispatch_settlement, should_dispatch_probability_report,
)


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run():
    root = Path(__file__).resolve().parents[1]
    capture_workflow = (root / ".github/workflows/nba-totals-price-capture.yml").read_text(encoding="utf-8")
    watchdog_workflow = (root / ".github/workflows/nba-totals-capture-watchdog.yml").read_text(encoding="utf-8")
    assert (
        "cron: '*/10 * * * *'" in capture_workflow
        or "cron: '0,10,20,30,40,50 * * * *'" in capture_workflow
    ), (
        "NBA SportyBet market-225 capture must run every 10 minutes to protect the 15-minute quote freshness gate."
    )
    assert "cron: '5,15,25,35,45,55 * * * *'" in watchdog_workflow, (
        "The freshness watchdog must run halfway between the 10-minute capture slots."
    )
    assert 'gh workflow enable "$workflow" --repo "$GITHUB_REPOSITORY"' in watchdog_workflow, (
        "NBA recovery watchdog must call the GitHub workflow-enable command after delivery gaps."
    )
    for workflow in (
        "nba-totals-price-capture.yml",
        "nba-totals-probability-value.yml",
        "nba-totals-settlement.yml",
        "nba-totals-capture-watchdog.yml",
        "live-expansion.yml",
    ):
        assert workflow in watchdog_workflow, (
            f"NBA recovery watchdog must include scheduled workflow {workflow} in its re-enable list."
        )

    now = dt("2026-11-02T08:25:00Z")
    assert round(capture_age_minutes("2026-11-02T08:16:39Z", now), 2) == 8.35
    assert not should_dispatch_capture("2026-11-02T08:16:39Z", now, 0), (
        "A capture under 10 minutes old must not be duplicated."
    )
    assert should_dispatch_capture("2026-11-02T08:14:59Z", now, 0, max_age_minutes=10), (
        "A capture at least 10 minutes old must trigger a recovery capture."
    )
    assert not should_dispatch_capture("2026-11-02T08:00:00Z", now, 1), (
        "An already queued/running capture must suppress a duplicate dispatch."
    )
    assert should_dispatch_capture(None, now, 0), "Missing status must fail safe to capture."
    assert should_dispatch_capture("not-a-time", now, 0), "Invalid timestamps must fail safe."
    assert not should_dispatch_capture("2026-11-02T08:26:00Z", now, 0), (
        "Small future clock skew should not trigger duplicate capture."
    )
    assert should_dispatch_capture("2026-11-02T08:29:00Z", now, 0), (
        "A timestamp more than two minutes in the future must fail safe."
    )


    model_now = dt("2026-11-02T13:55:00Z")
    assert should_dispatch_settlement(
        "2026-11-02T13:39:59Z", model_now, active_settlement_runs=0, max_age_minutes=15
    ), "A settlement ledger at the 15-minute stale boundary must trigger official ESPN settlement recovery."
    assert not should_dispatch_settlement(
        "2026-11-02T13:40:01Z", model_now, active_settlement_runs=0, max_age_minutes=15
    ), "A fresh settlement ledger must not be duplicated."
    assert not should_dispatch_settlement(
        "2026-11-02T13:00:00Z", model_now, active_settlement_runs=1, max_age_minutes=15
    ), "An active settlement run must suppress duplicate settlement recovery."
    assert should_dispatch_settlement(None, model_now, active_settlement_runs=0), (
        "A missing settlement ledger timestamp must fail safe to official settlement recovery."
    )

    assert should_dispatch_probability_report(
        "2026-11-02T13:35:00Z", "2026-11-02T13:50:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, max_age_minutes=15
    ), "A stale report with newer capture/settlement evidence must trigger research recovery."
    assert should_dispatch_probability_report(
        "2026-11-02T13:53:00Z", "2026-11-02T13:54:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, max_age_minutes=15
    ), "New settlement/capture evidence must refresh a recent report immediately."
    assert should_dispatch_probability_report(
        "2026-11-02T13:35:00Z", "2026-11-02T13:30:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, max_age_minutes=15
    ), "A report older than 15 minutes must refresh even if source timestamps are unchanged."
    assert not should_dispatch_probability_report(
        "2026-11-02T13:00:00Z", "2026-11-02T13:50:00Z", model_now,
        active_research_runs=1, active_settlement_runs=0, max_age_minutes=15
    ), "An active research run must suppress duplicate recovery."
    assert not should_dispatch_probability_report(
        "2026-11-02T13:00:00Z", "2026-11-02T13:50:00Z", model_now,
        active_research_runs=0, active_settlement_runs=1, max_age_minutes=15
    ), "An active settlement run must finish before report recovery."
    assert not should_dispatch_probability_report(
        "2026-11-02T13:00:00Z", "2026-11-02T13:50:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, settlement_dispatched=True,
        max_age_minutes=15
    ), "A just-dispatched settlement must finish before report recovery."
    assert not should_dispatch_probability_report(
        "2026-11-02T13:50:00Z", "2026-11-02T13:40:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, max_age_minutes=15
    ), "Older source evidence must not cause a needless report refresh."
    assert not should_dispatch_probability_report(
        "2026-11-02T13:58:00Z", "2026-11-02T13:50:00Z", model_now,
        active_research_runs=0, active_settlement_runs=0, max_age_minutes=15
    ), "Small future clock skew must not cause a report refresh loop."

    assert '"NBA totals SportyBet market-225 price capture"' in watchdog_workflow, (
        "Capture completion must trigger settlement/report recovery even when a schedule is missed."
    )
    assert "Dispatch stale official ESPN settlement recovery" in watchdog_workflow
    assert "gh workflow run nba-totals-settlement.yml --ref main" in watchdog_workflow
    assert "should_dispatch_probability_report" in watchdog_workflow
    assert "gh workflow run nba-totals-probability-value.yml --ref main" in watchdog_workflow, (
        "The watchdog must recover missed report refreshes without changing qualification thresholds."
    )
    assert 'sys.path.insert(0, "scripts")' in watchdog_workflow, (
        "The inline watchdog recovery step must import its tested policy from the scripts directory."
    )

    fresh_upcoming = [{
        "event_id": "fresh-1", "start_time": "2026-11-02T20:00:00Z",
        "generated_at": "2026-11-02T10:00:00Z"
    }]
    stale_upcoming = [{
        "event_id": "stale-1", "start_time": "2026-11-02T20:00:00Z",
        "generated_at": "2026-11-02T06:00:00Z"
    }]
    already_started = [{
        "event_id": "started-1", "start_time": "2026-11-02T12:00:00Z",
        "generated_at": "2026-11-02T04:00:00Z"
    }]
    assert stale_upcoming_prediction_count(fresh_upcoming, model_now) == 0
    assert stale_upcoming_prediction_count(stale_upcoming, model_now) == 1
    assert stale_upcoming_prediction_count(already_started, model_now) == 0, (
        "Started fixtures must retain their frozen pre-game snapshot and must not trigger a refresh."
    )
    assert should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T12:00:00Z", model_now, active_model_runs=0
    ), "A stale pre-game forecast with an old model status must trigger recovery."
    assert not should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T13:40:00Z", model_now, active_model_runs=0
    ), "A recent model refresh must suppress immediate retry loops."
    assert not should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T12:00:00Z", model_now, active_model_runs=1
    ), "An active model run must suppress duplicate recovery dispatches."
    assert not should_dispatch_model_refresh(
        fresh_upcoming, "2026-11-02T06:00:00Z", model_now, active_model_runs=0
    ), "Fresh predictions must not be rebuilt just because the status file is old."
    assert should_dispatch_model_refresh(None, None, model_now, active_model_runs=0), (
        "Missing prediction content and model status must fail safe to recovery."
    )

    print("PASS: capture, model, ESPN settlement, and probability-report recovery; freshness boundaries, active-run suppression, and clock-skew cases.")


if __name__ == "__main__":
    run()
