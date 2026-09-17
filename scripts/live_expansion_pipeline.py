"""Live-experimental NBA + Eredivisie pipeline.

Keeps the independent model separate from market prices while allowing the
current-season competitions to generate real, timestamped experimental signals.
The outputs are explicitly LIVE_EXPERIMENTAL, never live-trading approved.
"""
import csv, io, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

from expansion_pipeline import collect, current, nba_predict, NBA_START, NOW
from independent_football_model import independent_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (compatible; MatchSignal/1.0)"})


def dt(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        for f in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(v), f).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def football_data_fixtures():
    """Fallback/current Eredivisie fixture source with free odds.

    The season result CSV is intentionally not used for upcoming fixtures:
    Football-Data publishes a separate fixtures feed. This avoids treating a
    result archive as a future schedule and also avoids the redirect problem
    seen on the season CSV from the GitHub Actions runner.
    """
    urls = (
        "https://football-data.co.uk/fixtures.csv",
        "https://www.football-data.co.uk/fixtures.csv",
        "https://www.football-data.co.uk/matches/resources/fixtures.csv",
    )
    last_error = None
    text = None
    source_url = None
    for url in urls:
        try:
            r = S.get(url, timeout=45, allow_redirects=False)
            if r.status_code == 200 and r.text.strip():
                text = r.text
                source_url = url
                break
            last_error = f"{url}: HTTP {r.status_code}"
        except Exception as exc:
            last_error = f"{url}: {exc}"
    if text is None:
        raise RuntimeError(f"Football-Data fixtures feed unavailable: {last_error}")

    rows = []
    for x in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if (x.get("Div") or "").strip().upper() != "N1":
            continue
        d = dt(x.get("Date"))
        h = (x.get("HomeTeam") or "").strip()
        a = (x.get("AwayTeam") or "").strip()
        if not d or not h or not a:
            continue
        # The fixture feed is a schedule, so retain only the current/upcoming
        # window. Use the explicit kick-off time when it is present.
        time_value = (x.get("Time") or "").strip()
        if time_value:
            try:
                hh, mm = time_value.split(":", 1)
                d = d.replace(hour=int(hh), minute=int(mm))
            except Exception:
                pass
        if d < NOW - timedelta(hours=6) or d > NOW + timedelta(days=10):
            continue

        def num(k):
            try:
                return float(x[k]) if x.get(k) not in (None, "") else None
            except Exception:
                return None

        odds = {
            "home": num("B365H") or num("AvgH"),
            "draw": num("B365D") or num("AvgD"),
            "away": num("B365A") or num("AvgA"),
            "over_2_5": num("B365>2.5") or num("Avg>2.5"),
            "under_2_5": num("B365<2.5") or num("Avg<2.5"),
        }
        rows.append({
            "event_id": f"fd-fixture|N1|{d.isoformat()}|{h}|{a}",
            "date": d.isoformat(),
            "home": h,
            "away": a,
            "markets": {"odds": odds, "source": "football-data.co.uk", "source_url": source_url},
            "source": "football-data.co.uk",
        })
    return sorted(rows, key=lambda z: z["date"])


def current_ere():
    try:
        rows = current("Eredivisie")
    except Exception:
        rows = []
    return rows or football_data_fixtures()


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def goals_markets(xg_home, xg_away):
    total = max(0.05, xg_home + xg_away)
    under25 = sum(poisson_pmf(k, total) for k in range(3))
    over25 = max(0.0, 1.0 - under25)
    btts_yes = 1 - math.exp(-xg_home) - math.exp(-xg_away) + math.exp(-total)
    return {
        "over_under": {
            "line": 2.5, "over": round(over25, 6), "under": round(under25, 6),
            "pick": "over" if over25 >= under25 else "under"
        },
        "btts": {
            "yes": round(btts_yes, 6), "no": round(1-btts_yes, 6),
            "pick": "yes" if btts_yes >= 0.5 else "no"
        }
    }


def market_value(prob, odds):
    if not odds or odds <= 1:
        return None
    return round(prob * odds - 1, 5)


