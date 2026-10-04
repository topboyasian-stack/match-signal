"""Segment mispricing scan with time-split validation (PAPER / RESEARCH ONLY).

Question: does any (line, side, odds band, 6-hour block) segment of the O/U market
show positive flat-stake ROI that survives out of sample?

Method: split settled rows chronologically in half. Segments with at least
MIN_SEGMENT_ROWS rows and ROI above MIN_FIRST_HALF_ROI in the first half are
"candidates". Their ROI is then measured on the second half, which they have not
seen, and pooled across all candidates (so cherry-picking the best one is not possible).

Diagnostic only: reads data/virtual_lab_history.json, changes nothing.

Run:
    python scripts/segment_mispricing_scan.py [--output data/segment_mispricing_scan.json]
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "virtual_lab_history.json"
PRODUCTS = ("vfootball", "efootball_gt")
MIN_SEGMENT_ROWS = 40
MIN_FIRST_HALF_ROI = 0.05
MIN_SECOND_HALF_ROWS_TO_LIST = 20


def odds_band(o):
    return "<1.2" if o < 1.2 else "1.2-1.5" if o < 1.5 else "1.5-2.0" if o < 2.0 else "2.0+"


def seg_key(r):
    hour = datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00")).hour // 6
    return (r["line"], str(r["selection"])[0].upper(), odds_band(float(r["odds"])), hour)


def mean(v):
    return sum(v) / len(v)


def scan(rows):
    rows = sorted(rows, key=lambda r: r["timestamp"])
    cut = len(rows) // 2
    first, second = defaultdict(list), defaultdict(list)
    for i, r in enumerate(rows):
        pnl = float(r["odds"]) - 1.0 if r["win"] else -1.0
        (first if i < cut else second)[seg_key(r)].append(pnl)
    tested = [k for k, v in first.items() if len(v) >= MIN_SEGMENT_ROWS]
    cands = sorted(((mean(first[k]), len(first[k]), k) for k in tested if mean(first[k]) > MIN_FIRST_HALF_ROI), reverse=True)
    listed, pooled = [], []
    for roi1, n1, k in cands:
        b = second.get(k, [])
        pooled += b
        if len(b) >= MIN_SECOND_HALF_ROWS_TO_LIST:
            listed.append({"segment": list(k), "first_half_roi": round(roi1, 4), "first_half_n": n1,
                           "second_half_roi": round(mean(b), 4), "second_half_n": len(b)})
    out = {"rows": len(rows), "segments_tested": len(tested), "candidates": len(cands), "listed": listed}
    if pooled:
        sd = math.sqrt(sum((x - mean(pooled)) ** 2 for x in pooled) / max(1, len(pooled) - 1))
        out["pooled_second_half"] = {"roi": round(mean(pooled), 4), "n": len(pooled),
                                     "se": round(sd / math.sqrt(len(pooled)), 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(HISTORY))
    ap.add_argument("--output")
    args = ap.parse_args()
    data = json.loads(Path(args.history).read_text(encoding="utf-8"))
    report = {}
    for p in PRODUCTS:
        rows = [r for r in data if r.get("product") == p and r.get("market") == "ou"
                and r.get("win") is not None and r.get("odds")]
        report[p] = scan(rows)
        s = report[p]
        print(f"{p}: rows={s['rows']} tested={s['segments_tested']} candidates={s['candidates']}")
        for item in s["listed"]:
            print("  ", item)
        if "pooled_second_half" in s:
            print("   pooled second half:", s["pooled_second_half"])
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
