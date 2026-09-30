"""Track every generated Odds Builder batch as a paper ticket.

The tracker is deliberately separate from model qualification. It records the exact
batch that was generated, then updates each leg independently from authoritative
settlement ledgers. A single losing leg immediately changes the ticket status to
LOST; the remaining legs continue to show their own settlement state.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILDER = DATA / "odds_builder.json"
TRACKER = DATA / "odds_ticket_tracker.json"
VIRTUAL_HISTORY = DATA / "virtual_lab_history.json"
PREDICTION_HISTORY = DATA / "prediction_history.json"
EXPANSION_HISTORY = DATA / "expansion_prediction_history.json"
SETTLEMENT_ARCHIVE = DATA / "virtual_lab_archive" / "settlements"

MAX_TICKETS = 100


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def norm(v):
    return " ".join(str(v or "").strip().lower().split())


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_virtual_pick(leg):
    pick = norm(leg.get("builder_pick"))
    line = num(leg.get("line"))
    raw = norm(leg.get("pick"))
    if pick not in {"over", "under"}:
        m = re.search(r"\b(over|under)\s+([0-9]+(?:\.[0-9]+)?)\b", raw, re.I)
        if m:
            pick = m.group(1).lower()
            line = line if line is not None else float(m.group(2))
    return pick, line


def fingerprint_batch(batch):
    legs = []
    for leg in batch.get("legs") or []:
        product = norm(leg.get("product") or leg.get("sport"))
        event_id = str(leg.get("event_id") or "")
        market = norm(leg.get("market"))
        pick, line = parse_virtual_pick(leg)
        structured_pick = pick or norm(leg.get("builder_pick") or leg.get("pick"))
        legs.append((product, event_id, market, structured_pick, line))
    legs.sort()
    payload = json.dumps(legs, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


def ticket_id_from_batch(batch):
    return "T-" + fingerprint_batch(batch)


def normalize_fixture(value):
    s = norm(value).replace(" vs ", " v ").replace("vs", " v ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def leg_fixture_key(leg):
    product = norm(leg.get("product") or leg.get("sport"))
    match = normalize_fixture(leg.get("match"))
    return f"{product}|{match}" if product and match else ""


def row_fixture_key(row):
    product = norm(row.get("product") or row.get("sport"))
    p1 = normalize_fixture(row.get("participant_1"))
    p2 = normalize_fixture(row.get("participant_2"))
    if not product or not p1 or not p2:
        return ""
    return f"{product}|{p1} v {p2}"


def close_time(a, b, tolerance_seconds=30 * 60):
    try:
        if not a or not b:
            return False
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        if da.tzinfo is None:
            da = da.replace(tzinfo=timezone.utc)
        if db.tzinfo is None:
            db = db.replace(tzinfo=timezone.utc)
        return abs((da - db).total_seconds()) <= tolerance_seconds
    except (TypeError, ValueError):
        return False


def normalize_selection(value):
    s = norm(value)
    if re.fullmatch(r"o[0-9]+(?:\.[0-9]+)?", s):
        return "over", float(s[1:])
    if re.fullmatch(r"u[0-9]+(?:\.[0-9]+)?", s):
        return "under", float(s[1:])
    m = re.search(r"\b(over|under)\s*([0-9]+(?:\.[0-9]+)?)", s)
    if m:
        return m.group(1), float(m.group(2))
    return s, None


def flatten_history():
    rows = []
    for path in (VIRTUAL_HISTORY, PREDICTION_HISTORY, EXPANSION_HISTORY):
        raw = load(path, [])
        if isinstance(raw, list):
            rows.extend(x for x in raw if isinstance(x, dict))

    # Virtual Lab history is rolling; the append-only settlement archive is the
    # durable source and must also be read so older Builder tickets can settle.
    if SETTLEMENT_ARCHIVE.exists():
        for path in sorted(SETTLEMENT_ARCHIVE.glob("*.jsonl")):
            try:
                for raw_line in path.read_text(encoding="utf-8").splitlines():
                    if not raw_line.strip():
                        continue
                    row = json.loads(raw_line)
                    if isinstance(row, dict):
                        rows.append(row)
            except (OSError, json.JSONDecodeError):
                continue

    merged = {}
    for row in rows:
        key = str(row.get("record_id") or row.get("trace_id") or "")
        if not key:
            key = "|".join([
                str(row.get("event_id") or ""),
                str(row.get("market") or ""),
                str(row.get("line") if row.get("line") is not None else ""),
                str(row.get("selection") or ""),
            ])
        if not key or key == "|||":
            key = f"__row__{len(merged)}"
        merged[key] = row
    return list(merged.values())


def _score_pair(value):
    if isinstance(value, dict):
        pairs = [
            (value.get("home"), value.get("away")),
            (value.get("homeScore"), value.get("awayScore")),
            (value.get("home_score"), value.get("away_score")),
            (value.get("homeGoals"), value.get("awayGoals")),
            (value.get("homeGoalsCount"), value.get("awayGoalsCount")),
        ]
        for a, b in pairs:
            aa, bb = num(a), num(b)
            if aa is not None and bb is not None:
                return aa, bb
    return None


def fixture_parts(value):
    s = normalize_fixture(value)
    if " v " in s:
        left, right = s.split(" v ", 1)
        return left.strip(), right.strip()
    return "", ""


def fixture_side_key(value):
    s = re.sub(r"[^a-z0-9]+", "", norm(value))
    if not s:
        return ""
    return s if len(s) <= 4 else s[:3]


def event_start_time(event):
    for key in ("start_time_ms", "startTime", "estimateStartTime"):
        value = num(event.get(key)) if isinstance(event, dict) else None
        if value is not None:
            if 0 < value < 100000000000:
                value *= 1000
            return value
    raw = event.get("start_time") if isinstance(event, dict) else None
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp() * 1000
        except (TypeError, ValueError):
            pass
    return None


def legacy_fixture_matches(leg, event, tolerance_seconds=90 * 60):
    leg_home, leg_away = fixture_parts(leg.get("match"))
    event_home = event.get("team_1") or event.get("homeTeamName") or event.get("homeTeam") or event.get("participant_1")
    event_away = event.get("team_2") or event.get("awayTeamName") or event.get("awayTeam") or event.get("participant_2")
    if not leg_home or not leg_away or not event_home or not event_away:
        return False
    exact = normalize_fixture(f"{leg_home} v {leg_away}") == normalize_fixture(f"{event_home} v {event_away}")
    abbreviated = fixture_side_key(leg_home) == fixture_side_key(event_home) and fixture_side_key(leg_away) == fixture_side_key(event_away)
    if not (exact or abbreviated):
        return False
    event_ms = event_start_time(event)
    if event_ms is None:
        return True
    return close_time(leg.get("start_time"), datetime.fromtimestamp(event_ms / 1000, timezone.utc).isoformat(), tolerance_seconds=tolerance_seconds)


def result_event_score(event):
    if not isinstance(event, dict):
        return None
    for key in ("setScore", "score", "finalScore"):
        value = event.get(key)
        hit = _score_pair(value)
        if hit:
            return hit
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            aa, bb = num(value[0]), num(value[1])
            if aa is not None and bb is not None:
                return aa, bb
    direct = _score_pair(event)
    if direct:
        return direct
    for key in ("result", "resultScore"):
        nested = event.get(key)
        hit = _score_pair(nested)
        if hit:
            return hit
    return None


def backfill_vfootball_results(tickets, now_iso_value):
    pending = []
    wanted_ids = set()
    for ticket in tickets:
        for leg in ticket.get("legs") or []:
            if str(leg.get("status") or "PENDING").upper() != "PENDING":
                continue
            if norm(leg.get("product") or leg.get("sport")) != "vfootball" or not leg.get("event_id"):
                continue
            try:
                start = datetime.fromisoformat(str(leg.get("start_time") or "").replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if (datetime.now(timezone.utc) - start).total_seconds() < 10 * 60:
                continue
            pending.append(leg)
            wanted_ids.add(str(leg.get("event_id")))
    if not pending:
        return []

    starts = []
    for leg in pending:
        try:
            dt = datetime.fromisoformat(str(leg.get("start_time") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            starts.append(int(dt.timestamp() * 1000))
        except (TypeError, ValueError):
            pass
    start_ms = min(starts) - 6 * 3600000 if starts else int(datetime.now(timezone.utc).timestamp() * 1000) - 86400000
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        query = urllib.parse.urlencode({
            "source": "vfootball", "pageSize": 100, "pageNum": 1,
            "startTime": start_ms, "endTime": end_ms,
        })
        request = urllib.request.Request(
            "https://match-signal.pages.dev/api/sportybet-virtual-results?" + query,
            headers={"Accept": "application/json", "User-Agent": "MatchSignal-OddsTicketTracker/1.0"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        events = payload.get("events") if isinstance(payload, dict) else []
        events = events if isinstance(events, list) else []
        print("vFootball result backfill source:", len(events), "events; exact IDs wanted:", len(wanted_ids))
        print("vFootball pending fixture samples:", json.dumps([{"event_id":x.get("event_id"),"match":x.get("match"),"start_time":x.get("start_time")} for x in pending[:10]], ensure_ascii=False))
        print("vFootball result event samples:", json.dumps([{"event_id":e.get("eventId") or e.get("event_id"),"homeTeamName":e.get("homeTeamName"),"awayTeamName":e.get("awayTeamName"),"team_1":e.get("team_1"),"team_2":e.get("team_2"),"participant_1":e.get("participant_1"),"participant_2":e.get("participant_2"),"estimateStartTime":e.get("estimateStartTime"),"start_time":e.get("start_time"),"matchStatus":e.get("matchStatus")} for e in events[:5]], ensure_ascii=False))
    except Exception as exc:
        print("WARNING: vFootball result backfill failed:", exc)
        return []

    out = []
    matched_ids = set()
    matched_fixtures = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("eventId") or event.get("event_id") or "").strip()
        score = result_event_score(event)
        if not event_id or score is None:
            continue
        for leg in pending:
            same_id = event_id in wanted_ids and event_id == str(leg.get("event_id"))
            same_fixture = legacy_fixture_matches(leg, event)
            if not (same_id or same_fixture):
                continue
            pick, line = parse_virtual_pick(leg)
            if pick not in {"over", "under"} or line is None:
                continue
            total = score[0] + score[1]
            line_text = str(int(line) if float(line).is_integer() else line)
            actual = "O" + line_text if total > line else "U" + line_text if total < line else "PUSH"
            selected = "O" + line_text if pick == "over" else "U" + line_text
            mode = "event_id" if same_id else "fixture"
            out.append({
                "product": "vfootball", "event_id": event_id,
                "match": str(leg.get("match") or ""), "start_time": leg.get("start_time"),
                "market": "ou", "line": line, "selection": selected,
                "result": actual, "win": None if actual == "PUSH" else actual == selected,
                "score": f"{int(score[0])}:{int(score[1])}", "final_score": [score[0], score[1]],
                "settled_at": now_iso_value,
                "settlement_source": "SportyBet NG eventResultList via Match Signal vFootball fixture backfill",
                "record_id": f"{event_id}|ou|{line}|{selected}", "trace_id": f"{event_id}|ou|{line}|{selected}",
                "backfill_match_mode": mode,
            })
            if same_id: matched_ids.add(event_id)
            else: matched_fixtures.add(str(leg.get("match") or ""))
    print("vFootball result backfill matches:", len(out), "legs; exact IDs:", len(matched_ids), "fixture/time:", len(matched_fixtures))
    return out


def settle_virtual_leg(leg, rows):
    event_id = str(leg.get("event_id") or "")
    wanted_pick, wanted_line = parse_virtual_pick(leg)
    if wanted_pick not in {"over", "under"} or wanted_line is None:
        return None

    wanted_fixture = leg_fixture_key(leg)
    wanted_product = norm(leg.get("product") or leg.get("sport"))
    candidates = []
    for row in rows:
        if str(row.get("market") or "").lower() != "ou":
            continue
        row_product = norm(row.get("product") or row.get("sport"))
        if wanted_product and row_product != wanted_product:
            continue
        exact_id = bool(event_id and str(row.get("event_id") or "") == event_id)
        fallback_fixture = bool(
            not exact_id and wanted_fixture and row_fixture_key(row) == wanted_fixture
            and close_time(leg.get("start_time"), row.get("timestamp") or row.get("start_time"))
        )
        if exact_id or fallback_fixture:
            candidates.append(row)

    matches = []
    for row in candidates:
        row_line = num(row.get("line"))
        if row_line is None or abs(row_line - wanted_line) > 1e-9:
            continue
        row_pick, parsed_line = normalize_selection(row.get("selection"))
        if row_pick == wanted_pick and (parsed_line is None or abs(parsed_line - wanted_line) <= 1e-9):
            matches.append(row)

    for row in reversed(matches):
        win = row.get("win")
        actual = str(row.get("actual_result") or row.get("result") or "").upper()
        if win is True or win is False:
            return {
                "status": "WON" if win else "LOST",
                "correct": bool(win),
                "settled_at": row.get("settled_at"),
                "result": actual or ("WON" if win else "LOST"),
                "final_score": row.get("final_score") or row.get("score"),
            }
        if actual == "PUSH" or (win is None and actual.startswith("P")):
            return {
                "status": "VOID",
                "correct": None,
                "settled_at": row.get("settled_at"),
                "result": "PUSH",
                "final_score": row.get("final_score") or row.get("score"),
            }
    return None


def settle_core_leg(leg, rows):
    event_id = str(leg.get("event_id") or "")
    sport = norm(leg.get("sport"))
    market = norm(leg.get("market"))
    if not event_id:
        return None

    for row in reversed(rows):
        if str(row.get("event_id") or "") != event_id:
            continue
        rsport = norm(row.get("sport"))
        if rsport and rsport != sport:
            continue

        if sport == "tennis" and market in {"total_games", "total games"}:
            total = ((row.get("analytics") or {}).get("total_games") or {})
            pick = norm(total.get("pick"))
            line = num(total.get("line"))
            target = norm(leg.get("pick"))
            m = re.search(r"\b(over|under)\s+([0-9]+(?:\.[0-9]+)?)\b", target)
            wanted_pick = m.group(1) if m else target
            wanted_line = float(m.group(2)) if m else None
            if pick != wanted_pick:
                continue
            if wanted_line is not None and line is not None and abs(line - wanted_line) > 1e-9:
                continue
            actual = (row.get("actual_markets") or {}).get("total_games_result")
            correct = (row.get("actual_markets") or {}).get("total_games_correct")
            if isinstance(correct, bool):
                return {
                    "status": "WON" if correct else "LOST",
                    "correct": correct,
                    "settled_at": row.get("settled_at"),
                    "result": actual or ("WON" if correct else "LOST"),
                    "final_score": row.get("final_score"),
                }

        elif market in {"winner", "1x2"}:
            pick = norm(leg.get("builder_pick") or leg.get("pick"))
            row_pick = norm(row.get("pick"))
            if pick and row_pick and pick != row_pick:
                continue
            correct = row.get("correct")
            if isinstance(correct, bool):
                return {
                    "status": "WON" if correct else "LOST",
                    "correct": correct,
                    "settled_at": row.get("settled_at"),
                    "result": row.get("actual") or ("WON" if correct else "LOST"),
                    "final_score": row.get("final_score"),
                }
    return None


def settle_leg(leg, rows):
    sport = norm(leg.get("sport"))
    if sport == "virtual" or leg.get("product"):
        return settle_virtual_leg(leg, rows)
    return settle_core_leg(leg, rows)


def ticket_status(legs):
    statuses = [str(x.get("status") or "PENDING") for x in legs]
    if "LOST" in statuses:
        # A single settled loss is enough to close the ticket as a loss,
        # even while other legs remain live/pending.
        return "LOST"
    active = [s for s in statuses if s not in {"WON", "VOID"}]
    if active:
        return "PENDING"
    return "WON"


def refresh_ticket(ticket, rows, now):
    changed = False
    for leg in ticket.get("legs") or []:
        if not leg.get("fixture_key"):
            fixture_key = leg_fixture_key(leg)
            if fixture_key:
                leg["fixture_key"] = fixture_key
                changed = True
        if leg.get("status") not in {"PENDING", "WON", "LOST", "VOID"}:
            leg["status"] = "PENDING"
            changed = True
        settlement = settle_leg(leg, rows)
        if settlement:
            for key in ("status", "correct", "settled_at", "result", "final_score"):
                value = settlement.get(key)
                if leg.get(key) != value:
                    leg[key] = value
                    changed = True
    old_status = ticket.get("status")
    new_status = ticket_status(ticket.get("legs") or [])
    if old_status != new_status:
        ticket["status"] = new_status
        changed = True
        if new_status == "LOST":
            ticket["lost_at"] = ticket.get("lost_at") or now
        elif new_status == "WON":
            ticket["won_at"] = ticket.get("won_at") or now
    counts = {
        "won": sum(str(x.get("status")) == "WON" for x in ticket.get("legs") or []),
        "lost": sum(str(x.get("status")) == "LOST" for x in ticket.get("legs") or []),
        "void": sum(str(x.get("status")) == "VOID" for x in ticket.get("legs") or []),
        "pending": sum(str(x.get("status") or "PENDING") == "PENDING" for x in ticket.get("legs") or []),
    }
    settled_times = [
        str(x.get("settled_at"))
        for x in ticket.get("legs") or []
        if x.get("settled_at")
    ]
    values = sorted(settled_times)
    latest_settled = values[-1] if values else None
    settled_count = counts["won"] + counts["lost"] + counts["void"]
    if ticket.get("leg_counts") != counts:
        ticket["leg_counts"] = counts
        changed = True
    if ticket.get("settled_leg_count") != settled_count:
        ticket["settled_leg_count"] = settled_count
        changed = True
    if ticket.get("pending_leg_count") != counts["pending"]:
        ticket["pending_leg_count"] = counts["pending"]
        changed = True
    if ticket.get("last_settled_at") != latest_settled:
        ticket["last_settled_at"] = latest_settled
        changed = True
    if ticket.get("version", 1) < 2:
        ticket["version"] = 2
        ticket["snapshot_fingerprint"] = ticket.get("snapshot_fingerprint") or ticket_id_from_batch(ticket)[2:]
        changed = True
    return changed


def make_ticket(batch, now):
    legs = []
    for leg in batch.get("legs") or []:
        copied = dict(leg)
        copied["fixture_key"] = copied.get("fixture_key") or leg_fixture_key(copied)
        copied["status"] = "PENDING"
        copied.setdefault("correct", None)
        copied.setdefault("settled_at", None)
        copied.setdefault("result", None)
        copied.setdefault("final_score", None)
        legs.append(copied)

    fingerprint = fingerprint_batch(batch)
    return {
        "version": 2,
        "ticket_id": ticket_id_from_batch(batch),
        "snapshot_fingerprint": fingerprint,
        "batch_id": batch.get("batch_id"),
        "created_at": now,
        "last_seen_at": now,
        "last_settled_at": None,
        "status": "PENDING",
        "combined_odds": batch.get("combined_odds"),
        "combined_model_rating": batch.get("combined_model_rating"),
        "combined_model_probability": batch.get("combined_model_probability"),
        "products": batch.get("products") or [],
        "primary_lane": batch.get("primary_lane"),
        "leg_count": len(legs),
        "settled_leg_count": 0,
        "pending_leg_count": len(legs),
        "legs": legs,
        "leg_counts": {"won": 0, "lost": 0, "void": 0, "pending": len(legs)},
        "paper_only": True,
        "real_money_execution": False,
    }


def summary(tickets):
    return {
        "tracked_tickets": len(tickets),
        "pending": sum(x.get("status") == "PENDING" for x in tickets),
        "won": sum(x.get("status") == "WON" for x in tickets),
        "lost": sum(x.get("status") == "LOST" for x in tickets),
        "active_with_loss": sum(x.get("status") == "LOST" and x.get("leg_counts", {}).get("pending", 0) > 0 for x in tickets),
        "legs_won": sum(x.get("leg_counts", {}).get("won", 0) for x in tickets),
        "legs_lost": sum(x.get("leg_counts", {}).get("lost", 0) for x in tickets),
        "legs_pending": sum(x.get("leg_counts", {}).get("pending", 0) for x in tickets),
        "settled_tickets": sum(x.get("status") in {"WON", "LOST"} for x in tickets),
    }


def main():
    now = iso_now()
    builder = load(BUILDER, {})
    batches = builder.get("batches") if isinstance(builder, dict) else []
    batches = batches if isinstance(batches, list) else []

    existing = load(TRACKER, {})
    tickets = existing.get("tickets") if isinstance(existing, dict) else []
    tickets = tickets if isinstance(tickets, list) else []

    by_id = {str(t.get("ticket_id")): t for t in tickets if isinstance(t, dict) and t.get("ticket_id")}
    changed = False

    # Register every exact batch once. A refreshed batch with different legs is a
    # new paper ticket, while an identical regenerated batch remains the same ticket.
    for batch in batches:
        if not isinstance(batch, dict) or not batch.get("legs"):
            continue
        tid = ticket_id_from_batch(batch)
        if tid in by_id:
            t = by_id[tid]
            if t.get("batch_id") != batch.get("batch_id"):
                t["batch_id"] = batch.get("batch_id")
                changed = True
            continue
        ticket = make_ticket(batch, now)
        tickets.append(ticket)
        by_id[tid] = ticket
        changed = True

    rows = flatten_history()
    backfilled = backfill_vfootball_results(tickets, now)
    if backfilled:
        rows.extend(backfilled)
        print('vFootball result backfill:', len(backfilled), 'legacy leg(s) recovered')
    # Re-evaluate all unresolved tickets. A ticket marked LOST stays LOST, but its
    # individual legs continue settling so the user can see exactly what happened.
    for ticket in tickets:
        changed = refresh_ticket(ticket, rows, now) or changed

    # Keep a useful rolling paper ledger. Settled tickets are trimmed first.
    tickets.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    if len(tickets) > MAX_TICKETS:
        settled = [x for x in tickets if x.get("status") in {"WON", "LOST"}]
        pending = [x for x in tickets if x.get("status") not in {"WON", "LOST"}]
        tickets = pending + settled[: max(0, MAX_TICKETS - len(pending))]
        tickets.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        changed = True

    output = {
        "version": 2,
        "updated_at": now if changed or not TRACKER.exists() else existing.get("updated_at"),
        "mode": "PAPER_ONLY",
        "summary": summary(tickets),
        "tickets": tickets,
    }

    old_norm = json.dumps(existing, sort_keys=True, ensure_ascii=False)
    new_norm = json.dumps(output, sort_keys=True, ensure_ascii=False)
    if old_norm != new_norm:
        TRACKER.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "changed": old_norm != new_norm,
        "summary": output["summary"],
        "new_ticket_count": sum(1 for t in tickets if t.get("created_at") == now),
    }, indent=2))


if __name__ == "__main__":
    main()
