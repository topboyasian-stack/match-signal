#!/usr/bin/env python3
"""Guard the tennis forward publisher against non-fast-forward data loss.

This is a workflow-contract regression test: a valid discovery run must retry
against the newest main feed after another automation writer publishes first.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tennis-forward-window.yml"


class TennisForwardPublicationTests(unittest.TestCase):
    def test_publication_rebuilds_from_latest_main_inside_each_retry(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("for attempt in 1 2 3 4 5; do", source)
        fetch = source.index("git fetch origin main", source.index("for attempt in 1 2 3 4 5; do"))
        reset = source.index("git reset --hard origin/main", fetch)
        snapshot = source.index("git show origin/main:data/predictions.json > /tmp/pre_window_latest.json", reset)
        generate = source.index("python scripts/tennis_forward_window.py", snapshot)
        merge = source.index(
            "python scripts/merge_generated_feed.py /tmp/pre_window_latest.json data/predictions.json",
            generate,
        )
        stage = source.index("git add data/predictions.json data/tennis_forward_status.json", merge)
        push = source.index("if git push origin main; then", stage)
        retry = source.index("sleep $((attempt * 2))", push)
        self.assertLess(fetch, reset)
        self.assertLess(reset, snapshot)
        self.assertLess(snapshot, generate)
        self.assertLess(generate, merge)
        self.assertLess(merge, stage)
        self.assertLess(stage, push)
        self.assertLess(push, retry)

    def test_merge_or_generator_changes_trigger_a_publication_run(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("push:", source)
        self.assertIn("'.github/workflows/tennis-forward-window.yml'", source)
        self.assertIn("'scripts/tennis_forward_window.py'", source)
        self.assertIn("'scripts/merge_generated_feed.py'", source)

    def test_failed_push_does_not_silently_end_successfully(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("main moved during tennis publication", source)
        self.assertIn("Failed to publish tennis forward-window data after five attempts.", source)
        self.assertIn("exit 1", source)

    def test_health_and_upcoming_rebuild_after_tennis_forward_publication(self):
        workflows = [
            ROOT / ".github" / "workflows" / "autopilot-refresh.yml",
            ROOT / ".github" / "workflows" / "unified-upcoming.yml",
        ]
        for path in workflows:
            with self.subTest(workflow=path.name):
                source = path.read_text(encoding="utf-8")
                workflow_run = source.split("workflow_run:", 1)[1].split("  schedule:", 1)[0]
                self.assertIn('"Match Signal Tennis Forward Window"', workflow_run)

    def test_discovery_scope_stays_explicitly_atp_only_and_watch_only(self):
        generator = (ROOT / "scripts" / "tennis_forward_window.py").read_text(encoding="utf-8")
        self.assertIn('"scope": "active ATP singles only; WTA retired"', generator)
        self.assertIn('"qualification_status"] = "TENNIS_FORWARD_WATCH_NOT_QUALIFIED"', generator)
        self.assertIn('"qualified_for_builder"] = False', generator)


if __name__ == "__main__":
    unittest.main(verbosity=2)
