"""Transactional production feed wrapper.

Runs the canonical Football + ATP/WTA engine, then restores valid prior rows
when a provider returns an empty sport feed and merges experimental leagues.
The goal is to prevent one transient source failure from deleting another
sport/competition from the public feed.
PAPER ONLY.
"""
from __future__ import annotations

import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FEED = DATA / "predictions.json"
CORE_LEAGUES = {"EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Champions League", "MLS", "Primeira Liga"}
EXPERIMENTAL_LEAGUES = {"Eredivisie", "Saudi Pro League"}
TENNIS_LEAGUES = {"ATP", "WTA"}


def load_rows():
    try:
        value = json.loads(FEED.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def valid_active(row, now):
    if not isinstance(row, dict):
        return False
    value = row.get("start_time")
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return dt >= now - timedelta(hours=6) and not row.get("settled")


def normalize_experimental(row):
    out = dict(row)
    out["paper_only"] = True
    out["live_experimental"] = True
    out["live_trading_approved"] = False
    out["prediction_status"] = "live_experimental"
    return out


def merge_unique(rows):
    by_id = {}
    for row in rows:
        event_id = str(row.get("event_id") or "")
        if event_id:
            by_id[event_id] = row
    return sorted(by_id.values(), key=lambda x: (str(x.get("start_time") or ""), str(x.get("sport") or ""), str(x.get("player_1") or "")))


def main():
    before = load_rows()
    now = datetime.now(timezone.utc)
    preserved = [r for r in before if valid_active(r, now)]

    print("Production transaction: running canonical Football + ATP/WTA engine")
    runpy.run_path(str(ROOT / "scripts" / "run_pipeline.py"), run_name="__main__")
    generated = load_rows()

    generated_core_football = [r for r in generated if r.get("league") in CORE_LEAGUES and r.get("sport") == "football"]
    generated_tennis = [r for r in generated if r.get("league") in TENNIS_LEAGUES and r.get("sport") == "tennis"]

    if not generated_core_football:
        old_core = [r for r in preserved if r.get("league") in CORE_LEAGUES and r.get("sport") == "football"]
        if old_core:
            generated.extend(old_core)
            print(f"WARNING: canonical football refresh returned zero rows; preserved {len(old_core)} active football rows")

    if not generated_tennis:
        old_tennis = [r for r in preserved if r.get("league") in TENNIS_LEAGUES and r.get("sport") == "tennis"]
        if old_tennis:
            generated.extend(old_tennis)
            print(f"WARNING: ATP/WTA refresh returned zero rows; preserved {len(old_tennis)} active tennis rows")

    # Expansion workflows own these competitions, but the canonical pipeline
    # must never erase them while refreshing the normal feed. Normalize their
    # safety flags even when the old row predates the safety-field fix.
    experimental = [normalize_experimental(r) for r in preserved if r.get("league") in EXPERIMENTAL_LEAGUES]
    generated = [r for r in generated if r.get("league") not in EXPERIMENTAL_LEAGUES]
    generated.extend(experimental)
    generated = merge_unique(generated)

    FEED.write_text(json.dumps(generated, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "final_rows": len(generated),
        "core_football_rows": sum(r.get("league") in CORE_LEAGUES for r in generated),
        "tennis_rows": sum(r.get("league") in TENNIS_LEAGUES for r in generated),
        "ere_divisie_rows": sum(r.get("league") == "Eredivisie" for r in generated),
        "saudi_rows": sum(r.get("league") == "Saudi Pro League" for r in generated),
        "preserved_rows": len(experimental),
        "transaction_policy": "NO_SPORT_ERASURE_ON_TRANSIENT_SOURCE_FAILURE",
    }
    print(json.dumps(summary, indent=2))
    if summary["core_football_rows"] == 0:
        raise SystemExit("ABORT: production feed contains no canonical football rows")


if __name__ == "__main__":
    main()
