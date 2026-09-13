"""Build reusable team behavior profiles from completed match data.

The profile is descriptive first: provider observations become auditable features for
next-match research. Features do not change model probabilities. PAPER ONLY.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "behavior_profiles.json"
FOOTBALL_SLUGS = {
    "EPL": "eng.1", "La Liga": "esp.1", "Bundesliga": "ger.1", "Serie A": "ita.1",
    "Ligue 1": "fra.1", "Champions League": "uefa.champions", "MLS": "usa.1", "Primeira Liga": "por.1",
}


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def pct(n, d):
    return round(n / d, 4) if d else None


def fetch_summary(league, event_id):
    slug = FOOTBALL_SLUGS.get(league)
    if not slug or not event_id:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Match-Signal/behavior-profiler"})
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    return None


def event_behaviour(summary):
    if not isinstance(summary, dict):
        return {}
    comp = (summary.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    home_id = str(home.get("team", {}).get("id") or "")
    away_id = str(away.get("team", {}).get("id") or "")
    plays = summary.get("plays") or comp.get("plays") or []
    out = {
        "events": 0,
        "side_events": {"home": 0, "away": 0},
        "goals": {"home": 0, "away": 0},
        "cards": {"home": 0, "away": 0},
        "shots": {"home": 0, "away": 0},
        "shots_on_target": {"home": 0, "away": 0},
        "red_cards": {"home": 0, "away": 0},
        "home_name": home.get("team", {}).get("displayName"),
        "away_name": away.get("team", {}).get("displayName"),
    }
    for p in plays:
        out["events"] += 1
        text = str(p.get("text") or p.get("shortText") or p.get("type", {}).get("text") or "").lower()
        tid = str((p.get("team") or {}).get("id") or "")
        side = "home" if tid and tid == home_id else "away" if tid and tid == away_id else None
        if not side:
            continue
        out["side_events"][side] += 1
        if "goal" in text and "own goal" not in text:
            out["goals"][side] += 1
        if "red card" in text:
            out["red_cards"][side] += 1
        if "yellow card" in text:
            out["cards"][side] += 1
        if "shot" in text:
            out["shots"][side] += 1
        if "shot on target" in text or "goal" in text:
            out["shots_on_target"][side] += 1
    return out


def add_team(store, sport, name, league, gf, ga, result, home=None, behavior=None):
    if not name:
        return
    key = f"{sport}|{league}|{name}"
    x = store[key]
    x["sport"] = sport
    x["league"] = league
    x["team"] = name
    x["matches"] += 1
    x["goals_for"].append(gf)
    x["goals_against"].append(ga)
    if result == "W": x["wins"] += 1
    elif result == "D": x["draws"] += 1
    else: x["losses"] += 1
    if gf == 0: x["blanked"] += 1
    if ga == 0: x["clean_sheets"] += 1
    if home is not None and home: x["home_matches"] += 1
    if behavior:
        side = "home" if home else "away"
        x["provider_event_counts"].append(behavior.get("side_events", {}).get(side, 0))
        x["provider_goals"] += behavior.get("goals", {}).get(side, 0)
        x["provider_shots"] += behavior.get("shots", {}).get(side, 0)
        x["provider_shots_on_target"] += behavior.get("shots_on_target", {}).get(side, 0)
        x["provider_cards"] += behavior.get("cards", {}).get(side, 0)
        x["provider_red_cards"] += behavior.get("red_cards", {}).get(side, 0)
        x["provider_observations"] += 1


def profile_rows(history, max_rows=250):
    rows = []
    for r in history:
        if isinstance(r, dict) and r.get("settled") and r.get("final_score") and r.get("player_1") and r.get("player_2"):
            rows.append(r)
    rows.sort(key=lambda r: r.get("start_time") or "", reverse=True)
    return rows[:max_rows]


def main():
    football = load("football_team_history.json", [])
    basketball = load("basketball_history.json", [])
    predictions = load("predictions.json", [])
    teams = defaultdict(lambda: {
        "sport": None, "matches": 0, "wins": 0, "draws": 0, "losses": 0,
        "goals_for": [], "goals_against": [], "blanked": 0, "clean_sheets": 0,
        "home_matches": 0, "provider_event_counts": [], "provider_goals": 0,
        "provider_shots": 0, "provider_shots_on_target": 0, "provider_cards": 0,
        "provider_red_cards": 0, "provider_observations": 0,
    })
    player_profiles = {}
    provider_enriched = 0
    provider_attempts = 0

    for r in profile_rows(football):
        score = r.get("final_score")
        h, a = num(score[0]), num(score[1])
        if h is None or a is None:
            continue
        behavior = None
        if provider_attempts < 60:
            provider_attempts += 1
            summary = fetch_summary(r.get("league"), r.get("event_id"))
            if summary:
                behavior = event_behaviour(summary)
                provider_enriched += 1
        league = r.get("league") or "global"
        add_team(teams, "football", r["player_1"], league, h, a, "W" if h > a else "D" if h == a else "L", True, behavior)
        add_team(teams, "football", r["player_2"], league, a, h, "W" if a > h else "D" if h == a else "L", False, behavior)

    for r in profile_rows(basketball):
        score = r.get("final_score") or r.get("score")
        if not isinstance(score, (list, tuple)) or len(score) < 2:
            continue
        h, a = num(score[0]), num(score[1])
        if h is None or a is None:
            continue
        league = r.get("league") or "global"
        add_team(teams, "basketball", r.get("player_1"), league, h, a, "W" if h > a else "L", True)
        add_team(teams, "basketball", r.get("player_2"), league, a, h, "W" if a > h else "L", False)

    out_teams = {}
    for key, x in teams.items():
        out_teams[key] = {
            "sport": x["sport"], "league": x["league"], "team": x["team"], "matches": x["matches"],
            "win_rate": pct(x["wins"], x["matches"]), "draw_rate": pct(x["draws"], x["matches"]),
            "loss_rate": pct(x["losses"], x["matches"]), "avg_goals_for": mean(x["goals_for"]),
            "avg_goals_against": mean(x["goals_against"]), "blank_rate": pct(x["blanked"], x["matches"]),
            "clean_sheet_rate": pct(x["clean_sheets"], x["matches"]),
            "provider_event_rate": mean(x["provider_event_counts"]),
            "provider_shots_per_match": round(x["provider_shots"] / max(1, x["provider_observations"]), 4),
            "provider_sot_per_match": round(x["provider_shots_on_target"] / max(1, x["provider_observations"]), 4),
            "provider_cards_per_match": round(x["provider_cards"] / max(1, x["provider_observations"]), 4),
            "provider_red_cards_per_match": round(x["provider_red_cards"] / max(1, x["provider_observations"]), 4),
            "provider_observations": x["provider_observations"],
            "source": "ESPN completed results + provider play-by-play when available",
        }

    for r in predictions:
        if r.get("sport") == "tennis" and r.get("player_1") and r.get("player_2"):
            for name in (r["player_1"], r["player_2"]):
                player_profiles.setdefault(name, {
                    "sport": "tennis", "name": name, "observations": 0,
                    "provider_identity": False,
                    "note": "Awaiting provider athlete identity/statistics feed",
                })

    result = {
        "version": "behavior-profiles-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "teams": out_teams,
        "individuals": player_profiles,
        "provider_enriched_events": provider_enriched,
        "provider_attempted_events": provider_attempts,
        "design": {
            "team_features": ["recent results", "goals for/against", "clean sheets", "blank rate", "provider event rate", "shots", "shots on target", "cards", "red cards"],
            "individual_features": "only populated from verified provider athlete identity/statistics; no name-based inference",
            "use_in_next_match_model": "diagnostic/context layer first; validated walk-forward gate required before probability changes",
        },
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "teams": len(out_teams), "individuals": len(player_profiles), "provider_enriched_events": provider_enriched, "provider_attempted_events": provider_attempts}, indent=2))


if __name__ == "__main__":
    main()