def ere_prediction(fixture, history):
    event = {
        "id": fixture["event_id"],
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": fixture["home"]}},
            {"homeAway": "away", "team": {"displayName": fixture["away"]}},
        ]}],
    }
    p = independent_prediction(event, "Eredivisie", history, cutoff=fixture["date"])
    if not p:
        return None
    markets = goals_markets(p["xg_home"], p["xg_away"])
    odds = (fixture.get("markets") or {}).get("odds") or {}
    probs = {"p1": p["p1"], "draw": p["draw"], "p2": p["p2"]}
    odds_values = {k: market_value(probs[k], odds.get(k)) for k in ("home", "draw", "away")}
    value_candidates = {"home": odds_values["home"], "draw": odds_values["draw"], "away": odds_values["away"]}
    value_candidates = {k:v for k,v in value_candidates.items() if v is not None}
    best_value = max(value_candidates.items(), key=lambda z:z[1]) if value_candidates else None
    return {
        "sport": "football", "league": "Eredivisie", "event_id": fixture["event_id"],
        "start_time": fixture["date"], "player_1": fixture["home"], "player_2": fixture["away"],
        "probabilities": probs,
        "pick": max(probs, key=probs.get),
        "confidence": round(max(probs.values()), 6),
        "expected_goals": {"p1": p["xg_home"], "p2": p["xg_away"], "total": round(p["xg_home"]+p["xg_away"],4)},
        "markets": markets,
        "market": {"odds": odds, "value_by_outcome": odds_values, "best_value": best_value},
        "model": p["method"],
        "signal_quality": {"effective_sample": p["effective_sample"], "home_sample": p["sample_home"], "away_sample": p["sample_away"], "status": "LIVE_EXPERIMENTAL"},
        "prediction_status": "live_experimental", "paper_only": False,
        "live_experimental": True,
    }


def main():
    nba_history, nba_errors = collect("NBA")
    ere_history, ere_errors = collect("Eredivisie")
    nba_fixtures = [] if NOW < NBA_START else current("NBA")
    ere_fixtures = current_ere()

    # Preserve the historical research files, but publish current fixtures separately.
    ere_hist_for_model = [{
        "sport": "football", "settled": True,
        "final_score": [r["home_score"], r["away_score"]],
        "event_id": r["event_id"], "start_time": r["date"],
        "league": "Eredivisie", "player_1": r["home"], "player_2": r["away"]
    } for r in ere_history]

    ere_predictions = [p for f in ere_fixtures if (p := ere_prediction(f, ere_hist_for_model))]
    nba_predictions = []
    for f in nba_fixtures:
        p = nba_predict(f, nba_history)
        if p:
            probs = p["moneyline"]
            nba_predictions.append({
                "sport": "basketball", "league": "NBA", "event_id": f["event_id"],
                "start_time": f["date"], "player_1": f["home"], "player_2": f["away"],
                "probabilities": {"p1": round(probs["home"],6), "p2": round(probs["away"],6)},
                "pick": "p1" if probs["home"] >= probs["away"] else "p2",
                "confidence": round(max(probs.values()),6),
                "expected_score": p["expected_score"], "expected_total": p["expected_total"],
                "markets": {"moneyline": p["moneyline"]},
                "model": p["model"], "signal_quality": {"status":"LIVE_EXPERIMENTAL"},
                "prediction_status": "live_experimental", "paper_only": False,
                "live_experimental": True,
            })

    (DATA/"ere_divisie_history.json").write_text(json.dumps(ere_history, indent=2), encoding="utf-8")
    (DATA/"nba_history.json").write_text(json.dumps(nba_history, indent=2), encoding="utf-8")
    (DATA/"ere_divisie_predictions.json").write_text(json.dumps(ere_predictions, indent=2), encoding="utf-8")
    (DATA/"nba_predictions.json").write_text(json.dumps(nba_predictions, indent=2), encoding="utf-8")

    status = {
        "updated_at": NOW.isoformat(), "release_mode": "LIVE_EXPERIMENTAL",
        "live_trading_approved": False,
        "competitions": {
            "NBA": {"historical_events": len(nba_history), "current_fixtures": len(nba_fixtures), "collection_errors": len(nba_errors), "status": "LIVE_EXPERIMENTAL" if nba_predictions else ("PRESEASON_READY" if NOW < NBA_START else "NO_CURRENT_FIXTURES")},
            "Eredivisie": {"historical_events": len(ere_history), "current_fixtures": len(ere_fixtures), "published_predictions": len(ere_predictions), "collection_errors": len(ere_errors), "status": "LIVE_EXPERIMENTAL" if ere_predictions else "NO_CURRENT_FIXTURES", "fixture_source": "ESPN primary; Football-Data fixtures.csv fallback"},
        },
        "monitoring": {"settlement": "expansion_prediction_history.json", "promotion_rule": "live evidence + calibration + market benchmark; automatic demotion on data failure", "market_data_is_benchmark_only": True},
        "notes": ["Independent probabilities never consume market probabilities.", "LIVE_EXPERIMENTAL signals are real generated predictions, not guarantees or live-trading approval.", "NBA remains preseason-ready until 2026-10-20, then enters live experimental mode automatically.", "Eredivisie uses the current ESPN scoreboard when available and the Football-Data fixtures feed as a resilient current-fixture fallback."],
    }
    (DATA/"expansion_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
