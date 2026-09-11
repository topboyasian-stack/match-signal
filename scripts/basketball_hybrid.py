"""Match Signal basketball collector.

Odds source priority:
1. OddsPapi when ODDSPAPI_API_KEY is configured.
2. Stake Sports Data API when STAKE_ODDS_API_KEY is configured.

Fixtures are anchored to the official BBL schedule. We never fabricate a
market: a fixture without a machine-readable moneyline/total remains
`no_qualified_signal`.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ODDSPAPI_BASE = "https://api.oddspapi.io"
STAKE_BASE = "https://odds-data.stake.com"
CACHE_PATH = DATA / "basketball_provider_cache.json"

BBL = [
    ("2026-09-11T20:00:00+02:00", "Veolia Towers Hamburg", "ROSTOCK SEAWOLVES"),
    ("2026-09-12T18:30:00+02:00", "GIESSEN 46ers", "NINERS Chemnitz"),
    ("2026-09-12T20:00:00+02:00", "BG Göttingen", "SYNTAINICS MBC"),
    ("2026-09-13T15:00:00+02:00", "Kreisbau Kirchheim Knights", "MHP RIESEN Ludwigsburg"),
    ("2026-09-13T16:30:00+02:00", "SKYLINERS", "Science City Jena"),
    ("2026-09-13T18:00:00+02:00", "MLP Academics Heidelberg", "EWE Baskets Oldenburg"),
]

S = requests.Session()
S.headers.update({"User-Agent": "Match-Signal/1.0", "Accept-Language": "en-US,en;q=0.9"})


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def norm(value):
    value = str(value).lower()
    value = value.replace("ö", "o").replace("ü", "u").replace("ä", "a").replace("ß", "ss")
    replacements = {
        "veolia towers hamburg": "hamburg towers",
        "rostock seavolves": "rostock seahawks",
        "rostock seewolves": "rostock seahawks",
        "giessen 46ers": "giessen46ers",
        "giessen 46": "giessen46ers",
        "niners chemnitz": "ninerschemnitz",
        "bg gottingen": "bgottingen",
        "syntainics mbc": "mbc",
        "mhp riesen ludwigsburg": "ludwigsburg",
        "science city jena": "jena",
        "mlp academics heidelberg": "heidelberg",
        "ewe baskets oldenburg": "oldenburg",
    }
    value = re.sub(r"[^a-z0-9 ]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return replacements.get(value, value.replace(" ", ""))


def name_match(a, b):
    a, b = norm(a), norm(b)
    if a == b or a in b or b in a:
        return True
    at = {a[i:i+5] for i in range(max(0, len(a)-4))}
    bt = {b[i:i+5] for i in range(max(0, len(b)-4))}
    return len(at & bt) >= 2


def get_json(base, path, params, api_key, timeout=25):
    if not api_key:
        return None, "not_configured"
    q = dict(params or {})
    q["apiKey"] = api_key
    try:
        r = S.get(base + path, params=q, timeout=timeout)
        if r.status_code == 200:
            return r.json(), "ok"
        if r.status_code in (401, 403):
            return None, "unauthorized"
        return None, f"http_{r.status_code}"
    except Exception as exc:
        return None, type(exc).__name__


def odds_value(node):
    if not isinstance(node, dict):
        return None
    for key in ("price", "odds"):
        try:
            value = float(node[key])
            if value > 1.0:
                return value
        except Exception:
            pass
    return None


def outcome_records(payload):
    """Yield (outcome id, player name, decimal price, main-line flag)."""
    for bookmaker in (payload.get("bookmakerOdds", {}) if isinstance(payload, dict) else {}).values():
        markets = bookmaker.get("markets", {}) if isinstance(bookmaker, dict) else {}
        if not isinstance(markets, dict):
            continue
        for market in markets.values():
            outcomes = market.get("outcomes", {}) if isinstance(market, dict) else {}
            if not isinstance(outcomes, dict):
                continue
            for outcome in outcomes.values():
                players = outcome.get("players", {}) if isinstance(outcome, dict) else {}
                if not isinstance(players, dict):
                    continue
                for player in players.values():
                    if not isinstance(player, dict) or player.get("active") is False:
                        continue
                    oid = str(player.get("bookmakerOutcomeId") or "")
                    pname = str(player.get("playerName") or "")
                    price = odds_value(player)
                    if price:
                        yield oid, pname, price, bool(player.get("mainLine"))


def parse_oddspapi_markets(payload, home, away):
    """Parse OddsPapi's bookmakerOutcomeId values for standard ML and totals."""
    money = []
    totals = {}
    for oid, pname, price, main_line in outcome_records(payload):
        low = oid.lower().replace(" ", "")
        label = (pname + " " + oid).lower()
        if low in {"home", "1", "participant1"} or name_match(pname, home):
            money.append(("p1", price))
        elif low in {"away", "2", "participant2"} or name_match(pname, away):
            money.append(("p2", price))

        side = None
        if "over" in low or "over" in label:
            side = "over"
        elif "under" in low or "under" in label:
            side = "under"
        if side:
            m = re.search(r"(-?\d+(?:\.\d+)?)", low)
            if m:
                line = float(m.group(1))
                totals.setdefault(line, {})[side] = price

    result = {}
    if money:
        by_side = {}
        for side, price in money:
            by_side.setdefault(side, price)
        if "p1" in by_side and "p2" in by_side:
            inv1, inv2 = 1 / by_side["p1"], 1 / by_side["p2"]
            denom = inv1 + inv2
            result["p1"] = inv1 / denom
            result["p2"] = inv2 / denom
            result["moneyline_odds"] = by_side

    candidates = [(line, sides) for line, sides in totals.items() if "over" in sides and "under" in sides]
    if candidates:
        line, sides = min(candidates, key=lambda x: (0 if abs(x[0] * 2 - round(x[0] * 2)) < 0.01 else 1, abs(x[0] - 167.5)))
        po, pu = 1 / sides["over"], 1 / sides["under"]
        denom = po + pu
        result["total"] = {
            "line": line,
            "over": po / denom,
            "under": pu / denom,
            "over_odds": sides["over"],
            "under_odds": sides["under"],
        }
    return result


