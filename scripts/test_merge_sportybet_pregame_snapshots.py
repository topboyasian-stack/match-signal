#!/usr/bin/env python3
"""Regressions for retry-safe append-only SportyBet quote ledger merging."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from merge_sportybet_pregame_snapshots import merge_ledgers, valid_snapshot

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def snapshot(event_id, *, sport="football", league="Champions League", quote_minutes=8, model_minutes=20, price=1.9):
    kickoff = NOW + timedelta(minutes=10)
    return {
        "event_id": event_id,
        "sport": sport,
        "league": league,
        "start_time": kickoff.isoformat(),
        "captured_at": (kickoff - timedelta(minutes=quote_minutes)).isoformat(),
        "model_calculated_at": (kickoff - timedelta(minutes=model_minutes)).isoformat(),
        "market_id": "1" if sport == "football" else "186",
        "source": "SportyBet NG",
        "pick": "p1",
        "model_probability": 0.62,
        "confidence": 0.62,
        "prices": {"p1": price, "p2": 2.1, "draw": 3.5} if sport == "football" else {"p1": price, "p2": 2.1},
    }


a = snapshot("event-a")
b = snapshot("event-b", price=2.05)
assert valid_snapshot(a)
assert valid_snapshot(b)

remote = {"version": 1, "snapshots": [a]}
incoming = {"policy": "immutable-test", "snapshots": [a, b, b]}
merged, stats = merge_ledgers(remote, incoming, updated_at="2026-11-05T12:00:00Z")
assert stats == {"added": 1, "rejected": 0, "total": 2}
assert [row["event_id"] for row in merged["snapshots"]] == ["event-a", "event-b"]
assert merged["snapshots"][0]["captured_at"] == a["captured_at"]
assert merged["snapshots"][1]["captured_at"] == b["captured_at"]

# A later main update may already have the same event snapshot. A retry must
# preserve the exact original observation and must not count it a second time.
retry, retry_stats = merge_ledgers(merged, incoming, updated_at="2026-11-05T12:10:00Z")
assert retry_stats == {"added": 0, "rejected": 0, "total": 2}
assert retry["snapshots"] == merged["snapshots"]

stale_quote = snapshot("stale-quote", quote_minutes=16)
stale_model = snapshot("stale-model", model_minutes=13 * 60)
post_kickoff = snapshot("post-kickoff")
post_kickoff["captured_at"] = (NOW + timedelta(minutes=11)).isoformat()
wta = snapshot("wta", sport="tennis", league="WTA")
wrong_market = snapshot("wrong-market")
wrong_market["market_id"] = "18"
assert not valid_snapshot(stale_quote)
assert not valid_snapshot(stale_model)
assert not valid_snapshot(post_kickoff)
assert not valid_snapshot(wta)
assert not valid_snapshot(wrong_market)

print("Race-safe immutable SportyBet pregame ledger merge tests passed.")
