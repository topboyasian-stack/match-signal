#!/usr/bin/env python3
"""Prevent Pages from smoke-testing the desk before its fresh board is published."""
from __future__ import annotations

import re
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_WORKFLOW = (ROOT / ".github/workflows/cloudflare-pages.yml").read_text(encoding="utf-8")
BOARD_WORKFLOW = (ROOT / ".github/workflows/unified-upcoming.yml").read_text(encoding="utf-8")
MONITOR_WORKFLOW = (ROOT / ".github/workflows/qualified-best-production-watch.yml").read_text(encoding="utf-8")
SCHEDULE_MONITOR_WORKFLOW = (ROOT / ".github/workflows/qualified-best-schedule-watch.yml").read_text(encoding="utf-8")
LOGO_WORKFLOW = (ROOT / ".github/workflows/sync-club-logos.yml").read_text(encoding="utf-8")
WATCHDOG_WORKFLOW = (ROOT / ".github/workflows/automation_watchdog.yml").read_text(encoding="utf-8")


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
        self.assertNotIn("4-59/5 * * * *", crons, "cron must change to re-arm the missing scheduled board publisher")
        self.assertNotIn("*/5 * * * *", crons)

    def test_monitor_schedule_is_rearmed_and_deployment_trigger_is_preserved(self):
        # Keep deployment-triggered monitoring separate from the newly registered cron identity.
        self.assertEqual(workflow_schedule_crons(MONITOR_WORKFLOW), [])
        crons = workflow_schedule_crons(SCHEDULE_MONITOR_WORKFLOW)
        self.assertIn("1,11,21,31,41,51 * * * *", crons)
        self.assertNotIn("5,15,25,35,45,55 * * * *", crons, "schedule must move to a fresh workflow identity")
        self.assertNotIn("*/5 * * * *", crons)
        events_end = MONITOR_WORKFLOW.find("\\npermissions:")
        self.assertGreater(events_end, 0)
        events = MONITOR_WORKFLOW[:events_end]
        self.assertIn('      - "Deploy Match Signal to Cloudflare Pages"', events)
        self.assertIn("    types: [completed]", events)
        self.assertIn("QUALIFIED_BEST_MONITOR_WORKFLOW_FILE: qualified-best-schedule-watch.yml", MONITOR_WORKFLOW)
        self.assertIn("QUALIFIED_BEST_MONITOR_WORKFLOW_FILE: qualified-best-schedule-watch.yml", SCHEDULE_MONITOR_WORKFLOW)

    def test_watchdog_schedule_is_rearmed_and_stale_board_self_heals_quickly(self):
        crons = workflow_schedule_crons(WATCHDOG_WORKFLOW)
        self.assertIn("9,19,29,39,49,59 * * * *", crons)
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
        self.assertIn("workflow', 'run', 'qualified-best-schedule-watch.yml'", WATCHDOG_WORKFLOW)
        self.assertIn("monitor_schedule_fallback_needed = monitor_schedule_status in {'STALE', 'MISSING_SCHEDULED_RUN'}", WATCHDOG_WORKFLOW)
        self.assertIn("monitor_dispatch_age_minutes < 10", WATCHDOG_WORKFLOW, "a stale/missing schedule should auto-repair even when a recent deployment-triggered check exists, but fallback dispatches need a cooldown")
        self.assertIn("elif active('qualified-best-production-watch.yml') and not monitor_schedule_fallback_needed:", WATCHDOG_WORKFLOW, "an active deploy-triggered monitor must not suppress fallback when cron is stale or missing")
        self.assertIn("A deployment-triggered monitor is active; the fallback is queued behind it.", WATCHDOG_WORKFLOW, "record that the fallback is queued behind the active deployment check")
        self.assertIn("or cloudflare_success_event or heartbeat_signal_event", WATCHDOG_WORKFLOW)
        self.assertIn("source_workflow_name in {'Match Signal Odds Ticket Tracker', 'Match Signal Virtual Lab Live Sync'}", WATCHDOG_WORKFLOW)
        self.assertIn('      - "Match Signal Virtual Lab Live Sync"', WATCHDOG_WORKFLOW)
        self.assertIn("and source_workflow_conclusion == 'success'", WATCHDOG_WORKFLOW, "the event-driven browser fallback must run only after Cloudflare deployment succeeds")
        self.assertIn("MISSING_SCHEDULED_RUN", WATCHDOG_WORKFLOW, "flag when a newly registered monitor workflow still has no scheduled invocation after its 15-minute startup grace")
        self.assertIn("actions/workflows/qualified-best-schedule-watch.yml", WATCHDOG_WORKFLOW, "derive the startup grace from the workflow registration date")
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

    def test_pages_deploy_is_board_driven_with_guarded_cache_only_promotion(self):
        events_end = PAGES_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = PAGES_WORKFLOW[:events_end]
        self.assertIn('      - "Match Signal Unified Upcoming Board"', events)
        self.assertIn('      - "Match Signal Persistent Club Logo Registry"', events)
        self.assertIn("    types: [completed]", events)
        self.assertIn("  workflow_dispatch:", events)

        # Direct promotion is limited to explicit static page/assets plus their
        # regression/workflow files. Every changed path is still checked against
        # the allowlist in the deployment workflow before any production upload.
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
            ".github/workflows/cloudflare-pages.yml",
            ".github/workflows/qualified-best-schedule-watch.yml",
        }
        self.assertEqual(direct_paths, expected_direct_paths)
        self.assertIn("name: Guard cache-only direct promotion", PAGES_WORKFLOW)
        self.assertIn("if: github.event_name == 'push'", PAGES_WORKFLOW)
        self.assertIn("compare/${BEFORE_SHA}...${PUSH_SHA}", PAGES_WORKFLOW)
        self.assertIn("const forcedRevalidation=cacheControl.includes('max-age=0')&&cacheControl.includes('must-revalidate')", PAGES_WORKFLOW)
        for allowed_path in (
            *expected_direct_paths,
            "scripts/test_deploy_freshness_order.py",
            "scripts/test_prediction_desk_gates.mjs",
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
            "data/odds_builder.json",
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

    def test_feeder_workflows_cannot_bypass_the_board_refresh(self):
        bypasses = []
        workflow_dir = ROOT / ".github/workflows"
        for workflow_path in sorted(workflow_dir.glob("*.yml")):
            if workflow_path.name == "cloudflare-pages.yml":
                continue
            source = workflow_path.read_text(encoding="utf-8")
            if "gh workflow run cloudflare-pages.yml --ref main" in source:
                bypasses.append(str(workflow_path.relative_to(ROOT)))
        self.assertEqual(
            bypasses,
            [],
            "Feeder workflows must hand off through Unified Upcoming before Pages deployment",
        )

    def test_board_owned_outputs_do_not_trigger_a_self_refresh_loop(self):
        paths = workflow_push_paths(BOARD_WORKFLOW)
        for output in (
            "data/unified_upcoming.json",
            "data/prediction_desk_health.json",
            "data/selection_candidates.json",
            "data/system_health.json",
        ):
            self.assertNotIn(output, paths, f"{output} is generated by this workflow and must not retrigger it")

    def test_publishing_refresh_is_not_cancelled_or_dispatched_twice(self):
        self.assertIn("  cancel-in-progress: false", BOARD_WORKFLOW)
        self.assertNotIn("gh workflow run cloudflare-pages.yml", BOARD_WORKFLOW)
        self.assertIn(
            "Cloudflare deployment will start after this workflow completes.",
            BOARD_WORKFLOW,
        )


if __name__ == "__main__":
    unittest.main()
