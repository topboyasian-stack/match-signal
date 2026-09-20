"""Autopilot freshness, coverage and probability-integrity guard.

Fail closed: source outages, erased core coverage, malformed probabilities and
unsafe experimental flags block publication. No fixtures or odds are fabricated.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATUS_PATH = DATA / "autopilot_status.json"
CORE_FOOTBALL = {"EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Champions League", "MLS", "Primeira Liga"}
EXPERIMENTAL = {"Eredivisie", "Saudi Pro League"}
TENNIS = {"ATP", "WTA"}


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


def check_prediction_row(row, errors):
    sport = row.get("sport")
    probs = row.get("probabilities") or {}
    try:
        if sport == "football":
            keys = ("p1", "draw", "p2")
        elif sport == "tennis":
            keys = ("p1", "p2")
        else:
            return
        values = [float(probs[k]) for k in keys]
        if any(v < 0 or v > 1 for v in values):
            raise ValueError("probability outside [0,1]")
        if abs(sum(values) - 1.0) > 0.02:
            raise ValueError(f"probabilities sum to {sum(values):.6f}")
        expected_pick = keys[max(range(len(values)), key=values.__getitem__)]
        if row.get("pick") and row.get("pick") != expected_pick:
            raise ValueError(f"pick {row.get('pick')} disagrees with probability maximum {expected_pick}")
        confidence = row.get("confidence")
        if confidence is not None and abs(float(confidence) - max(values)) > 0.02:
            raise ValueError("confidence disagrees with probability maximum")
        if sport == "football":
            ou = (row.get("markets") or {}).get("over_under") or {}
            if ou:
                over, under = float(ou.get("over")), float(ou.get("under"))
                if min(over, under) < 0 or max(over, under) > 1 or abs(over + under - 1) > 0.02:
                    raise ValueError("football O/U probabilities are invalid")
            btts = (row.get("markets") or {}).get("btts") or {}
            if btts:
                yes, no = float(btts.get("yes")), float(btts.get("no"))
                if min(yes, no) < 0 or max(yes, no) > 1 or abs(yes + no - 1) > 0.02:
                    raise ValueError("football BTTS probabilities are invalid")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"{row.get('event_id', '?')}: {exc}")


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
    league_counts = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("prediction feed contains non-object row")
            continue
        league = str(row.get("league") or "")
        league_counts[league] = league_counts.get(league, 0) + 1
        dt = parse_dt(row.get("start_time"))
        if not dt:
            errors.append(f"prediction {row.get('event_id','?')} has invalid start_time")
            continue
        check_prediction_row(row, errors)
        if row.get("paper_only") is False and row.get("league") in EXPERIMENTAL:
            errors.append(f"{row.get('event_id','?')}: experimental league is not marked paper_only")
        if dt >= current - timedelta(hours=6):
            active.append(row)
        elif not row.get("settled") and row.get("status") not in {"completed", "final"}:
            stale.append(row)

    if stale:
        errors.append(f"{len(stale)} unfinished predictions are older than 6 hours")

    core_rows = [r for r in rows if r.get("sport") == "football" and r.get("league") in CORE_FOOTBALL]
    if not core_rows:
        errors.append("canonical football feed is empty")

    try:
        ns = runpy.run_path(str(ROOT / "scripts" / "predict_today.py"))
        fetch_scoreboard = ns["fetch_scoreboard"]
        football_leagues = ns["FOOTBALL_LEAGUES"]
        source_checks = {}
        for label, league in football_leagues.items():
            try:
                board = fetch_scoreboard("soccer", league)
                source_events = {str(e.get("id")) for e in board.get("events", []) if not e.get("status", {}).get("type", {}).get("completed")}
                feed_events = {str(r.get("event_id")) for r in rows if r.get("league") == label}
                if source_events and not (source_events & feed_events):
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "MISSING"}
                    errors.append(f"{label}: source has upcoming events but feed has no matching event")
                elif source_events and not feed_events:
                    source_checks[label] = {"source_events": len(source_events), "feed_events": 0, "status": "MISSING"}
                    errors.append(f"{label}: source has events but feed has zero rows")
                else:
                    source_checks[label] = {"source_events": len(source_events), "feed_events": len(feed_events), "status": "OK"}
            except Exception as exc:
                source_checks[label] = {"status": "SOURCE_ERROR", "error": str(exc)}
                errors.append(f"{label}: source check failed: {exc}")

        flatten = ns["flatten_tennis_board"]
        tennis_fixture_quality = ns["tennis_fixture_quality"]
        today = current.date()
        end = today + timedelta(days=7)
        for label, tour in ns["TENNIS_LEAGUES"].items():
            try:
                board = fetch_scoreboard("tennis", tour.lower(), f"{today:%Y%m%d}-{end:%Y%m%d}")
                raw_events = [e for e in flatten(board) if str(e.get("id"))]
                source_events = {str(e.get("id")) for e in raw_events if tennis_fixture_quality(e)[0]}
                feed_events = {str(r.get("event_id")) for r in rows if r.get("league") == label}
                if source_events and not feed_events:
                    source_checks[label] = {"raw_source_events": len(raw_events), "actionable_source_events": len(source_events), "feed_events": 0, "status": "MISSING"}
                    errors.append(f"{label}: source has actionable singles but feed has zero rows")
                elif source_events and not (source_events & feed_events):
                    source_checks[label] = {"raw_source_events": len(raw_events), "actionable_source_events": len(source_events), "feed_events": len(feed_events), "status": "MISSING"}
                    errors.append(f"{label}: source has actionable singles but feed has no matching event")
                else:
                    source_checks[label] = {"raw_source_events": len(raw_events), "actionable_source_events": len(source_events), "feed_events": len(feed_events), "status": "OK"}
            except Exception as exc:
                source_checks[label] = {"status": "SOURCE_ERROR", "error": str(exc)}
                errors.append(f"{label}: source check failed: {exc}")
    except Exception as exc:
        source_checks = {}
        errors.append(f"canonical source check unavailable: {exc}")

    status = {
        "status": "HEALTHY" if not errors else "FAILED",
        "checked_at": current.isoformat(),
        "prediction_rows": len(rows),
        "active_rows": len(active),
        "stale_unfinished_rows": len(stale),
        "league_counts": league_counts,
        "source_checks": source_checks,
        "errors": errors,
        "warnings": warnings,
        "policy": "FAIL_CLOSED_NO_FABRICATION_NO_SPORT_ERASURE",
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
