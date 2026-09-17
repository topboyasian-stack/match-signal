"""Run the live expansion pipeline with a resilient daywise ESPN fixture probe.

ESPN soccer scoreboards are queried one UTC date at a time here. The previous
range query could return an empty/error response on GitHub Actions even though
the single-day Eredivisie scoreboard is available.
"""
from datetime import datetime, timedelta, timezone

import live_expansion_pipeline as pipeline


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

    # Keep the two existing non-ESPN fallbacks as the last-resort path.
    try:
        return pipeline.football_data_fixtures()
    except Exception:
        return pipeline.sofascore_fixtures()


pipeline.current_ere = daywise_current_ere
pipeline.main()
