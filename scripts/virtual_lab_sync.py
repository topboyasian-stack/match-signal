#!/usr/bin/env python3
"""Collect live SportyBet NG virtual/eFootball/SRL events for Match Signal.

Read-only. Uses the existing Match Signal Cloudflare proxy first, then the
public SportyBet web endpoint as a fallback. No login, wagering, or account
operations are performed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PUBLIC_BASE = os.getenv("MATCH_SIGNAL_PUBLIC_BASE", "https://match-signal.pages.dev").rstrip("/")
PROXY = f"{PUBLIC_BASE}/api/sportybet"
DIRECT = "https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents"
SPORTYBET_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Current-Country": "NG",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
}
MARKETS = "1,18,10,29,11,26,36,14,60100,186,189,202,204,210"
VIRTUAL_TERMS = re.compile(r"(simulated reality|\bsrl\b|gt sports league|gt leagues|eadriatic|efootball|e soccer|esoccer|virtual football|zoom|turbo)", re.I)


def request_json(url: str, params: dict, headers: dict) -> dict:
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict):
        raise RuntimeError("upstream JSON was not an object")
    if body.get("bizCode") not in (None, 10000):
        raise RuntimeError(f"SportyBet bizCode={body.get('bizCode')}")
    return body


def fetch_page(page: int) -> tuple[dict, str]:
    params = {
        "sportId": "sr:sport:1",
        "marketId": MARKETS,
        "pageSize": "100",
        "pageNum": str(page),
        "todayGames": "false",
        "timeline": "168",
        "_t": str(int(datetime.now(tz=timezone.utc).timestamp() * 1000)),
    }
    proxy_error = None
    try:
        body = request_json(PROXY, params, {"Accept": "application/json", "User-Agent": "MatchSignal-VirtualLab/1.0"})
        return body, "cloudflare_proxy"
    except Exception as exc:
        proxy_error = str(exc)
    try:
        return request_json(DIRECT, params, SPORTYBET_HEADERS), "sportybet_web_api"
    except Exception as exc:
        raise RuntimeError(f"proxy={proxy_error}; direct={exc}") from exc


def product_for(tournament: str, category: str, home: str, away: str) -> str | None:
    blob = f"{tournament} {category} {home} {away}".lower()
    if "eadriatic" in blob:
        return "efootball_adriatic"
    if "gt sports league" in blob or "gt leagues" in blob or "efootball" in blob or "e-soccer" in blob or "esoccer" in blob:
        return "efootball_gt"
    if "simulated reality" in blob or re.search(r"\bsrl\b", blob):
        return "srl"
    if "virtual football" in blob:
        return "vfootball"
    if "zoom" in blob or "turbo" in blob:
        return "zoom"
    if "virtual" in blob or "simulated" in blob:
        return "other"
    return None


def line_from_specifier(value: object) -> float | None:
    match = re.search(r"(?:total|line)=([0-9]+(?:\.[0-9]+)?)", str(value or ""), re.I)
    return float(match.group(1)) if match else None


def compact_event(event: dict, tournament: str, category: str, product: str) -> dict:
    markets = []
    for market in event.get("markets") or []:
        outcomes = []
        for outcome in market.get("outcomes") or []:
            odds = outcome.get("odds")
            try:
                odds = float(odds)
            except (TypeError, ValueError):
                odds = None
            if odds is None or odds <= 0:
                continue
            outcomes.append({
                "id": str(outcome.get("id") or ""),
                "name": str(outcome.get("desc") or outcome.get("name") or ""),
                "odds": odds,
                "active": bool(outcome.get("isActive", True)),
            })
        if outcomes:
            markets.append({
                "id": str(market.get("id") or ""),
                "name": str(market.get("desc") or market.get("name") or market.get("title") or ""),
                "specifier": market.get("specifier"),
                "line": line_from_specifier(market.get("specifier")),
                "status": market.get("status"),
                "outcomes": outcomes,
                "odds_changed_at": market.get("lastOddsChangeTime"),
            })
    start_ms = event.get("estimateStartTime")
    try:
        start_iso = datetime.fromtimestamp(float(start_ms) / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        start_iso = None
    return {
        "product": product,
        "provider": "SportyBet NG",
        "event_id": str(event.get("eventId") or ""),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "competition": tournament,
        "category": category,
        "participant_1": str(event.get("homeTeamName") or ""),
        "participant_2": str(event.get("awayTeamName") or ""),
        "start_time": start_iso,
        "match_status": event.get("matchStatus"),
        "markets": markets,
        "source": "SportyBet NG web API via Match Signal Cloudflare proxy",
    }


def main() -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    events_by_id: dict[str, dict] = {}
    sources: set[str] = set()
    errors: list[str] = []

    for page in range(1, 6):
        try:
            body, source = fetch_page(page)
            sources.add(source)
            data = body.get("data") or {}
            tournaments = data.get("tournaments") or []
            page_count = 0
            for tournament in tournaments:
                t_name = str(tournament.get("name") or "")
                category = str(tournament.get("categoryName") or "")
                for event in tournament.get("events") or []:
                    home = str(event.get("homeTeamName") or "")
                    away = str(event.get("awayTeamName") or "")
                    product = product_for(t_name, category, home, away)
                    if not product:
                        continue
                    row = compact_event(event, t_name, category, product)
                    if row["event_id"]:
                        events_by_id[row["event_id"]] = row
                        page_count += 1
            if len(tournaments) < 1 and page == 1:
                errors.append("SportyBet returned no tournaments")
            print(f"page={page} virtual_events={page_count}")
            if page_count == 0 and page > 1:
                break
        except Exception as exc:
            errors.append(f"page {page}: {exc}")
            print(errors[-1])

    events = sorted(
        events_by_id.values(),
        key=lambda x: (x.get("start_time") or "", x.get("product") or "", x.get("event_id") or ""),
    )
    counts: dict[str, int] = {}
    for row in events:
        counts[row["product"]] = counts.get(row["product"], 0) + 1

    payload = {
        "updated_at": now,
        "status": "LIVE" if events else "UPSTREAM_EMPTY",
        "source": sorted(sources) or ["none"],
        "endpoint": PROXY,
        "events_count": len(events),
        "product_counts": counts,
        "events": events,
        "errors": errors,
        "refresh_seconds": 30,
    }

    out = DATA / "virtual_lab_live.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "events_count": len(events),
        "product_counts": counts,
        "errors": errors,
    }, indent=2))
    if not events:
        raise SystemExit("ABORT: no virtual/eFootball/SRL events were collected from SportyBet")


if __name__ == "__main__":
    main()
