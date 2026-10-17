#!/usr/bin/env python3
"""Dispatch Odds Builder from board runs when its regular cadence was missed.

GitHub can suppress downstream workflow triggers for workflows originally
started with GITHUB_TOKEN. The board calls this helper after publishing, making
the intended workflow_dispatch explicit while respecting the Builder's cadence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

BUILDER_WORKFLOW = "odds_builder.yml"
BUILDER_RUN_MAX_AGE_MINUTES = 14
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


def evaluate_runs(runs: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Return whether to dispatch, never duplicating an active Builder run."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

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
        return {
            "dispatch": False,
            "reason": "active_builder_run",
            "active_run_id": run.get("databaseId"),
            "active_status": run.get("status"),
        }

    parsed_runs = [
        (parse_timestamp(run.get("createdAt")), run)
        for run in runs
    ]
    parsed_runs = [(stamp, run) for stamp, run in parsed_runs if stamp is not None]
    if not parsed_runs:
        return {
            "dispatch": True,
            "reason": "no_valid_builder_run_history",
            "age_minutes": None,
        }

    last_started_at, last_run = max(parsed_runs, key=lambda item: item[0])
    age_minutes = max(0.0, (now - last_started_at).total_seconds() / 60.0)
    dispatch = age_minutes >= BUILDER_RUN_MAX_AGE_MINUTES
    return {
        "dispatch": dispatch,
        "reason": "builder_run_stale" if dispatch else "builder_run_recent",
        "age_minutes": round(age_minutes, 2),
        "last_run_id": last_run.get("databaseId"),
        "last_run_status": last_run.get("status"),
        "max_age_minutes": BUILDER_RUN_MAX_AGE_MINUTES,
    }


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

    decision = evaluate_runs(runs)
    print(json.dumps({"workflow": BUILDER_WORKFLOW, **decision}, sort_keys=True))
    if not decision["dispatch"]:
        print("Odds Builder is active or ran within the 14-minute freshness guard; no additional run queued.")
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
    print("Dispatched Odds Builder because no active run exists and its last run is stale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
