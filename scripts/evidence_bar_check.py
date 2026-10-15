#!/usr/bin/env python3
"""Evidence bar check (REPORT ONLY, PAPER ONLY). Thresholds are fixed in docs/EVIDENCE_BAR.md
and are not tuned to results. Reads data/paper_record_ledger.json (else the desk's settled
observations) and writes data/evidence_bar_status.json. Changes no rule, gate or board output."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MIN_SETTLED = 1000
MAX_OVERALL_GAP = 0.02
MAX_BUCKET_GAP = 0.05
BUCKET_MIN_N = 30
MIN_COVERAGE = 0.70


def load_rows():
    ledger = DATA / "paper_record_ledger.json"
    src = ledger if ledger.exists() else DATA / "efootball_desk_settled_observations.json"
    rows = []
    for x in json.loads(src.read_text(encoding="utf-8")):
        if x.get("win") is None or x.get("push") or not x.get("bookmaker_odds") or x.get("model_probability") is None:
            continue
        key = x.get("key") or x.get("event_key")
        rows.append({"key": key, "odds": x["bookmaker_odds"], "p": x["model_probability"], "y": 1 if x["win"] else 0,
                     "start": str(x.get("start_time"))})
    rows.sort(key=lambda r: r["start"])
    return rows


def roi_ci(rows):
    vals = [(r["odds"] - 1) if r["y"] else -1.0 for r in rows]
    n = len(vals)
    if n < 2:
        return None, None, None
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    half = 1.96 * sd / math.sqrt(n)
    return m, m - half, m + half


def coverage(rows):
    path = DATA / "efootball_desk_prediction_history.json"
    if not path.exists():
        return None
    keys = {t.get("event_key") for t in json.loads(path.read_text(encoding="utf-8")) if t.get("product") == "efootball_gt"}
    keys.discard(None)
    if not keys:
        return None
    return len(keys & {r["key"] for r in rows}) / len(keys)


def verdict(ok, enough=True):
    return "INSUFFICIENT" if not enough else ("PASS" if ok else "FAIL")


def main():
    rows = load_rows()
    n = len(rows)
    out = {"mode": "PAPER_ONLY_REPORT_ONLY", "settled_picks": n, "criteria": []}

    out["criteria"].append({"name": "Sample size >= %d settled single picks" % MIN_SETTLED, "value": n, "result": "PASS" if n >= MIN_SETTLED else "INSUFFICIENT"})

    m, lo, hi = roi_ci(rows)
    out["criteria"].append({"name": "ROI 95% range entirely above zero", "value": None if m is None else {"roi": round(m, 4), "low": round(lo, 4), "high": round(hi, 4)},
                            "result": verdict(lo is not None and lo > 0, enough=n >= MIN_SETTLED)})

    half = n // 2
    r1, r2 = roi_ci(rows[:half])[0] if half > 1 else None, roi_ci(rows[half:])[0] if n - half > 1 else None
    out["criteria"].append({"name": "ROI positive in both chronological halves", "value": {"first_half": None if r1 is None else round(r1, 4), "second_half": None if r2 is None else round(r2, 4)},
                            "result": verdict(r1 is not None and r2 is not None and r1 > 0 and r2 > 0, enough=n >= MIN_SETTLED)})

    if n:
        gap = sum(r["p"] for r in rows) / n - sum(r["y"] for r in rows) / n
        out["criteria"].append({"name": "Overall |stated probability - hit rate| <= %.0f points" % (100 * MAX_OVERALL_GAP), "value": round(gap, 4),
                                "result": verdict(abs(gap) <= MAX_OVERALL_GAP, enough=n >= MIN_SETTLED)})
        worst = None
        for lo_b in (0.5, 0.6, 0.7, 0.8, 0.9):
            b = [r for r in rows if lo_b <= r["p"] < lo_b + 0.1]
            if len(b) >= BUCKET_MIN_N:
                g = sum(r["p"] for r in b) / len(b) - sum(r["y"] for r in b) / len(b)
                if worst is None or abs(g) > abs(worst[1]):
                    worst = ("%.1f-%.1f" % (lo_b, lo_b + 0.1), g, len(b))
        out["criteria"].append({"name": "Every 10-point probability bucket (n>=%d) within %.0f points" % (BUCKET_MIN_N, 100 * MAX_BUCKET_GAP),
                                "value": None if worst is None else {"worst_bucket": worst[0], "gap": round(worst[1], 4), "n": worst[2]},
                                "result": verdict(worst is not None and abs(worst[1]) <= MAX_BUCKET_GAP, enough=worst is not None and n >= MIN_SETTLED)})

    cov = coverage(rows)
    out["criteria"].append({"name": "Settlement coverage >= %.0f%% of forecast fixture-lines (indicative)" % (100 * MIN_COVERAGE),
                            "value": None if cov is None else round(cov, 3), "result": verdict(cov is not None and cov >= MIN_COVERAGE, enough=cov is not None)})

    results = [c["result"] for c in out["criteria"]]
    out["overall"] = "PASS" if all(r == "PASS" for r in results) else "NOT PASSED YET"
    (DATA / "evidence_bar_status.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for c in out["criteria"]:
        print("%-12s %s  %s" % (c["result"], c["name"], c["value"]))
    print("OVERALL:", out["overall"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
