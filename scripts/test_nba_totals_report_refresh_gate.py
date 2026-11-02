"""Regression tests for event-driven NBA totals report refresh timing."""

from datetime import datetime, timezone

from nba_totals_report_refresh_gate import should_refresh_report


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run():
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

    print("PASS: event-driven evidence refresh, duplicate suppression, schedule throttle, and missing-report cases.")


if __name__ == "__main__":
    run()
