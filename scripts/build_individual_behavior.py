"""Build verified individual-player behavior observations from ESPN event data.

Identity is accepted only from provider athlete IDs present in the event payload.
No name matching is used. The output is a research feature store only: it cannot
change production probabilities until the separate validation gate promotes it.
PAPER ONLY.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "individual_behavior.json"

LEAGUES = {
    "ATP": "tennis/atp",
    "WTA": "tennis/wta",
    "NBA": "basketball/nba",
    "WNBA": "basketball/wnba",
}


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def get_json(url):
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Match-Signal/individual-behavior"})
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


def athlete_identity(obj):
    if not isinstance(obj, dict):
        return None
    athlete = obj.get("athlete") if isinstance(obj.get("athlete"), dict) else obj
    aid = athlete.get("id")
    name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName")
    if aid and name:
        return {"id": str(aid), "name": name}
    return None


def extract_stats(summary):
    """Return verified athlete observations when the provider exposes them."""
    if not isinstance(summary, dict):
        return []
    out = []
    competitions = summary.get("competitions") or []
    comp = competitions[0] if competitions else {}
    for competitor in comp.get("competitors") or []:
        identity = athlete_identity(competitor)
        if not identity:
            # Some provider payloads place athletes under statistics.
            for stat_group in competitor.get("statistics") or []:
                identity = athlete_identity(stat_group)
                if identity:
                    break
        if not identity:
            continue
        stats = {}
        for s in competitor.get("statistics") or []:
            if not isinstance(s, dict):
                continue
            name = s.get("name") or s.get("abbreviation")
            value = s.get("value")
            if name and value is not None:
                stats[str(name)] = value
        out.append({"athlete_id": identity["id"], "athlete": identity["name"], "team_id": str((competitor.get("team") or {}).get("id") or ""), "stats": stats})
    return out


def main():
    predictions = load("predictions.json", [])
    history = load("prediction_history.json", [])
    candidates = []
    seen = set()
    for row in predictions + history:
        if not isinstance(row, dict):
            continue
        sport = str(row.get("sport") or "").lower()
        if sport not in {"tennis", "basketball"}:
            continue
        league = str(row.get("league") or "")
        event_id = row.get("event_id")
        if not event_id or not league or (sport, league, str(event_id)) in seen:
            continue
        seen.add((sport, league, str(event_id)))
        candidates.append(row)

    observations = []
    attempted = 0
    enriched = 0
    for row in candidates[:300]:
        league = str(row.get("league") or "")
        # Tennis ATP/WTA feeds may be served by ESPN's sport league endpoints;
        # basketball uses the same summary structure. We only accept payloads
        # that actually expose athlete IDs.
        slug = LEAGUES.get(league)
        if not slug:
            continue
        sport = str(row.get("sport")).lower()
        sport_name, league_name = slug.split("/", 1)
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_name}/{league_name}/summary?event={row['event_id']}"
        attempted += 1
        summary = get_json(url)
        stats = extract_stats(summary)
        if stats:
            enriched += 1
            for s in stats:
                observations.append({
                    "sport": sport,
                    "league": league,
                    "event_id": str(row["event_id"]),
                    "start_time": row.get("start_time"),
                    "athlete_id": s["athlete_id"],
                    "athlete": s["athlete"],
                    "team_id": s["team_id"],
                    "stats": s["stats"],
                    "source": "ESPN verified athlete identity in event payload",
                })

    by_player = defaultdict(list)
    for obs in observations:
        by_player[(obs["sport"], obs["league"], obs["athlete_id"])].append(obs)

    profiles = {}
    for key, rows in by_player.items():
        sport, league, athlete_id = key
        profiles["|".join(key)] = {
            "sport": sport,
            "league": league,
            "athlete_id": athlete_id,
            "athlete": rows[0]["athlete"],
            "observations": len(rows),
            "recent_observations": rows[-10:],
            "identity_verified": True,
        }

    result = {
        "version": "individual-behavior-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "attempted_events": attempted,
        "provider_enriched_events": enriched,
        "verified_observations": len(observations),
        "verified_players": len(profiles),
        "profiles": profiles,
        "observations": observations,
        "production_probability_adjustment": False,
        "promotion_rule": "Do not alter V4 probabilities until player features pass leakage-safe walk-forward validation with minimum sample and ablation thresholds.",
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "attempted_events", "provider_enriched_events", "verified_observations", "verified_players")}, indent=2))


if __name__ == "__main__":
    main()
