import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

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
TENNIS_LEAGUES = {"ATP": "atp", "WTA": "wta"}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/2.0 (+https://github.com/topboyasian-stack/match-signal)"})


def get_json(url, params=None):
    response = SESSION.get(url, params=params, timeout=25)
    response.raise_for_status()
    return response.json()


def clamp(value, low=0.01, high=0.98):
    return max(low, min(high, float(value)))


def normalise(values):
    total = sum(values)
    if total <= 0:
        return [1 / len(values)] * len(values)
    return [v / total for v in values]


def american_to_prob(odds):
    try:
        odds = float(odds)
        if odds > 0:
            return 100 / (odds + 100)
        return -odds / (-odds + 100)
    except (TypeError, ValueError):
        return None


def event_odds(event):
    try:
        odds = event["competitions"][0].get("odds") or []
        market = odds[0]
        ml = market.get("moneyline", {})
        out = []
        for side in ("home", "away", "draw"):
            value = ml.get(side, {}).get("close", {}).get("odds")
            out.append(american_to_prob(value))
        if any(v is None for v in out):
            return None
        return normalise(out)
    except (KeyError, IndexError, TypeError):
        return None


def form_score(form):
    if not form:
        return 0.5
    weights = {"W": 1.0, "D": 0.5, "L": 0.0}
    chars = [c for c in str(form)[-5:] if c in weights]
    return sum(weights[c] for c in chars) / len(chars) if chars else 0.5


def football_prediction(event):
    competition = event["competitions"][0]
    competitors = competition.get("competitors", [])
    if len(competitors) < 2:
        return None
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    market = event_odds(event)
    home_form = form_score(home.get("form"))
    away_form = form_score(away.get("form"))
    # Market probability is a strong prior; current form and home advantage are model features.
    if market:
        hp, ap, dp = market
        hp = clamp(hp + 0.08 * (home_form - away_form) + 0.015)
        ap = clamp(ap + 0.08 * (away_form - home_form))
        dp = clamp(dp - 0.02 * abs(home_form - away_form))
        probs = normalise([hp, dp, ap])
        source = "ESPN fixture + market + form"
    else:
        edge = 0.58 * (home_form - away_form) + 0.10
        hp = 0.46 + edge
        ap = 0.28 - edge * 0.35
        dp = 1 - hp - ap
        probs = normalise([clamp(hp), clamp(dp), clamp(ap)])
        source = "ESPN fixture + recent form"
    return {
        "sport": "football",
        "league": event.get("league", {}).get("name") or event.get("season", {}).get("slug", "Football"),
        "event_id": str(event["id"]),
        "start_time": event.get("date"),
        "player_1": home["team"]["displayName"],
        "player_2": away["team"]["displayName"],
        "venue": competition.get("venue", {}).get("fullName"),
        "surface": "Grass",
        "probabilities": {"p1": round(probs[0], 4), "draw": round(probs[1], 4), "p2": round(probs[2], 4)},
        "pick": ["p1", "draw", "p2"][probs.index(max(probs))],
        "confidence": round(max(probs), 4),
        "model": source,
    }


def tennis_competitors(event):
    competitors = event.get("competitions", [{}])[0].get("competitors", [])
    if len(competitors) < 2:
        return None
    return competitors[0], competitors[1]


def tennis_rank_probability(rank1, rank2):
    try:
        r1, r2 = float(rank1), float(rank2)
        # Smooth ranking edge; lower rank is stronger. Cap the edge to avoid overconfidence.
        edge = math.log((r2 + 4) / (r1 + 4))
        return 1 / (1 + math.exp(-1.35 * edge))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.5


def tennis_prediction(event, tour):
    pair = tennis_competitors(event)
    if not pair:
        return None
    p1, p2 = pair
    a1, a2 = p1.get("athlete", {}), p2.get("athlete", {})
    name1 = a1.get("displayName") or p1.get("displayName") or "Player 1"
    name2 = a2.get("displayName") or p2.get("displayName") or "Player 2"
    rank1 = p1.get("rank") or a1.get("rank")
    rank2 = p2.get("rank") or a2.get("rank")
    rank_prob = tennis_rank_probability(rank1, rank2)
    market = event_odds(event)
    market_prob = market[0] if market else None
    probability = normalise([0.72 * rank_prob + 0.28 * market_prob if market_prob else rank_prob,
                             0.72 * (1 - rank_prob) + 0.28 * (1 - market_prob) if market_prob else 1 - rank_prob])
    competition = event.get("competitions", [{}])[0]
    return {
        "sport": "tennis",
        "league": tour,
        "event_id": str(event["id"]),
        "start_time": event.get("date"),
        "player_1": name1,
        "player_2": name2,
        "surface": event.get("season", {}).get("slug", "Unknown"),
        "rankings": {"p1": rank1, "p2": rank2},
        "probabilities": {"p1": round(probability[0], 4), "p2": round(probability[1], 4)},
        "pick": "p1" if probability[0] >= probability[1] else "p2",
        "confidence": round(max(probability), 4),
        "model": "ESPN fixture + ATP/WTA ranking + market prior" if market_prob else "ESPN fixture + ATP/WTA ranking",
        "venue": competition.get("venue", {}).get("fullName"),
    }


def fetch_scoreboard(sport, league, date=None):
    url = f"{ESPN}/{sport}/{league}/scoreboard"
    params = {"dates": date} if date else None
    return get_json(url, params=params)


def fetch_current_predictions():
    predictions = []
    errors = []
    for label, league in FOOTBALL_LEAGUES.items():
        try:
            board = fetch_scoreboard("soccer", league)
            for event in board.get("events", []):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                prediction = football_prediction(event)
                if prediction:
                    prediction["league"] = label
                    predictions.append(prediction)
        except Exception as exc:
            errors.append(f"football:{label}:{exc}")
    for tour, league in TENNIS_LEAGUES.items():
        try:
            board = fetch_scoreboard("tennis", league)
            for event in board.get("events", []):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                prediction = tennis_prediction(event, tour)
                if prediction:
                    predictions.append(prediction)
        except Exception as exc:
            errors.append(f"tennis:{tour}:{exc}")
    predictions.sort(key=lambda p: (p.get("start_time") or "", p["sport"], p["player_1"]))
    return predictions, errors


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def settle_predictions(history):
    today = datetime.now(timezone.utc).date()
    pending = [p for p in history if not p.get("settled") and p.get("start_time")]
    dates = sorted({p["start_time"][:10] for p in pending if p["start_time"][:10] < today.isoformat()})[-7:]
    if not dates:
        return history
    boards = {}
    for date in dates:
        for label, league in FOOTBALL_LEAGUES.items():
            try:
                for event in fetch_scoreboard("soccer", league, date).get("events", []):
                    boards["football:" + str(event["id"])] = event
            except Exception:
                pass
        for tour, league in TENNIS_LEAGUES.items():
            try:
                for event in fetch_scoreboard("tennis", league, date).get("events", []):
                    boards["tennis:" + str(event["id"])] = event
            except Exception:
                pass
    for prediction in history:
        if prediction.get("settled"):
            continue
        event = boards.get(f"{prediction['sport']}:{prediction['event_id']}")
        if not event or not event.get("status", {}).get("type", {}).get("completed"):
            continue
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        if len(competitors) < 2:
            continue
        try:
            scores = [float(c.get("score", 0)) for c in competitors]
            if prediction["sport"] == "football":
                home = next(c for c in competitors if c.get("homeAway") == "home")
                away = next(c for c in competitors if c.get("homeAway") == "away")
                hs, ass = float(home.get("score", 0)), float(away.get("score", 0))
                actual = "p1" if hs > ass else "p2" if ass > hs else "draw"
            else:
                c1, c2 = competitors[0], competitors[1]
                actual = "p1" if float(c1.get("score", 0)) > float(c2.get("score", 0)) else "p2"
            pred_prob = prediction["probabilities"].get(prediction["pick"], 0)
            prediction.update({
                "settled": True,
                "settled_at": datetime.now(timezone.utc).isoformat(),
                "actual": actual,
                "correct": prediction["pick"] == actual,
                "brier": round((pred_prob - 1) ** 2 + sum((prediction["probabilities"].get(k, 0) - (1 if actual == k else 0)) ** 2 for k in prediction["probabilities"] if k != prediction["pick"]), 6),
                "final_scores": scores,
            })
        except (TypeError, ValueError, KeyError):
            continue
    return history


def accuracy_summary(history):
    settled = [p for p in history if p.get("settled")]
    summary = {"settled": len(settled), "correct": sum(bool(p.get("correct")) for p in settled), "accuracy": 0.0, "brier_score": 0.0}
    if settled:
        summary["accuracy"] = round(summary["correct"] / len(settled), 4)
        summary["brier_score"] = round(sum(float(p.get("brier", 0)) for p in settled) / len(settled), 4)
    for sport in ("football", "tennis"):
        group = [p for p in settled if p.get("sport") == sport]
        summary[sport] = {
            "settled": len(group),
            "correct": sum(bool(p.get("correct")) for p in group),
            "accuracy": round(sum(bool(p.get("correct")) for p in group) / len(group), 4) if group else 0.0,
        }
    return summary


def main():
    print("Match Signal 2.0 — live Football + Tennis pipeline")
    history_path = DATA / "prediction_history.json"
    accuracy_path = DATA / "accuracy.json"
    history = load_json(history_path, [])
    history = settle_predictions(history)
    predictions, errors = fetch_current_predictions()
    now = datetime.now(timezone.utc).isoformat()
    for prediction in predictions:
        prediction["calculated_at"] = now
    # Avoid duplicate snapshots of the same event on repeated manual workflow runs.
    existing_ids = {p.get("event_id") for p in history if not p.get("settled")}
    for prediction in predictions:
        if prediction["event_id"] not in existing_ids:
            history.append(prediction.copy())
    history = history[-2500:]
    summary = accuracy_summary(history)
    save_json(DATA / "predictions.json", predictions)
    save_json(history_path, history)
    save_json(accuracy_path, {"updated_at": now, "summary": summary, "recent_settled": [p for p in history if p.get("settled")][-50:]})
    meta = {"updated_at": now, "prediction_count": len(predictions), "errors": errors, "data_source": "ESPN public scoreboards", "free_server_cost": True}
    save_json(DATA / "pipeline_status.json", meta)
    print(f"Predictions: {len(predictions)} | Settled: {summary['settled']} | Accuracy: {summary['accuracy']:.1%}")
    if errors:
        print("Non-fatal source errors:")
        for error in errors:
            print(" -", error)


if __name__ == "__main__":
    main()
