"""Repair/publish Eredivisie LIVE_EXPERIMENTAL signals from resilient sources."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from independent_football_model import independent_prediction
from eredivisie_source import current_fixtures, current_results, norm_team

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def previous_history():
    try:
        raw = subprocess.check_output(["git", "show", "HEAD^:data/ere_divisie_history.json"], text=True, stderr=subprocess.DEVNULL)
        return json.loads(raw)
    except Exception:
        return []


def merge_rows(*groups):
    out = {}
    for group in groups:
        for x in group or []:
            eid = str(x.get("event_id") or "")
            if eid:
                y = dict(x)
                if y.get("home"):
                    y["home"] = norm_team(y["home"])
                if y.get("away"):
                    y["away"] = norm_team(y["away"])
                if y.get("player_1"):
                    y["player_1"] = norm_team(y["player_1"])
                if y.get("player_2"):
                    y["player_2"] = norm_team(y["player_2"])
                out[eid] = y
    return sorted(out.values(), key=lambda x: str(x.get("date") or x.get("start_time")))


def publish_to_main_feed(predictions):
    """Keep the normal Predictions page aware of the expansion feed.

    Existing football/tennis/basketball predictions remain untouched. Any stale
    Eredivisie rows are replaced atomically by the current experimental rows.
    """
    existing = load(DATA / "predictions.json", [])
    if not isinstance(existing, list):
        existing = []
    kept = [p for p in existing if str(p.get("league") or "") != "Eredivisie"]
    combined = kept + predictions
    combined.sort(key=lambda x: str(x.get("start_time") or ""))
    DATA.joinpath("predictions.json").write_text(json.dumps(combined, indent=2), encoding="utf-8")
    return len(combined)


def main():
    existing = load(DATA / "ere_divisie_history.json", [])
    prior = previous_history()
    season = current_results()
    history = merge_rows(prior, existing, season)
    fixtures = current_fixtures()

    model_hist = []
    for r in history:
        if r.get("home_score") is None or r.get("away_score") is None:
            continue
        model_hist.append({
            "sport": "football", "settled": True,
            "final_score": [r["home_score"], r["away_score"]],
            "event_id": r["event_id"], "start_time": r["date"],
            "league": "Eredivisie", "player_1": norm_team(r["home"]), "player_2": norm_team(r["away"])
        })

    predictions = []
    for f in fixtures:
        home, away = norm_team(f["home"]), norm_team(f["away"])
        event = {"id": f["event_id"], "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": home}},
            {"homeAway": "away", "team": {"displayName": away}},
        ]}]}
        try:
            p = independent_prediction(event, "Eredivisie", model_hist, cutoff=f["date"])
        except Exception:
            p = None
        if not p:
            continue
        xh, xa = float(p.get("xg_home", 0)), float(p.get("xg_away", 0))
        import math
        total = max(0.05, xh + xa)
        under25 = sum(math.exp(-total) * total**k / math.factorial(k) for k in range(3))
        over25 = 1 - under25
        btts = 1 - math.exp(-xh) - math.exp(-xa) + math.exp(-total)
        probs = {"p1": round(p["p1"], 6), "draw": round(p["draw"], 6), "p2": round(p["p2"], 6)}
        predictions.append({
            "sport": "football", "league": "Eredivisie", "event_id": f["event_id"],
            "start_time": f["date"], "player_1": home, "player_2": away,
            "probabilities": probs, "pick": max(probs, key=probs.get),
            "confidence": round(max(probs.values()), 6),
            "expected_goals": {"p1": round(xh, 4), "p2": round(xa, 4), "total": round(xh + xa, 4)},
            "markets": {
                "over_under": {"line": 2.5, "over": round(over25, 6), "under": round(under25, 6), "pick": "over" if over25 >= under25 else "under"},
                "btts": {"yes": round(btts, 6), "no": round(1 - btts, 6), "pick": "yes" if btts >= .5 else "no"}
            },
            "market": {"odds": {}, "value_by_outcome": {}, "best_value": None, "status": "NO_FREE_CURRENT_ODDS_SOURCE"},
            "model": p.get("method", "independent_football_model"),
            "signal_quality": {"effective_sample": p.get("effective_sample"), "home_sample": p.get("sample_home"), "away_sample": p.get("sample_away"), "status": "LIVE_EXPERIMENTAL", "history_events": len(model_hist)},
            "prediction_status": "live_experimental", "paper_only": False, "live_experimental": True,
            "source": {"fixtures": f.get("source"), "history": "openfootball current season + retained Match Signal history"},
        })

    DATA.joinpath("ere_divisie_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    DATA.joinpath("ere_divisie_predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    main_feed_count = publish_to_main_feed(predictions)

    status = load(DATA / "expansion_status.json", {})
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    status["release_mode"] = "LIVE_EXPERIMENTAL"
    status["live_trading_approved"] = False
    status.setdefault("competitions", {})["Eredivisie"] = {
        "historical_events": len(history), "current_fixtures": len(fixtures),
        "published_predictions": len(predictions), "collection_errors": 0,
        "status": "LIVE_EXPERIMENTAL" if predictions else "NO_CURRENT_FIXTURES",
        "fixture_source": "FixtureDownload JSON primary; openfootball current-season fallback",
        "history_source": "openfootball current season + retained Match Signal history",
    }
    status.setdefault("monitoring", {})["market_data_is_benchmark_only"] = True
    status.setdefault("notes", []).append("Eredivisie repair source added after free Football-Data endpoint rate limiting; no market odds are fabricated when unavailable.")
    status["main_prediction_feed_merged"] = True
    status["main_prediction_feed_count"] = main_feed_count
    DATA.joinpath("expansion_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps({"fixtures": len(fixtures), "predictions": len(predictions), "history": len(history), "main_prediction_feed_count": main_feed_count}, indent=2))


if __name__ == "__main__":
    main()
