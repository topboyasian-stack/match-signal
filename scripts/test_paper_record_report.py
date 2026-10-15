#!/usr/bin/env python3
"""Sanity tests for the paper-record maths (no network, no repo data needed)."""
import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location("paper_record_report", Path(__file__).with_name("paper_record_report.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 2 wins at 2.0 and 2 losses: ROI exactly 0, hit 50%, implied 50%.
rows = [{"odds": 2.0, "win": True}, {"odds": 2.0, "win": True}, {"odds": 2.0, "win": False}, {"odds": 2.0, "win": False}]
s = mod.bet_stats(rows)
assert s["n"] == 4 and s["wins"] == 2 and s["roi"] == 0.0 and s["hit_rate"] == 0.5 and s["implied_prob"] == 0.5, s
assert s["insufficient"] is True

# Winning bet pays odds-1; losing bet costs 1.
s = mod.bet_stats([{"odds": 1.5, "win": True}, {"odds": 3.0, "win": False}])
assert abs(s["roi"] - (0.5 - 1.0) / 2) < 1e-9, s

# Rows without odds, outcome or with odds <= 1 are ignored, never counted as wins.
s = mod.bet_stats([{"odds": None, "win": True}, {"odds": 2.0, "win": None}, {"odds": 1.0, "win": True}])
assert s["n"] == 0, s

# Overconfidence gap = mean model probability - hit rate.
s = mod.bet_stats([{"odds": 2.0, "win": True, "p": 0.9}, {"odds": 2.0, "win": False, "p": 0.9}], prob_key="p")
assert abs(s["overconfidence_gap"] - 0.4) < 1e-9, s

lo, hi = mod.wilson(50, 100)
assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60, (lo, hi)
assert mod.week_of("2026-10-14T20:00:00+00:00") == "2026-W42"
assert mod.bucket(0.72, [(0.6, 0.7), (0.7, 0.8)]) == "0.70-0.80"
print("paper record tests passed")
