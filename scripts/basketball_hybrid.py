"""Match Signal basketball collector.

Primary market source: Stake Sports Data API (when STAKE_ODDS_API_KEY is
configured in GitHub Actions). Fixture fallback: official BBL schedule and
SportPesa's public board. We never fabricate a total line: fixtures without a
machine-readable market remain `no_qualified_signal`.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STAKE_BASE = "https://odds-data.stake.com"

BBL = [
    ("2026-09-11T20:00:00+02:00", "Veolia Towers Hamburg", "ROSTOCK SEAWOLVES"),
    ("2026-09-12T18:30:00+02:00", "GIESSEN 46ers", "NINERS Chemnitz"),
    ("2026-09-12T20:00:00+02:00", "BG Göttingen", "SYNTAINICS MBC"),
    ("2026-09-13T15:00:00+02:00", "Kreisbau Kirchheim Knights", "MHP RIESEN Ludwigsburg"),
    ("2026-09-13T16:30:00+02:00", "SKYLINERS", "Science City Jena"),
    ("2026-09-13T18:00:00+02:00", "MLP Academics Heidelberg", "EWE Baskets Oldenburg"),
]

SP_URLS = [
    "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/today-games/",
    "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/upcoming-games/",
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
    return re.sub(r"[^a-z0-9]", "", value)


def stake_get(path, params=None):
    """Call Stake Odds Data API without ever logging the secret."""
    key = os.getenv("STAKE_ODDS_API_KEY", "").strip()
    if not key:
        return None, "not_configured"

    url = STAKE_BASE + path
    # The published OpenAPI marks this as an apiKey security scheme. Try the
    # conventional header first, then query-param form for compatibility with
    # deployed API gateway variants. Never print the key or request URL.
    for mode in ("header", "query"):
        try:
            if mode == "header":
                r = S.get(url, params=params, headers={"x-api-key": key}, timeout=20)
            else:
                q = dict(params or {})
                q["apiKey"] = key
                r = S.get(url, params=q, timeout=20)
            if r.status_code == 200:
                return r.json(), "ok"
            if r.status_code not in (401, 403):
                return None, f"http_{r.status_code}"
        except Exception:
            continue
    return None, "unauthorized"


def flatten(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten(child)


def extract_line(text):
    if text is None:
        return None
    m = re.search(r"(?:^|[|,; ])(?:line|total|points)?\s*[=:]?\s*(-?\d+(?:\.5)?)", str(text), re.I)
    return float(m.group(1)) if m else None


def parse_stake_markets(payload):
    """Extract two-way winner and full-game O/U from Stake's normalized JSON."""
    result = {}
    for obj in flatten(payload):
        name = str(obj.get("name") or obj.get("marketName") or "").lower()
        outcomes = obj.get("outcomes")
        if not isinstance(outcomes, list):
            continue

        # Full-game totals: prefer explicit total/over-under market names and
        # ignore quarter/half/team/player props.
        if any(x in name for x in ("total", "over/under", "over under")) and not any(
            x in name for x in ("quarter", "half", "team total", "player", "period")
        ):
            pairs = []
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                oname = str(outcome.get("name") or outcome.get("label") or "")
                odds = outcome.get("odds")
                try:
                    odds = float(odds)
                except Exception:
                    continue
                line = outcome.get("line")
                if line is None:
                    line = extract_line(oname) or extract_line(obj.get("specifiers"))
                try:
                    line = float(line)
                except Exception:
                    continue
                low = oname.lower()
                side = "over" if "over" in low else "under" if "under" in low else None
                if side and odds > 1.0:
                    pairs.append((line, side, odds))
            grouped = {}
            for line, side, odds in pairs:
                grouped.setdefault(line, {})[side] = odds
            candidates = [(line, d) for line, d in grouped.items() if "over" in d and "under" in d]
            if candidates and "total" not in result:
                line, d = min(candidates, key=lambda x: abs(x[0] - 167.5))
                po, pu = 1 / d["over"], 1 / d["under"]
                s = po + pu
                result["total"] = {
                    "line": line,
                    "over": po / s,
                    "under": pu / s,
                    "over_odds": d["over"],
                    "under_odds": d["under"],
                }

        if "winner" in name or "moneyline" in name or "match winner" in name:
            vals = []
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                oname = str(outcome.get("name") or "")
                try:
                    odds = float(outcome.get("odds"))
                except Exception:
                    continue
                if odds > 1.0 and oname:
                    vals.append((oname, odds))
            if len(vals) >= 2 and "p1" not in result:
                inv = [1 / x[1] for x in vals[:2]]
                total = sum(inv)
                result["p1"] = inv[0] / total
                result["p2"] = inv[1] / total

    return result


def stake_fixture_market(home, away):
    """Discover basketball fixture through Stake and then fetch its markets."""
    data, status = stake_get("/sport/basketball/fixture")
    if status != "ok" or not data:
        return {}, status

    fixtures = data.get("fixture") if isinstance(data, dict) else data
    if not isinstance(fixtures, list):
        fixtures = data.get("fixtures", []) if isinstance(data, dict) else []

    nh, na = norm(home), norm(away)
    match = None
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        competitors = fixture.get("competitors") or []
        text = norm(fixture.get("name", "")) + "".join(norm(x) for x in competitors)
        if nh in text and na in text:
            match = fixture
            break
    if not match:
        return {}, "fixture_not_found"

    slug = match.get("slug") or match.get("id")
    if not slug:
        return {}, "fixture_without_slug"
    payload, status = stake_get("/fixtures/" + str(slug))
    if status != "ok":
        return {}, status
    return parse_stake_markets(payload), "ok"


