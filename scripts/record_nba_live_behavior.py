#!/usr/bin/env python3
"""Capture timestamped, research-only NBA in-game team/player behavior snapshots."""
import json, os
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "nba_live_observations.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
S = requests.Session()
S.headers.update({"User-Agent": "MatchSignalResearch/1.0 (public scoreboard; paper-only)"})

def get(url, params=None):
    r = S.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def team_row(c):
    t = c.get("team") or {}
    return {"id": str(t.get("id") or c.get("id") or ""),
            "name": t.get("displayName") or t.get("name") or c.get("displayName") or "",
            "score": c.get("score"),
            "winner": c.get("winner")}

def main():
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    board = get(BASE + "/scoreboard", {"dates": day})
    events = board.get("events") or []
    observations = []
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        status = event.get("status") or {}
        st = status.get("type") or {}
        if st.get("state") != "in" and not st.get("completed"):
            continue
        competitors = comp.get("competitors") or []
        home = next((team_row(x) for x in competitors if x.get("homeAway") == "home"), team_row(competitors[0]) if competitors else {})
        away = next((team_row(x) for x in competitors if x.get("homeAway") == "away"), team_row(competitors[1]) if len(competitors)>1 else {})
        eid = str(event.get("id") or "")
        if not eid: continue
        record = {"observed_at": now.isoformat(), "event_id": eid, "scheduled_at": event.get("date"),
                  "game_state": "final" if st.get("completed") else "live",
                  "status": st.get("shortDetail") or st.get("description") or st.get("name"),
                  "period": status.get("period"), "clock": status.get("displayClock"),
                  "home": home, "away": away, "source": "ESPN public scoreboard",
                  "paper_only": True}
        # Capture play-by-play, team box score and individual player box score where ESPN exposes them.
        try:
            summary = get(BASE + "/summary", {"event": eid})
            plays = summary.get("plays") or summary.get("playByPlay", {}).get("plays") or []
            record["recent_plays"] = [{
                "period": (p.get("period") or {}).get("number"),
                "clock": p.get("clock", {}).get("displayValue") if isinstance(p.get("clock"), dict) else p.get("clock"),
                "text": p.get("text") or p.get("shortText") or "",
                "scoring_play": bool(p.get("scoringPlay")),
                "home_score": p.get("homeScore"), "away_score": p.get("awayScore"),
                "team": (p.get("team") or {}).get("displayName"),
                "athletes": [a.get("displayName") or a.get("fullName") for a in (p.get("participants") or []) if isinstance(a, dict)]
            } for p in plays[-40:]]
            box = summary.get("boxscore") or {}
            record["team_statistics"] = box.get("teams") or []
            record["player_statistics"] = box.get("players") or []
            record["plays_available"] = bool(plays)
            record["boxscore_available"] = bool(record["team_statistics"] or record["player_statistics"])
        except Exception as exc:
            record["detail_error"] = str(exc)[:300]
            record["recent_plays"] = []
            record["team_statistics"] = []
            record["player_statistics"] = []
            record["plays_available"] = False
            record["boxscore_available"] = False
        observations.append(record)

    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        if not isinstance(old, dict): old = {}
    except Exception:
        old = {}
    games = old.get("games") if isinstance(old.get("games"), dict) else {}
    for rec in observations:
        hist = games.setdefault(rec["event_id"], {"event_id": rec["event_id"], "scheduled_at": rec.get("scheduled_at"), "snapshots": []})
        # Avoid duplicate commits of the same observed game state within one minute.
        if not hist["snapshots"] or hist["snapshots"][-1].get("observed_at", "")[:16] != rec["observed_at"][:16]:
            hist["snapshots"].append(rec)
        hist["scheduled_at"] = rec.get("scheduled_at") or hist.get("scheduled_at")
        hist["latest"] = rec
    # Retain 30 days of snapshots, while preserving all games that have observations.
    cutoff = now.timestamp() - 30*86400
    for eid, hist in list(games.items()):
        snaps = hist.get("snapshots") or []
        hist["snapshots"] = [x for x in snaps if _timestamp(x.get("observed_at")) >= cutoff]
        if not hist["snapshots"]:
            del games[eid]
        else:
            hist["latest"] = hist["snapshots"][-1]
    payload = {"updated_at": now.isoformat(), "monitor": "NBA_IN_GAME_BEHAVIOR_V1",
               "cadence_target_minutes": 5, "source": "ESPN public scoreboard/summary",
               "limitations": ["Only publicly exposed play-by-play and box-score fields are recorded.",
                               "No proprietary tracking, player-tracking coordinates, or inferred intent.",
                               "Missing provider fields are recorded as unavailable, never fabricated."],
               "games": games}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(len(x.get("snapshots") or []) for x in games.values())
    print(json.dumps({"live_or_final_events_observed_this_run": len(observations),
                      "games_in_history": len(games), "snapshots_retained": total,
                      "play_by_play_available": sum(bool(x.get("plays_available")) for x in observations),
                      "boxscore_available": sum(bool(x.get("boxscore_available")) for x in observations),
                      "updated_at": now.isoformat()}, indent=2))

def _timestamp(value):
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
    except Exception: return 0

if __name__ == "__main__":
    main()
