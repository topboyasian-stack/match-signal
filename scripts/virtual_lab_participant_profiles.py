"""Build time-safe participant behavior and H2H profiles for the standalone Virtual Lab.

Participant identity is product-scoped. For eFootball it is the stable
parenthetical participant token, while the club/team label is retained only as
context. All internal features are derived from automatic settled SportyBet
history; user-reported tickets and external H2H sources are excluded.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "virtual_lab_history.json"
OUTPUT = DATA / "virtual_lab_participant_profiles.json"
H2H_OUTPUT = DATA / "virtual_lab_participant_h2h.json"

LINES = (1.5, 2.5, 3.5, 4.5, 5.5, 7.5)
MIN_PROFILE_N = 3
SUPPORTED_PRODUCTS = {"efootball_gt", "efootball_adriatic", "vfootball", "zoom"}


def participant_identity(product: str, value: str) -> str:
    s = " ".join(str(value or "").split()).strip()
    if not s:
        return ""
    product = str(product or "")
    if product.startswith("efootball"):
        match = re.search(r"\(([^()]+)\)\s*$", s)
        return match.group(1).strip() if match and match.group(1).strip() else ""
    if product in {"vfootball", "zoom"}:
        return s
    return ""


def participant_key(product: str, value: str) -> str:
    identity = participant_identity(product, value)
    return f"{product}|{identity.casefold()}" if identity else ""


def team_label(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    match = re.search(r"\(([^()]+)\)\s*$", text)
    return match.group(1).strip() if match else ""


def timestamp(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return float("inf")


def parse_score(value):
    text = str(value or "").replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)[:\-](\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except (TypeError, ValueError):
        return None


def event_total(event) -> float | None:
    score = event.get("score_home"), event.get("score_away")
    if score[0] is None or score[1] is None:
        return None
    return float(score[0]) + float(score[1])


def event_result_for(event, identity_key: str, side: str) -> str:
    home = float(event["score_home"])
    away = float(event["score_away"])
    if home == away:
        return "D"
    participant_home = participant_key(event["product"], event["home_raw"])
    participant_away = participant_key(event["product"], event["away_raw"])
    if side == "home" or participant_home == identity_key:
        return "W" if home > away else "L"
    if side == "away" or participant_away == identity_key:
        return "W" if away > home else "L"
    return "D"


def event_groups(history):
    groups = {}
    for row in history:
        if not isinstance(row, dict) or row.get("market") != "ou" or row.get("win") is None:
            continue
        product = str(row.get("product") or "")
        if product not in SUPPORTED_PRODUCTS:
            continue
        event_id = str(row.get("event_id") or "")
        stamp = str(row.get("timestamp") or "")
        if not event_id or not stamp:
            continue
        score = parse_score(row.get("score"))
        if score is None:
            continue
        key = f"{product}|{event_id}|{stamp}"
        group = groups.setdefault(
            key,
            {
                "event_key": key,
                "product": product,
                "timestamp": stamp,
                "competition": str(row.get("competition") or "Unknown"),
                "home_raw": str(row.get("participant_1") or ""),
                "away_raw": str(row.get("participant_2") or ""),
                "score_home": score[0],
                "score_away": score[1],
                "market_rows": [],
            },
        )
        group["market_rows"].append(row)
    return sorted(groups.values(), key=lambda e: timestamp(e["timestamp"]))


def line_stats(events):
    out = {}
    for line in LINES:
        decisive = [e for e in events if event_total(e) != line]
        over = sum(event_total(e) > line for e in decisive)
        out[str(line)] = {
            "n": len(decisive),
            "over": over,
            "over_rate": over / len(decisive) if decisive else None,
            "recent_n": 0,
            "recent_over_rate": None,
        }
    recent = events[-5:]
    for line in LINES:
        decisive = [e for e in recent if event_total(e) != line]
        over = sum(event_total(e) > line for e in decisive)
        out[str(line)]["recent_n"] = len(decisive)
        out[str(line)]["recent_over_rate"] = over / len(decisive) if decisive else None
    return out


def build_participant_profiles(events):
    groups = defaultdict(list)
    for event in events:
        for side, raw in (("home", event["home_raw"]), ("away", event["away_raw"])):
            identity = participant_identity(event["product"], raw)
            if not identity:
                continue
            groups[(event["product"], identity.casefold())].append((event, side, identity))

    profiles = []
    for (product, _), rows in groups.items():
        rows.sort(key=lambda x: timestamp(x[0]["timestamp"]))
        identity = rows[0][2]
        identity_key = f"{product}|{identity.casefold()}"
        wins = draws = losses = 0
        gf = ga = 0.0
        win_margins = []
        teams = defaultdict(int)
        decisions = []

        for event, side, _ in rows:
            home, away = float(event["score_home"]), float(event["score_away"])
            if side == "home":
                scored, conceded = home, away
            else:
                scored, conceded = away, home
            result = "W" if scored > conceded else "L" if scored < conceded else "D"
            if result == "W":
                wins += 1
                win_margins.append(scored - conceded)
            elif result == "L":
                losses += 1
            else:
                draws += 1
            gf += scored
            ga += conceded
            team = team_label(event["home_raw"] if side == "home" else event["away_raw"])
            if team:
                teams[team] += 1
            decisions.append({
                "timestamp": event["timestamp"],
                "competition": event["competition"],
                "result": result,
                "goals_for": scored,
                "goals_against": conceded,
                "margin": scored - conceded,
                "team": team,
                "opponent": (
                    participant_identity(product, event["away_raw"] if side == "home" else event["home_raw"])
                    or (event["away_raw"] if side == "home" else event["home_raw"])
                ),
            })

        recent = list(reversed(decisions[-10:]))
        unbeaten_streak = 0
        for item in recent:
            if item["result"] == "L":
                break
            unbeaten_streak += 1

        ls = line_stats([r[0] for r in rows])
        total_n = len(rows)
        avg_total = (
            sum(event_total(r[0]) for r in rows if event_total(r[0]) is not None) / total_n
            if total_n
            else None
        )
        line_hot = None
        candidates = []
        for line, stats in ls.items():
            if stats["n"] < MIN_PROFILE_N:
                continue
            overall = stats["over_rate"]
            recent_rate = stats["recent_over_rate"]
            if overall is None or recent_rate is None:
                continue
            direction = "OVER" if overall >= 0.67 else "UNDER" if overall <= 0.33 else None
            if direction is None:
                continue
            recent_ok = recent_rate >= 0.60 if direction == "OVER" else recent_rate <= 0.40
            if not recent_ok:
                continue
            strength = abs(overall - 0.5) * 0.65 + abs(recent_rate - 0.5) * 0.35
            candidates.append((strength, stats["n"], float(line), direction))
        if candidates:
            strength, basis_n, line, direction = max(candidates)
            line_hot = {"line": line, "direction": direction, "strength": strength, "basis_n": basis_n}

        profiles.append(
            {
                "participant_key": identity_key,
                "product": product,
                "participant": identity,
                "matches": total_n,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "win_rate": wins / total_n if total_n else None,
                "goals_for": gf,
                "goals_against": ga,
                "avg_goals_for": gf / total_n if total_n else None,
                "avg_goals_against": ga / total_n if total_n else None,
                "avg_total_goals": avg_total,
                "current_unbeaten_streak": unbeaten_streak,
                "avg_win_margin": sum(win_margins) / len(win_margins) if win_margins else None,
                "recent_form": recent,
                "last5": recent[:5],
                "last10": recent[:10],
                "team_usage": dict(sorted(teams.items(), key=lambda kv: (-kv[1], kv[0].casefold()))),
                "lines": ls,
                "hot": line_hot,
            }
        )

    profiles.sort(
        key=lambda x: (
            x["product"],
            0 if x["hot"] else 1,
            -(x["hot"]["strength"] if x["hot"] else 0),
            -x["matches"],
            x["participant"].casefold(),
        )
    )
    return profiles


def build_h2h(events):
    pairs = defaultdict(list)
    for event in events:
        a = participant_identity(event["product"], event["home_raw"])
        b = participant_identity(event["product"], event["away_raw"])
        if not a or not b or a.casefold() == b.casefold():
            continue
        pa = participant_key(event["product"], a)
        pb = participant_key(event["product"], b)
        key_a, key_b = sorted((pa, pb))
        pairs[(event["product"], key_a, key_b)].append((event, a, b))

    output = []
    for (product, key_a, key_b), rows in pairs.items():
        rows.sort(key=lambda x: timestamp(x[0]["timestamp"]))
        observed = rows[0]
        observed_names = sorted({
            str(observed[1] or "").strip(),
            str(observed[2] or "").strip(),
        }, key=lambda value: value.casefold())
        a = observed_names[0] if observed_names else ""
        b = observed_names[1] if len(observed_names) > 1 else ""
        wins_a = wins_b = draws = btts = 0
        goals_a = goals_b = 0.0
        recent = []
        line_data = {}
        for event, home_name, away_name in rows:
            home_id = participant_key(product, home_name)
            away_id = participant_key(product, away_name)
            home, away = float(event["score_home"]), float(event["score_away"])
            if home_id == key_a:
                ga, gb = home, away
            else:
                ga, gb = away, home
            if ga > gb:
                wins_a += 1
            elif gb > ga:
                wins_b += 1
            else:
                draws += 1
            goals_a += ga
            goals_b += gb
            if ga > 0 and gb > 0:
                btts += 1
            total = ga + gb
            for line in LINES:
                if total == line:
                    continue
                bucket = line_data.setdefault(str(line), {"n": 0, "over": 0})
                bucket["n"] += 1
                if total > line:
                    bucket["over"] += 1
            recent.append(
                {
                    "timestamp": event["timestamp"],
                    "competition": event["competition"],
                    "participant_a": a,
                    "participant_b": b,
                    "team_a": (
                        team_label(event["home_raw"]) if home_id == key_a else team_label(event["away_raw"])
                    ),
                    "team_b": (
                        team_label(event["away_raw"]) if home_id == key_a else team_label(event["home_raw"])
                    ),
                    "score": f"{int(ga)}:{int(gb)}",
                }
            )

        for bucket in line_data.values():
            bucket["over_rate"] = bucket["over"] / bucket["n"] if bucket["n"] else None

        total_n = len(rows)
        output.append(
            {
                "pair_key": f"{product}|{a}|{b}",
                "product": product,
                "participant_a": a,
                "participant_b": b,
                "matches": total_n,
                "a_wins": wins_a,
                "draws": draws,
                "b_wins": wins_b,
                "goals_a": goals_a,
                "goals_b": goals_b,
                "avg_goals_a": goals_a / total_n if total_n else None,
                "avg_goals_b": goals_b / total_n if total_n else None,
                "avg_total_goals": (goals_a + goals_b) / total_n if total_n else None,
                "btts_rate": btts / total_n if total_n else None,
                "lines": line_data,
                "last5": list(reversed(recent[-5:])),
                "last10": list(reversed(recent[-10:])),
            }
        )
    output.sort(key=lambda x: (-x["matches"], x["pair_key"].casefold()))
    return output


def main():
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    if not isinstance(history, list):
        history = []
    events = event_groups(history)
    profiles = build_participant_profiles(events)
    h2h = build_h2h(events)

    OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_contract": "automatic SportyBet settled O/U history only; user-reported tickets and external H2H excluded",
                "product_scope": sorted(SUPPORTED_PRODUCTS),
                "event_count": len(events),
                "participant_count": len(profiles),
                "hot_count": sum(1 for p in profiles if p["hot"]),
                "minimum_profile_history": MIN_PROFILE_N,
                "profiles": profiles,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    H2H_OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_contract": "automatic SportyBet settled O/U history only; participant identity is product-scoped",
                "product_scope": sorted(SUPPORTED_PRODUCTS),
                "event_count": len(events),
                "pair_count": len(h2h),
                "pairs": h2h,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event_count": len(events),
                "participant_count": len(profiles),
                "pair_count": len(h2h),
                "hot_count": sum(1 for p in profiles if p["hot"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
