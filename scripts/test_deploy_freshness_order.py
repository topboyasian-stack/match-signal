#!/usr/bin/env python3
"""Prevent Pages from smoke-testing the desk before its fresh board is published."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES_WORKFLOW = (ROOT / ".github/workflows/cloudflare-pages.yml").read_text(encoding="utf-8")
BOARD_WORKFLOW = (ROOT / ".github/workflows/unified-upcoming.yml").read_text(encoding="utf-8")
MONITOR_WORKFLOW = (ROOT / ".github/workflows/qualified-best-live-monitor.yml").read_text(encoding="utf-8")
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
    def test_board_schedule_is_offset_from_hour_boundary(self):
        crons = workflow_schedule_crons(BOARD_WORKFLOW)
        self.assertIn("4-59/5 * * * *", crons)
        self.assertNotIn("*/5 * * * *", crons)

    def test_monitor_schedule_is_staggered_and_deployment_trigger_is_preserved(self):
        crons = workflow_schedule_crons(MONITOR_WORKFLOW)
        self.assertIn("2,7,12,17,22,27,32,37,42,47,52,57 * * * *", crons)
        self.assertNotIn("*/5 * * * *", crons)
        events_end = MONITOR_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = MONITOR_WORKFLOW[:events_end]
        self.assertIn('      - "Deploy Match Signal to Cloudflare Pages"', events)
        self.assertIn("    types: [completed]", events)

    def test_watchdog_schedule_is_rearmed_and_stale_board_self_heals_quickly(self):
        crons = workflow_schedule_crons(WATCHDOG_WORKFLOW)
        self.assertIn("1,11,21,31,41,51 * * * *", crons)
        self.assertIn("if unified_age > 0.5 and not active('unified-upcoming.yml'):", WATCHDOG_WORKFLOW)
        self.assertIn("'unified_upcoming_hours': 0.5", WATCHDOG_WORKFLOW)

    def test_pages_deploy_is_board_driven_with_guarded_cache_only_promotion(self):
        events_end = PAGES_WORKFLOW.find("\npermissions:")
        self.assertGreater(events_end, 0)
        events = PAGES_WORKFLOW[:events_end]
        self.assertIn('      - "Match Signal Unified Upcoming Board"', events)
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
            "football.html",
            "tennis.html",
            "basketball.html",
            "sport-hubs.css",
            "ms-design-system.css",
            "league-logos.js",
            "scripts/test_league_logos.mjs",
            ".github/workflows/cloudflare-pages.yml",
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
            ".github/workflows/qualified-best-live-monitor.yml",
        ):
            self.assertIn(allowed_path, PAGES_WORKFLOW)

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
