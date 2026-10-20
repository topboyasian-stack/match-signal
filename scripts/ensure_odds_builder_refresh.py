#!/usr/bin/env python3
"""Dispatch Odds Builder when its published artifact is stale.

The artifact timestamp is the source of truth: a recent workflow run does not
prove that a new data/odds_builder.json was published. Active runs and a short
cooldown still prevent duplicate dispatches during normal workflow delivery.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BUILDER_WORKFLOW = "odds_builder.yml"
BUILDER_ARTIFACT_MAX_AGE_MINUTES = 18
RECENT_RUN_COOLDOWN_MINUTES = 5
UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES = 16
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_runs(
    runs: list[dict[str, Any]],
    now: datetime | None = None,
    artifact_generated_at: Any = None,
    upstream_board_generated_at: Any = None,
) -> dict[str, Any]:
    """Refresh after a newer board publish; otherwise use artifact-age and run guards."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    artifact_stamp = parse_timestamp(artifact_generated_at)
    upstream_stamp = parse_timestamp(upstream_board_generated_at)
    artifact_age = (
        max(0.0, (now - artifact_stamp).total_seconds() / 60.0)
        if artifact_stamp is not None else None
    )
    upstream_age = (
        max(0.0, (now - upstream_stamp).total_seconds() / 60.0)
        if upstream_stamp is not None else None
    )
    board_newer = bool(upstream_stamp and (artifact_stamp is None or upstream_stamp > artifact_stamp))
    artifact_fields = {
        "artifact_age_minutes": round(artifact_age, 2) if artifact_age is not None else None,
        "artifact_max_age_minutes": BUILDER_ARTIFACT_MAX_AGE_MINUTES,
        "upcoming_board_age_minutes": round(upstream_age, 2) if upstream_age is not None else None,
        "upcoming_board_generated_at": upstream_stamp.isoformat() if upstream_stamp else None,
        "builder_artifact_generated_at": artifact_stamp.isoformat() if artifact_stamp else None,
        "upcoming_board_newer_than_builder_artifact": board_newer,
    }

    active = [
        run for run in runs
        if str(run.get("status") or "").lower() in ACTIVE_STATUSES
    ]
    if active:
        run = max(
            active,
            key=lambda item: parse_timestamp(item.get("createdAt"))
            or datetime.min.replace(tzinfo=timezone.utc),
        )
        active_started_at = parse_timestamp(run.get("createdAt"))
        # A Builder started before this board was published checked out an older
        # main-branch snapshot. Queue one follow-up now; the Builder concurrency
        # group keeps it pending until the active run finishes.
        if (
            board_newer
            and upstream_stamp is not None
            and active_started_at is not None
            and active_started_at < upstream_stamp
        ):
            return {
                "dispatch": True,
                "reason": "upcoming_board_advanced_during_active_builder_run",
                "active_run_id": run.get("databaseId"),
                "active_status": run.get("status"),
                **artifact_fields,
            }
        return {
            "dispatch": False,
            "reason": "active_builder_run",
            "active_run_id": run.get("databaseId"),
            "active_status": run.get("status"),
            **artifact_fields,
        }

    # If the only difference is a newer board timestamp, don't run the Builder
    # more often than its 15-minute schedule. This is a recovery path when a
    # scheduled Builder run was missed, not a trigger on every 5-minute board build.
    # The pre-board active-run race is handled above by queuing one pending refresh.
    if board_newer and artifact_age is not None and artifact_age < BUILDER_ARTIFACT_MAX_AGE_MINUTES:
        recent_runs = [
            (parse_timestamp(run.get("createdAt")), run)
            for run in runs
        ]
        recent_runs = [(stamp, run) for stamp, run in recent_runs if stamp is not None]
        if recent_runs:
            last_started_at, last_run = max(recent_runs, key=lambda item: item[0])
            last_run_age = max(0.0, (now - last_started_at).total_seconds() / 60.0)
            if last_run_age < UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES:
                return {
                    "dispatch": False,
                    "reason": "upcoming_board_newer_but_builder_recent",
                    "last_run_id": last_run.get("databaseId"),
                    "last_run_status": last_run.get("status"),
                    "run_age_minutes": round(last_run_age, 2),
                    "upcoming_board_refresh_min_interval_minutes": UPCOMING_BOARD_REFRESH_MIN_INTERVAL_MINUTES,
                    **artifact_fields,
                }
        return {
            "dispatch": True,
            "reason": "upcoming_board_newer_than_builder_artifact",
            **artifact_fields,
        }

    # An absent/stale output uses the established stale-artifact recovery path below.
    if artifact_age is not None and artifact_age < BUILDER_ARTIFACT_MAX_AGE_MINUTES:
        return {
            "dispatch": False,
            "reason": "builder_artifact_fresh",
            **artifact_fields,
        }

    parsed_runs = [
        (parse_timestamp(run.get("createdAt")), run)
        for run in runs
    ]
    parsed_runs = [(stamp, run) for stamp, run in parsed_runs if stamp is not None]
    if parsed_runs:
        last_started_at, last_run = max(parsed_runs, key=lambda item: item[0])
        run_age = max(0.0, (now - last_started_at).total_seconds() / 60.0)
        if run_age < RECENT_RUN_COOLDOWN_MINUTES:
            return {
                "dispatch": False,
                "reason": "recent_builder_run_cooldown",
                "last_run_id": last_run.get("databaseId"),
                "last_run_status": last_run.get("status"),
                "run_age_minutes": round(run_age, 2),
                **artifact_fields,
            }
    else:
        last_run = None
        run_age = None

    reason = "builder_artifact_stale" if artifact_stamp is not None else "builder_artifact_missing_or_invalid"
    result: dict[str, Any] = {
        "dispatch": True,
        "reason": reason,
        **artifact_fields,
    }
    if last_run is not None:
        result.update({
            "last_run_id": last_run.get("databaseId"),
            "last_run_status": last_run.get("status"),
            "run_age_minutes": round(run_age, 2) if run_age is not None else None,
        })
    else:
        result["run_history"] = "no_valid_builder_run_history"
    return result


