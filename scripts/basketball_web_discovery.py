"""HTML fallback for basketball when SofaScore's JSON API is unavailable to Actions."""
import json, re
from datetime import datetime, timezone
from html import unescape
from curl_cffi import requests
from scripts.basketball_sofascore import TOURNAMENTS, DATA, done, form, odds, predict, settle, load, save

SESSION = requests.Session(impersonate="chrome")
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
PAGES = {
    359: "https://www.sofascore.com/basketball/tournament/germany/bbl-pokal/359",
    1195: "https://www.sofascore.com/basketball/tournament/international/club-friendly-games/1195",
}

def fetch_html(url):
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text

def walk(obj, out, tid):
    if isinstance(obj, dict):
        ht, at = obj.get("homeTeam"), obj.get("awayTeam")
        ts = obj.get("startTimestamp")
        eid = obj.get("id")
        if isinstance(ht, dict) and isinstance(at, dict) and ts and eid:
            tournament = obj.get("tournament") or {}
            ut = tournament.get("uniqueTournament") or {}
            candidate_tid = ut.get("id") or tournament.get("uniqueTournamentId")
            if str(candidate_tid) == str(tid):
                out[str(eid)] = obj
        for v in obj.values():
            walk(v, out, tid)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, out, tid)

def extract_events(html, tid):
    events = {}
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    for raw in scripts:
        text = unescape(raw).strip()
        if not text or len(text) > 20_000_000:
            continue
        try:
            walk(json.loads(text), events, tid)
        except Exception:
            continue
    return list(events.values())

def main():
    now = datetime.now(timezone.utc).timestamp()
    discovered = []
    source_status = []
    for league, tid in TOURNAMENTS.items():
        try:
            events = extract_events(fetch_html(PAGES[tid]), tid)
            future = [e for e in events if not done(e) and (e.get("startTimestamp") or 0) >= now - 3600]
            discovered.extend((league, e) for e in future)
            source_status.append({"competition": league, "events_discovered": len(events), "future_events": len(future)})
        except Exception as exc:
            source_status.append({"competition": league, "events_discovered": 0, "future_events": 0, "error": type(exc).__name__})

    existing = load(DATA / "basketball_predictions.json", [])
    predictions = list(existing)
    known = {(str(x.get("event_id")), x.get("league")) for x in predictions}
    all_events = [e for _, e in discovered]
    for league, event in discovered:
        eid = str(event.get("id"))
        if (eid, league) in known:
            continue
        team_history = all_events
        f = form(team_history)
        p = predict(event, league, {}, f)
        if p:
            predictions.append(p)
            known.add((eid, league))

    history = load(DATA / "basketball_history.json", [])
    known_history = {(str(x.get("event_id")), x.get("league")) for x in history}
    for p in predictions:
        if (str(p.get("event_id")), p.get("league")) not in known_history:
            history.append(p)
            known_history.add((str(p.get("event_id")), p.get("league")))
    history = settle(history)
    settled = [x for x in history if x.get("settled")]
    totals = [x for x in settled if x.get("total_correct") is not None]
    correct = sum(bool(x.get("correct")) for x in settled)
    total_correct = sum(bool(x.get("total_correct")) for x in totals)
    save(DATA / "basketball_predictions.json", sorted(predictions, key=lambda x: x.get("start_time", "")))
    save(DATA / "basketball_history.json", history)
    save(DATA / "basketball_accuracy.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "settled": len(settled), "correct": correct,
        "accuracy": correct / len(settled) if settled else None,
        "total_ou_settled": len(totals), "total_ou_correct": total_correct,
        "total_ou_accuracy": total_correct / len(totals) if totals else None,
    })
    status = load(DATA / "pipeline_status.json", {})
    status.update({
        "basketball_web_fallback": source_status,
        "basketball_web_fallback_updated_at": datetime.now(timezone.utc).isoformat(),
    })
    save(DATA / "pipeline_status.json", status)
    print(f"Basketball HTML fallback: {len(predictions)} predictions; sources={source_status}")

if __name__ == "__main__":
    main()
