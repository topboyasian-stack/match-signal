#!/usr/bin/env python3
"""Capture timestamped, research-only NBA in-game team/player behavior snapshots."""
import json, math, os, re
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


def _stat_number(value, prefer_denominator=False):
    """Parse ESPN stat values such as 82, 40-82, 40/82, or display strings."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    pair = re.search(r"(-?\d+(?:\.\d+)?)\s*[-/]\s*(-?\d+(?:\.\d+)?)", text)
    if pair:
        return float(pair.group(2) if prefer_denominator else pair.group(1))
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _stat_entries(node):
    """Yield normalized ESPN stat records from either team or category payloads."""
    if isinstance(node, dict):
        if any(k in node for k in ("name", "abbreviation", "shortDisplayName")):
            yield node
        for key, value in node.items():
            if key not in {"team", "athlete", "athletes"}:
                yield from _stat_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _stat_entries(value)


def _team_stat_row(record, side):
    teams = record.get("team_statistics") or []
    if not isinstance(teams, list):
        return None
    target = record.get(side) or {}
    target_id = str(target.get("id") or "")
    target_name = str(target.get("name") or "").strip().lower()
    for row in teams:
        if not isinstance(row, dict):
            continue
        team = row.get("team") or {}
        row_id = str(team.get("id") or row.get("team_id") or "")
        row_name = str(team.get("displayName") or team.get("name") or row.get("name") or "").strip().lower()
        if (target_id and row_id == target_id) or (target_name and row_name == target_name):
            return row
    # ESPN's summary endpoint normally returns home then away. Use order only
    # when the response has exactly two unlabelled team rows.
    if len(teams) == 2 and all(not isinstance(x, dict) or not (x.get("team") or {}).get("id") for x in teams):
        return teams[0 if side == "home" else 1]
    return None


def _team_possessions(record, side):
    row = _team_stat_row(record, side)
    if not row:
        return None
    stats = list(_stat_entries(row.get("statistics") or row.get("stats") or row))
    values = {}
    aliases = {
        "fga": ("fieldgoalsmadefieldgoalsattempted", "fieldgoalsattempted", "fieldgoalattempts", "fga", "fg"),
        "fta": ("freethrowsmadefreethrowsattempted", "freethrowsattempted", "freethrowattempts", "fta", "ft"),
        "orb": ("offensiverebounds", "offensiverebound", "oreb", "orb", "or"),
        "to": ("totalturnovers", "turnovers", "tov", "to"),
    }
    for key, names in aliases.items():
        found = None
        for stat in stats:
            label = " ".join(str(stat.get(k) or "") for k in ("name", "abbreviation", "shortDisplayName", "displayName")).lower()
            normalized = re.sub(r"[^a-z0-9]+", "", label)
            if any(name in normalized for name in names):
                raw = stat.get("displayValue")
                if raw is None:
                    raw = stat.get("value", stat.get("summary"))
                found = _stat_number(raw, prefer_denominator=key in {"fga", "fta"})
                if found is not None:
                    break
        values[key] = found
    if values["fga"] is None or values["fta"] is None or values["to"] is None:
        return None
    orb = values["orb"] if values["orb"] is not None else 0.0
    possessions = values["fga"] + 0.44 * values["fta"] - orb + values["to"]
    if not math.isfinite(possessions) or possessions <= 0:
        return None
    return {"possessions": possessions, **values}


def live_total_projection(record, prediction):
    """Blend the pre-game baseline with live score, clock and ESPN box-score pace/efficiency.

    Live stats are used only when both teams expose the fields needed to estimate
    possessions. Otherwise the estimator explicitly falls back to score/clock pace.
    It never changes the stored pre-game forecast or qualifies a bet.
    """
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
        return {"status": "COLLECTING", "reason": "At least six minutes of game time are required before showing a live estimate."}

    live_total = home_score + away_score
    pace_total = live_total / elapsed * 48
    score_pace = pace_total
    home_stats = _team_possessions(record, "home")
    away_stats = _team_possessions(record, "away")
    stats_used = bool(home_stats and away_stats)
    stat_projection = None
    live_weight = min(0.60, max(0.15, elapsed / 48 * 0.60))
    stats_summary = None

    if stats_used:
        average_possessions = (home_stats["possessions"] + away_stats["possessions"]) / 2
        if average_possessions >= 8:
            live_points_per_possession = live_total / average_possessions
            prior_points_per_possession = pregame / 100.0
            # Shrink volatile early-game efficiency toward the pre-game baseline.
            efficiency_weight = min(0.65, average_possessions / (average_possessions + 25.0))
            adjusted_points_per_possession = (
                prior_points_per_possession * (1 - efficiency_weight)
                + live_points_per_possession * efficiency_weight
            )
            possessions_per_minute = average_possessions / elapsed
            remaining_possessions = possessions_per_minute * (48 - elapsed)
            stat_projection = live_total + adjusted_points_per_possession * remaining_possessions
            stats_summary = {
                "home_possessions": round(home_stats["possessions"], 1),
                "away_possessions": round(away_stats["possessions"], 1),
                "average_possessions": round(average_possessions, 1),
                "live_points_per_possession": round(live_points_per_possession, 3),
                "pregame_points_per_possession_prior": round(prior_points_per_possession, 3),
                "adjusted_points_per_possession": round(adjusted_points_per_possession, 3),
                "efficiency_sample_weight": round(efficiency_weight, 3),
                "projected_remaining_possessions": round(remaining_possessions, 1),
                "fields_used": ["FGA", "FTA", "offensive rebounds", "turnovers", "score", "game clock"],
            }
        else:
            stats_used = False

    if stats_used and stat_projection is not None:
        # Blend the possession/efficiency projection with the independent
        # score-clock pace estimate; neither source can dominate early.
        live_signal = 0.70 * stat_projection + 0.30 * score_pace
        source = "ESPN_LIVE_BOXSCORE_POSSESSIONS_AND_SCORE_PACE"
    else:
        live_signal = score_pace
        source = "ESPN_LIVE_SCORE_CLOCK_PACE_ONLY"

    bounded_live = min(pregame + 18, max(pregame - 18, live_signal))
    blended = pregame * (1 - live_weight) + bounded_live * live_weight
    return {
        "status": "AVAILABLE",
        "pregame_expected_total": round(pregame, 1),
        "live_score_total": round(live_total, 1),
        "elapsed_minutes": round(elapsed, 1),
        "score_pace_total": round(score_pace, 1),
        "stat_adjusted_total": round(stat_projection, 1) if stat_projection is not None else None,
        "live_total_estimate": round(blended, 1),
        "live_weight": round(live_weight, 3),
        "projection_source": source,
        "uses_live_boxscore_stats": bool(stats_used and stat_projection is not None),
        "stats_summary": stats_summary,
        "formula": "Pregame total blended with live score pace and, when available, possession/efficiency estimated from FGA, FTA, offensive rebounds and turnovers; live adjustment capped at +/-18 points.",
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
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
