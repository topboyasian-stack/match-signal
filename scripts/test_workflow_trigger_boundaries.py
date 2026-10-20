#!/usr/bin/env python3
"""Regression checks that production artifact outputs do not re-trigger their consumers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def push_paths(filename):
    """Read the on.push.paths list without requiring a YAML parser dependency."""
    lines = (WORKFLOWS / filename).read_text(encoding="utf-8").splitlines()
    in_on = False
    in_push = False
    paths = set()
    for line in lines:
        if line.strip() == "on:":
            in_on = True
            in_push = False
            continue
        if not in_on:
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            in_push = line.strip() == "push:"
            continue
        if in_push and line.startswith("      - "):
            value = line.strip()[2:].strip()
            if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
                value = value[1:-1]
            paths.add(value)
    return paths


def main():
    builder = (WORKFLOWS / "odds_builder.yml").read_text(encoding="utf-8")
    board = (WORKFLOWS / "unified-upcoming.yml").read_text(encoding="utf-8")
    watch = (WORKFLOWS / "qualified-best-health-watch-v2.yml").read_text(encoding="utf-8")
    tracker = (WORKFLOWS / "odds-ticket-tracker.yml").read_text(encoding="utf-8")

    builder_paths = push_paths("odds_builder.yml")
    board_paths = push_paths("unified-upcoming.yml")
    tracker_paths = push_paths("odds-ticket-tracker.yml")

    # These are generated outputs, not Builder inputs. Keep the expensive Builder
    # on its 15-minute schedule and use the post-publication stale-artifact helper
    # for recovery, rather than running a full Builder on every five-minute board refresh.
    assert "data/unified_upcoming.json" not in builder_paths, (
        "Builder must rely on the Unified Upcoming workflow_run trigger, not both "
        "its artifact push and completion event."
    )
    assert "data/odds_ticket_tracker.json" not in builder_paths, (
        "Tracker output must not directly trigger the Builder; ticket calibration "
        "is refreshed on the Builder schedule and normal upstream completions."
    )
    # Preserve the repository's deploy-order contract: these public artifacts
    # are routed through the board workflow before the Pages deployment verifier.
    assert "data/odds_builder.json" in board_paths
    assert "data/odds_ticket_tracker.json" in board_paths

    # Verify that removing the output-to-consumer feedback does not stop updates.
    assert '"Match Signal Unified Upcoming Board"' not in builder, (
        "Avoid starting the expensive Builder after every five-minute board refresh; use its 15-minute schedule plus artifact-age recovery."
    )
    assert "Ensure Odds Builder refresh follows board publication" in board, (
        "The board must retain its stale-artifact recovery step after publishing outputs."
    )
    refresh_helper = (ROOT / "scripts" / "ensure_odds_builder_refresh.py").read_text(encoding="utf-8")
    assert "BUILDER_ARTIFACT_MAX_AGE_MINUTES = 18" in refresh_helper
    assert "- cron: '*/15 * * * *'" in builder, (
        "The 15-minute Builder refresh must remain active."
    )
    assert "- cron: '2-59/5 * * * *'" in board, (
        "The five-minute Unified Upcoming refresh must remain active."
    )
    assert '"Match Signal Live Prediction Pipeline"' in board
    assert '"Match Signal Virtual Lab Collector"' in board
    assert '"Match Signal Virtual Lab Live Sync"' in board

    # Tracker is still refreshed from Builder / settlement / collector outputs,
    # and its own five-minute safety schedule remains enabled.
    assert "- cron: '*/5 * * * *'" in tracker
    assert "- cron: '7,17,27,37,47,57 * * * *'" in watch
    assert '"Match Signal Odds Builder"' in tracker
    assert '"Match Signal Result Settlement"' in tracker
    assert '"Match Signal Virtual Lab Collector"' in tracker
    assert "data/odds_builder.json" in tracker_paths

    print("Match Signal workflow trigger boundary tests passed.")


if __name__ == "__main__":
    main()
