import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
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

SESSION = requests.Session()


def main():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=365)
    date_range = f"{start:%Y%m%d}-{today:%Y%m%d}"
    history = []
    errors = []

    for league, slug in FOOTBALL_LEAGUES.items():
        try:
            response = SESSION.get(
                f"{ESPN}/{slug}/scoreboard",
                params={"dates": date_range, "limit": 1000},
                timeout=60,
            )
            response.raise_for_status()
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
                history.append({
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
        except Exception as exc:
            errors.append(f"{league}:{str(exc)[:180]}")

    history.sort(key=lambda row: row.get("start_time") or "")
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
