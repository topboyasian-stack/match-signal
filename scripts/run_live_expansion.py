"""Run the live expansion pipeline with resilient current-fixture probes.

ESPN soccer scoreboards are queried one UTC date at a time. If the GitHub
Actions runner cannot reach ESPN, TheSportsDB's free upcoming-league feed is
used before the older Football-Data/SofaScore fallbacks.
"""
from datetime import datetime, timedelta, timezone

import live_expansion_pipeline as pipeline


def thesportsdb_current_ere():
    url = "https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php"
    response = pipeline.S.get(url, params={"id": 4337}, timeout=45)
    response.raise_for_status()
    payload = response.json()
    rows = []
    for event in payload.get("events") or []:
        home = (event.get("strHomeTeam") or "").strip()
        away = (event.get("strAwayTeam") or "").strip()
        if not home or not away:
            continue
        raw_date = (event.get("dateEvent") or "").strip()
        raw_time = (event.get("strTime") or "").strip()
        try:
            if raw_time:
                # TheSportsDB commonly returns HH:MM:SSZ; normalize to UTC.
                stamp = f"{raw_date}T{raw_time.replace('Z', '+00:00')}"
                start = datetime.fromisoformat(stamp)
            else:
                start = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
        except Exception:
            continue
        if start < pipeline.NOW - timedelta(hours=6) or start > pipeline.NOW + timedelta(days=10):
            continue
        rows.append({
            "event_id": f"tsdb|{event.get('idEvent')}",
            "date": start.isoformat(),
            "home": home,
            "away": away,
            "markets": {"odds": {}, "source": "thesportsdb"},
            "source": "thesportsdb",
        })
    if not rows:
        raise RuntimeError("TheSportsDB returned no current Eredivisie fixtures")
    return sorted({r["event_id"]: r for r in rows}.values(), key=lambda z: z["date"])


def daywise_current_ere():
    rows = []
    for offset in range(-1, 9):
        day = (pipeline.NOW + timedelta(days=offset)).date()
        try:
            payload = pipeline.get(
                f"{pipeline.BASE}/soccer/ned.1/scoreboard",
                {"dates": day.strftime("%Y%m%d")},
            )
            events = payload.get("events", [])
        except Exception:
            continue

        for event in events:
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors", [])
            if len(competitors) != 2:
                continue
            home = next((x for x in competitors if x.get("homeAway") == "home"), competitors[0])
            away = next((x for x in competitors if x.get("homeAway") == "away"), competitors[1])
            _, home_name = pipeline.team(home)
            _, away_name = pipeline.team(away)
            start = pipeline.dt(event.get("date"))
            if not start or not home_name or not away_name:
                continue
            if start < pipeline.NOW - timedelta(hours=6) or start > pipeline.NOW + timedelta(days=10):
                continue
            status = ((event.get("status") or {}).get("type") or {}).get("name")
            if status in {"STATUS_FINAL", "STATUS_POSTPONED", "STATUS_CANCELED"}:
                continue
            rows.append({
                "event_id": str(event.get("id")),
                "date": start.isoformat(),
                "home": home_name,
                "away": away_name,
                "markets": {},
                "source": "ESPN",
            })

    if rows:
        return sorted({r["event_id"]: r for r in rows}.values(), key=lambda z: z["date"])

    try:
        return thesportsdb_current_ere()
    except Exception:
        try:
            return pipeline.football_data_fixtures()
        except Exception:
            return pipeline.sofascore_fixtures()


pipeline.current_ere = daywise_current_ere
pipeline.main()