def oddspapi_tournament_id():
    key = os.getenv("ODDSPAPI_API_KEY", "").strip()
    cache = load(CACHE_PATH, {})
    cached = cache.get("oddspapi_tournament_id")
    if cached:
        return cached, "cached"
    data, status = get_json(ODDSPAPI_BASE, "/v4/tournaments", {"sportId": 11, "language": "en"}, key)
    if status != "ok" or not isinstance(data, list):
        return None, status
    candidates = []
    for t in data:
        text = " ".join(str(t.get(k, "")) for k in ("tournamentName", "tournamentSlug", "categoryName", "categorySlug")).lower()
        if any(x in text for x in ("german cup", "germany cup", "bbl pokal", "basketball bundesliga cup")):
            candidates.append(t)
    if not candidates:
        return None, "german_tournament_not_found"
    tournament_id = candidates[0].get("tournamentId")
    if tournament_id:
        cache.update({"oddspapi_tournament_id": tournament_id, "oddspapi_tournament_name": candidates[0].get("tournamentName")})
        save(CACHE_PATH, cache)
        return tournament_id, "discovered"
    return None, "tournament_without_id"


def oddspapi_markets(fixtures):
    key = os.getenv("ODDSPAPI_API_KEY", "").strip()
    if not key:
        return {}, "not_configured"
    tournament_id, tournament_status = oddspapi_tournament_id()
    if not tournament_id:
        return {}, tournament_status

    data, status = get_json(
        ODDSPAPI_BASE,
        "/v4/odds-by-tournaments",
        {"tournamentIds": str(tournament_id), "language": "en", "verbosity": 3, "oddsFormat": "decimal"},
        key,
    )
    if status != "ok":
        return {}, status

    rows = data if isinstance(data, list) else data.get("fixtures", data.get("events", [])) if isinstance(data, dict) else []
    if isinstance(rows, dict):
        rows = list(rows.values())
    markets = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rh = row.get("participant1Name") or row.get("homeTeam") or row.get("home") or ""
        ra = row.get("participant2Name") or row.get("awayTeam") or row.get("away") or ""
        if not rh or not ra:
            continue
        for fixture in fixtures:
            if name_match(rh, fixture["home"]) and name_match(ra, fixture["away"]):
                parsed = parse_oddspapi_markets(row, fixture["home"], fixture["away"])
                parsed["fixture_id"] = row.get("fixtureId")
                parsed["provider"] = "OddsPapi"
                markets[fixture["event_id"]] = parsed
                break
    return markets, "ok"


