"""Regression tests for event-driven NBA totals report refresh timing."""

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

from nba_totals_report_refresh_gate import (
    SOURCE_DATA_FILES,
    SOURCE_CODE_FILES,
    latest_snapshot_evidence_time,
    report_source_fingerprint_matches,
    should_refresh_report,
    source_data_fingerprint,
)
from verify_nba_totals_report_fingerprint import verify as verify_nba_totals_report_fingerprint


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
        for relative in SOURCE_DATA_FILES + SOURCE_CODE_FILES:
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
        # A data-identical report from an older evaluator must still be rejected.
                changed_code = root / "scripts/nba_totals_walk_forward.py"
                changed_code.write_text("evaluator-version-two", encoding="utf-8")
                third_fingerprint = source_data_fingerprint(root)
                assert third_fingerprint != second_fingerprint
                assert not report_source_fingerprint_matches(
                    {"source_data_fingerprint": second_fingerprint}, third_fingerprint
                ), "Evaluator-code changes must invalidate previously generated reports."
        
        report_path = root / "data/nba_totals_probability_value_experiment.json"
        report_path.write_text(
            json.dumps({"source_data_fingerprint": third_fingerprint}),
            encoding="utf-8",
        )
        verifier_ok, verifier_mismatches = verify_nba_totals_report_fingerprint(root)
        assert verifier_ok and not verifier_mismatches, (
            "The production verifier must accept an exact match to the current source files."
        )
        changed_path.write_text("version-three", encoding="utf-8")
        verifier_ok, verifier_mismatches = verify_nba_totals_report_fingerprint(root)
        assert not verifier_ok and any(
            "nba_totals_probability_settlements.json" in mismatch
            for mismatch in verifier_mismatches
        ), "The production verifier must reject source changes made after report publication."

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
    concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
    assert "group: nba-totals-probability-value-research-v3-${{ github.event_name == 'schedule' && 'scheduled' || 'event-driven' }}" in concurrency, (
        "The report publisher queue must use the recovery namespace so an orphaned prior run cannot block fresh evidence."
    )
    assert "latest_snapshot_evidence_time" in workflow, (
        "The scheduled/event-driven workflow must include newer immutable quote revisions in its report-refresh decision."
    )
    assert "source_data_fingerprint" in workflow and "report_source_fingerprint_matches" in workflow, (
        "The workflow must detect source files that changed after a run checked out main."
    )
    reset_index = workflow.index("git reset --hard origin/main")
    candidate_oos_index = workflow.index('cp "$candidate_oos" data/nba_totals_oos_value_test.json', reset_index)
    fingerprint_check_index = workflow.index('fingerprint_matches="$(PYTHONPATH=scripts python - "$candidate_probability"', reset_index)
    assert reset_index < candidate_oos_index < fingerprint_check_index, (
        "The candidate OOS report must be overlaid before checking the probability report fingerprint; otherwise every retry compares against the previous OOS artifact."
    )
    assert "scripts/refresh_nba_totals_oos_report.py" in workflow, (
        "Settlement-only changes must refresh the fixed-cutoff OOS report as well as probability diagnostics."
    )
    assert "Refresh fixed-cutoff NBA OOS report from current official evidence" in workflow, (
        "The OOS report must be regenerated from current ledger, predictions, history and immutable snapshots."
    )
    assert workflow.index("Refresh fixed-cutoff NBA OOS report from current official evidence") < workflow.index("Run residual-calibrated SportyBet value diagnostics"), (
        "The probability report fingerprint must include the freshly regenerated OOS report."
    )
    assert "git add data/nba_totals_oos_value_test.json data/nba_totals_probability_value_experiment.json" in workflow, (
        "Both source-dependent reports must be published together."
    )
    assert "Source data changed during report generation; regenerating both reports on latest main." in workflow, (
        "Concurrent main updates must not publish reports with stale source fingerprints."
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
    assert "Dispatch ordered Builder Production Promotion after fresh NBA report publication" in workflow, (
        "Verified report publication must hand off through the required board/Builder ordering because GITHUB_TOKEN pushes do not trigger push workflows."
    )
    assert "gh workflow run builder-production-promotion.yml --ref main" in workflow, (
        "The report publisher must request the ordered Builder Production Promotion, not bypass it with a direct Pages deployment."
    )
    assert "active_promotion_runs" in workflow and "An ordered Builder Production Promotion is already queued or running" in workflow, (
        "A report refresh must reuse an active ordered promotion instead of starting a competing deployment."
    )
    assert "gh workflow run cloudflare-pages.yml" not in workflow, (
        "Only Builder Production Promotion may dispatch Cloudflare Pages directly."
    )
    assert workflow.index("Publish OOS and probability reports without stale source fingerprints") < workflow.index("Dispatch ordered Builder Production Promotion after fresh NBA report publication"), (
        "Promotion must be dispatched only after both report files pass source-fingerprint verification and publication."
    )
    promotion_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/builder-production-promotion.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in promotion_workflow, (
        "The ordered Builder Production Promotion must support the explicit report-completion handoff."
    )
    pages_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/cloudflare-pages.yml").read_text(encoding="utf-8")
    assert "  workflow_dispatch:" in pages_workflow, (
        "The direct static report deployment handoff requires an explicit Pages workflow_dispatch entry point."
    )
    guard_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-ticket-guard-tests.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in guard_workflow, (
        "The NBA ticket guard must support the explicit report-completion dispatch."
    )
    assert "workflow_run:" not in guard_workflow, (
        "Use the explicit post-publication dispatch as the single handoff; do not queue a duplicate automatic workflow_run test."
    )

    settlement_text = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-totals-settlement.yml").read_text(encoding="utf-8")
    capture_text = (Path(__file__).resolve().parents[1] / ".github/workflows/nba-totals-price-capture.yml").read_text(encoding="utf-8")
    assert "capture_triggered" in settlement_text and "CAPTURE_TRIGGERED" in settlement_text, (
        "Capture-triggered settlement dispatches must use the same ledger-age duplicate-suppression gate."
    )
    assert "age_minutes >= 10" in settlement_text, "Capture-triggered settlement must be throttled by ledger freshness."
    assert "gh workflow run nba-totals-settlement.yml --ref main -f capture_triggered=true" in capture_text, (
        "New exact quote snapshots must explicitly dispatch official ESPN settlement when the ledger is stale."
    )

    promotion_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/builder-production-promotion.yml").read_text(encoding="utf-8")
    fingerprint_guard_name = "Wait for current NBA report fingerprint before Pages dispatch"
    assert fingerprint_guard_name in promotion_workflow, (
        "Production promotion must wait for the latest NBA report fingerprint before deploying static artifacts."
    )
    assert "python scripts/verify_nba_totals_report_fingerprint.py" in promotion_workflow, (
        "The production promotion must use the same source-fingerprint contract as the report publisher."
    )
    fingerprint_guard_index = promotion_workflow.index(fingerprint_guard_name)
    pages_dispatch_index = promotion_workflow.index("Dispatch Cloudflare Pages after post-build board and Builder publication")
    assert fingerprint_guard_index < pages_dispatch_index, (
        "The NBA report fingerprint guard must run before Pages dispatch, not after deployment."
    )
    fingerprint_guard = promotion_workflow[fingerprint_guard_index:pages_dispatch_index]
    assert "git fetch origin main" in fingerprint_guard and "git reset --hard origin/main" in fingerprint_guard, (
        "The promotion must re-read latest main while waiting for a concurrent report publication."
    )
    assert "seq 1 30" in fingerprint_guard and "sleep 10" in fingerprint_guard, (
        "A report publication race must be retried for a bounded period, then fail closed instead of deploying stale reports."
    )

    print("PASS: quote-revision freshness, source fingerprint race recovery, production deployment fingerprint verification, duplicate suppression, schedule throttle, and missing-report cases.")


if __name__ == "__main__":
    run()
