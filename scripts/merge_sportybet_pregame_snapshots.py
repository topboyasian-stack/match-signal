#!/usr/bin/env python3
"""Merge an immutable SportyBet pregame capture into the latest ledger."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from market_snapshot_freshness import (
    is_fresh_pregame_snapshot,
    parse_utc,
    pregame_snapshot_age_seconds,
)

EXPECTED_MARKETS = {"football": "1", "tennis": "186"}
MAX_MODEL_AGE_SECONDS = 12 * 60 * 60
MAX_ROWS = 12000


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def valid_snapshot(row):
    if not isinstance(row, dict):
        return False
    sport = str(row.get("sport") or "").lower()
    if sport not in EXPECTED_MARKETS:
        return False
    if sport == "tennis" and str(row.get("league") or "").upper() != "ATP":
        return False
    if str(row.get("market_id") or "") != EXPECTED_MARKETS[sport]:
        return False
    if str(row.get("source") or "").strip().lower() != "sportybet ng":
        return False
    captured_at = row.get("captured_at")
    start_time = row.get("start_time")
    if not is_fresh_pregame_snapshot(captured_at, start_time):
        return False
    model_calculated_at = parse_utc(row.get("model_calculated_at"))
    start_at = parse_utc(start_time)
    if model_calculated_at is None or start_at is None:
        return False
    model_age = (start_at - model_calculated_at).total_seconds()
    if model_age < 0 or model_age > MAX_MODEL_AGE_SECONDS:
        return False
    try:
        prices = row.get("prices") or {}
        expected_keys = {"p1", "p2", "draw"} if sport == "football" else {"p1", "p2"}
        if set(prices) != expected_keys:
            return False
        if any(float(prices[key]) <= 1.0 for key in expected_keys):
            return False
        probability = float(row.get("model_probability"))
        confidence = float(row.get("confidence"))
        if not (0 < probability < 1 and 0 < confidence <= 1):
            return False
        if confidence < 0.55:
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def snapshot_key(row):
    return (
        str(row.get("event_id") or ""),
        str(row.get("market_id") or ""),
        str(row.get("captured_at") or ""),
    )


def merge_ledgers(remote, incoming, *, updated_at=None):
    """Append unique, strictly valid snapshots; retain existing timestamps."""
    if not isinstance(remote, dict):
        remote = {"version": 1, "snapshots": []}
    if not isinstance(incoming, dict):
        incoming = {"version": 1, "snapshots": []}

    remote_rows = remote.get("snapshots")
    incoming_rows = incoming.get("snapshots")
    if not isinstance(remote_rows, list):
        remote_rows = []
    if not isinstance(incoming_rows, list):
        incoming_rows = []

    merged = []
    seen = set()
    for row in remote_rows:
        if not isinstance(row, dict):
            continue
        key = snapshot_key(row)
        if not key[0] or not key[1] or not key[2] or key in seen:
            continue
        # Do not silently rewrite earlier immutable rows during a retry.
        merged.append(row)
        seen.add(key)

    added = 0
    rejected = 0
    for row in incoming_rows:
        if not valid_snapshot(row):
            rejected += 1
            continue
        key = snapshot_key(row)
        if not key[0] or key in seen:
            continue
        merged.append(row)
        seen.add(key)
        added += 1

    merged.sort(key=lambda row: (str(row.get("captured_at") or ""), str(row.get("event_id") or "")))
    if len(merged) > MAX_ROWS:
        merged = merged[-MAX_ROWS:]

    remote["version"] = 1
    remote["policy"] = incoming.get("policy") or remote.get("policy") or (
        "Append-only SportyBet NG exact winner snapshots; football market 1, "
        "ATP market 186; model generated within 12h and quote captured 0..15m before kickoff."
    )
    remote["snapshots"] = merged
    if added:
        remote["updated_at"] = updated_at or datetime.now(timezone.utc).isoformat()
    return remote, {"added": added, "rejected": rejected, "total": len(merged)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()

    incoming = load_json(args.incoming, {"snapshots": []})
    remote = load_json(args.target, {"version": 1, "snapshots": []})
    merged, stats = merge_ledgers(remote, incoming)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
