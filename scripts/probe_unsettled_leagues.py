#!/usr/bin/env python3
"""Read-only probe: why do some eFootball leagues never settle? (PAPER / RESEARCH ONLY)

Finds leagues whose pending observations are still unsettled long after kickoff, then asks the
same SportyBet result proxy the collector uses (RESULT_API) for those leagues, in several ways,
and reports what comes back. It changes nothing: GET requests only, no writes except an optional
--output JSON report.

Run (needs network access to https://match-signal.pages.dev):
    python scripts/probe_unsettled_leagues.py --top 8 --output data/probe_unsettled_leagues.json

What to look for in the report:
  * returned_events == 0 for every variant      -> the proxy returns nothing for that league scope
  * returned_events > 0 but matched_pending == 0 -> result event IDs differ from upcoming event IDs
  * matched_pending > 0 but parsed_scores == 0   -> results exist but the score format is not parsed
  * matched_pending > 0 and parsed_scores > 0    -> settlement should work; look at windows/paging
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import virtual_lab_collector as C  # noqa: E402  (reuses the real parsing helpers and endpoints)

MIN_AGE_HOURS = 2.0
MAX_PAGES = 3


def stuck_leagues(pending, now, min_age_hours=MIN_AGE_HOURS):
    """Group unsettled eFootball rows that started more than min_age_hours ago, by league scope."""
    groups = defaultdict(lambda: {"rows": 0, "event_ids": set(), "starts": []})
    cutoff = now - timedelta(hours=min_age_hours)
    for item in pending:
        if item.get("settled") or not str(item.get("product") or "").startswith("efootball"):
            continue
        raw = item.get("start_time")
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if start > cutoff:
            continue
        key = (item.get("competition"), item.get("source") or "efootball",
               str(item.get("category_id") or ""), str(item.get("tournament_id") or ""))
        g = groups[key]
        g["rows"] += 1
        g["event_ids"].add(str(item.get("event_id")))
        g["starts"].append(start)
    out = []
    for (comp, source, cat, tour), g in groups.items():
        out.append({"competition": comp, "source": source, "category_id": cat, "tournament_id": tour,
                    "unsettled_rows": g["rows"], "unsettled_events": len(g["event_ids"]),
                    "event_ids": sorted(g["event_ids"]),
                    "oldest_start": min(g["starts"]).isoformat(), "newest_start": max(g["starts"]).isoformat()})
    out.sort(key=lambda x: -x["unsettled_rows"])
    return out


def query_variants(league):
    """The exact collector query first, then diagnostic variants."""
    oldest = datetime.fromisoformat(league["oldest_start"])
    newest = datetime.fromisoformat(league["newest_start"])
    start_ms = int((oldest - timedelta(hours=6)).timestamp() * 1000)
    end_ms = int(max(newest + timedelta(hours=6), datetime.now(timezone.utc)).timestamp() * 1000)
    base = {"source": league["source"], "pageSize": 100, "startTime": start_ms, "endTime": end_ms}
    scoped = dict(base, categoryId=league["category_id"], tournamentId=league["tournament_id"])
    return [
        ("collector_exact_scope", scoped),
        ("no_scope_ids", dict(base)),
        ("category_only", dict(base, categoryId=league["category_id"])),
        ("wide_window_48h", dict(scoped, startTime=int((newest - timedelta(hours=48)).timestamp() * 1000))),
    ]


def run_variant(fetch, params):
    info = {"requests": 0, "error": None, "events": []}
    for page in range(1, MAX_PAGES + 1):
        try:
            body = fetch(C.RESULT_API, dict(params, pageNum=page))
        except Exception as exc:  # report, do not raise
            info["error"] = str(exc)[:240]
            break
        info["requests"] += 1
        batch = C.result_events(body)
        info["events"].extend(batch)
        if len(batch) < 100:
            break
    return info


def analyse(league, variant_name, info):
    pending_ids = set(league["event_ids"])
    events = info["events"]
    ids = [str(e.get("eventId") or e.get("event_id") or "") for e in events]
    matched = [e for e, i in zip(events, ids) if i in pending_ids]
    parsed = [e for e in matched if C.score(e) is not None]
    sample = events[0] if events else {}
    return {
        "variant": variant_name, "requests": info["requests"], "error": info["error"],
        "returned_events": len(events),
        "returned_distinct_ids": len(set(ids)),
        "matched_pending": len(matched),
        "parsed_scores": len(parsed),
        "sample_returned_id": ids[0] if ids else None,
        "sample_pending_id": sorted(pending_ids)[0] if pending_ids else None,
        "sample_event_keys": sorted(sample.keys())[:30] if isinstance(sample, dict) else [],
        "returned_competitions": dict(Counter(str(e.get("tournamentName") or e.get("competition") or e.get("tournament") or "")
                                              for e in events).most_common(3)),
    }


def verdict(results):
    exact = next((r for r in results if r["variant"] == "collector_exact_scope"), None)
    if exact is None:
        return "no data"
    if exact["error"] and exact["returned_events"] == 0:
        return "request failed: " + str(exact["error"])
    if exact["matched_pending"] > 0 and exact["parsed_scores"] > 0:
        return "results available and parseable; check settle() windows/paging"
    if exact["matched_pending"] > 0:
        return "results found but score not parsed (new score format?)"
    for r in results:
        if r["variant"] != "collector_exact_scope" and r["matched_pending"] > 0:
            return f"exact scope returns nothing but variant '{r['variant']}' matches: scope ids are the problem"
    if exact["returned_events"] > 0:
        return "results returned but event IDs do not match pending IDs"
    return "proxy returns no results for this league scope at all"


def probe(pending, fetch, now=None, top=8):
    now = now or datetime.now(timezone.utc)
    report = []
    for league in stuck_leagues(pending, now)[:top]:
        results = [analyse(league, name, run_variant(fetch, params)) for name, params in query_variants(league)]
        report.append({k: v for k, v in league.items() if k != "event_ids"} | {"results": results, "verdict": verdict(results)})
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", default=str(C.PENDING_PATH))
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--output")
    args = ap.parse_args()
    pending = json.loads(Path(args.pending).read_text(encoding="utf-8"))
    report = probe(pending, C.proxy_json, top=args.top)
    for item in report:
        print(f"\n{item['competition']}  unsettled rows={item['unsettled_rows']} events={item['unsettled_events']}  "
              f"scope={item['category_id']}/{item['tournament_id']}")
        for r in item["results"]:
            print(f"   {r['variant']:22s} returned={r['returned_events']:4d} matched={r['matched_pending']:4d} "
                  f"parsed={r['parsed_scores']:4d} err={r['error']}")
        print("   VERDICT:", item["verdict"])
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