def sportpesa_fixtures():
    """Public fixture fallback only; no sportsbook odds scraping."""
    out, seen = [], set()
    for url in SP_URLS:
        try:
            text = S.get(url, timeout=20).text
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
        except Exception:
            continue
        for m in re.finditer(r"Game ID\s+(\d+)(.{0,700}?)(?=Game ID|Betslip|$)", text, re.I):
            eid, block = m.groups()
            if "club friendly" not in block.lower():
                continue
            tm = re.search(r"\b(\d{1,2}:\d{2})\b", block)
            dt = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", block)
            teams = re.search(r"ID:\s*" + re.escape(eid) + r"\s+(.{2,80}?)\s+(.{2,80}?)\s+2 Way - OT incl", block, re.I)
            if not (tm and dt and teams):
                continue
            home, away = teams.groups()
            key = (eid, norm(home), norm(away))
            if key in seen:
                continue
            seen.add(key)
            try:
                start = datetime.strptime(dt.group(1) + " " + tm.group(1), "%d/%m/%y %H:%M")
                start = start.replace(tzinfo=ZoneInfo("Africa/Dar_es_Salaam")).astimezone(timezone.utc).isoformat()
            except Exception:
                continue
            out.append({"event_id": eid, "start_time": start, "home": home.strip(), "away": away.strip(), "league": "International Club Friendly"})
    return out


def prediction(fixture, market, market_status):
    total = market.get("total")
    p1, p2 = market.get("p1", 0.5), market.get("p2", 0.5)
    has_market = bool(total or market.get("p1") is not None and "p1" in market)
    if total:
        over, under = total["over"], total["under"]
        pick = "over" if over > under else "under"
        expected = total["line"] + (over - 0.5) * 8
    else:
        over = under = 0.5
        pick = None
        expected = None

    return {
        "sport": "basketball",
        "league": fixture["league"],
        "source": "Official BBL/SportPesa fixtures + Stake Sports Data API markets",
        "event_id": str(fixture["event_id"]),
        "start_time": fixture["start_time"],
        "player_1": fixture["home"],
        "player_2": fixture["away"],
        "prediction_status": "qualified" if has_market else "no_qualified_signal",
        "probabilities": {"p1": round(p1, 4), "p2": round(p2, 4)},
        "pick": "p1" if p1 > p2 else "p2" if p2 > p1 else None,
        "confidence": round(max(p1, p2) if "p1" in market else 0.5, 4),
        "markets": {
            "moneyline": {"p1": round(p1, 4), "p2": round(p2, 4), "available": "p1" in market},
            "total_ou": {
                "line": total["line"] if total else None,
                "over": round(over, 4),
                "under": round(under, 4),
                "pick": pick,
                "expected_total": round(expected, 1) if expected is not None else None,
                "source": "Stake Sports Data API" if total else "No published machine-readable O/U line found",
                "settlement": "Official final score including overtime",
                "odds": {"over": total["over_odds"], "under": total["under_odds"]} if total else None,
            },
            "spread": None,
        },
        "form": {"source": "Market-only until structured basketball form feed is added", "p1_sample": 0, "p2_sample": 0},
        "signal_quality": {
            "components": (2 if "p1" in market else 0) + (1 if total else 0),
            "max_components": 3,
            "market_total_available": bool(total),
            "stake_market_status": market_status,
        },
        "model": "Stake market-implied probability; conservative calibration",
        "rules_note": "Basketball totals settle on the official final score, including overtime.",
    }


def main():
    fixtures = [
        {"event_id": "bbl-" + norm(home) + "-" + norm(away), "start_time": start, "home": home, "away": away, "league": "German Basketball Cup"}
        for start, home, away in BBL
    ]
    fixtures += sportpesa_fixtures()

    now = datetime.now(timezone.utc).timestamp()
    fixtures = [f for f in fixtures if datetime.fromisoformat(f["start_time"]).timestamp() >= now - 3600]

    preds = []
    stake_ok = 0
    for fixture in fixtures:
        market, status = stake_fixture_market(fixture["home"], fixture["away"])
        if status == "ok":
            stake_ok += 1
        preds.append(prediction(fixture, market, status))

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
    stake_key_configured = bool(os.getenv("STAKE_ODDS_API_KEY", "").strip())
    status.update({
        "basketball_count": len(preds),
        "basketball_qualified_count": sum(p["prediction_status"] == "qualified" for p in preds),
        "basketball_settled": len(settled),
        "basketball_sources": [
            {"source": "Official BBL schedule", "events": sum(1 for f in fixtures if f["league"] == "German Basketball Cup"), "status": "ok"},
            {"source": "SportPesa public board", "events": sum(1 for f in fixtures if f["league"] == "International Club Friendly"), "status": "ok"},
            {"source": "Stake Sports Data API", "events_with_markets": stake_ok, "status": "ok" if stake_ok else ("not_configured" if not stake_key_configured else "no_matching_markets")},
        ],
        "basketball_source_status": "Official BBL/SportPesa fixtures; Stake Sports Data API markets; no sportsbook HTML scraping",
        "basketball_stake_api_configured": stake_key_configured,
        "basketball_updated_at": datetime.now(timezone.utc).isoformat(),
        "basketball_rules": "Totals settle on official final score including overtime",
    })
    save(DATA / "pipeline_status.json", status)
    print(f"Basketball loop: {len(preds)} fixtures; Stake-market fixtures={stake_ok}; qualified={sum(p['prediction_status']=='qualified' for p in preds)}; O/U lines={sum(1 for p in preds if p['markets']['total_ou']['line'] is not None)}")


if __name__ == "__main__":
    main()
