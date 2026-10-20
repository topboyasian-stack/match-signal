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



def independent_settled_ticket_history(tracker: Any, min_legs: int = 2, max_legs: int = 7):
    """Return chronologically settled tickets with no event overlap.

    A ticket is evidence for independent ticket-level evaluation only when every
    leg has an event ID and none of those event IDs has appeared in an earlier
    included settled ticket. Tickets that reuse an event are kept in the source
    ledger but excluded from calibration and promotion sample counts.
    """
    rows = settled_ticket_history(tracker, min_legs=min_legs, max_legs=max_legs)
    rows.sort(key=lambda ticket: (
        str(ticket.get("_calibration_stamp") or ""),
        str(ticket.get("ticket_id") or ""),
    ))
    independent = []
    used_events = set()
    overlapping_tickets = 0
    overlapping_event_references = 0
    incomplete_identity_tickets = 0
    unique_events = 0

    for ticket in rows:
        legs = ticket.get("legs") if isinstance(ticket.get("legs"), list) else []
        expected = int(ticket.get("leg_count") or len(legs) or 0)
        event_ids = [
            str(leg.get("event_id") or leg.get("eventId") or "").strip()
            for leg in legs if isinstance(leg, dict)
        ]
        if not legs or expected != len(legs) or len(event_ids) != len(legs) or any(not event_id for event_id in event_ids):
            incomplete_identity_tickets += 1
            continue
        ids = set(event_ids)
        if len(ids) != len(event_ids):
            overlapping_tickets += 1
            overlapping_event_references += len(event_ids) - len(ids)
            continue
        overlap = ids & used_events
        if overlap:
            overlapping_tickets += 1
            overlapping_event_references += len(overlap)
            continue
        independent.append(ticket)
        used_events.update(ids)
        unique_events += len(ids)

    diagnostics = {
        "settled_ticket_rows": len(rows),
        "independent_ticket_rows": len(independent),
        "overlapping_event_tickets_excluded": overlapping_tickets,
        "overlapping_event_references_excluded": overlapping_event_references,
        "tickets_missing_complete_event_identity": incomplete_identity_tickets,
        "unique_events_in_independent_sample": unique_events,
        "scope": "chronological event-disjoint settled tickets across active + archived tracker history",
    }
    return independent, diagnostics
