#!/usr/bin/env python3
"""Prevent Pages from smoke-testing the desk before its fresh board is published."""
from __future__ import annotations

import re
import runpy
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_WORKFLOW = (ROOT / ".github/workflows/cloudflare-pages.yml").read_text(encoding="utf-8")
BOARD_WORKFLOW = (ROOT / ".github/workflows/unified-upcoming.yml").read_text(encoding="utf-8")
MONITOR_WORKFLOW = (ROOT / ".github/workflows/qualified-best-production-watch.yml").read_text(encoding="utf-8")
SCHEDULE_MONITOR_WORKFLOW = (ROOT / ".github/workflows/qualified-best-health-watch-v2.yml").read_text(encoding="utf-8")
LOGO_WORKFLOW = (ROOT / ".github/workflows/sync-club-logos.yml").read_text(encoding="utf-8")
WATCHDOG_WORKFLOW = (ROOT / ".github/workflows/automation_watchdog.yml").read_text(encoding="utf-8")
PROMOTION_WORKFLOW = (ROOT / ".github/workflows/builder-production-promotion.yml").read_text(encoding="utf-8")
BUILDER_WORKFLOW = (ROOT / ".github/workflows/odds_builder.yml").read_text(encoding="utf-8")


def workflow_push_paths(source: str) -> set[str]:
    start = source.find("  push:\n")
    if start < 0:
        return set()
    paths_start = source.find("    paths:\n", start)
    paths_end = source.find("\n  workflow_dispatch:", paths_start)
    if paths_start < 0 or paths_end < 0:
        return set()
    return set(re.findall(r"^      - '([^']+)'$", source[paths_start:paths_end], re.MULTILINE))


def workflow_schedule_crons(source: str) -> list[str]:
    start = source.find("  schedule:\n")
    if start < 0:
        return []
    body_start = start + len("  schedule:\n")
    next_event = re.search(r"(?m)^  [A-Za-z_][A-Za-z0-9_-]*:", source[body_start:])
    end = body_start + next_event.start() if next_event else len(source)
    return [
        line.strip().split("'")[1]
        for line in source[start:end].splitlines()
        if "- cron: '" in line
    ]


