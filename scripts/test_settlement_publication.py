#!/usr/bin/env python3
"""Regression tests for append-only result-settlement publication under concurrent main writers."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "settle-results.yml"


class SettlementPublicationTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        marker = "      - name: Commit newly settled results"
        self.assertIn(marker, self.source)
        self.publish = self.source.split(marker, 1)[1]

    def test_non_fast_forward_retries_are_bounded_and_time_limited(self):
        self.assertIn("for attempt in 1 2 3 4 5; do", self.publish)
        self.assertIn("timeout --signal=TERM --kill-after=10s 60s", self.publish)
        self.assertIn("push origin HEAD:main", self.publish)
        self.assertIn("git fetch origin main", self.publish)
        self.assertIn("Failed to publish settled results after five synchronized attempts.", self.publish)
        self.assertIn("exit 1", self.publish)

    def test_unrelated_main_updates_rebase_without_losing_settlements(self):
        self.assertIn("if git rebase origin/main; then", self.publish)
        self.assertIn("git commit --amend --no-edit", self.publish)
        self.assertIn("scripts/current_performance.py", self.publish)
        self.assertIn("scripts/verify_performance_ledger.py", self.publish)

    def test_same_file_conflicts_rebuild_from_latest_main(self):
        abort = self.publish.index("git rebase --abort || true")
        reset = self.publish.index("git reset --hard origin/main", abort)
        settle = self.publish.index("python scripts/settle_same_day.py", reset)
        verify = self.publish.index("python scripts/verify_performance_ledger.py", settle)
        stage = self.publish.index("git add data/prediction_history.json", verify)
        self.assertLess(abort, reset)
        self.assertLess(reset, settle)
        self.assertLess(settle, verify)
        self.assertLess(verify, stage)

    def test_settlement_remains_scheduled_and_archives_are_not_rewritten(self):
        self.assertIn("- cron: '7,22,37,52 * * * *'", self.source)
        self.assertIn("data/prediction_history.json", self.publish)
        self.assertIn("Verify append-only performance ledger", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
