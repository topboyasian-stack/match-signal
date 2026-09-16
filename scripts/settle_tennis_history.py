"""Batch-settle persisted ATP/WTA predictions using ESPN date scoreboards.

One scoreboard request is made per tour/date instead of one summary request per
match. This is deliberately separate from the general settlement path so a
large historical tennis backlog cannot stall football settlement.
PAPER ONLY.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from settle_same_day import brier, build_tennis_performance

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY_PATH = DATA / "prediction_history.json"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
ACCURACY_PATH = DATA / "accuracy.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/3.4 (+https://github.com/topboyasian-stack/match-signal)"})


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def event_date(row):
    return datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00")).strftime("%Y%m%d")


def scoreboard(league, date):
    r = SESSION.get(f"{ESPN}/{league}/scoreboard", params={"dates": date, "limit": 1000}, timeout=30)
    r.raise_for_status()
    return {str(e.get("id")): e for e in r.json().get("events", [])}


def settle_row(row, event):
    competition = (event.get("competitions") or [{}])[0]
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
        row["actual_markets"] = {
            "total_games": total_games,
            "total_games_line": line,
            "total_games_result": actual_ou,
            "total_games_correct": ou.get("pick") in {"over", "under"} and actual_ou == ou.get("pick"),
            "sets": max(len(lines1), len(lines2)),
            "sets_won_p1": sum(float(x.get("value", 0)) > float(y.get("value", 0)) for x, y in zip(lines1, lines2)),
            "sets_won_p2": sum(float(y.get("value", 0)) > float(x.get("value", 0)) for x, y in zip(lines1, lines2)),
        }
        row["final_score"] = [s1, s2]
        row.update({
            "settled": True,
            "settled_at": datetime.now(timezone.utc).isoformat(),
            "actual": actual,
            "correct": row.get("pick") == actual,
            "brier": brier(row.get("probabilities", {}), actual),
            "settlement_source": "ESPN tennis scoreboard",
        })
        return True
    except (TypeError, ValueError, KeyError):
        return False


def main():
    history = load(HISTORY_PATH, [])
    archive = load(ARCHIVE_PATH, [])
    # Archive is authoritative for tennis; merge any history-only tennis rows.
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
    for (league, date), group in sorted(groups.items()):
        try:
            events = scoreboard(league.lower(), date)
        except Exception as exc:
            print(f"Tennis scoreboard failed {league} {date}: {exc}")
            continue
        for row in group:
            event = events.get(str(row.get("event_id")))
            if event and settle_row(row, event):
                settled_count += 1
                print(f"Settled {league} {row.get('event_id')} {row.get('player_1')} vs {row.get('player_2')}")

    merged_archive = sorted(rows.values(), key=lambda x: str(x.get("start_time", "")))[-5000:]
    save(ARCHIVE_PATH, merged_archive)

    non_tennis = [x for x in history if str(x.get("sport")).lower() != "tennis"]
    final = sorted(non_tennis + merged_archive, key=lambda x: str(x.get("start_time", "")))[-5000:]
    save(HISTORY_PATH, final)

    settled = [x for x in final if x.get("settled")]
    tennis = [x for x in settled if str(x.get("sport")).lower() == "tennis"]
    all_summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "settled": len(settled),
            "correct": sum(bool(x.get("correct")) for x in settled),
            "accuracy": round(sum(bool(x.get("correct")) for x in settled) / len(settled), 4) if settled else 0.0,
            "football": {
                "settled": sum(str(x.get("sport")).lower() == "football" for x in settled),
                "correct": sum(bool(x.get("correct")) for x in settled if str(x.get("sport")).lower() == "football"),
            },
            "tennis": {
                "settled": len(tennis),
                "correct": sum(bool(x.get("correct")) for x in tennis),
                "accuracy": round(sum(bool(x.get("correct")) for x in tennis) / len(tennis), 4) if tennis else 0.0,
            },
        },
        "recent_settled": settled[-50:],
    }
    save(ACCURACY_PATH, all_summary)
    save(DATA / "tennis_performance.json", build_tennis_performance(settled))
    print(f"Batch tennis settlement complete: {settled_count} newly settled | total tennis settled {len(tennis)}")


if __name__ == "__main__":
    main()
