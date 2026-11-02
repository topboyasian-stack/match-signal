#!/usr/bin/env python3
"""Regression tests for fixture-independent recent eFootball performance."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.efootball_desk_learning import recent_fixture_window


def row(product, start, home, away, win, settled, probability=0.6, line=2.5):
    return {
        "product": product,
        "start_time": start,
        "timestamp": start,
        "participant_1": home,
        "participant_2": away,
        "win": win,
        "settled_at": settled,
        "model_probability": probability,
        "line": line,
    }


def main():
    rows = []
    # An older fixture has ten line decisions and is outside the selected window.
    for i in range(10):
        rows.append(row(
            "efootball_gt", "2026-11-01T10:00:00+00:00", "Home A", "Away A",
            False, f"2026-11-01T11:{i:02d}:00+00:00", probability=0.4, line=1.5+i,
        ))

    # Two latest fixtures have very different numbers of line decisions.
    # The second row reverses participants intentionally: fixture identity is order-independent.
    for i in range(3):
        rows.append(row(
            "efootball_gt", "2026-11-01T10:10:00+00:00",
            "Home B" if i != 1 else "Away B", "Away B" if i != 1 else "Home B",
            True, f"2026-11-01T12:1{i}:00+00:00", probability=0.7, line=2.5+i,
        ))
    rows.append(row(
        "efootball_gt", "2026-11-01T10:20:00+00:00", "Home C", "Away C",
        False, "2026-11-01T12:30:00+00:00", probability=0.3,
    ))

    # Same names/time in another product must be kept in a separate cluster.
    rows.append(row(
        "efootball_adriatic", "2026-11-01T10:20:00+00:00", "Home C", "Away C",
        True, "2026-11-01T12:31:00+00:00", probability=0.8,
    ))

    result = recent_fixture_window(rows, window=2)
    assert result["n"] == 2, result
    assert result["unique_fixtures"] == 2, result
    assert result["decision_count"] == 4, result
    # Each fixture contributes one cluster score: (3/3 + 0/1) / 2 = 0.50.
    assert abs(result["accuracy"] - 0.50) < 1e-12, result
    # Decision-weighted accuracy is retained only as a diagnostic: 3/4 = 0.75.
    assert abs(result["decision_accuracy"] - 0.75) < 1e-12, result
    assert result["window_unit"] == "unique_product_fixture_clusters", result
    assert result["first_settled_at"] == "2026-11-01T12:10:00+00:00", result
    assert result["last_settled_at"] == "2026-11-01T12:30:00+00:00", result

    empty = recent_fixture_window([], window=50)
    assert empty["n"] == 0 and empty["decision_count"] == 0, empty
    print("eFootball desk recent fixture window: 9 assertions passed.")


if __name__ == "__main__":
    main()
