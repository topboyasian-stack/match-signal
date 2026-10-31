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
    watchdog = (WORKFLOWS / "automation_watchdog.yml").read_text(encoding="utf-8")
    tracker = (WORKFLOWS / "odds-ticket-tracker.yml").read_text(encoding="utf-8")
    collector = (WORKFLOWS / "virtual-lab-collector.yml").read_text(encoding="utf-8")
    live_sync = (WORKFLOWS / "virtual-lab-live-sync-heartbeat.yml").read_text(encoding="utf-8")
    autopilot = (WORKFLOWS / "autopilot-refresh.yml").read_text(encoding="utf-8")
    core_pipeline = (WORKFLOWS / "tennis_pipeline.yml").read_text(encoding="utf-8")
    health_audit = (ROOT / "scripts" / "system_health_audit.py").read_text(encoding="utf-8")

    builder_paths = push_paths("odds_builder.yml")
    board_paths = push_paths("unified-upcoming.yml")
    tracker_paths = push_paths("odds-ticket-tracker.yml")
    collector_paths = push_paths("virtual-lab-collector.yml")
    autopilot_paths = push_paths("autopilot-refresh.yml")

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
    # Builder publishes its artifact and then dispatches the promotion workflow,
    # which refreshes the board. A direct artifact push trigger would duplicate that run.
    assert "data/odds_builder.json" not in board_paths, (
        "Builder artifact must flow through the promotion workflow, not trigger a second board refresh."
    )
    assert "gh workflow run builder-production-promotion.yml --ref main" in builder
    assert "data/odds_ticket_tracker.json" in board_paths
    assert "data/virtual_lab_model_eval.json" not in board_paths, (
        "The model-evaluation artifact is collector-owned and must not retrigger the board workflow."
    )
    for generated_virtual_artifact in (
        "data/virtual_lab_participant_lifecycle.json",
        "data/virtual_lab_history.json",
        "data/virtual_lab_live.json",
        "data/virtual_lab_eligibility.json",
        "data/virtual_lab_participant_profiles.json",
        "data/virtual_lab_confirmed_participants.json",
        "data/virtual_lab_confirmed_participant_results.json",
        "data/virtual_lab_participants/**",
    ):
        assert generated_virtual_artifact not in board_paths, (
            f"Collector/live-sync output {generated_virtual_artifact} must be handled by its workflow_run completion, "
            "not also create a duplicate board run from push."
        )
    assert "data/virtual_lab_participants/**" not in collector_paths, (
        "The collector must not watch its own generated registry under the broad participant namespace."
    )
    assert "data/virtual_lab_participants/efootball_confirmed_watch.json" in collector_paths, (
        "The explicit manual watch input must still be able to trigger the collector."
    )
    for generated_collector_output in (
        "data/virtual_lab_confirmed_participants.json",
        "data/virtual_lab_participant_h2h.json",
        "data/virtual_lab_external_h2h.json",
        "data/virtual_lab_archive/**",
    ):
        assert generated_collector_output not in collector_paths, (
            f"Collector output {generated_collector_output} must not trigger another expensive collector run."
        )
    assert "cancel-in-progress: true" in collector, (
        "A newer fixed collector run must supersede an obsolete artifact-publication retry."
    )

    # Unified Upcoming is the single owner of the canonical all-sports board,
    # eFootball candidate pool and shared system-health artifact. Autopilot and
    # live/settlement collectors must not publish the same files concurrently.
    assert "scripts/unified_upcoming.py" not in autopilot_paths
    assert "scripts/selection_candidate_collector.py" not in autopilot_paths
    assert "python scripts/unified_upcoming.py" not in autopilot
    assert "python scripts/selection_candidate_collector.py" not in autopilot
    autopilot_publish = autopilot.split("      - name: Publish football readiness and autopilot status", 1)[1]
    autopilot_publish = autopilot_publish.split("      - name:", 1)[0]
    assert "data/unified_upcoming.json" not in autopilot_publish
    assert "data/selection_candidates.json" not in autopilot_publish
    assert "data/system_health.json" not in autopilot_publish
    assert "cancel-in-progress: true" in autopilot, (
        "A newer readiness-only heartbeat should supersede stale autopilot work instead of publishing behind it."
    )

    collector_publish = collector.split("      - name: Publish collector artifacts", 1)[1]
    assert "git add " in collector_publish
    assert "data/system_health.json" not in collector_publish

    live_sync_publish = live_sync.split("      - name: Publish live snapshot without overwriting newer data", 1)[1]
    assert "git add data/virtual_lab_live.json data/system_health.json" not in live_sync_publish
    assert "python scripts/virtual_lab_model_eval.py" not in board, (
        "Avoid recomputing the expensive chronological evaluation on every five-minute board refresh."
    )
    assert "python scripts/virtual_lab_model_eval.py" in collector
    assert "data/virtual_lab_model_eval.json" in collector
    assert "promotion_child:" in board
    assert "cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' || inputs.promotion_child != true }}" in board
    assert "SKIP_PROMOTION: ${{ github.event_name == 'workflow_dispatch' && inputs.promotion_child == true }}" in board

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
    assert "- cron: '5-59/5 * * * *'" in board, (
        "The five-minute Unified Upcoming refresh must remain active."
    )
    assert '"Match Signal Live Prediction Pipeline"' in board
    assert '"Match Signal Virtual Lab Collector"' in board
    assert '"Match Signal Virtual Lab Live Sync"' in board

    # Tracker is still refreshed from Builder / settlement / collector outputs,
    # and its own five-minute safety schedule remains enabled.
    assert "- cron: '*/5 * * * *'" in tracker
    assert "- cron: '7,17,27,37,47,57 * * * *'" in watch
    assert "or (watchdog_event_name == 'workflow_run' and source_workflow_conclusion == 'success')" in watchdog, (
        "A successful workflow-run heartbeat must trigger the Qualified Best monitor fallback when cron delivery is stale."
    )
    assert '"Match Signal Odds Builder"' in tracker
    assert '"Match Signal Result Settlement"' in tracker
    assert '"Match Signal Virtual Lab Collector"' in tracker
    assert "data/odds_builder.json" in tracker_paths

    # Optional NBA history enrichment must not block the canonical football/tennis feed.
    nba_step = core_pipeline.split("      - name: Normalize NBA 2026 team gamelog", 1)[1].split("      - name:", 1)[0]
    assert "continue-on-error: true" in nba_step, (
        "Missing optional NBA source must not stop core football/tennis predictions."
    )
    # Keep the retired core moneyline provider distinct from the active paper-only NBA totals lane.
    assert '"basketball_core_moneyline"' in health_audit
    assert '"nba_totals_desk"' in health_audit
    assert '"basketball": {"status": "RETIRED"' not in health_audit

    print("Match Signal workflow trigger boundary tests passed.")


if __name__ == "__main__":
    main()
