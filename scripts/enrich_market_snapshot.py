import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues"
FOOTBALL_LEAGUES = {
    "EPL": "eng.1",
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Serie A": "ita.1",
    "Ligue 1": "fra.1",
    "Champions League": "uefa.champions",
    "MLS": "usa.1",
    "Primeira Liga": "por.1",
}

# Use the default requests identity. Some ESPN public endpoints reject
# browser-spoofed/custom User-Agent headers with 403.
SESSION = requests.Session()


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def american_to_prob(odds):
    try:
        odds = float(odds)
        return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)
    except (TypeError, ValueError):
        return None


def get_json(url):
    response = SESSION.get(url, timeout=25)
    response.raise_for_status()
    return response.json()


def resolve_item(item):
    if item.get("provider") or item.get("homeTeamOdds") or item.get("awayTeamOdds"):
        return item
    ref = item.get("$ref")
    if not ref:
        return item
    return get_json(ref.replace("http://", "https://", 1))


def market_snapshot(league, event_id):
    url = f"{CORE}/{league}/events/{event_id}/competitions/{event_id}/odds"
    body = get_json(url)
    items = body.get("items") or []
    for raw in items:
        try:
            market = resolve_item(raw)
            home = (market.get("homeTeamOdds") or {}).get("moneyLine")
            away = (market.get("awayTeamOdds") or {}).get("moneyLine")
            draw = (market.get("drawOdds") or {}).get("moneyLine")
            if home is None or away is None or draw is None:
                # Some ESPN schemas use a nested moneyline block.
                ml = market.get("moneyline") or market.get("moneyLine") or {}
                home = home if home is not None else ((ml.get("home") or {}).get("odds"))
                away = away if away is not None else ((ml.get("away") or {}).get("odds"))
                draw = draw if draw is not None else ((ml.get("draw") or {}).get("odds"))
            probs = [american_to_prob(home), american_to_prob(draw), american_to_prob(away)]
            if any(p is None for p in probs):
                continue
            total = sum(probs)
            if total <= 0:
                continue
            return {
                "p1": probs[0] / total,
                "draw": probs[1] / total,
                "p2": probs[2] / total,
                "odds": [home, draw, away],
                "source": "ESPN core bookmaker odds",
                "provider": (market.get("provider") or {}).get("name"),
                "odds_timestamp": market.get("lastUpdated") or market.get("updateTime"),
            }
        except Exception:
            continue
    return None


def main():
    pred_path = DATA / "predictions.json"
    predictions = load(pred_path, [])
    by_id = {str(p.get("event_id")): p for p in predictions if p.get("sport") == "football" and p.get("event_id")}
    found = 0
    missing = 0
    errors = []

    for label, league in FOOTBALL_LEAGUES.items():
        targets = [p for p in by_id.values() if p.get("league") == label]
        for row in targets:
            try:
                snap = market_snapshot(league, str(row["event_id"]))
                if not snap:
                    missing += 1
                    continue
                row["market_probabilities"] = {
                    "p1": round(snap["p1"], 6),
                    "draw": round(snap["draw"], 6),
                    "p2": round(snap["p2"], 6),
                }
                row["market_odds"] = snap["odds"]
                row["market_source"] = snap["source"]
                row["market_provider"] = snap.get("provider")
                row["odds_timestamp"] = snap["odds_timestamp"]
                found += 1
            except Exception as exc:
                errors.append(f"{label}:{row.get('event_id')}:{str(exc)[:160]}")
                missing += 1

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "market_snapshots": found, "football_without_market": missing, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
