"""Regression tests for event-driven NBA totals report refresh timing."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile

from nba_totals_report_refresh_gate import (
    SOURCE_DATA_FILES,
    latest_snapshot_evidence_time,
    report_source_fingerprint_matches,
    should_refresh_report,
    source_data_fingerprint,
)


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


    # A report generated after a capture can still have used an older checkout.
    # Fingerprints, not generated_at alone, must detect that race.
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for relative in SOURCE_DATA_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("version-one", encoding="utf-8")
        first_fingerprint = source_data_fingerprint(root)
        assert report_source_fingerprint_matches(
            {"source_data_fingerprint": first_fingerprint}, first_fingerprint
        )
        assert not report_source_fingerprint_matches({}, first_fingerprint), (
            "Reports without source fingerprints must be treated as unverified inputs."
        )
        changed_path = root / "data/nba_totals_probability_settlements.json"
        changed_path.write_text("version-two", encoding="utf-8")
        second_fingerprint = source_data_fingerprint(root)
        assert second_fingerprint != first_fingerprint
        assert not report_source_fingerprint_matches(
            {"source_data_fingerprint": first_fingerprint}, second_fingerprint
        )

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
    assert should_refresh_report(
        "workflow_run", now, new_capture, now, source_fingerprint_matches=False
    ), "A capture committed during report generation must force a fresh-input rerun even when generated_at is later."
    assert not should_refresh_report(
        "schedule", now, new_capture, now, source_fingerprint_matches=False
    ), "Periodic schedule refreshes must keep the ten-minute throttle."

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-totals-probability-value.yml").read_text(encoding="utf-8")
    assert "latest_snapshot_evidence_time" in workflow, (
        "The scheduled/event-driven workflow must include newer immutable quote revisions in its report-refresh decision."
    )
    assert "source_data_fingerprint" in workflow and "report_source_fingerprint_matches" in workflow, (
        "The workflow must detect source files that changed after a run checked out main."
    )
    assert "  workflow_run:" not in workflow, (
        "Capture and settlement must explicitly dispatch the report after new evidence is published; remove duplicate workflow_run handoffs."
    )

    assert "actions: write" in workflow, (
        "The evidence workflow needs Actions write permission to dispatch the post-publication release-gate regression."
    )
    assert "Dispatch latest-main NBA ticket gate regression after report publication" in workflow, (
        "Every refreshed evidence report must explicitly trigger the latest-main fail-closed gate regression."
    )
    assert "gh workflow run nba-ticket-guard-tests.yml --ref main" in workflow, (
        "The report-to-gate handoff must run against main after the report has been published."
    )
    guard_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-ticket-guard-tests.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in guard_workflow, (
        "The NBA ticket guard must support the explicit report-completion dispatch."
    )
    assert "workflow_run:" not in guard_workflow, (
        "Use the explicit post-publication dispatch as the single handoff; do not queue a duplicate automatic workflow_run test."
    )

    print("PASS: quote-revision freshness, source fingerprint race recovery, duplicate suppression, schedule throttle, and missing-report cases.")


if __name__ == "__main__":
    run()
