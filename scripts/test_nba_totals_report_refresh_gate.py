"""Regression tests for event-driven NBA totals report refresh timing."""

from datetime import datetime, timezone
from pathlib import Path

from nba_totals_report_refresh_gate import latest_snapshot_evidence_time, should_refresh_report


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run():

    # A repeated quote revision retains the original publication time; the later
    # quote timestamp must still make the research report stale for CLV purposes.
    quote_revisions = [
        {
            "totals_model_version": "nba-total-v5.1-pace-efficiency-calibrated",
            "event_id": "401909922",
            "published_at": "2026-11-02T05:00:00Z",
            "quote_timestamp": "2026-11-02T05:00:00Z",
        },
        {
            "totals_model_version": "nba-total-v5.1-pace-efficiency-calibrated",
            "event_id": "401909922",
            "published_at": "2026-11-02T05:00:00Z",
            "quote_timestamp": "2026-11-02T06:53:33Z",
        },
        {
            "totals_model_version": "other-model",
            "published_at": "2026-11-02T07:00:00Z",
            "quote_timestamp": "2026-11-02T07:00:00Z",
        },
    ]
    assert latest_snapshot_evidence_time(
        quote_revisions, "nba-total-v5.1-pace-efficiency-calibrated"
    ) == dt("2026-11-02T06:53:33Z"), (
        "A newer exact SportyBet quote revision must refresh CLV diagnostics even "
        "when it does not create a new publication, bet, or fixture."
    )
    assert latest_snapshot_evidence_time([], "nba-total-v5.1-pace-efficiency-calibrated") is None

    now = dt("2026-11-02T06:53:45Z")
    prior_report = dt("2026-11-02T06:49:43Z")
    new_capture = dt("2026-11-02T06:53:33Z")

    assert should_refresh_report("workflow_run", prior_report, new_capture, now), (
        "A successful capture/settlement event must refresh newer evidence even "
        "when the prior report is less than ten minutes old."
    )
    assert not should_refresh_report(
        "workflow_run", now, new_capture, now
    ), "A duplicate event must skip when the report already covers the newest evidence."
    assert not should_refresh_report(
        "schedule", prior_report, new_capture, now
    ), "The periodic schedule must retain its ten-minute workload throttle."
    assert should_refresh_report(
        "schedule",
        dt("2026-11-02T06:43:45Z"),
        new_capture,
        now,
    ), "A stale scheduled report at least ten minutes old must refresh."
    assert should_refresh_report(
        "push", now, new_capture, now
    ), "Code-change validation must run regardless of report freshness."
    assert should_refresh_report(
        "schedule", None, new_capture, now
    ), "A missing report must be regenerated."
    assert not should_refresh_report(
        "schedule",
        now,
        dt("2026-11-02T06:52:00Z"),
        now,
    ), "A report newer than all evidence must not rerun."

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-totals-probability-value.yml").read_text(encoding="utf-8")
    assert "latest_snapshot_evidence_time" in workflow and "quote_timestamp" in workflow, (
        "The scheduled/event-driven workflow must include newer immutable quote revisions in its report-refresh decision."
    )

    print("PASS: quote-revision evidence freshness, event-driven refresh, duplicate suppression, schedule throttle, and missing-report cases.")


if __name__ == "__main__":
    run()
