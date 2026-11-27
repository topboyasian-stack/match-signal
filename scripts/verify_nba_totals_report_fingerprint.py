#!/usr/bin/env python3
"""Fail closed when the published NBA totals research report lags its source files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from nba_totals_report_refresh_gate import (
    SOURCE_DATA_FILES,
    report_source_fingerprint_matches,
    source_data_fingerprint,
)


def verify(root: Path) -> tuple[bool, list[str]]:
    report_path = root / "data/nba_totals_probability_value_experiment.json"
    if not report_path.is_file():
        return False, [f"Missing report: {report_path}"]

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"Could not read report {report_path}: {exc}"]

    current = source_data_fingerprint(root)
    if report_source_fingerprint_matches(report, current):
        return True, []

    recorded = report.get("source_data_fingerprint") if isinstance(report, dict) else None
    if not isinstance(recorded, dict):
        return False, ["Report has no valid source_data_fingerprint object."]

    mismatches = []
    for relative in SOURCE_DATA_FILES:
        expected = recorded.get(relative)
        actual = current.get(relative)
        if expected != actual:
            mismatches.append(
                f"{relative}: report={expected!r}, current={actual!r}"
            )
    return False, mismatches or ["The report fingerprint does not exactly match current inputs."]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    ok, mismatches = verify(root)
    if ok:
        print(
            "PASS: NBA totals probability/value report fingerprint matches "
            f"all {len(SOURCE_DATA_FILES)} current source files."
        )
        return 0
    print("STALE: NBA totals probability/value report does not match current main inputs.")
    for mismatch in mismatches:
        print(f"  - {mismatch}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
