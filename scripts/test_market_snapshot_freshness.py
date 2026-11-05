#!/usr/bin/env python3
"""Shared pregame price snapshot freshness contract tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from market_snapshot_freshness import (
    is_fresh_pregame_snapshot,
    pregame_snapshot_age_seconds,
)

kickoff = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)

exact_boundary = kickoff - timedelta(minutes=15)
inside_window = kickoff - timedelta(minutes=7, seconds=30)
too_old = kickoff - timedelta(minutes=15, seconds=1)
after_start = kickoff + timedelta(seconds=1)

assert is_fresh_pregame_snapshot(exact_boundary.isoformat(), kickoff.isoformat())
assert is_fresh_pregame_snapshot(inside_window.isoformat(), kickoff.isoformat())
assert not is_fresh_pregame_snapshot(too_old.isoformat(), kickoff.isoformat())
assert not is_fresh_pregame_snapshot(after_start.isoformat(), kickoff.isoformat())
assert not is_fresh_pregame_snapshot("not-a-time", kickoff.isoformat())
assert not is_fresh_pregame_snapshot(inside_window.isoformat(), None)
assert pregame_snapshot_age_seconds(inside_window.isoformat(), kickoff.isoformat()) == 450.0

print("Pregame snapshot final-15-minute boundary tests passed.")
