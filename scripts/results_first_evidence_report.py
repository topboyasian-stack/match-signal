"""Generate a read-only exact-line/side and ticket-construction evidence report.

This report is diagnostic only. It does not change Builder qualification or create
bets. It aggregates settled ticket legs by product + exact O/U line + side and
adds ticket-shape, co-occurrence, and strong-leg-on-lost-ticket diagnostics.
"""
from __future__ import annotations

import itertools
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRACKER = DATA / "odds_ticket_tracker.json"
OUTPUT = DATA / "results_first_evidence_report.json"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def stamp(row):
    raw = row.get("settled_at") or row.get("created_at") or ""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def side_line(leg):
    side = str(leg.get("builder_pick") or "").strip().lower()
    line = leg.get("line")
    pick = str(leg.get("pick") or "").strip().lower()
    match = re.search(r"\b(over|under)\s+([0-9]+(?:\.[0-9]+)?)\b", pick)
    if side not in {"over", "under"} and match:
        side = match.group(1)
    if line is None and match:
        line = match.group(2)
    try:
        line_key = f"{float(line):g}"
    except (TypeError, ValueError):
        line_key = ""
    return side, line_key


def empty():
    return {"n": 0, "wins": 0, "losses": 0, "accuracy": None}


def calc(rows):
    out = empty()
    for row in rows:
        out["n"] += 1
        if bool(row.get("won")):
            out["wins"] += 1
        else:
            out["losses"] += 1
    out["accuracy"] = round(out["wins"] / out["n"], 6) if out["n"] else None
    return out


