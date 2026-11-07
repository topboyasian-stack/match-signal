"""Regression tests for the NBA market-225 capture freshness watchdog."""

from datetime import datetime, timezone
from pathlib import Path

from nba_totals_capture_watchdog import (
    capture_age_minutes, should_dispatch_capture,
    stale_upcoming_prediction_count, should_dispatch_model_refresh,
    should_dispatch_settlement, should_dispatch_probability_report,
    settlement_evidence_changed,
)


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run():
    root = Path(__file__).resolve().parents[1]
    capture_workflow = (root / ".github/workflows/nba-totals-price-capture.yml").read_text(encoding="utf-8")
    watchdog_workflow = (root / ".github/workflows/nba-totals-capture-watchdog.yml").read_text(encoding="utf-8")
    settlement_workflow = (root / ".github/workflows/nba-totals-settlement.yml").read_text(encoding="utf-8")
    probability_workflow = (root / ".github/workflows/nba-totals-probability-value.yml").read_text(encoding="utf-8")
    live_expansion_workflow = (root / ".github/workflows/live-expansion.yml").read_text(encoding="utf-8")
    assert "cron: '2,12,22,32,42,52 * * * *'" in capture_workflow, (
        "NBA SportyBet market-225 capture must run every 10 minutes after the schedule re-arm."
    )

    assert "actions: write" in capture_workflow, (
        "Capture must be allowed to dispatch a follow-up evidence refresh with GITHUB_TOKEN."
    )
    assert "Dispatch NBA probability/value refresh when new immutable quotes were added" in capture_workflow, (
        "Fresh quote revisions must explicitly trigger probability/value report refresh rather than relying only on workflow_run delivery."
    )
    assert "gh workflow run nba-totals-probability-value.yml --ref main" in capture_workflow and "immutable_snapshots_added" in capture_workflow, (
        "Only a capture that adds immutable market-225 quote snapshots should dispatch the research report."
    )
    assert "cron: '5,20,35,50 * * * *'" in settlement_workflow, (
        "Official ESPN settlement backup must remain scheduled and staggered between capture slots."
    )

    assert "actions: write" in settlement_workflow, (
        "The settlement workflow needs Actions write permission for its explicit report handoff."
    )
    assert "Dispatch probability/value report after new official settlement evidence" in settlement_workflow, (
        "New official settlement records must explicitly refresh probability/value research."
    )
    assert "steps.persist.outputs.changed == 'true'" in settlement_workflow, (
        "Settlement should dispatch a report only when new ledger artifacts were published."
    )
    assert 'echo "changed=false" >> "$GITHUB_OUTPUT"' in settlement_workflow and 'echo "changed=$evidence_changed" >> "$GITHUB_OUTPUT"' in settlement_workflow, (
        "The settlement publication output must distinguish new settled records from timestamp-only checks."
    )
    assert "settlement_evidence_changed" in settlement_workflow, (
        "The settlement workflow must compare official records and summaries, ignoring updated_at-only changes."
    )
    assert "gh workflow run nba-totals-probability-value.yml --ref main" in settlement_workflow, (
        "The settlement-to-report handoff must use the existing research workflow."
    )
    assert "cron: '8,23,38,53 * * * *'" in probability_workflow, (
        "Probability/value evidence must refresh on its staggered backup schedule."
    )
    assert "cron: '7,17,27,37,47,57 * * * *'" in watchdog_workflow, (
        "The freshness watchdog must run halfway between the 10-minute capture slots."
    )
    assert "cron: '9,39 * * * *'" in live_expansion_workflow, (
        "The NBA forecast refresh schedule must be re-armed without changing model thresholds."
    )
    assert 'gh workflow enable "$workflow" --repo "$GITHUB_REPOSITORY"' in watchdog_workflow, (
        "Schedule recovery must reassert enable state even when GitHub still reports the workflow active."
    )
    assert 'gh workflow enable "$workflow" --repo "$GITHUB_REPOSITORY"' in watchdog_workflow, (
        "NBA recovery watchdog must call the GitHub workflow-enable command after delivery gaps."
    )

    assert "workflow_state=\"$(gh api \"repos/$GITHUB_REPOSITORY/actions/workflows/$workflow\" --jq '.state')\"" in watchdog_workflow, (
        "Recovery must read the authoritative GitHub Actions workflow state."
    )
    assert 'if [ "$workflow_state" != "active" ]; then' in watchdog_workflow, (
        "Recovery must re-enable workflows that are not active."
    )
    assert 'Verified active scheduled workflow:' in watchdog_workflow, (
        "A successful enable command alone must not be treated as proof of active scheduling."
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

    # A scheduled run can be the only source of new prospective evidence when
    # event-driven runs are quiet. GitHub retains only one pending run per
    # concurrency group, so workflow_run/push activity must use a separate lane.
    scheduled_lane = "${{ github.event_name == 'schedule' && 'scheduled' || 'event-driven' }}"
    for workflow_text, group_prefix, name in (
        (capture_workflow, "nba-totals-price-capture-", "price capture"),
        (settlement_workflow, "nba-totals-settlement-ledger-", "settlement"),
        (probability_workflow, "nba-totals-probability-value-research-", "probability report"),
        (live_expansion_workflow, "match-signal-pipeline-", "model refresh"),
    ):
        expected_group = f"group: {group_prefix}{scheduled_lane}"
        assert expected_group in workflow_text, (
            f"Scheduled {name} must be isolated from event-driven concurrency to prevent cron starvation."
        )
    watchdog_group = "group: nba-totals-capture-freshness-watchdog-${{ github.event_name == 'schedule' && 'scheduled' || (github.event_name == 'push' || github.event_name == 'workflow_dispatch') && 'recovery' || 'event-driven' }}"
    assert watchdog_group in watchdog_workflow, (
        "Scheduled freshness checks and push/manual schedule-state recovery must each have a protected concurrency lane."
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

    base_ledger = {"updated_at": "2026-11-02T13:00:00Z", "records": [{"event_id": "game-1", "result": "over"}], "summary": {"settled": 1}}
    checked_ledger = {"updated_at": "2026-11-02T13:15:00Z", "records": [{"event_id": "game-1", "result": "over"}], "summary": {"settled": 1}}
    base_probability = {"updated_at": "2026-11-02T13:00:00Z", "records": [{"event_id": "game-1", "total": 225}], "summary": {"settled_unique_fixtures": 1}}
    checked_probability = {"updated_at": "2026-11-02T13:15:00Z", "records": [{"event_id": "game-1", "total": 225}], "summary": {"settled_unique_fixtures": 1}}
    assert not settlement_evidence_changed(base_ledger, checked_ledger, base_probability, checked_probability), (
        "Updated timestamps alone are not new official settlement evidence and must not dispatch another report."
    )
    new_ledger = {"updated_at": "2026-11-02T13:20:00Z", "records": [{"event_id": "game-1", "result": "over"}, {"event_id": "game-2", "result": "under"}], "summary": {"settled": 2}}
    assert settlement_evidence_changed(new_ledger, checked_ledger, checked_probability, base_probability), (
        "A newly settled official fixture must trigger a report refresh."
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
        active_research_runs=0, active_settlement_runs=0, active_capture_runs=1,
        max_age_minutes=15
    ), "An active exact-market capture must finish before the report refreshes, so the report includes its new immutable snapshots."
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
    assert "  push:" in watchdog_workflow and "'.github/workflows/nba-totals-capture-watchdog.yml'" in watchdog_workflow, (
        "A relevant main-branch workflow change must trigger schedule recovery without waiting for a cron slot."
    )
    assert "github.event_name == 'workflow_run'" in watchdog_workflow and "gh workflow enable \"$workflow\"" in watchdog_workflow, (
        "The live event-driven recovery path must re-arm NBA schedules when scheduled delivery has lapsed."
    )
    assert "'.github/workflows/nba-totals-price-capture.yml'" in watchdog_workflow and "'.github/workflows/nba-totals-settlement.yml'" in watchdog_workflow and "'.github/workflows/nba-totals-probability-value.yml'" in watchdog_workflow, (
        "Capture, settlement and probability workflow changes must all trigger schedule recovery."
    )
    assert '"NBA totals probability and value research"' in watchdog_workflow, (
        "A successful report refresh must also run the freshness watchdog so a missed capture schedule can recover."
    )
    assert "github.event.workflow_run.name == 'NBA totals probability and value research' && github.event.workflow_run.conclusion == 'success'" in watchdog_workflow, (
        "Only successful probability report completion should trigger the additional freshness check."
    )
    assert "Dispatch stale official ESPN settlement recovery" in watchdog_workflow
    assert "gh workflow run nba-totals-settlement.yml --ref main" in watchdog_workflow
    assert "should_dispatch_probability_report" in watchdog_workflow
    assert "gh workflow run nba-totals-probability-value.yml --ref main" in watchdog_workflow, (
        "The watchdog must recover missed report refreshes without changing qualification thresholds."
    )
    assert "ACTIVE_CAPTURE_RUNS: ${{ steps.active_capture.outputs.count }}" in watchdog_workflow, (
        "The report freshness decision must know when a fresh immutable quote capture is still running."
    )
    assert "active_capture_runs=active_capture" in watchdog_workflow, (
        "The report watchdog must defer its own dispatch until the active capture finishes."
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