def stake_markets(home, away):
    key = os.getenv("STAKE_ODDS_API_KEY", "").strip()
    if not key:
        return {}, "not_configured"
    data, status = get_json(STAKE_BASE, "/sport/basketball/fixture", {}, key)
    if status != "ok" or not data:
        return {}, status
    fixtures = data.get("fixtures", data.get("fixture", [])) if isinstance(data, dict) else data
    if not isinstance(fixtures, list):
        return {}, "fixture_shape_unknown"
    match = next((f for f in fixtures if isinstance(f, dict) and name_match(str(f.get("name", "")), home) and name_match(str(f.get("name", "")), away)), None)
    if not match:
        return {}, "fixture_not_found"
    fixture_id = match.get("id") or match.get("slug")
    if not fixture_id:
        return {}, "fixture_without_id"
    payload, status = get_json(STAKE_BASE, "/fixtures/" + str(fixture_id), {}, key)
    if status != "ok":
        return {}, status
    # Stake parsing retained as a generic recursive fallback.
    totals, money = {}, []
    def walk(v):
        if isinstance(v, dict):
            yield v
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)
    for obj in walk(payload):
        name = str(obj.get("name") or obj.get("marketName") or "").lower()
        outcomes = obj.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        for o in outcomes:
            if not isinstance(o, dict):
                continue
            oid = str(o.get("name") or o.get("label") or "").lower()
            price = odds_value(o)
            if not price:
                continue
            if "over" in oid or "under" in oid:
                m = re.search(r"(-?\d+(?:\.5)?)", oid)
                if m:
                    totals.setdefault(float(m.group(1)), {})["over" if "over" in oid else "under"] = price
            elif "winner" in name or "moneyline" in name:
                money.append((oid, price))
    result = {}
    if len(money) >= 2:
        inv = [1 / x[1] for x in money[:2]]
        d = sum(inv)
        result.update({"p1": inv[0] / d, "p2": inv[1] / d})
    pairs = [(line, d) for line, d in totals.items() if "over" in d and "under" in d]
    if pairs:
        line, d = min(pairs, key=lambda x: abs(x[0] - 167.5))
        po, pu = 1 / d["over"], 1 / d["under"]
        s = po + pu
        result["total"] = {"line": line, "over": po / s, "under": pu / s, "over_odds": d["over"], "under_odds": d["under"]}
    return result, "ok"