def latest_artifact_generated_at(repo: str) -> str | None:
    """Read the committed main-branch artifact, falling back to the checked-out copy."""
    api = subprocess.run(
        [
            "gh", "api",
            f"repos/{repo}/contents/data/odds_builder.json?ref=main",
            "--jq", ".content",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if api.returncode == 0:
        try:
            decoded = base64.b64decode(api.stdout.strip()).decode("utf-8")
            artifact = json.loads(decoded)
            value = artifact.get("generated_at") if isinstance(artifact, dict) else None
            if value:
                return str(value)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"::warning::Could not parse the latest committed Odds Builder artifact: {exc}", file=sys.stderr)
    else:
        detail = api.stderr.strip() or "GitHub contents API read failed"
        print(f"::warning::Could not fetch the latest committed Odds Builder artifact: {detail}", file=sys.stderr)

    try:
        artifact = json.loads(Path("data/odds_builder.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::warning::No readable local Odds Builder artifact fallback: {exc}", file=sys.stderr)
        return None
    value = artifact.get("generated_at") if isinstance(artifact, dict) else None
    return str(value) if value else None


def latest_upcoming_board_generated_at() -> str | None:
    """Read the board file built earlier in the same Unified Upcoming workflow."""
    path = Path("data/unified_upcoming.json")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::warning::Could not parse Unified Upcoming artifact: {exc}", file=sys.stderr)
        return None
    value = artifact.get("generated_at") if isinstance(artifact, dict) else None
    if value is None and isinstance(artifact, dict):
        value = artifact.get("updated_at")
    return str(value) if value else None


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        print("::error::GITHUB_REPOSITORY is not set; cannot inspect Odds Builder history.", file=sys.stderr)
        return 1

    history = subprocess.run(
        [
            "gh", "run", "list",
            "--workflow", BUILDER_WORKFLOW,
            "--branch", "main",
            "--json", "databaseId,status,createdAt,conclusion,event",
            "--limit", "10",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if history.returncode != 0:
        print("::error::Could not inspect Odds Builder history: " + (history.stderr.strip() or "gh run list failed"), file=sys.stderr)
        return 1
    try:
        runs = json.loads(history.stdout)
    except json.JSONDecodeError as exc:
        print(f"::error::Odds Builder run history was not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(runs, list):
        print("::error::Odds Builder run history was not a JSON list.", file=sys.stderr)
        return 1

    artifact_generated_at = latest_artifact_generated_at(repo)
    upcoming_board_generated_at = latest_upcoming_board_generated_at()
    decision = evaluate_runs(
        runs,
        artifact_generated_at=artifact_generated_at,
        upstream_board_generated_at=upcoming_board_generated_at,
    )
    print(json.dumps({"workflow": BUILDER_WORKFLOW, **decision}, sort_keys=True))
    if not decision["dispatch"]:
        print("Odds Builder artifact is fresh, a run is active, or the short recent-run cooldown is in effect.")
        return 0

    dispatch = subprocess.run(
        ["gh", "workflow", "run", BUILDER_WORKFLOW, "--ref", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if dispatch.returncode != 0:
        print("::error::Odds Builder dispatch failed: " + (dispatch.stderr.strip() or "gh workflow run failed"), file=sys.stderr)
        return 1
    print("Dispatched Odds Builder because its artifact is stale/missing or a newer Upcoming Desk board postdates the active run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
