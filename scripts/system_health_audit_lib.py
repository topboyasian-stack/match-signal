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
