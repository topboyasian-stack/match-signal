#!/usr/bin/env python3
"""Idempotently settle only timestamped NBA full-game totals from exact ESPN event IDs."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "nba_predictions.json"
LEDGER = ROOT / "data" / "nba_totals_ledger.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignalResearch/1.0 (paper-only NBA totals ledger)"})

def load(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def result_for(prediction, event):
    """Return a settlement record only when exact identity and pregame evidence pass."""
    if str(prediction.get("event_id") or "") != str(event.get("id") or ""):
        return None
    status = (event.get("status") or {}).get("type") or {}
    if not (status.get("completed") or status.get("state") == "post"):
        return None
    pred_time = parse_time(prediction.get("prediction_created_at") or prediction.get("generated_at") or prediction.get("published_at"))
    start_time = parse_time(prediction.get("start_time"))
    if not pred_time or not start_time or pred_time >= start_time:
        return None
    market = ((prediction.get("markets") or {}).get("total_ou") or {})
    if str(market.get("market_id") or "") != "225":
        return None
    line = market.get("line")
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    if not 100 <= line <= 300:
        return None
    pick = str(market.get("pick") or "").lower()
    if pick not in ("over", "under"):
        return None
    comp = (event.get("competitions") or [{}])[0]
    teams = comp.get("competitors") or []
    home = next((x for x in teams if x.get("homeAway") == "home"), None)
    away = next((x for x in teams if x.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    try:
        hs, aws = float(home["score"]), float(away["score"])
    except (KeyError, TypeError, ValueError):
        return None
    if hs < 0 or aws < 0:
        return None
    total = hs + aws
    outcome = "over" if total > line else "under" if total < line else "push"
    return {
        "ledger_id": "nba-total:" + str(event["id"]),
        "sport": "basketball", "league": "NBA", "event_id": str(event["id"]),
        "start_time": prediction["start_time"], "player_1": prediction.get("player_1"),
        "player_2": prediction.get("player_2"), "prediction_created_at": pred_time.isoformat(),
        "model": prediction.get("model"), "expected_total": prediction.get("expected_total"),
        "market_id": "225", "market_source": market.get("source"),
        "quote_timestamp": market.get("quote_timestamp"), "line": line, "pick": pick,
        "final_score": [int(hs) if hs.is_integer() else hs, int(aws) if aws.is_integer() else aws],
        "final_total": total, "result": outcome,
        "settled": True, "settled_at": datetime.now(timezone.utc).isoformat(),
        "settlement_source": "ESPN official scoreboard event ID; final score includes overtime",
        "paper_only": True,
    }

def main():
    predictions = load(PREDICTIONS, [])
    old = load(LEDGER, {"records": []})
    records = old.get("records", []) if isinstance(old, dict) else []
    by_id = {str(r.get("event_id")): r for r in records if r.get("event_id")}
    # Reconcile every prediction date, including recently completed games missed by a prior run.
    dates = set()
    for p in predictions:
        dt = parse_time(p.get("start_time"))
        if dt:
            dates.add(dt.astimezone(timezone.utc).strftime("%Y%m%d"))
    added = 0
    for day in sorted(dates):
        try:
            response = SESSION.get(BASE + "/scoreboard", params={"dates": day}, timeout=20)
            response.raise_for_status()
            events = response.json().get("events") or []
        except (requests.RequestException, ValueError) as exc:
            print("Scoreboard fetch failed for", day, ":", str(exc)[:180])
            continue
        event_by_id = {str(e.get("id")): e for e in events if e.get("id")}
        for p in predictions:
            eid = str(p.get("event_id") or "")
            event = event_by_id.get(eid)
            if not event or eid in by_id:
                continue
            row = result_for(p, event)
            if row:
                by_id[eid] = row
                added += 1
    records = sorted(by_id.values(), key=lambda x: x.get("start_time", ""))
    decided = [r for r in records if r.get("result") in ("over", "under")]
    wins = sum(r.get("pick") == r.get("result") for r in decided)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN public NBA scoreboard",
        "market_definition": "SportyBet market 225 full-game totals, overtime included",
        "paper_only": True,
        "settlement_rules": ["Exact ESPN event ID only", "Pre-game prediction timestamp required",
                             "Market ID 225 and saved Over/Under line/pick required",
                             "Final official score includes overtime", "Pushes excluded from accuracy",
                             "Existing settled event IDs are immutable and never duplicated"],
        "summary": {"settled": len(records), "decided": len(decided), "correct": wins,
                    "accuracy": wins / len(decided) if decided else None,
                    "pushes": sum(r.get("result") == "push" for r in records),
                    "over_settled": sum(r.get("pick") == "over" for r in decided),
                    "under_settled": sum(r.get("pick") == "under" for r in decided)},
        "records": records,
    }
    LEDGER.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"new_settlements": added, **payload["summary"], "updated_at": payload["updated_at"]}))

if __name__ == "__main__":
    main()
