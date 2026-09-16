"""Recover and persist tennis predictions before settlement.

The live prediction feed is intentionally short-lived. This script prevents
completed ATP/WTA predictions from disappearing when predictions.json is
replaced by the next run. It uses the repository's own git history as the
source of truth for recent prediction snapshots, then merges them into a
persistent tennis archive and prediction_history.json.
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


def valid_tennis_prediction(row):
    if str(row.get("sport") or "").lower() != "tennis":
        return False
    if row.get("league") not in {"ATP", "WTA"}:
        return False
    if not row.get("event_id") or not row.get("start_time"):
        return False
    try:
        start = datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00"))
        calc = datetime.fromisoformat(str(row.get("calculated_at", "")).replace("Z", "+00:00"))
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    return calc < start and start <= now and start >= now - timedelta(days=LOOKBACK_DAYS)


def event_key(row):
    return f"{row.get('sport')}:{row.get('league')}:{row.get('event_id')}"


def git_prediction_snapshots():
    try:
        result = subprocess.run(
            ["git", "log", "--since=14 days ago", "--until=now", "--format=%H", "--", "data/predictions.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        print(f"Git history unavailable: {exc}")
        return []

    snapshots = []
    seen_commits = set()
    for sha in result.stdout.splitlines():
        sha = sha.strip()
        if not sha or sha in seen_commits:
            continue
        seen_commits.add(sha)
        try:
            raw = subprocess.run(
                ["git", "show", f"{sha}:data/predictions.json"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            payload = json.loads(raw)
            if isinstance(payload, list):
                snapshots.extend(x for x in payload if valid_tennis_prediction(x))
        except Exception:
            continue
    return snapshots


def merge_rows(*groups):
    merged = {}
    for group in groups:
        for row in group:
            if not valid_tennis_prediction(row) and not row.get("settled"):
                continue
            key = event_key(row)
            previous = merged.get(key)
            # Never replace a settled record with an un-settled snapshot.
            if previous and previous.get("settled") and not row.get("settled"):
                continue
            if not previous or row.get("settled") or row.get("calculated_at", "") > previous.get("calculated_at", ""):
                merged[key] = row
    return list(merged.values())


def main():
    current = load(CURRENT_PATH, [])
    history = load(HISTORY_PATH, [])
    archive = load(ARCHIVE_PATH, [])
    recovered = git_prediction_snapshots()

    candidates = [x for x in current if valid_tennis_prediction(x)]
    merged_tennis = merge_rows(archive, history, recovered, candidates)

    # Keep the dedicated archive independently of the short public feed.
    merged_tennis.sort(key=lambda x: str(x.get("start_time", "")))
    merged_tennis = merged_tennis[-MAX_ARCHIVE:]
    ARCHIVE_PATH.write_text(json.dumps(merged_tennis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Rebuild history as existing records plus any recovered tennis records.
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

    print(f"Recovered tennis snapshots: {len(recovered)}")
    print(f"Current tennis candidates: {len(candidates)}")
    print(f"Persistent tennis archive: {len(merged_tennis)}")
    print(f"Prediction history total: {len(final_history)}")


if __name__ == "__main__":
    main()
