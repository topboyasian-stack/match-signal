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
    # Domestic competitions needed to establish each Champions League club's
    # own league form; do not infer it from the UCL table.
    "Premier League": "eng.1",
    "Serie A": "ita.1",
    "Eredivisie": "ned.1",
    "Primeira Liga": "por.1",
    "Süper Lig": "tur.1",
    "Belgian Pro League": "bel.1",
    "Austrian Bundesliga": "aut.1",
    "Eliteserien": "nor.1",
    "Czech First League": "cze.1",
    "Ukrainian Premier League": "ukr.1",
    "Super League Greece": "gre.1",
    "Scottish Premiership": "sco.1",
    "Swiss Super League": "sui.1",
    "Danish Superliga": "den.1",
    "Polish Ekstraklasa": "pol.1",
    "Croatian First Football League": "cro.1",
    "Serbian SuperLiga": "srb.1",
    "Slovak Super Liga": "svk.1",
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


def _canonical_history_league(value):
    return str(value or "").strip()


def main():
    today = datetime.now(timezone.utc).date()
    history = []
    errors = []
    prior_path = DATA / "football_team_history.json"
    try:
        prior_history = json.loads(prior_path.read_text(encoding="utf-8"))
        if not isinstance(prior_history, list):
            prior_history = []
    except Exception:
        prior_history = []

    # Existing competitions get a 14-day incremental refresh. Each newly added
    # domestic league receives its own 365-day backfill even when other leagues
    # already have a populated artifact.
    lookback_days_by_league = {
        league: (365 if not any(_canonical_history_league(row.get("league")) == league for row in prior_history) else 14)
        for league in FOOTBALL_LEAGUES
    }
    start_by_league = {
        league: today - timedelta(days=lookback_days)
        for league, lookback_days in lookback_days_by_league.items()
    }
    date_ranges_by_league = {
        league: f"{start:%Y%m%d}-{today:%Y%m%d}"
        for league, start in start_by_league.items()
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = [
        (league, slug, start_by_league[league] + timedelta(days=offset))
        for league, slug in FOOTBALL_LEAGUES.items()
        for offset in range((today - start_by_league[league]).days + 1)
    ]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(fetch_day, league, slug, day): (league, day)
            for league, slug, day in jobs
        }
        for future in as_completed(futures):
            rows, error = future.result()
            history.extend(rows)
            if error:
                errors.append(error)

    by_event = {}
    for row in prior_history + history:
        event_id = str(row.get("event_id") or "")
        league = _canonical_history_league(row.get("league"))
        if event_id:
            by_event[(league, event_id)] = row
    history = sorted(
        by_event.values(),
        key=lambda row: (row.get("start_time") or "", row.get("league") or ""),
    )
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
        "refresh_policy": "365-day backfill for each newly added competition; 14-day incremental refresh for populated competitions",
        "lookback_days_by_league": lookback_days_by_league,
        "date_ranges_by_league": date_ranges_by_league,
        "matches": len(history),
        "matches_by_league": {
            league: sum(1 for row in history if _canonical_history_league(row.get("league")) == league)
            for league in FOOTBALL_LEAGUES
        },
        "errors": errors,
        "unique_teams": len({r["player_1"] for r in history} | {r["player_2"] for r in history}),
    }, indent=2))


if __name__ == "__main__":
    main()
