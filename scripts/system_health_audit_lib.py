"""Small, testable diagnostics for the experimental England U21 PDL feed."""
from __future__ import annotations

from typing import Any


PDL_LEAGUE = "England Amateur - U21 Professional Development League"
STALE_PDL_STATES = {"STALE", "STALE_SOURCE_UNAVAILABLE"}


def pdl_health_summary(payload: dict[str, Any] | None, published_rows: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return a visible lane summary and safety issue without hiding source outages."""
    data = payload if isinstance(payload, dict) else {}
    state = str(data.get("status") or "UNKNOWN").strip().upper()
    try:
        published = max(0, int(published_rows))
    except (TypeError, ValueError):
        published = 0
    try:
        historical_rows = max(0, int(data.get("historical_rows") or 0))
    except (TypeError, ValueError):
        historical_rows = 0
    try:
        last_success_upcoming = max(0, int(data.get("current_upcoming") or 0))
    except (TypeError, ValueError):
        last_success_upcoming = 0

    stale = state in STALE_PDL_STATES
    lane = {
        "status": state,
        "paper_only": bool(data.get("paper_only", True)),
        "historical_rows_last_success": historical_rows,
        "upcoming_rows_last_success": last_success_upcoming,
        "published_prediction_rows": published,
        "last_attempt_at": data.get("last_attempt_at"),
        "last_successful_update_at": data.get("last_successful_update_at") or data.get("updated_at"),
        "last_error": (str(data.get("last_error"))[:500] if stale and data.get("last_error") else None),
    }

    issues: list[dict[str, str]] = []
    if stale and published:
        issues.append({
            "code": "PDL_STALE_PREDICTIONS_STILL_PUBLISHED",
            "severity": "critical",
            "detail": f"PDL status is {state} but {published} PDL prediction row(s) remain in data/predictions.json; stale experimental fixtures must be withheld.",
        })
    elif stale:
        issues.append({
            "code": "PDL_EXPERIMENTAL_FEED_STALE",
            "severity": "info",
            "detail": f"PDL experimental source is {state}; last-success timestamp is {lane['last_successful_update_at'] or 'unknown'}. The current prediction feed contains no PDL rows, so stale fixtures remain withheld.",
        })
    elif state != "CURRENT":
        issues.append({
            "code": "PDL_EXPERIMENTAL_FEED_STATUS_UNKNOWN",
            "severity": "warning",
            "detail": f"PDL feed status is {state}; source freshness has not been confirmed.",
        })
    return lane, issues



def virtual_live_health_summary(
    payload: dict[str, Any] | None,
    snapshot_age_hours: float,
    max_age_hours: float = 0.5,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Judge the actual live-feed snapshot, never a downstream board heartbeat."""
    data = payload if isinstance(payload, dict) else {}
    state = str(data.get("status") or "UNKNOWN").strip().upper()
    try:
        events = max(0, int(data.get("events_count") or 0))
    except (TypeError, ValueError):
        events = 0
    try:
        age = max(0.0, float(snapshot_age_hours))
    except (TypeError, ValueError):
        age = float("inf")

    check = {
        "engine": "virtual_live_feed",
        "status": "PASS",
        "age_hours": round(age, 2) if age != float("inf") else None,
        "threshold_hours": max_age_hours,
        "heartbeat_source": "virtual_lab_live.json",
        "events_count": events,
    }
    issues: list[dict[str, str]] = []

    if state != "LIVE" or events <= 0:
        check["status"] = "FAIL"
        issues.append({
            "code": "VIRTUAL_LIVE_FEED_INVALID",
            "severity": "critical",
            "detail": f"live virtual status={state!r}, events={events}; a non-empty LIVE snapshot is required",
        })
    elif age > max_age_hours:
        check["status"] = "STALE"
        issues.append({
            "code": "VIRTUAL_LIVE_FEED_STALE",
            "severity": "warning",
            "detail": (
                f"virtual_lab_live.json age {age:.2f}h exceeds {max_age_hours:.2f}h; "
                "a downstream Unified Upcoming refresh cannot substitute for a fresh source snapshot"
            ),
        })

    return check, issues


def nba_live_observation_health_summary(
    payload: dict[str, Any] | None,
    snapshot_age_hours: float,
    max_age_hours: float = 0.25,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Track the NBA live-observation collector heartbeat independently of game count."""
    data = payload if isinstance(payload, dict) else {}
    try:
        age = max(0.0, float(snapshot_age_hours))
    except (TypeError, ValueError):
        age = float("inf")
    games = data.get("games") or {}
    games_count = len(games) if isinstance(games, (dict, list)) else 0
    snapshots_count = 0
    values = games.values() if isinstance(games, dict) else games if isinstance(games, list) else []
    for game in values:
        if isinstance(game, dict):
            snapshots = game.get("snapshots") or []
            if isinstance(snapshots, list):
                snapshots_count += len(snapshots)

    check = {
        "engine": "nba_live_observation_recorder",
        "status": "PASS" if age <= max_age_hours else "STALE",
        "age_hours": round(age, 2) if age != float("inf") else None,
        "threshold_hours": max_age_hours,
        "heartbeat_source": "nba_live_observations.json",
        "games_tracked": games_count,
        "snapshots_recorded": snapshots_count,
    }
    issues: list[dict[str, str]] = []
    if check["status"] == "STALE":
        issues.append({
            "code": "NBA_LIVE_OBSERVATION_STALE",
            "severity": "warning",
            "detail": (
                f"nba_live_observations.json age {age:.2f}h exceeds {max_age_hours:.2f}h; "
                "the in-game observation recorder has not published a recent heartbeat"
            ),
        })
    return check, issues
