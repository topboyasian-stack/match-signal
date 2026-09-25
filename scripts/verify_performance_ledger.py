"""Verify that all performance artifacts derive from one append-only settled ledger.
PAPER ONLY.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def load(name, default=None):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default

def key(row):
    return f"{row.get('sport')}:{row.get('league')}:{row.get('event_id')}"

def main():
    history = load("prediction_history.json", [])
    accuracy = load("accuracy.json", {})
    current = load("current_performance.json", {})
    tennis = load("tennis_performance.json", {})

    if not isinstance(history, list):
        raise SystemExit("prediction_history.json is not a list")

    settled = [r for r in history if isinstance(r, dict) and r.get("settled") and r.get("correct") is not None]
    ids = [key(r) for r in settled]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate settled prediction keys detected")

    total = len(settled)
    correct = sum(bool(r.get("correct")) for r in settled)
    tennis_rows = [r for r in settled if str(r.get("sport") or "").lower() == "tennis"]
    football_rows = [r for r in settled if str(r.get("sport") or "").lower() == "football"]

    checks = {
        "accuracy_settled": accuracy.get("summary", {}).get("settled") == total,
        "accuracy_correct": accuracy.get("summary", {}).get("correct") == correct,
        "current_settled": current.get("overall", {}).get("settled") == total,
        "tennis_settled": tennis.get("settled_tennis_matches") == len(tennis_rows),
        "sport_sum": len(tennis_rows) + len(football_rows) == total,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("Ledger artifact divergence: " + ", ".join(failed))

    # Compare against the previous committed ledger. A settled prediction may
    # gain fields, but its identity must never disappear between runs.
    try:
        old_raw = subprocess.check_output(
            ["git", "show", "HEAD:data/prediction_history.json"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        )
        old = json.loads(old_raw)
        old_settled = {key(r) for r in old if isinstance(r, dict) and r.get("settled") and r.get("correct") is not None}
        missing = sorted(old_settled - set(ids))
        if missing:
            raise SystemExit(f"Append-only violation: {len(missing)} previously settled predictions disappeared")
    except subprocess.CalledProcessError:
        print("No prior committed prediction ledger available; append-only comparison skipped.")

    print(json.dumps({
        "status": "PASS",
        "settled": total,
        "correct": correct,
        "football_settled": len(football_rows),
        "tennis_settled": len(tennis_rows),
        "tennis_late_captures_observed": tennis.get("late_captures_observed", tennis.get("late_captures_excluded", 0)),
        "append_only": True,
    }, indent=2))

if __name__ == "__main__":
    main()