def prediction(fixture, market, status):
    total = market.get("total")
    p1, p2 = market.get("p1"), market.get("p2")
    has_ml = p1 is not None and p2 is not None
    has_total = bool(total)
    qualified = has_ml or has_total
    if has_ml:
        pick = "p1" if p1 > p2 else "p2" if p2 > p1 else None
        confidence = max(p1, p2)
    else:
        pick = None
        confidence = 0.5
    if has_total:
        over, under = total["over"], total["under"]
        ou_pick = "over" if over > under else "under"
        expected = total["line"] + (over - 0.5) * 8
    else:
        over = under = 0.5
        ou_pick = None
        expected = None
    return {
        "sport": "basketball",
        "league": fixture["league"],
        "source": f"Official BBL schedule + {market.get('provider', 'market provider')}",
        "event_id": fixture["event_id"],
        "start_time": fixture["start_time"],
        "player_1": fixture["home"],
        "player_2": fixture["away"],
        "prediction_status": "qualified" if qualified else "no_qualified_signal",
        "probabilities": {"p1": round(p1 if p1 is not None else 0.5, 4), "p2": round(p2 if p2 is not None else 0.5, 4)},
        "pick": pick,
        "confidence": round(confidence, 4),
        "markets": {
            "moneyline": {"p1": round(p1, 4) if p1 is not None else 0.5, "p2": round(p2, 4) if p2 is not None else 0.5, "available": has_ml},
            "total_ou": {
                "line": total["line"] if total else None,
                "over": round(over, 4), "under": round(under, 4), "pick": ou_pick,
                "expected_total": round(expected, 1) if expected is not None else None,
                "source": f"{market.get('provider')} market" if total else "No published machine-readable O/U line found",
                "settlement": "Official final score including overtime",
                "odds": {"over": total["over_odds"], "under": total["under_odds"]} if total else None,
            },
            "spread": None,
        },
        "form": {"source": "Market-only until structured basketball form feed is added", "p1_sample": 0, "p2_sample": 0},
        "signal_quality": {
            "components": (2 if has_ml else 0) + (1 if has_total else 0),
            "max_components": 3,
            "market_total_available": has_total,
            "market_provider_status": status,
        },
        "model": "Market-implied probability; conservative calibration",
        "rules_note": "Basketball totals settle on the official final score, including overtime.",
    }


def main():
    fixtures = [
        {"event_id": "bbl-" + norm(home) + "-" + norm(away), "start_time": start, "home": home, "away": away, "league": "German Basketball Cup"}
        for start, home, away in BBL
    ]
    now = datetime.now(timezone.utc).timestamp()
    fixtures = [f for f in fixtures if datetime.fromisoformat(f["start_time"]).timestamp() >= now - 3600]

    markets = {}
    provider_status = "not_configured"
    provider = "none"
    if os.getenv("ODDSPAPI_API_KEY", "").strip():
        markets, provider_status = oddspapi_markets(fixtures)
        provider = "OddsPapi"
    if not markets and os.getenv("STAKE_ODDS_API_KEY", "").strip():
        for f in fixtures:
            m, s = stake_markets(f["home"], f["away"])
            if m:
                markets[f["event_id"]] = m
        provider = "Stake"
        if not markets:
            provider_status = "stake_no_markets"

    preds = [prediction(f, markets.get(f["event_id"], {}), provider_status if f["event_id"] not in markets else "ok") for f in fixtures]

    history = load(DATA / "basketball_history.json", [])
    known = {(str(x.get("event_id")), x.get("league")) for x in history}
    for row in preds:
        if (row["event_id"], row["league"]) not in known:
            history.append(row)

    settled = [x for x in history if x.get("settled")]
    totals = [x for x in settled if x.get("total_correct") is not None]
    save(DATA / "basketball_predictions.json", sorted(preds, key=lambda x: x["start_time"]))
    save(DATA / "basketball_history.json", history)
    save(DATA / "basketball_accuracy.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "settled": len(settled),
        "correct": sum(bool(x.get("correct")) for x in settled),
        "accuracy": sum(bool(x.get("correct")) for x in settled) / len(settled) if settled else None,
        "total_ou_settled": len(totals),
        "total_ou_correct": sum(bool(x.get("total_correct")) for x in totals),
        "total_ou_accuracy": sum(bool(x.get("total_correct")) for x in totals) / len(totals) if totals else None,
    })

    status = load(DATA / "pipeline_status.json", {})
    status.update({
        "basketball_count": len(preds),
        "basketball_qualified_count": sum(p["prediction_status"] == "qualified" for p in preds),
        "basketball_settled": len(settled),
        "basketball_market_provider": provider,
        "basketball_market_provider_status": provider_status,
        "basketball_sources": [{"source": "Official BBL schedule", "events": len(fixtures), "status": "ok"}],
    })
    save(DATA / "pipeline_status.json", status)
    print(f"Basketball loop: {len(fixtures)} fixtures; provider={provider}; provider_status={provider_status}; qualified={sum(p['prediction_status'] == 'qualified' for p in preds)}; O/U lines={sum(bool(p['markets']['total_ou']['line']) for p in preds)}")


if __name__ == "__main__":
    main()
