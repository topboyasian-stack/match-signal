"""Match Signal basketball pipeline using ESPN public scoreboards and market odds.

The pipeline is deliberately conservative: it only publishes real ESPN fixtures,
never fabricates missing odds, and settles totals from the final score (including
overtime when ESPN reports the official final score).
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
ESPN = "https://site.api.espn.com/apis/site/v2/sports"

# ESPN's international basketball catalogue changes over time. Probe several known
# naming conventions and use only a feed that actually returns events.
COMPETITIONS = {
    "German Basketball Cup": [
        "germany.cup", "germany-cup", "ger.cup", "germany.bbl.cup", "germany.bbl_pokal", "germany.bbl.pokal"
    ],
    "International Club Friendly": [
        "intl.club.friendly", "international.club.friendly", "club.friendly", "intl.club.friendlies", "world.club.friendly"
    ],
    "EuroLeague": ["euroleague"],
    "EuroCup": ["eurocup"],
    "Basketball Champions League": ["basketball-champions-league", "champions-league"],
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/4.0 (+https://github.com/topboyasian-stack/match-signal)"})


def get_json(url, params=None):
    r = SESSION.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def american_to_prob(odds):
    try:
        odds = float(odds)
        return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)
    except (TypeError, ValueError):
        return None


def normalise(values):
    values = [max(0.0001, float(v)) for v in values]
    total = sum(values)
    return [v / total for v in values]


def clamp(x, lo=0.05, hi=0.95):
    return max(lo, min(hi, float(x)))


def market(event):
    try:
        odds = event.get("competitions", [{}])[0].get("odds") or []
        return odds[0] if odds else None
    except (IndexError, TypeError):
        return None


def moneyline(event):
    m = market(event)
    if not m:
        return None
    ml = m.get("moneyline") or m.get("moneyLine") or {}
    vals = []
    for side in ("home", "away"):
        node = ml.get(side) or {}
        close = node.get("close") or node.get("open") or {}
        vals.append(american_to_prob(close.get("odds")))
    if any(v is None for v in vals):
        return None
    p = normalise(vals)
    return {"home": p[0], "away": p[1]}


def total_market(event):
    m = market(event)
    if not m:
        return None
    total = m.get("total") or {}
    over = total.get("over") or {}
    under = total.get("under") or {}
    oc = over.get("close") or over.get("open") or {}
    uc = under.get("close") or under.get("open") or {}
    line = m.get("overUnder")
    if line is None:
        line = oc.get("line") or uc.get("line")
    try:
        line = float(str(line).replace("+", ""))
    except (TypeError, ValueError):
        return None
    op = american_to_prob(oc.get("odds"))
    up = american_to_prob(uc.get("odds"))
    if op is None or up is None:
        return None
    probs = normalise([op, up])
    return {"line": line, "over": probs[0], "under": probs[1]}


def spread_market(event):
    m = market(event)
    if not m:
        return None
    spread = m.get("pointSpread") or {}
    home = spread.get("home") or {}
    away = spread.get("away") or {}
    hc = home.get("close") or home.get("open") or {}
    ac = away.get("close") or away.get("open") or {}
    try:
        hp, ap = american_to_prob(hc.get("odds")), american_to_prob(ac.get("odds"))
        if hp is None or ap is None:
            return None
        probs = normalise([hp, ap])
        return {"line": float(hc.get("line")), "home_cover": probs[0], "away_cover": probs[1]}
    except (TypeError, ValueError):
        return None


def competitors(event):
    try:
        return event["competitions"][0].get("competitors", [])[:2]
    except (IndexError, KeyError, TypeError):
        return []


def team_info(c):
    team = c.get("team") or {}
    name = (team.get("displayName") or c.get("displayName") or "").strip()
    team_id = str(team.get("id") or c.get("id") or "")
    return team_id, name


def completed(event):
    return bool(event.get("status", {}).get("type", {}).get("completed"))


def scores(event):
    cs = competitors(event)
    if len(cs) != 2:
        return None
    try:
        vals = []
        for c in cs:
            vals.append(float(c.get("score", 0)))
        return vals
    except (TypeError, ValueError):
        return None


def fetch_feed(slug, date_range):
    return get_json(f"{ESPN}/basketball/{slug}/scoreboard", {"dates": date_range})


def choose_feeds(start, end):
    feeds = []
    seen = set()
    for label, candidates in COMPETITIONS.items():
        selected = None
        for slug in candidates:
            try:
                board = fetch_feed(slug, f"{start:%Y%m%d}-{end:%Y%m%d}")
                events = board.get("events", [])
                if events:
                    selected = (slug, board)
                    break
            except Exception:
                continue
        if selected:
            slug, board = selected
            if slug not in seen:
                feeds.append((label, slug, board))
                seen.add(slug)
    return feeds


def recent_team_form(slug, start, end):
    form = {}
    if end < start:
        return form
    try:
        board = fetch_feed(slug, start and f"{start:%Y%m%d}-{end:%Y%m%d}")
    except Exception:
        return form
    for event in board.get("events", []):
        if not completed(event):
            continue
        cs = competitors(event)
        if len(cs) != 2:
            continue
        sc = scores(event)
        if not sc:
            continue
        for idx, c in enumerate(cs):
            tid, name = team_info(c)
            if not tid or not name:
                continue
            opp = sc[1 - idx]
            bucket = form.setdefault(tid, {"wins": [], "totals": []})
            bucket["wins"].append(1 if sc[idx] > opp else 0)
            bucket["totals"].append(sc[idx] + opp)
    for tid, bucket in form.items():
        wins = bucket["wins"][-8:]
        totals = bucket["totals"][-8:]
        bucket["win_rate"] = sum(wins) / len(wins) if wins else 0.5
        bucket["avg_total"] = sum(totals) / len(totals) if totals else None
        bucket["sample"] = len(wins)
    return form


def predict(event, competition, slug, form):
    cs = competitors(event)
    if len(cs) != 2:
        return None
    home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
    away = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
    hid, hname = team_info(home)
    aid, aname = team_info(away)
    if not hname or not aname or hname.lower() == aname.lower():
        return None

    hf = form.get(hid, {})
    af = form.get(aid, {})
    hform, aform = hf.get("win_rate", 0.5), af.get("win_rate", 0.5)
    ml = moneyline(event)
    if ml:
        hp = clamp(0.92 * ml["home"] + 0.08 * (0.5 + (hform - aform) * 0.5))
        source = "ESPN moneyline + recent form"
    else:
        hp = clamp(0.50 + 0.22 * (hform - aform) + 0.025)
        source = "recent form + home edge"
    ap = 1 - hp
    total = total_market(event)
    spread = spread_market(event)

    form_total = None
    if hf.get("avg_total") is not None and af.get("avg_total") is not None:
        form_total = (hf["avg_total"] + af["avg_total"]) / 2
    if total:
        # Market is the anchor; form only nudges the total direction to avoid false precision.
        form_signal = 0.5
        if form_total is not None:
            form_signal = 1 / (1 + math.exp(-(form_total - total["line"]) / 8.0))
        over = clamp(0.90 * total["over"] + 0.10 * form_signal)
        under = 1 - over
        total_source = "ESPN O/U odds + recent scoring form"
        expected_total = total["line"] + (over - 0.5) * 8.0
        line = total["line"]
    else:
        line = round(form_total, 1) if form_total is not None else None
        if line is None:
            over, under, expected_total = 0.5, 0.5, None
            total_source = "No ESPN total available"
        else:
            expected_total = line
            over, under = 0.5, 0.5
            total_source = "Recent scoring prior; no ESPN O/U odds"

    signal_components = sum([
        1 if ml else 0,
        1 if total else 0,
        1 if spread else 0,
        1 if hf.get("sample", 0) >= 3 else 0,
        1 if af.get("sample", 0) >= 3 else 0,
    ])
    confidence = max(hp, ap)
    # Keep low-evidence basketball picks from looking artificially certain.
    confidence = 0.5 + (confidence - 0.5) * (0.82 if signal_components < 3 else 0.94)
    pick = "p1" if hp >= ap else "p2"
    return {
        "sport": "basketball",
        "league": competition,
        "source_league": slug,
        "event_id": str(event.get("id")),
        "start_time": event.get("date"),
        "player_1": hname,
        "player_2": aname,
        "venue": (event.get("competitions", [{}])[0].get("venue") or {}).get("fullName"),
        "probabilities": {"p1": round(hp, 4), "p2": round(ap, 4)},
        "pick": pick,
        "confidence": round(confidence, 4),
        "markets": {
            "moneyline": {"p1": round(hp, 4), "p2": round(ap, 4), "available": bool(ml)},
            "spread": spread,
            "total_ou": {
                "line": line,
                "over": round(over, 4),
                "under": round(under, 4),
                "pick": "over" if over > under else "under" if under > over else None,
                "expected_total": round(expected_total, 1) if expected_total is not None else None,
                "source": total_source,
                "settlement": "Final score including overtime",
            },
        },
        "form": {"p1_win_rate": round(hform, 3), "p2_win_rate": round(aform, 3), "p1_sample": hf.get("sample", 0), "p2_sample": af.get("sample", 0)},
        "signal_quality": {"components": signal_components, "max_components": 5, "moneyline_available": bool(ml), "total_available": bool(total), "spread_available": bool(spread)},
        "model": source,
        "rules_note": "Basketball totals settle on the official final score, including overtime when played.",
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
    pending = [p for p in history if not p.get("settled") and p.get("start_time")]
    dates = sorted({p["start_time"][:10] for p in pending if p["start_time"][:10] < today.isoformat()})[-14:]
    if not dates:
        return history
    lookup = {}
    for date in dates:
        for p in pending:
            if p["start_time"][:10] != date:
                continue
            slug = p.get("source_league")
            if not slug:
                continue
            try:
                board = fetch_feed(slug, date)
                for event in board.get("events", []):
                    lookup[(slug, str(event.get("id")))] = event
            except Exception:
                pass
    for p in history:
        if p.get("settled"):
            continue
        event = lookup.get((p.get("source_league"), str(p.get("event_id"))))
        if not event or not completed(event):
            continue
        sc = scores(event)
        if not sc:
            continue
        actual = "p1" if sc[0] > sc[1] else "p2"
        p["final_score"] = sc
        p["actual_pick"] = actual
        p["correct"] = p.get("pick") == actual
        ou = p.get("markets", {}).get("total_ou", {})
        line = ou.get("line")
        if line is not None:
            total = sum(sc)
            p["actual_total"] = total
            p["actual_total_pick"] = "over" if total > float(line) else "under" if total < float(line) else "push"
            if ou.get("pick") in ("over", "under"):
                p["total_correct"] = p["actual_total_pick"] == ou.get("pick")
        p["settled"] = True
        p["settled_at"] = datetime.now(timezone.utc).isoformat()
    return history


def accuracy(history):
    settled = [p for p in history if p.get("settled")]
    correct = sum(bool(p.get("correct")) for p in settled)
    total_market_rows = [p for p in settled if p.get("total_correct") is not None]
    total_correct = sum(bool(p.get("total_correct")) for p in total_market_rows)
    brier = None
    if settled:
        brier = sum((float(p.get("probabilities", {}).get("p1", 0.5)) - (1 if p.get("actual_pick") == "p1" else 0)) ** 2 for p in settled) / len(settled)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "settled": len(settled),
        "correct": correct,
        "accuracy": correct / len(settled) if settled else None,
        "brier_score": brier,
        "total_ou_settled": len(total_market_rows),
        "total_ou_correct": total_correct,
        "total_ou_accuracy": total_correct / len(total_market_rows) if total_market_rows else None,
    }


def main():
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=7)
    form_start = today - timedelta(days=30)
    feeds = choose_feeds(today, end)
    predictions = []
    source_status = []
    for label, slug, board in feeds:
        form = recent_team_form(slug, form_start, today - timedelta(days=1))
        accepted = 0
        for event in board.get("events", []):
            if completed(event):
                continue
            prediction = predict(event, label, slug, form)
            if prediction:
                predictions.append(prediction)
                accepted += 1
        source_status.append({"competition": label, "slug": slug, "events": accepted})
    predictions.sort(key=lambda p: (p.get("start_time") or "", p.get("league", ""), p.get("player_1", "")))

    history = load(DATA / "basketball_history.json", [])
    # Keep prior predictions that have not been replaced by the same event.
    existing = {(str(p.get("event_id")), p.get("source_league")) for p in history}
    for p in predictions:
        if (p["event_id"], p["source_league"]) not in existing:
            history.append(p)
    history = settle(history)
    save(DATA / "basketball_predictions.json", predictions)
    save(DATA / "basketball_history.json", history)
    save(DATA / "basketball_accuracy.json", accuracy(history))

    status = load(DATA / "pipeline_status.json", {})
    status["basketball_count"] = len(predictions)
    status["basketball_settled"] = sum(1 for p in history if p.get("settled"))
    status["basketball_sources"] = source_status
    status["basketball_updated_at"] = datetime.now(timezone.utc).isoformat()
    status["basketball_rules"] = "Totals settle on official final score including overtime"
    save(DATA / "pipeline_status.json", status)
    print(f"Basketball predictions: {len(predictions)} | sources: {source_status} | settled: {status['basketball_settled']}")


if __name__ == "__main__":
    main()
