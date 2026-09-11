"""Basketball extension for competitions not covered by ESPN's public basketball catalogue.

Uses SofaScore's public JSON for BBL-Pokal (359) and Club Friendly Games (1195),
including available pre-match odds. No fixtures or odds are fabricated when the
source does not publish them.
"""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
BASE = "https://www.sofascore.com/api/v1"
TOURNAMENTS = {
    "German Basketball Cup": 359,
    "International Club Friendly": 1195,
}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/4.1 (+https://github.com/topboyasian-stack/match-signal)"})


def get_json(path):
    r = SESSION.get(BASE + path, timeout=30)
    r.raise_for_status()
    return r.json()


def normalise(values):
    vals = [max(0.0001, float(v)) for v in values]
    total = sum(vals)
    return [v / total for v in vals]


def decimal_to_prob(odds):
    try:
        return 1 / float(odds)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def event_done(event):
    status = event.get("status") or {}
    return status.get("type") in {"finished", "ended"} or status.get("code") == 100


def score(event):
    h = (event.get("homeScore") or {}).get("current")
    a = (event.get("awayScore") or {}).get("current")
    try:
        return float(h), float(a)
    except (TypeError, ValueError):
        return None


def event_pages(tournament_id, pages=2):
    events = []
    seen = set()
    for page in range(pages):
        for path in (f"/unique-tournament/{tournament_id}/events/next/{page}", f"/unique-tournament/{tournament_id}/events/last/{page}"):
            try:
                payload = get_json(path)
            except Exception:
                continue
            for event in payload.get("events", []):
                eid = str(event.get("id"))
                if eid and eid not in seen:
                    seen.add(eid)
                    events.append(event)
    return events


def odds(event_id):
    try:
        return get_json(f"/event/{event_id}/odds/1/all")
    except Exception:
        return {}


def flatten_markets(payload):
    markets = []
    def walk(value):
        if isinstance(value, dict):
            choices = value.get("choices")
            name = value.get("marketName") or value.get("name") or ""
            if isinstance(choices, list) and choices:
                markets.append({"name": str(name), "choices": choices})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(payload)
    unique = []
    seen = set()
    for market in markets:
        key = (market["name"], tuple(str(c.get("name")) for c in market["choices"]))
        if key not in seen:
            seen.add(key)
            unique.append(market)
    return unique


def parse_odds(event_id):
    markets = flatten_markets(odds(event_id))
    result = {"moneyline": None, "total": None, "spread": None}
    for m in markets:
        name = m["name"].lower()
        choices = m["choices"]
        if result["total"] is None and ("total" in name or "over/under" in name or "over under" in name):
            found = []
            for c in choices:
                label = str(c.get("name") or "")
                match = re.search(r"(over|under)\s*([0-9]+(?:\.[0-9])?)", label, re.I)
                p = decimal_to_prob(c.get("decimalValue"))
                if match and p:
                    found.append((match.group(1).lower(), float(match.group(2)), p))
            if len(found) >= 2:
                lines = [x[1] for x in found]
                line = max(set(lines), key=lines.count)
                op = next((x[2] for x in found if x[0] == "over" and x[1] == line), None)
                up = next((x[2] for x in found if x[0] == "under" and x[1] == line), None)
                if op and up:
                    op, up = normalise([op, up])
                    result["total"] = {"line": line, "over": op, "under": up, "source": "SofaScore odds"}
        if result["moneyline"] is None and ("winner" in name or "moneyline" in name or name in {"1x2", "full time"}):
            vals = []
            for c in choices:
                label = str(c.get("name") or "").lower()
                p = decimal_to_prob(c.get("decimalValue"))
                if p and label in {"1", "2", "home", "away"}:
                    vals.append((label, p))
            if len(vals) >= 2:
                home = next((p for k, p in vals if k in {"1", "home"}), None)
                away = next((p for k, p in vals if k in {"2", "away"}), None)
                if home and away:
                    home, away = normalise([home, away])
                    result["moneyline"] = {"home": home, "away": away, "source": "SofaScore odds"}
        if result["spread"] is None and ("handicap" in name or "spread" in name):
            found = []
            for c in choices:
                label = str(c.get("name") or "")
                p = decimal_to_prob(c.get("decimalValue"))
                if p:
                    found.append((label, p))
            if len(found) >= 2:
                result["spread"] = {"choices": found[:2], "source": "SofaScore odds"}
    return result


def recent_form(events):
    form = {}
    for event in sorted(events, key=lambda e: e.get("startTimestamp", 0)):
        if not event_done(event):
            continue
        sc = score(event)
        if not sc:
            continue
        for side, team_key in (("homeTeam", "home"), ("awayTeam", "away")):
            team = event.get(side) or {}
            tid = str(team.get("id") or "")
            if not tid:
                continue
            own, opp = (sc[0], sc[1]) if team_key == "home" else (sc[1], sc[0])
            bucket = form.setdefault(tid, {"wins": [], "totals": []})
            bucket["wins"].append(1 if own > opp else 0)
            bucket["totals"].append(own + opp)
    for tid, b in form.items():
        b["wins"] = b["wins"][-8:]
        b["totals"] = b["totals"][-8:]
        b["win_rate"] = sum(b["wins"]) / len(b["wins"]) if b["wins"] else 0.5
        b["avg_total"] = sum(b["totals"]) / len(b["totals"]) if b["totals"] else None
    return form


def predict(event, competition, form):
    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    hname, aname = home.get("name"), away.get("name")
    hid, aid = str(home.get("id") or ""), str(away.get("id") or "")
    if not hname or not aname or hname.lower() == aname.lower():
        return None
    hf, af = form.get(hid, {}), form.get(aid, {})
    hform, aform = hf.get("win_rate", 0.5), af.get("win_rate", 0.5)
    m = parse_odds(str(event.get("id")))
    if m["moneyline"]:
        hp = 0.92 * m["moneyline"]["home"] + 0.08 * (0.5 + 0.5 * (hform - aform))
        source = "SofaScore moneyline + recent form"
    else:
        hp = 0.525 + 0.22 * (hform - aform)
        source = "recent form + home edge"
    hp = max(0.08, min(0.92, hp))
    ap = 1 - hp

    total = m["total"]
    form_total = None
    if hf.get("avg_total") is not None and af.get("avg_total") is not None:
        form_total = (hf["avg_total"] + af["avg_total"]) / 2
    if total:
        form_signal = 0.5 if form_total is None else 1 / (1 + math.exp(-(form_total - total["line"]) / 8))
        over = max(0.05, min(0.95, 0.90 * total["over"] + 0.10 * form_signal))
        under = 1 - over
        expected_total = total["line"] + (over - 0.5) * 8
        total_data = {**total, "over": round(over, 4), "under": round(under, 4), "pick": "over" if over > under else "under", "expected_total": round(expected_total, 1), "settlement": "Official final score including overtime"}
    else:
        total_data = {"line": None, "over": 0.5, "under": 0.5, "pick": None, "expected_total": round(form_total, 1) if form_total is not None else None, "source": "No published total odds", "settlement": "Official final score including overtime"}

    components = sum([bool(m["moneyline"]), bool(m["total"]), bool(m["spread"]), hf.get("wins") and len(hf.get("wins", [])) >= 3, af.get("wins") and len(af.get("wins", [])) >= 3])
    confidence = 0.5 + (max(hp, ap) - 0.5) * (0.92 if components >= 3 else 0.80)
    return {
        "sport": "basketball", "league": competition, "source": "SofaScore", "event_id": str(event.get("id")),
        "start_time": datetime.fromtimestamp(event.get("startTimestamp", 0), timezone.utc).isoformat(),
        "player_1": hname, "player_2": aname,
        "venue": (event.get("venue") or {}).get("name"),
        "probabilities": {"p1": round(hp, 4), "p2": round(ap, 4)},
        "pick": "p1" if hp >= ap else "p2", "confidence": round(confidence, 4),
        "markets": {"moneyline": m["moneyline"], "total_ou": total_data, "spread": m["spread"]},
        "form": {"p1_win_rate": round(hform, 3), "p2_win_rate": round(aform, 3), "p1_sample": len(hf.get("wins", [])), "p2_sample": len(af.get("wins", []))},
        "signal_quality": {"components": int(components), "max_components": 5, "moneyline_available": bool(m["moneyline"]), "total_available": bool(m["total"]), "spread_available": bool(m["spread"])},
        "model": source,
        "rules_note": "Basketball total settlement uses the official final score, including overtime.",
    }


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def settle(history):
    today = datetime.now(timezone.utc).date()
    for p in history:
        if p.get("settled") or not p.get("start_time") or p["start_time"][:10] >= today.isoformat():
            continue
        try:
            event = get_json(f"/event/{p['event_id']}").get("event", {})
            if not event_done(event):
                continue
            hs = (event.get("homeScore") or {}).get("current")
            aas = (event.get("awayScore") or {}).get("current")
            hs, aas = float(hs), float(aas)
            actual = "p1" if hs > aas else "p2"
            p["final_score"] = [hs, aas]
            p["actual_pick"] = actual
            p["correct"] = p.get("pick") == actual
            line = p.get("markets", {}).get("total_ou", {}).get("line")
            if line is not None:
                total = hs + aas
                p["actual_total"] = total
                p["actual_total_pick"] = "over" if total > float(line) else "under" if total < float(line) else "push"
                pick = p.get("markets", {}).get("total_ou", {}).get("pick")
                p["total_correct"] = pick in {"over", "under"} and p["actual_total_pick"] == pick
            p["settled"] = True
            p["settled_at"] = datetime.now(timezone.utc).isoformat()
        except Exception:
            continue
    return history


def main():
    all_predictions = []
    sources = []
    today = datetime.now(timezone.utc).date()
    for competition, tournament_id in TOURNAMENTS.items():
        events = event_pages(tournament_id, pages=2)
        form = recent_form(events)
        accepted = 0
        for event in events:
            if event_done(event):
                continue
            start = event.get("startTimestamp", 0)
            if not start or start < datetime.now(timezone.utc).timestamp() - 3600:
                continue
            p = predict(event, competition, form)
            if p:
                all_predictions.append(p)
                accepted += 1
        sources.append({"competition": competition, "tournament_id": tournament_id, "events": accepted})

    history = load(DATA / "basketball_history.json", [])
    known = {(str(p.get("event_id")), p.get("league")) for p in history}
    for p in all_predictions:
        key = (p["event_id"], p["league"])
        if key not in known:
            history.append(p)
    history = settle(history)
    settled = [p for p in history if p.get("settled")]
    correct = sum(bool(p.get("correct")) for p in settled)
    ou_rows = [p for p in settled if p.get("total_correct") is not None]
    ou_correct = sum(bool(p.get("total_correct")) for p in ou_rows)
    accuracy = {"updated_at": datetime.now(timezone.utc).isoformat(), "settled": len(settled), "correct": correct, "accuracy": correct/len(settled) if settled else None, "total_ou_settled": len(ou_rows), "total_ou_correct": ou_correct, "total_ou_accuracy": ou_correct/len(ou_rows) if ou_rows else None}
    save(DATA / "basketball_predictions.json", sorted(all_predictions, key=lambda x: x.get("start_time", "")))
    save(DATA / "basketball_history.json", history)
    save(DATA / "basketball_accuracy.json", accuracy)
    status = load(DATA / "pipeline_status.json", {})
    status["basketball_count"] = len(all_predictions)
    status["basketball_settled"] = len(settled)
    status["basketball_sources"] = sources
    status["basketball_source_status"] = "SofaScore public JSON"
    status["basketball_updated_at"] = datetime.now(timezone.utc).isoformat()
    status["basketball_rules"] = "Totals settle on official final score including overtime"
    save(DATA / "pipeline_status.json", status)
    print(f"SofaScore basketball: {len(all_predictions)} predictions; sources={sources}; settled={len(settled)}")


if __name__ == "__main__":
    main()
