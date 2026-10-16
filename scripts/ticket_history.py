"""Safe, deduplicated access to the rolling Odds Builder ticket ledger."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def merge_ticket_history(tracker: Any):
    """Combine the active and archived lists, preferring active records on duplicate IDs."""
    if not isinstance(tracker, dict):
        tracker = {}
    current = tracker.get("tickets")
    archived = tracker.get("archived_tickets")
    current = current if isinstance(current, list) else []
    archived = archived if isinstance(archived, list) else []

    merged = {}
    duplicate_keys = 0

    def identity(ticket, source, index):
        ticket_id = str(ticket.get("ticket_id") or "").strip()
        if ticket_id:
            return "ticket:" + ticket_id
        fingerprint = str(ticket.get("snapshot_fingerprint") or "").strip()
        if fingerprint:
            return "fingerprint:" + fingerprint
        # Old rows without IDs can still be deduplicated when their fixture payload
        # and creation timestamp are identical. Otherwise preserve them independently.
        legs = []
        for leg in ticket.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            legs.append((
                str(leg.get("product") or leg.get("sport") or ""),
                str(leg.get("event_id") or ""),
                str(leg.get("market") or ""),
                str(leg.get("builder_pick") or leg.get("pick") or ""),
                str(leg.get("line") or ""),
            ))
        payload = {
            "created_at": ticket.get("created_at"),
            "legs": sorted(legs),
        }
        if payload["created_at"] or payload["legs"]:
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
            return "fallback:" + digest
        return f"missing:{source}:{index}"

    # Archived first, then active tickets. The active record is the current
    # canonical version if a ticket ID appears in both lists.
    for source, rows in (("archived", archived), ("current", current)):
        for index, ticket in enumerate(rows):
            if not isinstance(ticket, dict):
                continue
            key = identity(ticket, source, index)
            if key in merged:
                duplicate_keys += 1
            merged[key] = dict(ticket)

    unique = list(merged.values())
    diagnostics = {
        "current_rows": len(current),
        "archived_rows": len(archived),
        "unique_rows": len(unique),
        "duplicate_rows_collapsed": duplicate_keys,
        "settled_unique_rows": sum(
            1 for t in unique if str(t.get("status") or "").upper() in {"WON", "LOST"}
        ),
        "pending_unique_rows": sum(
            1 for t in unique if str(t.get("status") or "").upper() == "PENDING"
        ),
    }
    return unique, diagnostics


def settled_ticket_history(tracker: Any, min_legs: int = 2, max_legs: int = 7):
    """Return time-ordered, settled 2–7-leg tickets from both ledger partitions."""
    unique, _ = merge_ticket_history(tracker)
    rows = []
    for ticket in unique:
        status = str(ticket.get("status") or "").upper()
        if status not in {"WON", "LOST"}:
            continue
        try:
            leg_count = int(ticket.get("leg_count") or len(ticket.get("legs") or []))
        except (TypeError, ValueError):
            continue
        if not min_legs <= leg_count <= max_legs:
            continue
        stamp = (
            ticket.get("last_settled_at")
            or ticket.get("settled_at")
            or ticket.get("updated_at")
        )
        if not stamp:
            continue
        item = dict(ticket)
        item["_calibration_stamp"] = str(stamp)
        rows.append(item)

    rows.sort(key=lambda ticket: ticket["_calibration_stamp"])
    return rows
