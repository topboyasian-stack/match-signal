#!/usr/bin/env python3
"""Regression tests for active-tour scoping and time-safe risk evidence."""
from datetime import datetime, timedelta, timezone
import runpy

GUARD = runpy.run_path("scripts/model_guard.py")
evaluate = GUARD["evaluate"]
value_trial = GUARD["value_trial"]
value_testing = GUARD["value_testing"]
in_scope = GUARD["in_scope"]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def settled_row(*, league="ATP", capture_status=None, evaluation_eligible=True, quote_before_kickoff=True):
    quote_at = NOW - timedelta(minutes=30)
    kickoff = NOW + timedelta(hours=2)
    if not quote_before_kickoff:
        quote_at = kickoff + timedelta(minutes=1)
    return {
        "sport": "tennis",
        "league": league,
        "event_id": f"{league}-{capture_status or 'valid'}-{quote_before_kickoff}",
        "start_time": kickoff.isoformat(),
        "settled": True,
        "actual": "p1",
        "pick": "p1",
        "confidence": 0.60,
        "probabilities": {"p1": 0.60, "p2": 0.40},
        "sportybet_winner_odds": {"p1": 1.90, "p2": 2.10, "market_id": "186"},
        "market_insights": {"snapshot_at": quote_at.isoformat()},
        "capture_status": capture_status,
        "evaluation_eligible": evaluation_eligible,
    }


atp = settled_row()
wta = settled_row(league="WTA")
late = settled_row(capture_status="LATE_CAPTURE")
invalid = settled_row(evaluation_eligible=False)
post_kickoff_price = settled_row(quote_before_kickoff=False)

assert in_scope(atp, "tennis", "ATP") is True
assert in_scope(wta, "tennis", "ATP") is False
assert evaluate([atp, wta], "tennis", league="ATP")["settled"] == 1
assert evaluate([atp, wta], "tennis")["settled"] == 2

# ATP is the active ticket scope; WTA may be measured separately but cannot
# inflate the active ATP trial count or ROI.
assert value_testing([atp, wta], "tennis", league="ATP")["trials"] == 1
assert value_testing([atp, wta], "tennis", league="WTA")["trials"] == 1

assert value_trial(atp) is not None
assert value_trial(wta) is not None  # retained as a separate research record
assert value_trial(late) is None
assert value_trial(invalid) is None
assert value_trial(post_kickoff_price) is None

print("Active ATP scope and time-safe risk-evidence regressions passed.")
