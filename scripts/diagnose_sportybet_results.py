#!/usr/bin/env python3
"""Diagnose SportyBet eFootball result API failures without writing settlement data."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE = os.getenv("MATCH_SIGNAL_PUBLIC_BASE", "https://match-signal.pages.dev").rstrip("/")
ORIGIN = "https://www.sportybet.com"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Current-Country": "NG",
    "Origin": ORIGIN,
    "Referer": ORIGIN + "/ng/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0 Safari/537.36",
}
SPORT_ID = "sr:sport:137"
RESULT_PATH = "/api/ng/factsCenter/eventResultList"
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def stamp(value: Any) -> datetime | None:
    try:
        if value is None:
            return None
        number = int(value)
        if number <= 0:
            return None
        if number < 10_000_000_000:
            number *= 1000
        return datetime.fromtimestamp(number / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None


def list_events(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        ts = data.get("tournaments")
        if isinstance(ts, list):
            return [e for t in ts if isinstance(t, dict)
                    for e in (t.get("events") or []) if isinstance(e, dict)]
    for key in ("events", "results"):
        if isinstance(body.get(key), list):
            return [e for e in body[key] if isinstance(e, dict)]
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    return []


def choose_archived_pending_scopes(now: datetime) -> list[dict[str, Any]]:
    """Target the actual pending archive IDs the collector could not match."""
    archive_path = Path(__file__).resolve().parents[1] / "data" / "efootball_market_research.json"
    try:
        archive = json.loads(archive_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("ARCHIVE_TARGET_READ_ERROR:", str(exc)[:300])
        return []
    samples = archive.get("observations", []) if isinstance(archive, dict) else []
    if not isinstance(samples, list):
        return []
    pending = {}
    for row in samples:
        if not isinstance(row, dict) or row.get("settlement_status") != "PENDING":
            continue
        event_id = str(row.get("event_id") or "")
        category = str(row.get("category_id") or "")
        tournament = str(row.get("tournament_id") or "")
        start = stamp(row.get("start_time"))
        product = str(row.get("product") or "")
        if not event_id or not category or not tournament or not start:
            continue
        age_minutes = (now - start).total_seconds() / 60
        if age_minutes < 10 or age_minutes > 24 * 60:
            continue
        old = pending.get(event_id)
        if old is None or start < old["start"]:
            pending[event_id] = {
                "categoryId": category,
                "tournamentId": tournament,
                "eventId": event_id,
                "start": start,
                "product": product,
                "age_minutes": round(age_minutes, 1),
            }
    if not pending:
        return []
    last_run = archive.get("last_run") or {}
    diagnostics = last_run.get("settlement_diagnostics") or {}
    preferred_ids = diagnostics.get("unmatched_event_ids_sample") or []
    ordered = []
    seen = set()
    for event_id in preferred_ids:
        event_id = str(event_id)
        if event_id in pending and event_id not in seen:
            ordered.append(pending[event_id])
            seen.add(event_id)
    for row in sorted(pending.values(), key=lambda x: x["age_minutes"], reverse=True):
        if row["eventId"] not in seen:
            ordered.append(row)
            seen.add(row["eventId"])
    selected = ordered[:2]
    if selected:
        print("ARCHIVE_TARGETED_DIAGNOSTICS: prioritizing pending/missed event IDs from the current research archive")
    return selected


def choose_scopes(now: datetime) -> list[dict[str, Any]]:
    """Prefer missed archived IDs, then fall back to current-feed discovery."""
    archived_scopes = choose_archived_pending_scopes(now)
    if archived_scopes:
        return archived_scopes
    try:
        response = requests.get(
            BASE + "/api/sportybet-virtual",
            params={"sources": "efootball", "pageSize": 100, "pageNum": 1, "timeline": 720},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = []
        for event in payload.get("events", []) if isinstance(payload, dict) else []:
            if not isinstance(event, dict) or event.get("product") not in {"efootball_gt", "efootball_adriatic"}:
                continue
            start = stamp(event.get("start_time_ms") or event.get("start_time"))
            category = str(event.get("category_id") or "")
            tournament = str(event.get("tournament_id") or "")
            event_id = str(event.get("event_id") or "")
            if not start or not category or not tournament or not event_id:
                continue
            age_minutes = (now - start).total_seconds() / 60
            if 5 <= age_minutes <= 360:
                candidates.append({
                    "categoryId": category,
                    "tournamentId": tournament,
                    "eventId": event_id,
                    "start": start,
                    "product": event.get("product"),
                })
        candidates.sort(key=lambda e: e["start"], reverse=True)
        seen = set()
        scopes = []
        for row in candidates:
            key = (row["categoryId"], row["tournamentId"])
            if key in seen:
                continue
            seen.add(key)
            scopes.append(row)
            if len(scopes) == 2:
                break
        if scopes:
            return scopes
        print("FEED_DIAGNOSTIC: no currently published eFootball events 5 minutes–6 hours past kickoff had complete result scopes")
    except Exception as exc:
        print("FEED_FETCH_ERROR:", str(exc)[:500])

    # Last-resort diagnostic scopes taken from real archived observations.
    # These are not used to settle any observations.
    return [
        {
            "categoryId": "sr:category:DUOZulxGpROuiWJY9mSejHQ",
            "tournamentId": "sr:tournament:DM1x2M3IySEGujruAVUPAGw",
            "eventId": "sr:match:D178111026",
            "start": datetime(2026, 10, 11, 10, 20, tzinfo=timezone.utc),
            "product": "efootball_gt",
        },
        {
            "categoryId": "sr:category:BcZlJfYIIStawujzL61oFaw",
            "tournamentId": "sr:tournament:BURtgjJwwT66zTf5NEuXEgA",
            "eventId": "sr:match:BAaEfkGbmfVG97BKAY4y9cg",
            "start": datetime(2026, 10, 11, 10, 54, tzinfo=timezone.utc),
            "product": "efootball_gt",
        },
    ]


def probe(scope: dict[str, Any], use_time_filter: bool, now: datetime) -> dict[str, Any]:
    params: dict[str, Any] = {
        "sportId": SPORT_ID,
        "categoryId": scope["categoryId"],
        "tournamentId": scope["tournamentId"],
        "pageSize": 100,
        "pageNum": 1,
    }
    if use_time_filter:
        # Mirror the collector's bounded query shape: 15m before the target
        # kickoff through the remainder of a fixed three-hour result window.
        start = scope["start"] - timedelta(minutes=15)
        end = start + timedelta(hours=3)
        params["startTime"] = int(start.timestamp() * 1000)
        params["endTime"] = int(end.timestamp() * 1000)

    result: dict[str, Any] = {
        "product": scope.get("product"),
        "categoryId": scope["categoryId"],
        "tournamentId": scope["tournamentId"],
        "targetEventId": scope["eventId"],
        "time_filter": use_time_filter,
        "params": params,
    }
    try:
        response = SESSION.get(ORIGIN + RESULT_PATH, params=params, timeout=12)
        result["http_status"] = response.status_code
        try:
            payload = response.json()
        except ValueError:
            result["non_json_preview"] = response.text[:300]
            return result

        result["bizCode"] = payload.get("bizCode") if isinstance(payload, dict) else None
        if isinstance(payload, dict):
            for key in ("message", "msg", "error", "errMsg", "code"):
                value = payload.get(key)
                if value is not None:
                    result[key] = str(value)[:600]
            result["payload_keys"] = sorted(payload.keys())[:40]
            data = payload.get("data")
            if isinstance(data, dict):
                result["data_keys"] = sorted(data.keys())[:40]
            events = list_events(payload)
            result["returned_events"] = len(events)
            exact_matches = [
                e for e in events
                if str(e.get("eventId") or e.get("event_id") or "") == scope["eventId"]
            ]
            result["exact_target_event_matches"] = len(exact_matches)
            result["sample_result_rows"] = [
                {
                    "eventId": str(e.get("eventId") or e.get("event_id") or ""),
                    "matchStatus": e.get("matchStatus"),
                    "setScore": e.get("setScore"),
                    "homeScore": e.get("homeScore"),
                    "awayScore": e.get("awayScore"),
                    "keys": sorted(e.keys())[:30],
                }
                for e in events[:3]
            ]
    except Exception as exc:
        result["request_error"] = str(exc)[:600]
    return result


def probe_deployed_proxy(scope: dict[str, Any], window_hours: float | None, now: datetime) -> dict[str, Any]:
    """Ask the deployed Cloudflare proxy, whose outbound network differs from Actions."""
    params: dict[str, Any] = {
        "source": "efootball",
        "categoryId": scope["categoryId"],
        "tournamentId": scope["tournamentId"],
        "pageSize": 100,
        "pageNum": 1,
    }
    if window_hours is not None:
        params["startTime"] = int((now - timedelta(hours=window_hours)).timestamp() * 1000)
        params["endTime"] = int((now + timedelta(minutes=2)).timestamp() * 1000)
    result: dict[str, Any] = {
        "probe": "deployed_match_signal_proxy",
        "categoryId": scope["categoryId"],
        "tournamentId": scope["tournamentId"],
        "targetEventId": scope["eventId"],
        "window_hours_before_now": window_hours,
    }
    try:
        response = requests.get(
            BASE + "/api/sportybet-virtual-results", params=params, timeout=25
        )
        result["http_status"] = response.status_code
        result["content_type"] = response.headers.get("content-type")
        try:
            payload = response.json()
        except ValueError:
            result["non_json_preview"] = response.text[:300]
            return result
        if isinstance(payload, dict):
            result["payload_keys"] = sorted(payload.keys())[:30]
            events = list_events(payload)
            result["returned_events"] = len(events)
            result["exact_target_event_matches"] = sum(
                1 for e in events
                if str(e.get("eventId") or e.get("event_id") or "") == scope["eventId"]
            )
            errors = payload.get("errors")
            if isinstance(errors, list):
                result["errors"] = [str(e)[:900] for e in errors[:5]]
            if payload.get("ok") is not None:
                result["ok"] = payload.get("ok")
    except Exception as exc:
        result["request_error"] = str(exc)[:600]
    return result

def main() -> None:
    now = datetime.now(timezone.utc)
    scopes = choose_scopes(now)
    print("DIAGNOSTIC_STARTED_AT:", now.isoformat())
    print("DIAGNOSTIC_SCOPE_COUNT:", len(scopes))
    for scope in scopes:
        scope["start"] = scope["start"] if isinstance(scope["start"], datetime) else stamp(scope["start"])
        print("SCOPE:", json.dumps({
            "product": scope.get("product"),
            "categoryId": scope["categoryId"],
            "tournamentId": scope["tournamentId"],
            "targetEventId": scope["eventId"],
            "start": scope["start"].isoformat() if scope.get("start") else None,
            "age_minutes": scope.get("age_minutes"),
        }, ensure_ascii=False))
        if not scope.get("start"):
            scope["start"] = now - timedelta(minutes=30)
        for with_filter in (False, True):
            print("DIRECT_RESULT_API_PROBE:", json.dumps(probe(scope, with_filter, now), ensure_ascii=False))
            time.sleep(0.4)
        for window_hours in (None, 3, 24, 26):
            print("DEPLOYED_PROXY_PROBE:", json.dumps(probe_deployed_proxy(scope, window_hours, now), ensure_ascii=False))
            time.sleep(0.4)
    print("DIAGNOSTIC_FINISHED_AT:", datetime.now(timezone.utc).isoformat())
    print("SAFETY: diagnostic only; no archive or production-selection writes performed")


if __name__ == "__main__":
    main()