class FreshnessDeployOrderingTests(unittest.TestCase):
    def test_virtual_qualified_rows_wait_for_the_next_60_minute_window(self):
        upcoming = runpy.run_path(str(ROOT / "scripts" / "unified_upcoming.py"))
        gate = upcoming["apply_virtual_kickoff_window_gate"]
        now = datetime(2026, 10, 14, 22, 0, tzinfo=timezone.utc)
        qualified = "BETTING_QUALIFIED_PAPER"
        self.assertEqual(gate(qualified, now + timedelta(hours=5), now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now + timedelta(minutes=61), now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now + timedelta(minutes=60), now), qualified)
        self.assertEqual(gate(qualified, now + timedelta(minutes=1), now), qualified)
        self.assertEqual(gate(qualified, now, now), "KICKOFF_WINDOW_PENDING")
        self.assertEqual(gate(qualified, now - timedelta(seconds=1), now), "KICKOFF_WINDOW_PENDING")
        # Existing model/value blockers must remain the reported blocker.
        self.assertEqual(gate("EDGE_BELOW_2PCT", now + timedelta(hours=5), now), "EDGE_BELOW_2PCT")

    def test_logo_registry_refreshes_after_live_team_feeds(self):
        events_end = LOGO_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = LOGO_WORKFLOW[:events_end]
        self.assertIn('      - "Match Signal Odds Builder"', events)
        self.assertIn('      - "Match Signal Virtual Lab Live Sync"', events)
        self.assertIn("    types: [completed]", events)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", LOGO_WORKFLOW)

    def test_board_schedule_is_offset_from_hour_boundary(self):
        crons = workflow_schedule_crons(BOARD_WORKFLOW)
        self.assertIn("2-59/5 * * * *", crons)
        self.assertNotIn("3-59/5 * * * *", crons, "cron must change to re-arm the missing scheduled board publisher")
        self.assertNotIn("4-59/5 * * * *", crons)
        self.assertNotIn("*/5 * * * *", crons)

    def test_monitor_schedule_is_rearmed_and_deployment_trigger_is_preserved(self):
        # Keep deployment-triggered monitoring separate from the newly registered cron identity.
        self.assertEqual(workflow_schedule_crons(MONITOR_WORKFLOW), [])
        crons = workflow_schedule_crons(SCHEDULE_MONITOR_WORKFLOW)
        self.assertIn("6,16,26,36,46,56 * * * *", crons)
        self.assertNotIn("1,11,21,31,41,51 * * * *", crons, "schedule must move to a fresh workflow identity")
        self.assertNotIn("*/5 * * * *", crons)
        events_end = MONITOR_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = MONITOR_WORKFLOW[:events_end]
        self.assertIn('      - "Deploy Match Signal to Cloudflare Pages"', events)
        self.assertIn("    types: [completed]", events)
        self.assertIn("QUALIFIED_BEST_MONITOR_WORKFLOW_FILE: qualified-best-health-watch-v2.yml", MONITOR_WORKFLOW)
        self.assertIn("QUALIFIED_BEST_MONITOR_WORKFLOW_FILE: qualified-best-health-watch-v2.yml", SCHEDULE_MONITOR_WORKFLOW)

    def test_watchdog_schedule_is_rearmed_and_stale_board_self_heals_quickly(self):
        crons = workflow_schedule_crons(WATCHDOG_WORKFLOW)
        self.assertIn("8,18,28,38,48,58 * * * *", crons)
        self.assertNotIn("1,11,21,31,41,51 * * * *", crons, "cron must change to re-arm the missing scheduled watchdog")
        self.assertIn("if unified_age > 0.2 and not active('unified-upcoming.yml'):", WATCHDOG_WORKFLOW)
        self.assertIn("'unified_upcoming_hours': 0.2", WATCHDOG_WORKFLOW)

    def test_watchdog_has_event_driven_monitoring_and_bounded_failure_recovery(self):
        self.assertIn('  workflow_run:\n    workflows:\n      - "Match Signal Unified Upcoming Board"\n      - "Deploy Match Signal to Cloudflare Pages"\n      - "Match Signal Odds Ticket Tracker"', WATCHDOG_WORKFLOW)
        self.assertIn("github.event.workflow_run.conclusion != 'success'", WATCHDOG_WORKFLOW, "successful board completions should be checked after deployment, not before it")
        self.assertIn("if: github.event_name != 'workflow_run'\n        run: python -m pip install --upgrade requests", WATCHDOG_WORKFLOW, "event-driven health checks must not reinstall the feed-sync dependency")
        self.assertIn("if: github.event_name != 'workflow_run'", WATCHDOG_WORKFLOW)
        self.assertIn("WATCHDOG_SOURCE_WORKFLOW_CONCLUSION", WATCHDOG_WORKFLOW)
        self.assertIn("source_workflow_conclusion != 'success'", WATCHDOG_WORKFLOW)
        self.assertIn("retry_age < 20", WATCHDOG_WORKFLOW)
        self.assertIn("qualified_best_monitor_last_run_age_minutes", WATCHDOG_WORKFLOW)
        self.assertIn("qualified_best_monitor_last_scheduled_run_age_minutes", WATCHDOG_WORKFLOW)
        self.assertIn("qualified_best_monitor_last_fallback_dispatch_age_minutes", WATCHDOG_WORKFLOW)
        self.assertIn("workflow', 'run', 'qualified-best-health-watch-v2.yml'", WATCHDOG_WORKFLOW)
        self.assertIn("monitor_schedule_fallback_needed = monitor_schedule_status in {'STALE', 'MISSING_SCHEDULED_RUN'}", WATCHDOG_WORKFLOW)
        self.assertIn("monitor_dispatch_age_minutes < 10", WATCHDOG_WORKFLOW, "a stale/missing schedule should auto-repair even when a recent deployment-triggered check exists, but fallback dispatches need a cooldown")
        self.assertIn("elif active('qualified-best-production-watch.yml') and not monitor_schedule_fallback_needed:", WATCHDOG_WORKFLOW, "an active deploy-triggered monitor must not suppress fallback when cron is stale or missing")
        self.assertIn("A deployment-triggered monitor is active; the fallback is queued behind it.", WATCHDOG_WORKFLOW, "record that the fallback is queued behind the active deployment check")
        self.assertIn("or cloudflare_success_event or heartbeat_signal_event", WATCHDOG_WORKFLOW)
        self.assertIn("source_workflow_name in {'Match Signal Odds Ticket Tracker', 'Match Signal Virtual Lab Live Sync'}", WATCHDOG_WORKFLOW)
        self.assertIn('      - "Match Signal Virtual Lab Live Sync"', WATCHDOG_WORKFLOW)
        self.assertIn("and source_workflow_conclusion == 'success'", WATCHDOG_WORKFLOW, "the event-driven browser fallback must run only after Cloudflare deployment succeeds")
        self.assertIn("MISSING_SCHEDULED_RUN", WATCHDOG_WORKFLOW, "flag when a newly registered monitor workflow still has no scheduled invocation after its 15-minute startup grace")
        self.assertIn("actions/workflows/qualified-best-health-watch-v2.yml", WATCHDOG_WORKFLOW, "derive the startup grace from the workflow registration date")
        step_start = WATCHDOG_WORKFLOW.index("      - name: Check freshness and self-heal stale workflows")
        heredoc_start = WATCHDOG_WORKFLOW.index("          python - <<'PY'\n", step_start) + len("          python - <<'PY'\n")
        heredoc_end = WATCHDOG_WORKFLOW.index("\n          PY", heredoc_start)
        embedded_python = textwrap.dedent(WATCHDOG_WORKFLOW[heredoc_start:heredoc_end])
        compile(embedded_python, ".github/workflows/automation_watchdog.yml:embedded-check", "exec")

    def test_watchdog_continues_self_heal_when_virtual_feed_fails(self):
        sync_step = re.search(
            r"(?ms)^      - name: Refresh Virtual Lab live snapshot\n(.*?)(?=^      - name: )",
            WATCHDOG_WORKFLOW,
        )
        self.assertIsNotNone(sync_step, "Watchdog must have a dedicated Virtual Lab sync step")
        self.assertIn(
            "if python scripts/virtual_lab_sync.py; then",
            sync_step.group(0),
            "Virtual Lab upstream outage must not abort the watchdog before stale-board recovery",
        )
        self.assertIn(
            "Continuing into freshness checks and stale-board recovery.",
            sync_step.group(0),
        )

    def test_cloudflare_deploy_concurrency_is_scoped_after_eligible_event_filter(self):
        before_jobs = PAGES_WORKFLOW.split("\njobs:", 1)[0]
        deploy_job = PAGES_WORKFLOW.split("\n  deploy:", 1)[1]
        self.assertNotIn("\nconcurrency:", before_jobs, "workflow-level locking lets an ineligible skipped workflow_run replace a pending deployment")
        self.assertIn("github.event.workflow_run.conclusion == 'success'", deploy_job)
        self.assertIn("    concurrency:\n      group: cloudflare-pages-v3\n      cancel-in-progress: false", deploy_job, "only an eligible deploy job should enter the shared production promotion queue")

    def test_pages_deploy_is_board_driven_with_guarded_cache_only_promotion(self):
        events_end = PAGES_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = PAGES_WORKFLOW[:events_end]
        self.assertIn('      - "Match Signal Unified Upcoming Board"', events)
        self.assertIn('      - "Match Signal Persistent Club Logo Registry"', events)
        self.assertIn("    types: [completed]", events)
        self.assertIn("  workflow_dispatch:", events)

        # Direct promotion is limited to UI/static assets and the scoped booking API.
        # Builder outputs, Builder engines, and the Pages workflow itself must wait for
        # Unified Upcoming to refresh and publish the board before production promotion.
        direct_paths = workflow_push_paths(PAGES_WORKFLOW)
        expected_direct_paths = {
            "_headers",
            "index.html",
            "upcoming.html",
            "qualified-best.html",
            "qualified-best-design.css",
            "scripts/test_qualified_best_design.mjs",
            "sport-hubs-design.css",
            "scripts/test_sport_hub_design.mjs",
            "independent-sport-design.css",
            "scripts/test_independent_sports_design.mjs",
            "darts.html",
            "table-tennis.html",
            "odds-builder.html",
            "expansion-odds-builder.js",
            "scripts/test_odds_builder_ui_freshness.mjs",
            "scripts/test_desk_quote_contract.mjs",
            "functions/api/sportybet-booking.js",
            "functions/api/odds-builder-data.js",
            "functions/api/sportybet-virtual-results.js",
            "scripts/test_sportybet_booking_batch_ids.mjs",
            "odds-builder-design.css",
            "reports.html",
            "reports-design.css",
            "virtual-lab/index.html",
            "virtual-lab-terminal.css",
            "scripts/test_workspace_terminal_design.mjs",
            "football.html",
            "tennis.html",
            "basketball.html",
            "sport-hubs.css",
            "sport-hubs.js",
            "ms-design-system.css",
            "core-workspaces-design.css",
            "scripts/test_core_workspaces_design.mjs",
            "league-logos.js",
            "scripts/test_league_logos.mjs",
            "workspace-ui.js",
            "data/club-logo-registry.json",
            "assets/club-logos/**",
            "data/licenses/**",
            "scripts/sync_club_logos.py",
            "scripts/test_club_logo_registry.py",
            ".github/workflows/qualified-best-health-watch-v2.yml",
            ".github/workflows/automation_watchdog.yml",
            ".github/workflows/efootball-market-research-schedule.yml",
            ".github/workflows/efootball-market-research-tests.yml",
            "scripts/test_automation_watchdog_research_recovery.py",
            "scripts/test_qualified_best_monitor.mjs",
        }
        self.assertEqual(direct_paths, expected_direct_paths)
        builder_owned_paths = {
            "scripts/odds_builder.py",
            "scripts/odds_builder_core.py",
            "scripts/test_odds_builder_score_replay.py",
            "scripts/test_odds_builder_upcoming_desk_recent_losses.py",
            ".github/workflows/odds_builder.yml",
            ".github/workflows/cloudflare-pages.yml",
        }
        self.assertTrue(builder_owned_paths.isdisjoint(direct_paths),
                        "Builder data/code and Pages workflow changes must deploy only after a fresh Unified Upcoming board")
        self.assertIn("name: Guard cache-only direct promotion", PAGES_WORKFLOW)
        self.assertIn("if: github.event_name == 'push'", PAGES_WORKFLOW)
        self.assertIn("compare/${BEFORE_SHA}...${PUSH_SHA}", PAGES_WORKFLOW)
        self.assertIn("const forcedRevalidation=cacheControl.includes('max-age=0')&&cacheControl.includes('must-revalidate')", PAGES_WORKFLOW)
        for allowed_path in (
            *expected_direct_paths,
            "scripts/test_deploy_freshness_order.py",
            "scripts/test_workflow_trigger_boundaries.py",
            "scripts/test_prediction_desk_gates.mjs",
            "scripts/test_upcoming_desk_policy.py",
            "docs/PREDICTION_DESK_POLICY.md",
            "scripts/qualified_best_monitor.mjs",
            "scripts/test_qualified_best_monitor.mjs",
            ".github/workflows/qualified-best-watch.yml",  # historical delete path for this schedule migration
            ".github/workflows/qualified-best-production-watch.yml",
            ".github/workflows/qualified-best-live-monitor.yml",  # historical delete path for this schedule migration
            ".github/workflows/unified-upcoming.yml",
        ):
            self.assertIn(allowed_path, PAGES_WORKFLOW)

    def test_pages_wait_for_the_exact_fresh_board_to_reach_production(self):
        self.assertIn("getFrom(deploymentBase, '/data/unified_upcoming.json')", PAGES_WORKFLOW)
        self.assertIn("immutableBoardGeneratedAt", PAGES_WORKFLOW)
        self.assertIn("attempt<=10", PAGES_WORKFLOW)
        self.assertIn("verifiedProductionBoard=snapshot", PAGES_WORKFLOW)
        self.assertIn("stale board timestamps cannot pass deployment verification", PAGES_WORKFLOW)
        self.assertIn("async function verifyImmutableContract(contract)", PAGES_WORKFLOW)
        self.assertIn("attempt <= 6", PAGES_WORKFLOW)
        self.assertIn("Immutable deployment verification exhausted retries", PAGES_WORKFLOW)

    def test_pages_inputs_route_through_board_workflow(self):
        board_paths = workflow_push_paths(BOARD_WORKFLOW)
        self.assertTrue(board_paths, "Unified workflow should trigger on publishable source/data paths")
        required_inputs = {
            "index.html",
            "upcoming.html",
            "qualified-best.html",
            "sport-hubs.js",
            "sport-hubs.css",
            "workspace-ui.js",
            "league.html",
            "functions/**",
            "data/predictions.json",
            "data/odds_ticket_tracker.json",
            "data/virtual_lab_live.json",
            "data/darts_*.json",
            "data/table_tennis_*.json",
            "data/pdl_predictions.json",
            "data/tennis_forward_status.json",
            "data/club-logo-registry.json",
            "assets/club-logos/**",
            ".github/workflows/cloudflare-pages.yml",
        }
        missing = sorted(required_inputs - board_paths)
        self.assertEqual(missing, [], f"Deployable inputs bypass the Unified board workflow: {missing}")

    def test_builder_promotion_dispatches_one_pages_deployment_for_manual_board_refresh(self):
        self.assertIn("uses: actions/checkout@v4", PROMOTION_WORKFLOW)
        self.assertIn("group: builder-production-promotion-v3", PROMOTION_WORKFLOW)
        self.assertNotIn("group: builder-production-promotion-v2", PROMOTION_WORKFLOW)
        self.assertIn("with:\n          ref: main", PROMOTION_WORKFLOW)
        self.assertIn("gh workflow run unified-upcoming.yml --ref main", PROMOTION_WORKFLOW)
        self.assertIn("id: board-refresh", PROMOTION_WORKFLOW)
        self.assertIn("BOARD_RUN_ID: ${{ steps.board-refresh.outputs.board_run_id }}", PROMOTION_WORKFLOW)
        self.assertIn("BOARD_HEAD_SHA: ${{ steps.board-refresh.outputs.board_head_sha }}", PROMOTION_WORKFLOW)
        self.assertIn("Dispatch Pages once for manually refreshed board and verify the published artifact", PROMOTION_WORKFLOW)
        self.assertIn("gh workflow run cloudflare-pages.yml --ref main", PROMOTION_WORKFLOW)
        self.assertIn("DEPLOY-VERIFY-CLOUDFLARE.json?ref=main", PROMOTION_WORKFLOW)
        self.assertIn("[[ \"$verification_status\" == VERIFIED* ]]", PROMOTION_WORKFLOW)
        self.assertIn("compare/$BOARD_HEAD_SHA...$verification_source", PROMOTION_WORKFLOW)
        self.assertIn('if [ "$verified_epoch_us" -ge "$dispatched_epoch_us" ] && [ "$merge_base" = "$BOARD_HEAD_SHA" ]; then', PROMOTION_WORKFLOW)
        self.assertIn('if: ${{ github.event_name != \'workflow_run\' || (github.event.workflow_run.conclusion == \'success\' && (github.event.workflow_run.name != \'Match Signal Unified Upcoming Board\' || github.event.workflow_run.event != \'workflow_dispatch\')) }}', PAGES_WORKFLOW)
        self.assertLess(
            PROMOTION_WORKFLOW.index("gh workflow run unified-upcoming.yml --ref main"),
            PROMOTION_WORKFLOW.index("Dispatch Pages once for manually refreshed board and verify the published artifact"),
            "Promotion must refresh the board before dispatching the one Pages deployment for that manual refresh.",
        )
    def test_builder_explicitly_dispatches_promotion_after_artifact_publish(self):
        publish_step = BUILDER_WORKFLOW.find("      - name: Commit generated accumulator artifact")
        dispatch_step = BUILDER_WORKFLOW.find("      - name: Dispatch production promotion after Builder artifact publish")
        self.assertGreaterEqual(publish_step, 0, "Builder must commit its generated artifact before promotion")
        self.assertGreater(dispatch_step, publish_step, "promotion must happen after the artifact publication step")
        self.assertIn("GH_TOKEN: ${{ github.token }}", BUILDER_WORKFLOW[dispatch_step:])
        self.assertIn("gh workflow run builder-production-promotion.yml --ref main", BUILDER_WORKFLOW[dispatch_step:])
        self.assertIn("  workflow_dispatch:", PROMOTION_WORKFLOW)
        self.assertIn(
            "concurrency:" + chr(10) + "  # A new queue identity lets the repaired promotion bypass jobs stuck in the old SHA matcher." + chr(10) + "  group: builder-production-promotion-v2" + chr(10) + "  cancel-in-progress: false",
            PROMOTION_WORKFLOW,
            "serialize promotion runs; each must finish board refresh and deploy before the next begins",
        )

    def test_feeder_workflows_cannot_bypass_the_board_refresh(self):
        bypasses = []
        workflow_dir = ROOT / ".github/workflows"
        for workflow_path in sorted(workflow_dir.glob("*.yml")):
            if workflow_path.name in {"cloudflare-pages.yml", "builder-production-promotion.yml"}:
                continue
            source = workflow_path.read_text(encoding="utf-8")
            if "gh workflow run cloudflare-pages.yml --ref main" in source:
                bypasses.append(str(workflow_path.relative_to(ROOT)))
        self.assertEqual(
            bypasses,
            [],
            "Only the promotion workflow may dispatch Pages, and only after the board refresh succeeds.",
        )
        self.assertIn("gh workflow run cloudflare-pages.yml --ref main", PROMOTION_WORKFLOW)
    def test_board_owned_outputs_do_not_trigger_a_self_refresh_loop(self):
        paths = workflow_push_paths(BOARD_WORKFLOW)
        for output in (
            "data/unified_upcoming.json",
            "data/prediction_desk_health.json",
            "data/selection_candidates.json",
            "data/system_health.json",
        ):
            self.assertNotIn(output, paths, f"{output} is generated by this workflow and must not retrigger it")

    def test_root_build_and_css_markers_are_generated_per_deployment(self):
        # Root-page smoke checks must follow the deployed source, not freeze the
        # 2026-10-13 pilot marker and thereby block later production changes.
        self.assertIn("id: prepare-pages", PAGES_WORKFLOW)
        self.assertIn('build_id="MS-UNIFIED-${build_tag}"', PAGES_WORKFLOW)
        self.assertIn("SOURCE_SHA: ${{ steps.source.outputs.sha }}", PAGES_WORKFLOW)
        self.assertIn('build_tag="$(date -u +%Y%m%d)-${SOURCE_SHA:0:12}"', PAGES_WORKFLOW)
        self.assertNotIn('build_tag="$(date -u +%Y%m%d)-${GITHUB_SHA:0:12}"', PAGES_WORKFLOW)
        self.assertIn('echo "build_id=$build_id" >> "$GITHUB_OUTPUT"', PAGES_WORKFLOW)
        self.assertIn("PAGES_BUILD_ID: ${{ steps.prepare-pages.outputs.build_id }}", PAGES_WORKFLOW)
        self.assertIn("const rootBuildMarker = String(process.env.PAGES_BUILD_ID || '')", PAGES_WORKFLOW)
        self.assertIn("markers:[rootBuildMarker,rootCssHref,'MS-DESK-2026.10.14-V1'", PAGES_WORKFLOW)
        self.assertIn("for (const marker of [rootBuildMarker,rootCssHref])", PAGES_WORKFLOW)
        self.assertNotIn("MS-UNIFIED-2026.10.13.4-DESIGN-PILOT1", PAGES_WORKFLOW)
        self.assertNotIn("ms-design-system.css?v=20261013-premium-terminal1", PAGES_WORKFLOW)

    def test_production_verification_json_uses_a_real_newline(self):
        # A literal backslash-n after the JSON document makes JSON.parse fail.
        self.assertIn("},indent=2)+'\\n')", PAGES_WORKFLOW)
        self.assertNotIn("},indent=2)+'\\\\n')", PAGES_WORKFLOW)
    def test_production_verification_does_not_claim_unrun_booking_smoke_passed(self):
        # A completed feed scan does not prove the booking POST was exercised.
        # NO_FUTURE_BATCH is an honest diagnostic, not a successful booking check.
        self.assertIn("booking_verified = booking.get('ok') is True and booking_status in {'PASS', 'VOLATILE_MARKET'}", PAGES_WORKFLOW)
        self.assertIn("'booking_api_post_not_verified'", PAGES_WORKFLOW)
        self.assertIn("'status':'VERIFIED' if verification_complete else 'VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE'", PAGES_WORKFLOW)
        self.assertIn("'booking_api_status':'VERIFIED' if booking_verified else booking_status", PAGES_WORKFLOW)

    def test_publishing_refresh_is_not_cancelled_or_dispatched_twice(self):
        self.assertIn("  cancel-in-progress: false", BOARD_WORKFLOW)
        self.assertNotIn("gh workflow run cloudflare-pages.yml", BOARD_WORKFLOW)
        self.assertIn(
            "Cloudflare deployment will start after this workflow completes.",
            BOARD_WORKFLOW,
        )


if __name__ == "__main__":
    unittest.main()
