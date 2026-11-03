import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SOFASCORE = "https://www.sofascore.com/api/v1"
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
    "Super League Greece": "gre.1",
    "Scottish Premiership": "sco.1",
    "Danish Superliga": "den.1",
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "MatchSignal/3.0 (+https://github.com/topboyasian-stack/match-signal)",
    "Accept": "application/json, text/plain, */*",
})


# ESPN currently returns unsupported-competition errors for these national leagues.
# Use the public SofaScore team-event endpoint as a source-attributed fallback.
# If results are blocked or the domestic competition cannot be verified, leave the
# club's domestic history missing; this path never fabricates scores.
SOFASCORE_TEAM_FALLBACKS = {
    "Shakhtar Donetsk": {
        "team_id": 3313, "league": "Ukrainian Premier League",
        "country_aliases": ("ukraine",), "team_aliases": ("shakhtar donetsk",),
        "tournament_tokens": ("premier league", "ukrainian premier league"),
    },
    "Slovan Bratislava": {
        "team_id": 2404, "league": "Slovak Super Liga",
        "country_aliases": ("slovakia",), "team_aliases": ("slovan bratislava",),
        "tournament_tokens": ("nike liga", "slovak super liga"),
    },
    "Slavia Prague": {
        "team_id": 2216, "league": "Czech First League",
        "country_aliases": ("czechia", "czech republic"), "team_aliases": ("slavia praha", "slavia prague"),
        "tournament_tokens": ("czech first league", "chance liga", "fortuna liga", "1 liga"),
    },
    "Sabah FK": {
        "team_id": 267828, "league": "Azerbaijan Premier League",
        "country_aliases": ("azerbaijan",), "team_aliases": ("sabah", "sabah fk"),
        "tournament_tokens": ("misli premier league", "azerbaijan premier league", "premier league"),
    },
}


def _normalized_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _event_team(event, camel, snake):
    value = event.get(camel) or event.get(snake) or {}
    return str(value.get("name") or value.get("shortName") or value.get("short_name") or "").strip()


def _event_score(event, camel, snake):
    value = event.get(camel) or event.get(snake) or {}
    if isinstance(value, dict):
        value = value.get("current")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_sofascore_domestic_event(event, team_label, config, cutoff=None):
    """Convert one finished, verified domestic match into the history schema."""
    status = event.get("status") or {}
    status_type = str(status.get("type") or "").lower()
    if status_type not in {"finished", "ended", "closed"} and status.get("code") != 100:
        return None

    try:
        timestamp = event.get("startTimestamp") or event.get("start_timestamp")
        if timestamp is not None:
            event_dt = datetime.fromtimestamp(float(timestamp), timezone.utc)
        else:
            raw_time = event.get("startTime") or event.get("start_time") or event.get("date")
            event_dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            event_dt = event_dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError):
        return None

    cutoff_dt = cutoff or datetime.now(timezone.utc)
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    if event_dt >= cutoff_dt or (cutoff_dt - event_dt) > timedelta(days=365):
        return None

    tournament = event.get("tournament") or {}
    unique_tournament = tournament.get("uniqueTournament") or tournament.get("unique_tournament") or {}
    names = [
        tournament.get("name"),
        unique_tournament.get("name"),
        event.get("tournamentName"),
        event.get("tournament_name"),
    ]
    tournament_text = " ".join(_normalized_text(value) for value in names if value)
    category = tournament.get("category") or event.get("category") or {}
    country = _normalized_text(category.get("name") or category.get("country") or event.get("country"))
    if not any(alias in country for alias in config["country_aliases"]):
        return None
    if not any(_normalized_text(token) in tournament_text for token in config["tournament_tokens"]):
        return None

    home_name = _event_team(event, "homeTeam", "home_team")
    away_name = _event_team(event, "awayTeam", "away_team")
    if not home_name or not away_name:
        return None
    aliases = tuple(_normalized_text(alias) for alias in config["team_aliases"])
    if not any(alias and alias in _normalized_text(name) for alias in aliases for name in (home_name, away_name)):
        return None

    home_score = _event_score(event, "homeScore", "home_score")
    away_score = _event_score(event, "awayScore", "away_score")
    if home_score is None or away_score is None:
        return None
    event_id = str(event.get("id") or event.get("eventId") or event.get("event_id") or "")
    if not event_id:
        return None
    return {
        "sport": "football",
        "league": config["league"],
        "event_id": f"sofascore:{event_id}",
        "start_time": event_dt.isoformat(),
        "calculated_at": event_dt.isoformat(),
        "player_1": home_name,
        "player_2": away_name,
        "final_score": [home_score, away_score],
        "settled": True,
        "source": "SofaScore public team-events API; country and domestic competition verified",
        "source_url": f"{SOFASCORE}/event/{event_id}",
    }


def fetch_sofascore_domestic_history(team_label, config, cutoff=None):
    try:
        response = SESSION.get(
            f"{SOFASCORE}/team/{int(config['team_id'])}/events/last/0",
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        events = payload.get("events") or []
        rows = [
            row for event in events
            if (row := normalize_sofascore_domestic_event(event, team_label, config, cutoff))
        ]
        if not rows:
            return [], (
                f"SofaScore fallback {team_label}: no finished domestic matches matched the expected "
                f"competition in the last 365 days"
            )
        return rows, None
    except Exception as exc:
        return [], f"SofaScore fallback {team_label}: {str(exc)[:180]}"



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
    def prior_dates_for(league):
        dates = []
        for row in prior_history:
            if _canonical_history_league(row.get("league")) != league:
                continue
            value = row.get("start_time") or row.get("calculated_at")
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dates.append(dt.astimezone(timezone.utc).date())
            except (TypeError, ValueError):
                continue
        return dates

    lookback_days_by_league = {}
    for league in FOOTBALL_LEAGUES:
        dates = prior_dates_for(league)
        if league == "Champions League":
            # Backfill three seasons once because UCL team form needs prior
            # European campaigns, not only the tail of last season.
            lookback_days_by_league[league] = 1095 if not dates or min(dates) > today - timedelta(days=1090) else 14
        else:
            lookback_days_by_league[league] = 365 if not dates else 14
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

    sofascore_coverage = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        fallback_futures = {
            pool.submit(fetch_sofascore_domestic_history, team, config, datetime.now(timezone.utc)): team
            for team, config in SOFASCORE_TEAM_FALLBACKS.items()
        }
        for future in as_completed(fallback_futures):
            team = fallback_futures[future]
            rows, error = future.result()
            history.extend(rows)
            sofascore_coverage[team] = len(rows)
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
        "refresh_policy": "1095-day UCL backfill for multi-season European history; 365-day domestic backfill for new competitions; 14-day incremental refresh otherwise",
        "sofascore_fallback_matches_by_team": sofascore_coverage,
        "lookback_days_by_league": lookback_days_by_league,
        "date_ranges_by_league": date_ranges_by_league,
        "matches": len(history),
        "matches_by_league": {
            league: sum(1 for row in history if _canonical_history_league(row.get("league")) == league)
            for league in sorted(set(FOOTBALL_LEAGUES) | {config["league"] for config in SOFASCORE_TEAM_FALLBACKS.values()})
        },
        "errors": errors,
        "unique_teams": len({r["player_1"] for r in history} | {r["player_2"] for r in history}),
    }, indent=2))


if __name__ == "__main__":
    main()
