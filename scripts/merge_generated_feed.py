"""Merge generated auxiliary prediction rows into the latest main feed.

Writers using GITHUB_TOKEN can finish after another workflow has published newer
predictions. This helper makes the final publication additive: latest main wins
for existing event IDs; only genuinely new rows from the auxiliary job are added.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} is not a list")
    return value


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: merge_generated_feed.py latest.json generated.json")
    latest_path, generated_path = map(Path, sys.argv[1:])
    latest = load(latest_path)
    generated = load(generated_path)
    by_id = {str(r.get("event_id")): r for r in latest if r.get("event_id")}
    added = 0
    for row in generated:
        event_id = str(row.get("event_id") or "")
        if not event_id or event_id in by_id:
            continue
        by_id[event_id] = row
        added += 1
    merged = sorted(by_id.values(), key=lambda r: (str(r.get("start_time") or ""), str(r.get("sport") or ""), str(r.get("player_1") or "")))
    generated_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"latest_rows": len(latest), "generated_rows": len(generated), "final_rows": len(merged), "added_rows": added}, indent=2))


if __name__ == "__main__":
    main()
