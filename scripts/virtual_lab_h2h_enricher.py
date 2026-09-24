#!/usr/bin/env python3
"""Capture prospective external eSoccer H2H context for upcoming Virtual Lab events.

This is an enrichment ledger, not a model override. Snapshots are timestamped
at lookup time and tied to the upcoming SportyBet event so later validation can
test whether the information adds predictive value without look-ahead leakage.

Green365 is treated as an independent secondary source. The collector fails
open if the site is unavailable or rate-limits us; internal SportyBet history
remains authoritative.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "virtual_lab_external_h2h.json"
PROFILES = DATA / "virtual_lab_participant_profiles.json"

SPORTYBET_URL = "https://match-signal.pages.dev/api/sportybet-virtual"
GREEN365_HOME = "https://green365.com.br/fifa"
GREEN365_ROOT = "https://green365.com.br"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": "MatchSignal-VirtualLab-H2H/1.0",
    }
)

MAX_EVENTS = 200
MAX_PAIR_FETCHES = 24
MIN_CACHE_MINUTES = 30
HISTORY_CAP = 12000


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def participant_from_name(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    match = re.search(r"\(([^()]+)\)\s*$", text)
    return match.group(1).strip() if match else text


def product_for_event(raw):
    product = str(raw.get("product") or "").lower().strip()
    return product if product in {"efootball_gt", "efootball_adriatic"} else None


def load_json(path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch_upcoming():
    events = []
    seen = set()
    errors = []
    for page_num in (1, 2):
        try:
            response = SESSION.get(
                SPORTYBET_URL,
                params={
                    "pageSize": 100,
                    "pageNum": page_num,
                    "timeline": 168,
                    "sources": "efootball",
                    "_t": int(time.time() * 1000),
                },
                timeout=25,
            )
            response.raise_for_status()
            body = response.json()
            for raw in body.get("events") or []:
                product = product_for_event(raw)
                event_id = str(raw.get("event_id") or raw.get("eventId") or "").strip()
                p1 = participant_from_name(raw.get("participant_1") or raw.get("team_1") or "")
                p2 = participant_from_name(raw.get("participant_2") or raw.get("team_2") or "")
                if not product or not event_id or not p1 or not p2 or event_id in seen:
                    continue
                start_ms = raw.get("start_time_ms")
                try:
                    start_ms = int(float(start_ms))
                except (TypeError, ValueError):
                    start_ms = None
                if start_ms and start_ms < int(time.time() * 1000) - 120000:
                    continue
                seen.add(event_id)
                events.append(
                    {
                        "event_id": event_id,
                        "product": product,
                        "competition": str(raw.get("tournament") or raw.get("competition") or "Unknown"),
                        "participant_1": p1,
                        "participant_2": p2,
                        "team_1": str(raw.get("team_1") or ""),
                        "team_2": str(raw.get("team_2") or ""),
                        "start_time_ms": start_ms,
                    }
                )
            if len(body.get("events") or []) < 100:
                break
        except Exception as exc:
            errors.append(f"page {page_num}: {exc}")
            break
    return events[:MAX_EVENTS], errors


def parse_h2h_links(html):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    pattern = re.compile(
        r"/fifa/estatisticas/([^/]+)\.([0-9]+)-vs-([^/]+)\.([0-9]+)",
        re.I,
    )
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = pattern.search(href)
        if not match:
            continue
        slug_a, id_a, slug_b, id_b = match.groups()
        key = tuple(sorted((normalize_name(slug_a), normalize_name(slug_b))))
        if not key[0] or not key[1]:
            continue
        full = urljoin(GREEN365_ROOT, href)
        out.setdefault(
            key,
            {
                "url": full,
                "slug_a": slug_a,
                "slug_b": slug_b,
                "provider_id_a": id_a,
                "provider_id_b": id_b,
            },
        )
    return out


def parse_percent_pair(value):
    match = re.search(r"(\d+(?:[.,]\d+)?)%\s*(\d+(?:[.,]\d+)?)%", value or "")
    if not match:
        return None, None
    return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))


def find_section_percent(text, heading, line_label="2.5"):
    pattern = re.compile(
        re.escape(heading) + r".{0,1800}?" + re.escape(line_label) +
        r"\s+(\d+(?:[.,]\d+)?)%\s+(\d+(?:[.,]\d+)?)%",
        re.I | re.S,
    )
    match = pattern.search(text)
    if not match:
        return None, None
    return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))


def parse_recent_results(lines):
    results = []
    for idx in range(1, len(lines) - 5):
        if not re.fullmatch(r"\d+", lines[idx]):
            continue
        if lines[idx + 1] != ":" or not re.fullmatch(r"\d+", lines[idx + 2]):
            continue
        interval = re.match(r"Intervalo:\s*(\d+)\s*-\s*(\d+)", lines[idx + 4], re.I)
        if not interval:
            continue
        p1_line = lines[idx - 1].strip()
        p2_line = lines[idx + 5].strip()
        if not p1_line or not p2_line:
            continue
        match_time = None
        for prev in reversed(lines[max(0, idx - 4):idx]):
            date_match = re.search(
                r"(\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2})",
                prev,
            )
            if date_match:
                match_time = date_match.group(1)
                break
        team_a = ""
        team_b = ""
        ma = re.search(r"\(([^()]+)\)\s*$", p1_line)
        mb = re.search(r"\(([^()]+)\)\s*$", p2_line)
        if ma:
            team_a = ma.group(1).strip()
        if mb:
            team_b = mb.group(1).strip()
        p1 = re.sub(r"\s*\([^()]+\)\s*$", "", p1_line).strip()
        p2 = re.sub(r"\s*\([^()]+\)\s*$", "", p2_line).strip()
        results.append(
            {
                "timestamp_text": match_time,
                "participant_1": p1,
                "participant_2": p2,
                "team_1": team_a,
                "team_2": team_b,
                "score": f"{lines[idx]}:{lines[idx + 2]}",
                "halftime_score": f"{interval.group(1)}:{interval.group(2)}",
            }
        )
    # preserve page order but remove accidental duplicates
    seen = set()
    unique = []
    for item in results:
        key = (item["participant_1"], item["participant_2"], item["score"], item["timestamp_text"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:10]


def parse_h2h_page(html, requested_p1, requested_p2):
    soup = BeautifulSoup(html, "html.parser")
    lines = [x.strip() for x in soup.get_text("\n", strip=True).splitlines() if x.strip()]
    text = " ".join(lines)

    sample_n = None
    over25_count = None
    m = re.search(
        r"Nos últimos\s+(\d+)\s+confrontos,\s+(\d+)\s+terminaram com mais de 2,5 gols",
        text,
        re.I,
    )
    if m:
        sample_n = int(m.group(1))
        over25_count = int(m.group(2))

    avg_h2h = None
    m = re.search(r"Média Gols/Jogo \(H2H\)\s*([0-9]+(?:[.,][0-9]+)?)", text, re.I)
    if m:
        avg_h2h = float(m.group(1).replace(",", "."))

    win_stats = {}
    for name in (requested_p1, requested_p2):
        pattern = re.compile(
            re.escape(name) + r"\s+(\d+)%\s*(\d+)V\s*(\d+)E\s*(\d+)D\s+em\s+\d+",
            re.I,
        )
        match = pattern.search(text)
        if match:
            win_stats[name] = {
                "win_rate": float(match.group(1)) / 100.0,
                "wins": int(match.group(2)),
                "draws": int(match.group(3)),
                "losses": int(match.group(4)),
            }

    h2h_record = None
    direct = re.search(
        re.escape(requested_p1) + r"\s+(\d+)\s+Empates\s+(\d+)\s+" +
        re.escape(requested_p2) + r"\s+(\d+)",
        text,
        re.I,
    )
    if direct:
        h2h_record = {
            "p1_wins": int(direct.group(1)),
            "draws": int(direct.group(2)),
            "p2_wins": int(direct.group(3)),
        }

    total_goals = None
    goal_row = re.search(r"Gols Totais H2H\s*\|?\s*(\d+)\s*\|?\s*(\d+)", text, re.I)
    if goal_row:
        total_goals = {
            "p1": int(goal_row.group(1)),
            "p2": int(goal_row.group(2)),
        }

    avg_goals_player = None
    avg_row = re.search(
        r"Média Gols/Jogo\s*\|?\s*([0-9]+(?:[.,][0-9]+)?)\s*\|?\s*([0-9]+(?:[.,][0-9]+)?)",
        text,
        re.I,
    )
    if avg_row:
        avg_goals_player = {
            "p1": float(avg_row.group(1).replace(",", ".")),
            "p2": float(avg_row.group(2).replace(",", ".")),
        }

    btts = None
    btts_match = re.search(
        r"Ambos Marcaram\s*\|?\s*([0-9]+(?:[.,][0-9]+)?)%\s*\|?\s*([0-9]+(?:[.,][0-9]+)?)%",
        text,
        re.I,
    )
    if btts_match:
        btts = float(btts_match.group(1).replace(",", ".")) / 100.0

    h2h_o25_over, h2h_o25_under = find_section_percent(text, "Over/Under H2H - Gols")
    fh_o25_over, fh_o25_under = find_section_percent(text, "Over/Under H2H - Gols 1º Tempo")

    recent = parse_recent_results(lines)

    updated_text = None
    m = re.search(r"Atualizado em\s+([^\.]+)\.", text, re.I)
    if m:
        updated_text = m.group(1).strip()

    return {
        "sample_n": sample_n,
        "over_2_5_count": over25_count,
        "avg_total_goals": avg_h2h,
        "provider_win_stats": win_stats,
        "h2h_record": h2h_record,
        "goals": total_goals,
        "avg_goals_per_player": avg_goals_player,
        "btts_rate": btts,
        "over_under_2_5": {
            "over": h2h_o25_over / 100.0 if h2h_o25_over is not None else None,
            "under": h2h_o25_under / 100.0 if h2h_o25_under is not None else None,
        },
        "first_half_over_under_2_5": {
            "over": fh_o25_over / 100.0 if fh_o25_over is not None else None,
            "under": fh_o25_under / 100.0 if fh_o25_under is not None else None,
        },
        "recent_h2h": recent,
        "provider_updated_text": updated_text,
    }


def run():
    artifact = load_json(OUTPUT, {})
    old = artifact.get("snapshots") if isinstance(artifact, dict) else []
    old = old if isinstance(old, list) else []
    cached = {}
    for item in old:
        if not isinstance(item, dict):
            continue
        pair_key = str(item.get("pair_key") or "")
        captured = str(item.get("captured_at") or "")
        try:
            captured_ts = datetime.fromisoformat(captured.replace("Z", "+00:00")).timestamp()
        except Exception:
            captured_ts = 0
        if pair_key:
            cached[pair_key] = (captured_ts, item)

    events, upstream_errors = fetch_upcoming()
    if upstream_errors and not events:
        OUTPUT.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": now_iso(),
                    "source_contract": "Prospective external H2H enrichment; no model override",
                    "source": "Green365 FIFA ESoccer",
                    "status": "UPSTREAM_UNAVAILABLE",
                    "upstream_errors": upstream_errors,
                    "snapshots": old[-HISTORY_CAP:],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return {"status": "UPSTREAM_UNAVAILABLE", "events": 0, "snapshots": len(old)}

    try:
        home_html = SESSION.get(GREEN365_HOME, timeout=25)
        home_html.raise_for_status()
        links = parse_h2h_links(home_html.text)
    except Exception as exc:
        OUTPUT.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": now_iso(),
                    "source_contract": "Prospective external H2H enrichment; no model override",
                    "source": "Green365 FIFA ESoccer",
                    "status": "SOURCE_UNAVAILABLE",
                    "source_error": str(exc),
                    "upstream_errors": upstream_errors,
                    "snapshots": old[-HISTORY_CAP:],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return {"status": "SOURCE_UNAVAILABLE", "events": len(events), "snapshots": len(old)}

    profiles = load_json(PROFILES, {})
    known = {
        str(p.get("participant_key"))
        for p in (profiles.get("profiles") if isinstance(profiles, dict) else [])
        if isinstance(p, dict)
    }

    candidates = {}
    for event in events:
        p1 = participant_from_name(event["participant_1"])
        p2 = participant_from_name(event["participant_2"])
        pair_key = "|".join(
            sorted(
                (
                    f'{event["product"]}|{normalize_name(p1)}',
                    f'{event["product"]}|{normalize_name(p2)}',
                )
            )
        )
        slug_key = tuple(sorted((normalize_name(p1), normalize_name(p2))))
        link = links.get(slug_key)
        if not link:
            continue
        age = 10**9
        if pair_key in cached:
            age = time.time() - cached[pair_key][0]
        cold_start = (
            f'{event["product"]}|{normalize_name(p1)}' not in known
            or f'{event["product"]}|{normalize_name(p2)}' not in known
        )
        if age >= MIN_CACHE_MINUTES * 60:
            current = candidates.get(pair_key)
            if current is None or (cold_start and not current["cold_start"]):
                candidates[pair_key] = {
                    "pair_key": pair_key,
                    "event": event,
                    "link": link,
                    "cold_start": cold_start,
                }

    ordered = sorted(
        candidates.values(),
        key=lambda x: (
            0 if x["cold_start"] else 1,
            x["event"].get("start_time_ms") or 10**18,
        ),
    )[:MAX_PAIR_FETCHES]

    snapshots = list(old)
    fetched = 0
    errors = []
    for item in ordered:
        event = item["event"]
        p1 = participant_from_name(event["participant_1"])
        p2 = participant_from_name(event["participant_2"])
        try:
            response = SESSION.get(item["link"]["url"], timeout=25)
            if response.status_code == 429:
                errors.append(f'429 H2H {p1} vs {p2}')
                time.sleep(2.5)
                continue
            response.raise_for_status()
            parsed = parse_h2h_page(response.text, p1, p2)
            snapshot = {
                "schema_version": 1,
                "captured_at": now_iso(),
                "source": "green365_fifa_esoccer",
                "source_url": item["link"]["url"],
                "product": event["product"],
                "competition": event["competition"],
                "event_id": event["event_id"],
                "upcoming_start_time_ms": event["start_time_ms"],
                "participant_1": p1,
                "participant_2": p2,
                "participant_1_key": f'{event["product"]}|{normalize_name(p1)}',
                "participant_2_key": f'{event["product"]}|{normalize_name(p2)}',
                "provider_participant_ids": {
                    "a": item["link"]["provider_id_a"],
                    "b": item["link"]["provider_id_b"],
                },
                "cold_start_enrichment": bool(item["cold_start"]),
                "h2h": parsed,
            }
            snapshots = [
                x
                for x in snapshots
                if not (
                    isinstance(x, dict)
                    and x.get("event_id") == event["event_id"]
                    and x.get("participant_1_key") == snapshot["participant_1_key"]
                    and x.get("participant_2_key") == snapshot["participant_2_key"]
                )
            ]
            snapshots.append(snapshot)
            fetched += 1
            time.sleep(0.35)
        except Exception as exc:
            errors.append(f'H2H {p1} vs {p2}: {exc}')

    snapshots = snapshots[-HISTORY_CAP:]
    OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": now_iso(),
                "source_contract": "Prospective external H2H snapshots only; no model override; timestamps are required for later time-safe validation",
                "source": "Green365 FIFA ESoccer",
                "status": "LIVE" if links else "NO_MATCHING_LINKS",
                "upcoming_efootball_events": len(events),
                "homepage_h2h_links": len(links),
                "candidate_pairs": len(candidates),
                "fetched_pairs": fetched,
                "cold_start_pairs_considered": sum(1 for x in candidates.values() if x["cold_start"]),
                "upstream_errors": upstream_errors,
                "errors": errors[-30:],
                "snapshots": snapshots,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "status": "LIVE" if links else "NO_MATCHING_LINKS",
        "events": len(events),
        "links": len(links),
        "candidates": len(candidates),
        "fetched": fetched,
        "errors": len(errors),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
