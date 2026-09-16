"""Batch-settle persisted ATP/WTA predictions using ESPN scoreboards with summary fallback.

Uses curl_cffi browser impersonation in CI because ESPN may return HTTP 403 to
plain automation clients. Late-captured predictions are recorded but excluded
from verified performance metrics; only predictions calculated before their
start time are eligible.
PAPER ONLY.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests as http
except ImportError:
    import requests as http

from settle_same_day import brier

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY_PATH = DATA / "prediction_history.json"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
ACCURACY_PATH = DATA / "accuracy.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"
SESSION = http.Session(impersonate="chrome") if hasattr(http, "Session") else http.Session()


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def event_date(row):
    return datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00")).strftime("%Y%m%d")


def get_json(url, params):
    r = SESSION.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def scoreboard(league, date):
    payload = get_json(f"{ESPN}/{league}/scoreboard", {"dates": date, "limit": 1000})
    return {str(e.get("id")): e for e in payload.get("events", [])}


def summary(league, event_id):
    payload = get_json(f"{ESPN}/{league}/summary", {"event": event_id})
    competitions = (payload.get("header") or {}).get("competitions") or payload.get("competitions") or []
    return competitions[0] if competitions else None


def settle_row(row, competition):
    if not competition:
        return False
    status = (competition.get("status") or {}).get("type") or {}
    if not status.get("completed"):
        return False
    competitors = competition.get("competitors") or []
    if len(competitors) < 2:
        return False
    c1, c2 = competitors[0], competitors[1]
    lines1 = c1.get("linescores") or []
    lines2 = c2.get("linescores") or []
    if not lines1 or not lines2:
        return False
    try:
        s1 = sum(float(x.get("value", 0)) for x in lines1)
        s2 = sum(float(x.get("value", 0)) for x in lines2)
        actual = "p1" if c1.get("winner") else "p2"
        ou = ((row.get("analytics") or {}).get("total_games") or {})
        line = float(ou.get("line", 22.5))
        total_games = s1 + s2
        actual_ou = "over" if total_games > line else "under" if total_games < line else "push"
        row["actual_markets"] = {"total_games": total_games, "total_games_line": line, "total_games_result": actual_ou, "total_games_correct": ou.get("pick") in {"over", "under"} and actual_ou == ou.get("pick"), "sets": max(len(lines1), len(lines2)), "sets_won_p1": sum(float(x.get("value", 0)) > float(y.get("value", 0)) for x, y in zip(lines1, lines2)), "sets_won_p2": sum(float(y.get("value", 0)) > float(x.get("value", 0)) for x, y in zip(lines1, lines2))}
        row["final_score"] = [s1, s2]
        row.update({"settled": True, "settled_at": datetime.now(timezone.utc).isoformat(), "actual": actual, "correct": row.get("pick") == actual, "brier": brier(row.get("probabilities", {}), actual), "settlement_source": "ESPN tennis scoreboard/summary via browser client"})
        return True
    except (TypeError, ValueError, KeyError):
        return False


def tennis_performance(rows):
    eligible = [x for x in rows if str(x.get("sport")).lower() == "tennis" and x.get("evaluation_eligible") is True and x.get("settled")]
    ou_rows = [x for x in eligible if ((x.get("actual_markets") or {}).get("total_games_result")) in {"over", "under", "push"}]
    ou_decisions = [x for x in ou_rows if ((x.get("analytics") or {}).get("total_games") or {}).get("pick") in {"over", "under"} and ((x.get("actual_markets") or {}).get("total_games_result")) != "push"]
    correct = sum(bool(x.get("correct")) for x in eligible)
    ou_correct = sum(bool((x.get("actual_markets") or {}).get("total_games_correct")) for x in ou_decisions)
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "settled_tennis_matches": len(eligible), "match_wins": correct, "match_accuracy": round(correct / len(eligible), 4) if eligible else 0.0, "ou_settled": len(ou_rows), "ou_decisions": len(ou_decisions), "ou_correct": ou_correct, "ou_accuracy": round(ou_correct / len(ou_decisions), 4) if ou_decisions else 0.0, "by_tour": {tour: {"settled": sum(x.get("league") == tour for x in eligible), "correct": sum(bool(x.get("correct")) for x in eligible if x.get("league") == tour), "ou_decisions": sum(x.get("league") == tour for x in ou_decisions), "ou_correct": sum(bool((x.get("actual_markets") or {}).get("total_games_correct")) for x in ou_decisions if x.get("league") == tour)} for tour in ("ATP", "WTA")}, "late_captures_excluded": sum(bool(x.get("capture_status") == "LATE_CAPTURE" and x.get("settled")) for x in rows), "status": "PAPER_RESEARCH_ONLY"}


def main():
    history = load(HISTORY_PATH, [])
    archive = load(ARCHIVE_PATH, [])
    rows = {}
    for row in archive + [x for x in history if str(x.get("sport")).lower() == "tennis"]:
        key = f"{row.get('league')}:{row.get('event_id')}"
        if not row.get("settled") or key not in rows:
            rows[key] = row
        elif row.get("settled"):
            rows[key] = row
    pending = [x for x in rows.values() if not x.get("settled") and x.get("event_id") and x.get("start_time")]
    groups = defaultdict(list)
    for row in pending:
        try:
            groups[(row.get("league"), event_date(row))].append(row)
        except Exception:
            continue

    settled_count = 0
    summary_fallbacks = 0
    for (league, date), group in sorted(groups.items()):
        try:
            events = scoreboard(league.lower(), date)
        except Exception as exc:
            print(f"Tennis scoreboard failed {league} {date}: {exc}")
            events = {}
        for row in group:
            competition = events.get(str(row.get("event_id")))
            if competition and settle_row(row, competition):
                settled_count += 1
                continue
            try:
                competition = summary(league.lower(), row.get("event_id"))
                if competition and settle_row(row, competition):
                    settled_count += 1
                    summary_fallbacks += 1
                    print(f"Summary fallback settled {league} {row.get('event_id')}")
            except Exception as exc:
                print(f"Could not settle {league} {row.get('event_id')}: {exc}")

    merged_archive = sorted(rows.values(), key=lambda x: str(x.get("start_time", "")))[-5000:]
    save(ARCHIVE_PATH, merged_archive)
    non_tennis = [x for x in history if str(x.get("sport")).lower() != "tennis"]
    final = sorted(non_tennis + merged_archive, key=lambda x: str(x.get("start_time", "")))[-5000:]
    save(HISTORY_PATH, final)
    settled = [x for x in final if x.get("settled")]
    tennis = [x for x in settled if str(x.get("sport")).lower() == "tennis"]
    save(ACCURACY_PATH, {"updated_at": datetime.now(timezone.utc).isoformat(), "summary": {"settled": len(settled), "correct": sum(bool(x.get("correct")) for x in settled), "accuracy": round(sum(bool(x.get("correct")) for x in settled) / len(settled), 4) if settled else 0.0, "tennis": {"settled": len(tennis), "correct": sum(bool(x.get("correct")) for x in tennis), "accuracy": round(sum(bool(x.get("correct")) for x in tennis) / len(tennis), 4) if tennis else 0.0}}, "recent_settled": settled[-50:]})
    save(DATA / "tennis_performance.json", tennis_performance(final))
    print(f"Batch tennis settlement complete: {settled_count} newly settled | summary fallbacks {summary_fallbacks} | total tennis settled {len(tennis)} | eligible tennis settled {sum(bool(x.get('evaluation_eligible') is True) for x in tennis)}")


if __name__ == "__main__":
    main()
