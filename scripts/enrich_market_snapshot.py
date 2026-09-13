import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/4.1 market-snapshot"})


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


def market_snapshot(event):
    try:
        market = (event.get("competitions") or [{}])[0].get("odds") or []
        market = market[0] if market else {}
        ml = market.get("moneyline") or market.get("moneyLine") or {}
        odds = []
        probs = []
        for side in ("home", "draw", "away"):
            node = ml.get(side) or {}
            close = node.get("close") or node.get("open") or {}
            value = close.get("odds")
            odds.append(value)
            probs.append(american_to_prob(value))
        if any(p is None for p in probs):
            return None
        total = sum(probs)
        if total <= 0:
            return None
        return {
            "p1": probs[0] / total,
            "draw": probs[1] / total,
            "p2": probs[2] / total,
            "odds": odds,
            "source": "ESPN scoreboard odds",
            "odds_timestamp": market.get("lastUpdated") or market.get("updateTime"),
        }
    except Exception:
        return None


def main():
    pred_path = DATA / "predictions.json"
    predictions = load(pred_path, [])
    by_id = {str(p.get("event_id")): p for p in predictions if p.get("sport") == "football" and p.get("event_id")}
    found = 0
    missing = 0
    errors = []

    for label, league in FOOTBALL_LEAGUES.items():
        try:
            response = SESSION.get(f"{ESPN}/soccer/{league}/scoreboard", timeout=30)
            response.raise_for_status()
            board = response.json()
            for event in board.get("events", []):
                row = by_id.get(str(event.get("id")))
                if not row:
                    continue
                snap = market_snapshot(event)
                if not snap:
                    continue
                row["market_probabilities"] = {
                    "p1": round(snap["p1"], 6),
                    "draw": round(snap["draw"], 6),
                    "p2": round(snap["p2"], 6),
                }
                row["market_odds"] = snap["odds"]
                row["market_source"] = snap["source"]
                row["odds_timestamp"] = snap["odds_timestamp"]
                found += 1
        except Exception as exc:
            errors.append(f"football:{label}:{str(exc)[:160]}")

    for row in predictions:
        if row.get("sport") == "football" and not row.get("market_probabilities"):
            missing += 1

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "market_snapshots": found, "football_without_market": missing, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
