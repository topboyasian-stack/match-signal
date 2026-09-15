"""Autopilot freshness and source-coverage guard for Match Signal.

The guard is intentionally conservative: it verifies that the generated feed is
not stale and that live source data is represented. It never fabricates a match
or odds. A failed guard blocks publication so stale/broken data cannot silently
become the public feed.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATUS_PATH = DATA / "autopilot_status.json"


def now():
    return datetime.now(timezone.utc)


def parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    errors = []
    warnings = []
    predictions_path = DATA / "predictions.json"
    if not predictions_path.exists():
        errors.append("predictions.json missing")
        rows = []
    else:
        try:
            rows = json.loads(predictions_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError("predictions.json is not a list")
        except Exception as exc:
            rows = []
            errors.append(f"predictions.json unreadable: {exc}")

    current = now()
    active = []
    stale = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("prediction feed contains non-object row")
            continue
        dt = parse_dt(row.get("start_time"))
        if not dt:
            errors.append(f"prediction {row.get('event_id','?')} has invalid start_time")
            continue
        if dt >= current - timedelta(hours=6):
            active.append(row)
        elif not row.get("settled") and row.get("status") not in {"completed", "final"}:
            stale.append(row)

    if stale:
        errors.append(f"{len(stale)} unfinished predictions are older than 6 hours")

    try:
        ns = runpy.run_path(str(ROOT / "scripts" / "predict_today.py"))
        fetch_scoreboard = ns["fetch_scoreboard"]
        football_leagues = ns["FOOTBALL_LEAGUES"]
        source_checks = {}
        for label, league in football_leagues.items():
            try:
                board = fetch_scoreboard("soccer", league)
                source_events = {
                    str(e.get("id")) for e in board.get("events", [])
                    if not e.get("status", {}).get("type", {}).get("completed")
                }
                feed_events = {str(r.get("event_id")) for r in rows if r.get("league") == label}
                if source_events and not (source_events & feed_events):
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "MISSING"}
                    errors.append(f"{label}: source has upcoming events but feed has no matching event")
                else:
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "OK"}
            except Exception as exc:
                source_checks[label] = {"status": "SOURCE_ERROR", "error": str(exc)}
                warnings.append(f"{label}: source check failed: {exc}")

        tennis_leagues = ns["TENNIS_LEAGUES"]
        flatten = ns["flatten_tennis_board"]
        today = current.date()
        end = today + timedelta(days=7)
        for label, tour in tennis_leagues.items():
            try:
                board = fetch_scoreboard("tennis", tour.lower(), f"{today:%Y%m%d}-{end:%Y%m%d}")
                source_events = {str(e.get("id")) for e in flatten(board) if str(e.get("id"))}
                feed_events = {str(r.get("event_id")) for r in rows if r.get("league") == label}
                if source_events and not (source_events & feed_events):
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "MISSING"}
                    errors.append(f"{label}: source has upcoming events but feed has no matching event")
                else:
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "OK"}
            except Exception as exc:
                source_checks[label] = {"status": "SOURCE_ERROR", "error": str(exc)}
                warnings.append(f"{label}: source check failed: {exc}")
    except Exception as exc:
        source_checks = {}
        errors.append(f"canonical source check unavailable: {exc}")

    status = {
        "status": "HEALTHY" if not errors else "FAILED",
        "checked_at": current.isoformat(),
        "prediction_rows": len(rows),
        "active_rows": len(active),
        "stale_unfinished_rows": len(stale),
        "source_checks": source_checks,
        "errors": errors,
        "warnings": warnings,
        "policy": "FAIL_CLOSED_NO_FABRICATION",
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
