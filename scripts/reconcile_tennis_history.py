"""Recover and persist ATP/WTA predictions before settlement.

The public predictions feed is short-lived. This script uses repository git
history to recover recent tennis predictions and keeps a dedicated persistent
archive. Predictions are tagged as pre-event eligible or late-captured so
historical data is not silently lost while late predictions are excluded from
verified performance metrics.
PAPER ONLY.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY_PATH = DATA / "prediction_history.json"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
CURRENT_PATH = DATA / "predictions.json"
LOOKBACK_DAYS = 14
MAX_ARCHIVE = 5000
MAX_HISTORY = 5000


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def classify(row):
    if str(row.get("sport") or "").lower() != "tennis" or row.get("league") not in {"ATP", "WTA"}:
        return None
    if not row.get("event_id") or not row.get("start_time"):
        return None
    try:
        start = datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00"))
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    if start < now - timedelta(days=LOOKBACK_DAYS) or start > now:
        return None
    row = dict(row)
    # Eligibility is immutable once captured; preserve prior classification.
    if "evaluation_eligible" in row and "capture_status" in row:
        return row
    try:
        calc = datetime.fromisoformat(str(row.get("calculated_at", "")).replace("Z", "+00:00"))
        eligible = calc < start
    except Exception:
        eligible = False
    row["evaluation_eligible"] = bool(eligible)
    row["capture_status"] = "PRE_EVENT" if eligible else "LATE_CAPTURE"
    return row


def event_key(row):
    return f"{row.get('sport')}:{row.get('league')}:{row.get('event_id')}"


def git_prediction_snapshots():
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--since=14 days ago", "--until=now", "--format=%H", "--", "data/predictions.json"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    except Exception as exc:
        print(f"Git history unavailable: {exc}")
        return []
    snapshots, seen = [], set()
    for sha in result.stdout.splitlines():
        sha = sha.strip()
        if not sha or sha in seen:
            continue
        seen.add(sha)
        try:
            raw = subprocess.run(["git", "show", f"{sha}:data/predictions.json"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
            payload = json.loads(raw)
            if isinstance(payload, list):
                for row in payload:
                    item = classify(row)
                    if item:
                        snapshots.append(item)
        except Exception:
            continue
    return snapshots


def merge_tennis(*groups):
    merged = {}
    for group in groups:
        for row in group:
            item = classify(row) if not row.get("settled") else dict(row)
            if not item:
                continue
            key = event_key(item)
            previous = merged.get(key)
            if previous and previous.get("settled") and not item.get("settled"):
                continue
            if not previous or item.get("settled") or item.get("calculated_at", "") > previous.get("calculated_at", ""):
                merged[key] = item
    return list(merged.values())


def main():
    current = load(CURRENT_PATH, [])
    history = load(HISTORY_PATH, [])
    archive = load(ARCHIVE_PATH, [])
    recovered = git_prediction_snapshots()
    current_tennis = [x for x in (classify(r) for r in current) if x]
    existing_tennis = [x for x in archive + history if str(x.get("sport") or "").lower() == "tennis"]
    merged_tennis = merge_tennis(existing_tennis, recovered, current_tennis)
    merged_tennis.sort(key=lambda x: str(x.get("start_time", "")))
    merged_tennis = merged_tennis[-MAX_ARCHIVE:]
    ARCHIVE_PATH.write_text(json.dumps(merged_tennis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    non_tennis_history = [x for x in history if str(x.get("sport") or "").lower() != "tennis"]
    combined = non_tennis_history + merged_tennis
    dedup = {}
    for row in combined:
        key = event_key(row)
        previous = dedup.get(key)
        if not previous or row.get("settled") or row.get("calculated_at", "") > previous.get("calculated_at", ""):
            dedup[key] = row
    final_history = sorted(dedup.values(), key=lambda x: str(x.get("start_time", "")))[-MAX_HISTORY:]
    HISTORY_PATH.write_text(json.dumps(final_history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    eligible = sum(x.get("evaluation_eligible") is True for x in merged_tennis)
    late = sum(x.get("capture_status") == "LATE_CAPTURE" for x in merged_tennis)
    print(f"Recovered tennis snapshots: {len(recovered)}")
    print(f"Current tennis candidates: {len(current_tennis)}")
    print(f"Persistent tennis archive: {len(merged_tennis)} | pre-event eligible: {eligible} | late capture: {late}")
    print(f"Prediction history total: {len(final_history)}")


if __name__ == "__main__":
    main()
