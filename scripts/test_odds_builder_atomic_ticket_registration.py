#!/usr/bin/env python3
"""Guard against registering the same live event in sequential Builder runs.

The generated Builder artifact and its tracker reservation must be published in
one commit. Otherwise a queued Builder can read the new batch before the ticket
tracker has reserved its pending event IDs and produce overlapping tickets.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "odds_builder.yml"


class AtomicBuilderTicketRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        start = self.source.index("- name: Commit generated accumulator artifact")
        end = self.source.index("- name: Dispatch production promotion after Builder artifact publish", start)
        self.commit_step = self.source[start:end]

    def test_tracker_refresh_runs_inside_each_latest_main_publication_attempt(self):
        block = self.commit_step
        loop_start = block.index("for attempt in 1 2 3 4; do")
        loop_end = block.index("done", loop_start)
        loop = block[loop_start:loop_end]

        reset = loop.index("git reset --mixed origin/main")
        copy_builder = loop.index('cp "$output_dir/odds_builder.json" data/odds_builder.json')
        track = loop.index("python scripts/odds_ticket_tracker.py")
        stage = loop.index("git add data/odds_builder.json")

        self.assertLess(reset, copy_builder)
        self.assertLess(copy_builder, track)
        self.assertLess(track, stage)
        self.assertIn("data/odds_ticket_tracker.json", loop[stage:])

    def test_tracker_is_recomputed_after_retry_instead_of_copying_a_stale_snapshot(self):
        block = self.commit_step
        loop_start = block.index("for attempt in 1 2 3 4; do")
        loop_end = block.index("done", loop_start)
        loop = block[loop_start:loop_end]
        self.assertNotIn('cp "$output_dir/odds_ticket_tracker.json"', loop)
        self.assertEqual(loop.count("python scripts/odds_ticket_tracker.py"), 1)

    def test_workflow_explains_atomic_event_reservation_purpose(self):
        self.assertIn("Commit the tracker and batch artifact atomically", self.commit_step)
        self.assertIn("pending event holds", self.commit_step)
        self.assertIn("preserve settlements that landed on main", self.commit_step)


if __name__ == "__main__":
    unittest.main(verbosity=2)
