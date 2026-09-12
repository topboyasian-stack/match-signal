"""Settle completed Match Signal fixtures from the same day and recent days.

The main pipeline intentionally looks at dates before today. This companion pass
also checks today's scoreboard so finished matches are recorded immediately.
"""
import json
from datetime import datetime, timedelta, timezone
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
TENNIS_LEAGUES = {"ATP": "atp", "WTA": "wta"}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/3.0 (+https://github.com/topboyasian-stack/match-signal)"})


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def scoreboard(sport, league, date):
    r = SESSION.get(f"{ESPN}/{sport}/{league}/scoreboard", params={"dates": date}, timeout=30)
    r.raise_for_status()
    return r.json()


def flatten_tennis(board):
    out = []
    for tournament in board.get("events", []):
        for grouping in tournament.get("groupings", []):
            for comp in grouping.get("competitions", []):
                out.append(comp)
    return out


def brier(probs, actual):
    return round(sum((float(probs.get(k, 0)) - (1 if actual == k else 0)) ** 2 for k in probs), 6)


def settle(history):
    now = datetime.now(timezone.utc)
    today = now.date()
    pending = [p for p in history if not p.get("settled") and p.get("start_time")]
    dates = sorted({p["start_time"][:10] for p in pending})
    dates = [d for d in dates if d <= today.isoformat()][-10:]
    if not dates:
        return 0

    boards = {}
    for date in dates:
        for label, league in FOOTBALL_LEAGUES.items():
            try:
                for event in scoreboard("soccer", league, date).get("events", []):
                    boards[f"football:{event.get('id')}"] = event
            except Exception as exc:
                print(f"football {label} {date}: {exc}")
        for tour, league in TENNIS_LEAGUES.items():
            try:
                for event in flatten_tennis(scoreboard("tennis", league, date)):
                    boards[f"tennis:{event.get('id')}"] = event
            except Exception as exc:
                print(f"tennis {tour} {date}: {exc}")

    settled = 0
    for prediction in history:
        if prediction.get("settled"):
            continue
        event = boards.get(f"{prediction.get('sport')}:{prediction.get('event_id')}")
        if not event or not event.get("status", {}).get("type", {}).get("completed"):
            continue
        competitors = event.get("competitions", [{}])[0].get("competitors", []) or event.get("competitors", [])
        if len(competitors) < 2:
            continue
        try:
            if prediction.get("sport") == "football":
                home = next(c for c in competitors if c.get("homeAway") == "home")
                away = next(c for c in competitors if c.get("homeAway") == "away")
                hs, ass = float(home.get("score", 0)), float(away.get("score", 0))
                actual = "p1" if hs > ass else "p2" if ass > hs else "draw"
                line = float(prediction.get("markets", {}).get("over_under", {}).get("line", 2.5))
                prediction["actual_markets"] = {
                    "over_under": "over" if hs + ass > line else "under",
                    "btts": "yes" if hs > 0 and ass > 0 else "no",
                }
                prediction["final_score"] = [int(hs) if hs.is_integer() else hs, int(ass) if ass.is_integer() else ass]
            else:
                c1, c2 = competitors[0], competitors[1]
                s1 = sum(float(x.get("value", 0)) for x in c1.get("linescores", []))
                s2 = sum(float(x.get("value", 0)) for x in c2.get("linescores", []))
                actual = "p1" if c1.get("winner") else "p2"
                prediction["actual_markets"] = {"total_games": s1 + s2, "sets": len(c1.get("linescores", []))}
                prediction["final_score"] = [s1, s2]
            prediction.update({
                "settled": True,
                "settled_at": now.isoformat(),
                "actual": actual,
                "correct": prediction.get("pick") == actual,
                "brier": brier(prediction.get("probabilities", {}), actual),
            })
            settled += 1
            print(f"Settled {prediction.get('player_1')} vs {prediction.get('player_2')}: {prediction.get('final_score')} ({'WIN' if prediction.get('correct') else 'LOSS'})")
        except (TypeError, ValueError, KeyError, StopIteration) as exc:
            print(f"Could not settle {prediction.get('event_id')}: {exc}")
    return settled


def main():
    history_path = DATA / "prediction_history.json"
    accuracy_path = DATA / "accuracy.json"
    history = load(history_path, [])
    count = settle(history)
    settled = [p for p in history if p.get("settled")]
    summary = {
        "settled": len(settled),
        "correct": sum(bool(p.get("correct")) for p in settled),
        "accuracy": round(sum(bool(p.get("correct")) for p in settled) / len(settled), 4) if settled else 0.0,
        "brier_score": round(sum(float(p.get("brier", 0)) for p in settled) / len(settled), 4) if settled else 0.0,
        "markets": {},
    }
    for sport in ("football", "tennis"):
        group = [p for p in settled if p.get("sport") == sport]
        summary[sport] = {
            "settled": len(group),
            "correct": sum(bool(p.get("correct")) for p in group),
            "accuracy": round(sum(bool(p.get("correct")) for p in group) / len(group), 4) if group else 0.0,
        }
    save(history_path, history[-2500:])
    save(accuracy_path, {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "recent_settled": [p for p in history if p.get("settled")][-50:],
    })
    print(f"Same-day settlement complete: {count} newly settled | total settled {summary['settled']}")


if __name__ == "__main__":
    main()
