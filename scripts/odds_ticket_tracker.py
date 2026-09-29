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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BUILDER = DATA / "odds_builder.json"
TRACKER = DATA / "odds_ticket_tracker.json"
VIRTUAL_HISTORY = DATA / "virtual_lab_history.json"
PREDICTION_HISTORY = DATA / "prediction_history.json"
EXPANSION_HISTORY = DATA / "expansion_prediction_history.json"

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
    return rows


def settle_virtual_leg(leg, rows):
    event_id = str(leg.get("event_id") or "")
    wanted_pick, wanted_line = parse_virtual_pick(leg)
    if not event_id or wanted_pick not in {"over", "under"} or wanted_line is None:
        return None

    matches = []
    for row in rows:
        if str(row.get("event_id") or "") != event_id:
            continue
        if str(row.get("market") or "").lower() != "ou":
            continue
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
                "final_score": row.get("score"),
            }
        if actual == "PUSH" or win is None and actual.startswith("P"):
            return {
                "status": "VOID",
                "correct": None,
                "settled_at": row.get("settled_at"),
                "result": "PUSH",
                "final_score": row.get("score"),
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
    if ticket.get("leg_counts") != counts:
        ticket["leg_counts"] = counts
        changed = True
    if ticket.get("last_evaluated_at") != now:
        ticket["last_evaluated_at"] = now
        # Timestamp is operational metadata; do not count it as a file change.
    return changed


def make_ticket(batch, now):
    legs = []
    for leg in batch.get("legs") or []:
        copied = dict(leg)
        copied.setdefault("status", "PENDING")
        copied.setdefault("correct", None)
        copied.setdefault("settled_at", None)
        copied.setdefault("result", None)
        copied.setdefault("final_score", None)
        legs.append(copied)

    return {
        "ticket_id": ticket_id_from_batch(batch),
        "batch_id": batch.get("batch_id"),
        "created_at": now,
        "last_seen_at": now,
        "status": "PENDING",
        "combined_odds": batch.get("combined_odds"),
        "combined_model_rating": batch.get("combined_model_rating"),
        "combined_model_probability": batch.get("combined_model_probability"),
        "products": batch.get("products") or [],
        "leg_count": len(legs),
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
            if t.get("last_seen_at") != now:
                t["last_seen_at"] = now
            continue
        ticket = make_ticket(batch, now)
        tickets.append(ticket)
        by_id[tid] = ticket
        changed = True

    rows = flatten_history()
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
        "version": 1,
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