def main():
    raw = load(TRACKER, {})
    tickets = raw.get("tickets") if isinstance(raw, dict) else []
    tickets = [t for t in tickets if isinstance(t, dict)]

    exact = {}
    product = {}
    pair_buckets = {}
    shape_buckets = {}
    settled_ticket_rows = []
    strong_leg_lost = []

    for ticket in tickets:
        ticket_status = str(ticket.get("status") or "")
        if ticket_status not in {"WON", "LOST"}:
            continue

        ticket_won = ticket_status == "WON"
        settled_ou = []

        for leg in ticket.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            leg_status = str(leg.get("status") or "")
            if leg_status not in {"WON", "LOST"}:
                continue

            product_name = str(leg.get("product") or leg.get("sport") or "").strip()
            side, line = side_line(leg)
            if not product_name or side not in {"over", "under"} or not line:
                continue

            row = {
                "ticket_id": ticket.get("ticket_id"),
                "batch_id": ticket.get("batch_id"),
                "settled_at": leg.get("settled_at") or ticket.get("settled_at"),
                "won": leg_status == "WON",
                "ticket_won": ticket_won,
                "event_id": leg.get("event_id"),
                "fixture": leg.get("fixture") or leg.get("match"),
                "product": product_name,
                "line": line,
                "side": side,
                "odds": leg.get("bookmaker_odds") or leg.get("sportybet_odds"),
                "model_probability": leg.get("model_probability"),
                "model_rating": leg.get("model_rating"),
                "result": leg.get("result"),
                "final_score": leg.get("final_score"),
            }
            row["exact_key"] = f"{product_name}|{line}|{side}"
            settled_ou.append(row)

            exact.setdefault((product_name, line, side), []).append(row)
            p = product.setdefault(product_name, {"tickets": {}, "legs": []})
            p["tickets"][str(ticket.get("ticket_id"))] = ticket_won
            p["legs"].append(row)

            if row["won"] and not ticket_won:
                strong_leg_lost.append({
                    "ticket_id": row["ticket_id"],
                    "settled_at": row["settled_at"],
                    "exact_key": row["exact_key"],
                    "fixture": row["fixture"],
                    "odds": row["odds"],
                })

        if not settled_ou:
            continue

        settled_ou.sort(key=stamp)
        keys = sorted(set(r["exact_key"] for r in settled_ou))
        settled_ticket_rows.append({
            "ticket_id": ticket.get("ticket_id"),
            "batch_id": ticket.get("batch_id"),
            "status": ticket_status,
            "settled_at": ticket.get("settled_at") or settled_ou[-1].get("settled_at"),
            "ou_leg_count": len(settled_ou),
            "won_ou_legs": sum(1 for r in settled_ou if r["won"]),
            "lost_ou_legs": sum(1 for r in settled_ou if not r["won"]),
            "exact_keys": keys,
        })

        shape = f"ou_legs_{len(settled_ou)}"
        shape_buckets.setdefault(shape, []).append({"won": ticket_won})

        for a, b in itertools.combinations(keys, 2):
            pair_buckets.setdefault((a, b), []).append({
                "won": ticket_won,
                "ticket_id": ticket.get("ticket_id"),
            })

    strong_leg_lost.sort(key=stamp)
    settled_ticket_rows.sort(key=stamp)

    records = []
    for key, rows in exact.items():
        rows.sort(key=stamp)
        ticket_map = {}
        for row in rows:
            tid = str(row.get("ticket_id"))
            ticket_map[tid] = row["ticket_won"]

        ticket_level = [{"won": value} for value in ticket_map.values()]
        strong_lost_count = sum(1 for row in rows if row["won"] and not row["ticket_won"])

        records.append({
            "product": key[0],
            "line": key[1],
            "side": key[2],
            "settled_n": len(rows),
            "full_history": calc(rows),
            "last_10": calc(rows[-10:]),
            "last_20": calc(rows[-20:]),
            "ticket_history": calc(ticket_level),
            "ticket_count": len(ticket_map),
            "strong_leg_on_lost_ticket_count": strong_lost_count,
            "sample_settled_at": rows[-1].get("settled_at") if rows else None,
        })

    records.sort(key=lambda row: (
        -(row["settled_n"]),
        -(row["full_history"]["accuracy"] or 0),
        row["product"],
        float(row["line"]),
        row["side"],
    ))

    pair_records = []
    for (a, b), rows in pair_buckets.items():
        stats = calc(rows)
        pair_records.append({
            "leg_a": a,
            "leg_b": b,
            "cooccurrence_tickets": len(rows),
            "ticket_history": stats,
        })
    pair_records.sort(key=lambda row: (
        -row["cooccurrence_tickets"],
        -(row["ticket_history"]["accuracy"] or 0),
        row["leg_a"],
        row["leg_b"],
    ))

    shape_records = []
    for shape, rows in shape_buckets.items():
        shape_records.append({
            "ticket_shape": shape,
            "settled_tickets": len(rows),
            "ticket_history": calc(rows),
        })
    shape_records.sort(key=lambda row: row["ticket_shape"])

    product_records = []
    for name, p in product.items():
        unique_tickets = list(p["tickets"].values())
        product_records.append({
            "product": name,
            "ticket_count": len(unique_tickets),
            "ticket_history": calc([{"won": value} for value in unique_tickets]),
            "leg_history": calc(p["legs"]),
        })
    product_records.sort(key=lambda row: row["product"])

    output = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "diagnostic_only": True,
        "source": "data/odds_ticket_tracker.json",
        "tracker_summary": raw.get("summary", {}),
        "settled_ou_legs": sum(row["ou_leg_count"] for row in settled_ticket_rows),
        "settled_tickets_with_ou_legs": len(settled_ticket_rows),
        "exact_line_side_records": records,
        "ticket_shape_records": shape_records,
        "cooccurrence_records": pair_records,
        "strong_leg_on_lost_ticket": {
            "count": len(strong_leg_lost),
            "by_exact_key": {
                key: sum(1 for row in strong_leg_lost if row["exact_key"] == key)
                for key in sorted({row["exact_key"] for row in strong_leg_lost})
            },
            "recent": strong_leg_lost[-20:],
        },
        "product_records": product_records,
        "method": {
            "grouping": "exact product + exact O/U line + selected side",
            "recent_windows": [10, 20],
            "ticket_outcome": "current settled ticket status containing the leg",
            "cooccurrence": "pairs of exact O/U line-side keys within the same settled ticket",
            "strong_leg_on_lost_ticket": "the exact O/U leg won while its containing ticket lost",
            "qualification_unchanged": True,
        },
    }

    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "settled_ou_legs": output["settled_ou_legs"],
        "settled_tickets_with_ou_legs": output["settled_tickets_with_ou_legs"],
        "exact_line_side_records": len(records),
        "cooccurrence_records": len(pair_records),
        "ticket_shapes": len(shape_records),
        "strong_leg_on_lost_ticket_count": len(strong_leg_lost),
    }, indent=2))


if __name__ == "__main__":
    main()
