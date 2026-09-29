#!/usr/bin/env python3
"""Cleanup pass for the unified upcoming board.

The upstream builder can still emit historical retired lanes in the raw board.
This post-process step keeps the user-facing board focused on active engines
only, without changing the research artifacts preserved elsewhere.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PATH = DATA / "unified_upcoming.json"
NOW = datetime.now(timezone.utc)

RETIRED_SPORTS = {"darts", "table_tennis", "basketball"}

def load_payload() -> dict:
    try:
        raw = PATH.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}

def sort_key(row: dict):
    return (str(row.get("start_time") or ""), str(row.get("sport") or ""), str(row.get("league") or ""))

def rebuild_summary(events: list[dict], payload: dict) -> dict:
    sports = defaultdict(int)
    dates = defaultdict(int)
    live = 0
    pending = 0
    for row in events:
        sports[str(row.get("sport") or "unknown")] += 1
        dates[str(row.get("start_time") or "")[:10]] += 1
        if row.get("event_state") == "LIVE":
            live += 1
        if row.get("event_state") == "PENDING_SETTLEMENT":
            pending += 1
    summary = dict(payload.get("summary") or {})
    summary["events"] = len(events)
    summary["sports"] = dict(sorted(sports.items()))
    summary["dates"] = dict(sorted(dates.items()))
    summary["live"] = live
    summary["pending_settlement"] = pending
    return summary

def main() -> None:
    payload = load_payload()
    events = payload.get("events") if isinstance(payload, dict) else []
    if not isinstance(events, list):
        events = []

    kept = [
        row for row in events
        if isinstance(row, dict) and str(row.get("sport") or "").lower() not in RETIRED_SPORTS
    ]
    kept.sort(key=sort_key)
    payload["events"] = kept
    payload["summary"] = rebuild_summary(kept, payload)
    payload["generated_at"] = NOW.isoformat()
    payload.setdefault("mode", "PAPER_ONLY")
    payload.setdefault("horizon_days", 7)

    PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "retired_removed": sorted(RETIRED_SPORTS),
        "events_before": len(events),
        "events_after": len(kept),
        "generated_at": payload["generated_at"],
    }, indent=2))

if __name__ == "__main__":
    main()
