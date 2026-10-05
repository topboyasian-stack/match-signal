import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
FOOTBALL_LEAGUES = {
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Ligue 1": "fra.1",
    "Champions League": "uefa.champions",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "MatchSignal/3.0 (+https://github.com/topboyasian-stack/match-signal)",
    "Accept": "application/json, text/plain, */*",
})


def fetch_day(league, slug, day):
    try:
        response = SESSION.get(
            f"{ESPN}/{slug}/scoreboard",
            params={"dates": day.strftime("%Y%m%d"), "limit": 1000},
            timeout=20,
        )
        response.raise_for_status()
        rows = []
        for event in response.json().get("events", []):
            status = event.get("status", {}).get("type", {})
            if not status.get("completed"):
                continue
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            try:
                hs = float(home.get("score"))
                ass = float(away.get("score"))
            except (TypeError, ValueError):
                continue
            home_name = (home.get("team") or {}).get("displayName")
            away_name = (away.get("team") or {}).get("displayName")
            if not home_name or not away_name:
                continue
            rows.append({
                "sport": "football",
                "league": league,
                "event_id": str(event.get("id")),
                "start_time": event.get("date"),
                "calculated_at": event.get("date") or "",
                "player_1": home_name,
                "player_2": away_name,
                "final_score": [hs, ass],
                "settled": True,
                "source": "ESPN completed scoreboard",
            })
        return rows, None
    except Exception as exc:
        return [], f"{league}:{day.isoformat()}:{str(exc)[:180]}"


def main():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=365)
    history = []
    errors = []
    prior_path = DATA / "football_team_history.json"
    try:
        prior_history = json.loads(prior_path.read_text(encoding="utf-8"))
        if not isinstance(prior_history, list):
            prior_history = []
    except Exception:
        prior_history = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = [
        (league, slug, start + timedelta(days=offset))
        for league, slug in FOOTBALL_LEAGUES.items()
        for offset in range((today - start).days + 1)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_day, league, slug, day): (league, day) for league, slug, day in jobs}
        for future in as_completed(futures):
            rows, error = future.result()
            history.extend(rows)
            if error:
                errors.append(error)

    by_event = {}
    for row in history:
        event_id = row.get("event_id")
        if event_id:
            by_event[event_id] = row
    history = sorted(by_event.values(), key=lambda row: row.get("start_time") or "")
    # Never silently replace a non-empty research history with an empty file.
    # A total provider failure must fail closed so the model layer cannot lose
    # its independent team-history evidence.
    if not history:
        if prior_history:
            history = prior_history
            errors.append("active team-history sources returned zero rows; preserved prior non-empty artifact")
        else:
            errors.append("active team-history sources returned zero rows; independent history is unavailable for this run")
    (DATA / "football_team_history.json").write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "status": "ok",
        "date_range": date_range,
        "matches": len(history),
        "errors": errors,
        "unique_teams": len({r["player_1"] for r in history} | {r["player_2"] for r in history}),
    }, indent=2))


if __name__ == "__main__":
    main()
