"""Generate a read-only exact-line/side evidence report from the paper ticket ledger.

This report is diagnostic only. It does not change Builder qualification or create
bets. It aggregates settled ticket legs by product + exact O/U line + side and
includes full-history, recent-10, recent-20, and ticket-level outcomes.
"""
from __future__ import annotations

import json
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
    import re
    side = str(leg.get("builder_pick") or "").strip().lower()
    line = leg.get("line")
    pick = str(leg.get("pick") or "").strip().lower()
    m = re.search(r"\b(over|under)\s+([0-9]+(?:\.[0-9]+)?)\b", pick)
    if side not in {"over", "under"} and m:
        side = m.group(1)
    if line is None and m:
        line = m.group(2)
    try:
        line_key = f"{float(line):g}"
    except (TypeError, ValueError):
        line_key = ""
    return side, line_key


def empty():
    return {"n": 0, "wins": 0, "losses": 0, "accuracy": None}


def add(row, won):
    row["n"] += 1
    if won:
        row["wins"] += 1
    else:
        row["losses"] += 1
    row["accuracy"] = round(row["wins"] / row["n"], 6) if row["n"] else None


def calc(rows):
    out = empty()
    for r in rows:
        add(out, r["won"])
    return out


def main():
    raw = load(TRACKER, {})
    tickets = raw.get("tickets") if isinstance(raw, dict) else []
    tickets = [t for t in tickets if isinstance(t, dict)]

    exact = {}
    product = {}
    all_legs = []

    for ticket in tickets:
        status = str(ticket.get("status") or "")
        if status not in {"WON", "LOST"}:
            continue
        ticket_won = status == "WON"
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
                "settled_at": leg.get("settled_at"),
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
            all_legs.append(row)

            key = (product_name, line, side)
            bucket = exact.setdefault(key, [])
            bucket.append(row)

            p = product.setdefault(product_name, {"tickets": {}, "legs": []})
            p["tickets"][str(ticket.get("ticket_id"))] = ticket_won
            p["legs"].append(row)

    all_legs.sort(key=stamp)
    records = []
    for key, rows in exact.items():
        rows.sort(key=stamp)
        recent10 = rows[-10:]
        recent20 = rows[-20:]
        product_name, line, side = key
        ticket_results = {}
        for r in rows:
            ticket_results[r["ticket_id"]] = r["ticket_won"]
        ticket_list = [{"ticket_id": k, "won": v} for k, v in ticket_results.items()]
        ticket_stats = calc([{"won": x["won"]} for x in ticket_list])

        records.append({
            "product": product_name,
            "line": line,
            "side": side,
            "settled_n": len(rows),
            "full_history": calc(rows),
            "last_10": calc(recent10),
            "last_20": calc(recent20),
            "ticket_history": ticket_stats,
            "ticket_count": len(ticket_list),
            "sample_settled_at": rows[-1].get("settled_at") if rows else None,
        })

    records.sort(key=lambda r: (-(r["settled_n"]), -(r["full_history"]["accuracy"] or 0), r["product"], float(r["line"]), r["side"]))

    product_records = []
    for name, p in product.items():
        unique = list(p["tickets"].items())
        ticket_stats = calc([{"won": v} for _, v in unique])
        leg_stats = calc(p["legs"])
        product_records.append({
            "product": name,
            "ticket_count": len(unique),
            "ticket_history": ticket_stats,
            "leg_history": leg_stats,
        })
    product_records.sort(key=lambda r: r["product"])

    output = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "diagnostic_only": True,
        "source": "data/odds_ticket_tracker.json",
        "tracker_summary": raw.get("summary", {}),
        "settled_ou_legs": len(all_legs),
        "exact_line_side_records": records,
        "product_records": product_records,
        "method": {
            "grouping": "exact product + exact O/U line + selected side",
            "recent_windows": [10, 20],
            "ticket_outcome": "current settled ticket status containing the leg",
            "qualification_unchanged": True,
        },
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "settled_ou_legs": len(all_legs),
        "exact_line_side_records": len(records),
        "products": len(product_records),
        "tracker_summary": raw.get("summary", {}),
    }, indent=2))


if __name__ == "__main__":
    main()
