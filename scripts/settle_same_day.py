"""Settle completed Match Signal fixtures from authoritative ESPN data.

Primary lookup uses event summary. If ESPN rejects summary requests (400/403),
settlement falls back to the scoreboard endpoint for the prediction's match
calendar date. Tennis settlement also records total-games O/U and set outcomes
so completed tennis predictions become usable evidence for calibration and model
improvement research. PAPER ONLY.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
FOOTBALL_LEAGUES = {
    "EPL":"eng.1", "La Liga":"esp.1", "Bundesliga":"ger.1", "Serie A":"ita.1",
    "Ligue 1":"fra.1", "Champions League":"uefa.champions", "MLS":"usa.1",
    "Primeira Liga":"por.1", "Eredivisie":"ned.1", "Saudi Pro League":"ksa.1",
}
TENNIS_LEAGUES = {"ATP":"atp", "WTA":"wta"}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/3.4 (+https://github.com/topboyasian-stack/match-signal)"})


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def event_summary(sport, league, event_id):
    r = SESSION.get(f"{ESPN}/{sport}/{league}/summary", params={"event": event_id}, timeout=30)
    r.raise_for_status()
    return r.json()


def scoreboard_event(sport, league, event_id, date):
    r = SESSION.get(f"{ESPN}/{sport}/{league}/scoreboard", params={"dates": date, "limit": 1000}, timeout=30)
    r.raise_for_status()
    for event in r.json().get("events", []):
        if str(event.get("id")) == str(event_id):
            return event
    return None


def extract_competition(payload):
    header = payload.get("header") or {}
    competitions = header.get("competitions") or payload.get("competitions") or []
    return competitions[0] if competitions else None


def brier(probs, actual):
    return round(sum((float(probs.get(k, 0)) - (1 if actual == k else 0)) ** 2 for k in probs), 6)


def prediction_date(prediction):
    try:
        dt = datetime.fromisoformat(str(prediction.get("start_time")).replace("Z", "+00:00"))
        return dt.strftime("%Y%m%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y%m%d")


def tennis_total_games_prediction(prediction):
    return ((prediction.get("analytics") or {}).get("total_games") or {})


def settle(history):
    now = datetime.now(timezone.utc)
    pending = [p for p in history if not p.get("settled") and p.get("event_id")]
    if not pending:
        return 0, {"newly_settled": 0, "tennis_newly_settled": 0, "tennis_ou_settled": 0}

    competitions = {}
    for prediction in pending:
        sport = str(prediction.get("sport") or "").lower()
        label = prediction.get("league")
        league = FOOTBALL_LEAGUES.get(label) if sport == "football" else TENNIS_LEAGUES.get(label)
        if not league:
            continue
        key = f"{sport}:{league}:{prediction.get('event_id')}"
        if key in competitions:
            continue
        provider_sport = "soccer" if sport == "football" else "tennis"
        try:
            summary = event_summary(provider_sport, league, prediction.get("event_id"))
            competition = extract_competition(summary)
            if competition:
                competitions[key] = competition
        except Exception as summary_exc:
            try:
                competition = scoreboard_event(provider_sport, league, prediction.get("event_id"), prediction_date(prediction))
                if competition:
                    competitions[key] = competition
                    print(f"Fallback scoreboard settlement source used for {label} {prediction.get('event_id')} after summary error: {summary_exc}")
                else:
                    print(f"No scoreboard event found for {label} {prediction.get('event_id')} after summary error: {summary_exc}")
            except Exception as fallback_exc:
                print(f"{sport} {label} {prediction.get('event_id')}: summary={summary_exc}; scoreboard={fallback_exc}")

    settled = 0
    tennis_new = 0
    tennis_ou = 0
    for prediction in history:
        if prediction.get("settled"):
            continue
        sport = str(prediction.get("sport") or "").lower()
        label = prediction.get("league")
        league = FOOTBALL_LEAGUES.get(label) if sport == "football" else TENNIS_LEAGUES.get(label)
        if not league:
            continue
        competition = competitions.get(f"{sport}:{league}:{prediction.get('event_id')}")
        if not competition:
            continue
        status_type = (competition.get("status") or {}).get("type") or {}
        if not status_type.get("completed"):
            continue
        competitors = competition.get("competitors") or []
        if len(competitors) < 2:
            continue
        try:
            if sport == "football":
                home = next(c for c in competitors if c.get("homeAway") == "home")
                away = next(c for c in competitors if c.get("homeAway") == "away")
                hs, ass = float(home.get("score", 0)), float(away.get("score", 0))
                actual = "p1" if hs > ass else "p2" if ass > hs else "draw"
                line = float(prediction.get("markets", {}).get("over_under", {}).get("line", 2.5))
                prediction["actual_markets"] = {"over_under": "over" if hs + ass > line else "under", "btts": "yes" if hs > 0 and ass > 0 else "no"}
                prediction["final_score"] = [int(hs) if hs.is_integer() else hs, int(ass) if ass.is_integer() else ass]
            else:
                # Resolve tennis settlement by the corrected public player identities,
                # never by raw ESPN competitor order.
                def tennis_name(competitor):
                    athlete = competitor.get("athlete") or {}
                    return str(athlete.get("displayName") or competitor.get("displayName") or "").strip().lower()
                pred_p1 = str(prediction.get("player_1") or "").strip().lower()
                pred_p2 = str(prediction.get("player_2") or "").strip().lower()
                c1 = next((c for c in competitors[:2] if tennis_name(c) == pred_p1), competitors[0])
                c2 = next((c for c in competitors[:2] if tennis_name(c) == pred_p2), competitors[1])
                lines1 = c1.get("linescores") or []
                lines2 = c2.get("linescores") or []
                s1 = sum(float(x.get("value", 0)) for x in lines1)
                s2 = sum(float(x.get("value", 0)) for x in lines2)
                winner = next((c for c in competitors[:2] if c.get("winner")), None)
                winner_name = tennis_name(winner) if winner else ""
                actual = "p1" if winner_name == pred_p1 else "p2" if winner_name == pred_p2 else ("p1" if c1.get("winner") else "p2")
                total_games = s1 + s2
                ou = tennis_total_games_prediction(prediction)
                line = float(ou.get("line", 22.5))
                actual_ou = "over" if total_games > line else "under" if total_games < line else "push"
                prediction["actual_markets"] = {
                    "total_games": total_games,
                    "total_games_line": line,
                    "total_games_result": actual_ou,
                    "total_games_correct": (ou.get("pick") in {"over", "under"} and actual_ou == ou.get("pick")),
                    "sets": max(len(lines1), len(lines2)),
                    "sets_won_p1": sum(float(x.get("value", 0)) > float(y.get("value", 0)) for x, y in zip(lines1, lines2)),
                    "sets_won_p2": sum(float(y.get("value", 0)) > float(x.get("value", 0)) for x, y in zip(lines1, lines2)),
                }
                prediction["final_score"] = [s1, s2]
                tennis_new += 1
                if ou.get("line") is not None:
                    tennis_ou += 1
            prediction.update({"settled": True, "settled_at": now.isoformat(), "actual": actual, "correct": prediction.get("pick") == actual, "brier": brier(prediction.get("probabilities", {}), actual)})
            settled += 1
            print(f"Settled {prediction.get('sport')} {prediction.get('league')} {prediction.get('event_id')}: {prediction.get('final_score')} ({'WIN' if prediction.get('correct') else 'LOSS'})")
        except (TypeError, ValueError, KeyError, StopIteration) as exc:
            print(f"Could not settle {prediction.get('event_id')}: {exc}")

    return settled, {"newly_settled": settled, "tennis_newly_settled": tennis_new, "tennis_ou_settled": tennis_ou}


def build_tennis_performance(settled):
    rows = [p for p in settled if p.get("sport") == "tennis"]
    ou_rows = [p for p in rows if ((p.get("actual_markets") or {}).get("total_games_result")) in {"over", "under", "push"}]
    ou_decisions = [p for p in ou_rows if ((p.get("analytics") or {}).get("total_games") or {}).get("pick") in {"over", "under"} and ((p.get("actual_markets") or {}).get("total_games_result")) != "push"]
    match_correct = sum(bool(p.get("correct")) for p in rows)
    ou_correct = sum(bool(((p.get("actual_markets") or {}).get("total_games_correct"))) for p in ou_decisions)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "settled_tennis_matches": len(rows),
        "match_wins": match_correct,
        "match_accuracy": round(match_correct / len(rows), 4) if rows else 0.0,
        "ou_settled": len(ou_rows),
        "ou_decisions": len(ou_decisions),
        "ou_correct": ou_correct,
        "ou_accuracy": round(ou_correct / len(ou_decisions), 4) if ou_decisions else 0.0,
        "three_set_rate": round(sum(float(((p.get("analytics") or {}).get("three_sets")) or 0) for p in rows) / len(rows), 4) if rows else 0.0,
        "late_captures_observed": sum(bool(p.get("capture_status") == "LATE_CAPTURE") for p in rows),
        "by_tour": {
            tour: {
                "settled": sum(p.get("league") == tour for p in rows),
                "correct": sum(bool(p.get("correct")) for p in rows if p.get("league") == tour),
                "ou_decisions": sum(p.get("league") == tour for p in ou_decisions),
                "ou_correct": sum(bool(((p.get("actual_markets") or {}).get("total_games_correct"))) for p in ou_decisions if p.get("league") == tour),
            }
            for tour in ("ATP", "WTA")
        },
        "improvement_inputs": [
            "compare match-probability Brier score by tour and signal components",
            "compare tennis O/U accuracy by line and confidence",
            "compare ranking+form vs form-only predictions",
            "measure calibration of match and O/U probabilities before changing model weights",
        ],
        "status": "PAPER_RESEARCH_ONLY",
    }


def main():
    history_path = DATA / "prediction_history.json"
    accuracy_path = DATA / "accuracy.json"
    performance_path = DATA / "tennis_performance.json"
    history = load(history_path, [])
    count, settlement_stats = settle(history)
    settled = [p for p in history if p.get("settled")]
    summary = {
        "settled": len(settled),
        "correct": sum(bool(p.get("correct")) for p in settled),
        "accuracy": round(sum(bool(p.get("correct")) for p in settled) / len(settled), 4) if settled else 0.0,
        "brier_score": round(sum(float(p.get("brier", 0)) for p in settled) / len(settled), 4) if settled else 0.0,
        "markets": {},
    }
    for sport in ("football", "tennis"):
        group = [p for p in settled if p.get("sport") == sport]
        summary[sport] = {
            "settled": len(group),
            "correct": sum(bool(p.get("correct")) for p in group),
            "accuracy": round(sum(bool(p.get("correct")) for p in group) / len(group), 4) if group else 0.0,
        }
    tennis_performance = build_tennis_performance(settled)
    save(history_path, history[-2500:])
    save(accuracy_path, {"updated_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "recent_settled": [p for p in history if p.get("settled")][-50:]})
    save(performance_path, tennis_performance)
    print(f"Settlement complete: {count} newly settled | total settled {summary['settled']} | tennis newly settled {settlement_stats['tennis_newly_settled']} | tennis O/U {settlement_stats['tennis_ou_settled']}")


if __name__ == "__main__":
    main()
