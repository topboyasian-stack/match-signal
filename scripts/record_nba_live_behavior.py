#!/usr/bin/env python3
"""Capture timestamped, research-only NBA in-game team/player behavior snapshots."""
import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "nba_live_observations.json"
CURRENT_OUT = ROOT / "data" / "nba_live_current.json"
PREDICTIONS = ROOT / "data" / "nba_predictions.json"
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


def live_total_projection(record, prediction):
    """Create a transparent score-pace estimate without altering the pre-game forecast."""
    if not isinstance(prediction, dict):
        return {"status": "NO_PREGAME_BASELINE", "reason": "No saved pre-game NBA projection for this exact ESPN event."}
    try:
        pregame = float(prediction.get("expected_total"))
    except (TypeError, ValueError):
        return {"status": "NO_PREGAME_BASELINE", "reason": "Saved pre-game expected total is unavailable."}
    if not 100 <= pregame <= 320:
        return {"status": "NO_PREGAME_BASELINE", "reason": "Saved pre-game projection is outside the valid NBA total range."}
    try:
        period = int(record.get("period") or 0)
        home_score = float((record.get("home") or {}).get("score"))
        away_score = float((record.get("away") or {}).get("score"))
    except (TypeError, ValueError):
        return {"status": "LIVE_DATA_INCOMPLETE", "reason": "Current period or score is unavailable."}
    if period < 1 or period > 4:
        return {"status": "OVERTIME_CONTEXT_ONLY" if period > 4 else "LIVE_DATA_INCOMPLETE",
                "reason": "Regulation pace projection is withheld during overtime or when period data is missing."}
    clock = str(record.get("clock") or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", clock)
    if not match:
        return {"status": "LIVE_DATA_INCOMPLETE", "reason": "ESPN game clock is unavailable."}
    remaining = int(match.group(1)) + int(match.group(2)) / 60
    if remaining < 0 or remaining > 12:
        return {"status": "LIVE_DATA_INCOMPLETE", "reason": "ESPN game clock is outside the regulation-period range."}
    elapsed = (period - 1) * 12 + (12 - remaining)
    if elapsed < 6:
        return {"status": "COLLECTING", "reason": "At least six minutes of game time are required before showing a pace estimate."}
    live_total = home_score + away_score
    pace_total = live_total / elapsed * 48
    weight = min(0.45, max(0.15, elapsed / 48 * 0.45))
    # Limit the live-pace contribution to +/-18 points until walk-forward
    # evaluation proves a wider adjustment is reliable.
    bounded_pace = min(pregame + 18, max(pregame - 18, pace_total))
    blended = pregame * (1 - weight) + bounded_pace * weight
    return {
        "status": "AVAILABLE",
        "pregame_expected_total": round(pregame, 1),
        "live_score_total": round(live_total, 1),
        "elapsed_minutes": round(elapsed, 1),
        "score_pace_total": round(pace_total, 1),
        "bounded_score_pace_total": round(bounded_pace, 1),
        "live_weight": round(weight, 3),
        "live_total_estimate": round(blended, 1),
        "formula": "Pregame projection blended with current score pace; live contribution capped at +/-18 points.",
        "uses_bookmaker_prices": False,
        "qualification": "PAPER_RESEARCH_ONLY_NOT_BETTING_QUALIFIED",
    }


def main():
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    board = get(BASE + "/scoreboard", {"dates": day})
    events = board.get("events") or []
    observations = []
    try:
        predictions = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
        if not isinstance(predictions, list): predictions = []
    except Exception:
        predictions = []
    predictions_by_event = {str(x.get("event_id")): x for x in predictions if isinstance(x, dict) and x.get("event_id")}
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
    # Publish a small latest-only artifact for the live desk. The 30-day audit
    # history remains separate and is never downloaded by the browser.
    current_games = {}
    for rec in observations:
        if rec.get("game_state") != "live":
            continue
        current = dict(rec)
        current["recent_plays"] = (current.get("recent_plays") or [])[-8:]
        current["live_total_projection"] = live_total_projection(
            rec, predictions_by_event.get(str(rec.get("event_id")))
        )
        current_games[str(rec["event_id"])] = current
    CURRENT_OUT.write_text(json.dumps({
        "updated_at": now.isoformat(),
        "source": "ESPN public scoreboard/summary",
        "mode": "PAPER_RESEARCH_ONLY",
        "games": current_games,
    }, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
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
