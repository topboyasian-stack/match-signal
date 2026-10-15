#!/usr/bin/env python3
"""Shadow test (REPORT ONLY, PAPER ONLY): would blending the eFootball model toward the
bookmaker's de-vigged price improve its probabilities?

This never changes a qualification rule, a gate or any board output. It only reads settled
picks (data/paper_record_ledger.json when present, else the desk's settled observations) and
writes data/shrinkage_shadow_report.json and docs/SHRINKAGE_SHADOW.md.

blended = market + w * (model - market).  w=1 is today's model, w=0 is the market price.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
MIN_N = 30
RULE_EDGE, RULE_RETURN = 0.02, 0.02   # the page's stated minimums: +2% edge and +2% expected return


def load_rows():
    ledger = DATA / "paper_record_ledger.json"
    source = ledger if ledger.exists() else DATA / "efootball_desk_settled_observations.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for x in raw:
        if x.get("win") is None or x.get("push") or not x.get("bookmaker_odds"):
            continue
        if x.get("model_probability") is None or x.get("model_edge_vs_market") is None:
            continue
        rows.append({"p": x["model_probability"], "q": x["model_probability"] - x["model_edge_vs_market"],
                     "odds": x["bookmaker_odds"], "y": 1 if x["win"] else 0, "start": str(x.get("start_time"))})
    rows.sort(key=lambda r: r["start"])
    return rows, source.name


def blend(r, w):
    return r["q"] + w * (r["p"] - r["q"])


def brier(rows, f):
    return sum((f(r) - r["y"]) ** 2 for r in rows) / len(rows)


def logloss(rows, f):
    total = 0.0
    for r in rows:
        p = min(max(f(r), 1e-4), 1 - 1e-4)
        total += -(math.log(p) if r["y"] else math.log(1 - p))
    return total / len(rows)


def best_w(rows):
    num = sum((r["p"] - r["q"]) * (r["y"] - r["q"]) for r in rows)
    den = sum((r["p"] - r["q"]) ** 2 for r in rows)
    return num / den if den else 0.0


def qualifying(rows, w):
    out = []
    for r in rows:
        p = blend(r, w)
        if p - r["q"] >= RULE_EDGE and p * r["odds"] - 1 >= RULE_RETURN:
            out.append(r)
    return out


def roi(rows):
    return sum((r["odds"] - 1) if r["y"] else -1.0 for r in rows) / len(rows) if rows else None


def main():
    rows, source = load_rows()
    n = len(rows)
    report = {"mode": "PAPER_ONLY_REPORT_ONLY", "source": source, "n": n,
              "note": "Does not change any qualification rule or board output."}
    if n < MIN_N:
        report["status"] = "insufficient settled picks (need %d)" % MIN_N
        print(report["status"])
        (DATA / "shrinkage_shadow_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return 0
    rng = random.Random(7)
    w_hat = best_w(rows)
    boots = sorted(best_w([rng.choice(rows) for _ in rows]) for _ in range(4000))
    report["best_fit_weight_on_model"] = round(w_hat, 3)
    report["best_fit_weight_95_range"] = [round(boots[100], 3), round(boots[3900], 3)]
    report["scores"] = {"market": {"brier": round(brier(rows, lambda r: r["q"]), 4), "logloss": round(logloss(rows, lambda r: r["q"]), 4)}}
    for w in (1.0, 0.75, 0.5, 0.35, 0.25):
        f = lambda r, w=w: blend(r, w)
        report["scores"]["w=%.2f" % w] = {"brier": round(brier(rows, f), 4), "logloss": round(logloss(rows, f), 4)}
    base = qualifying(rows, 1.0)
    report["qualifying"] = {}
    for w in (1.0, 0.75, 0.5, 0.35, 0.25):
        k = qualifying(rows, w)
        report["qualifying"]["w=%.2f" % w] = {
            "kept": len(k), "of_picks": n, "share_of_todays_qualifying": round(len(k) / len(base), 3) if base else None,
            "hit_rate": round(sum(r["y"] for r in k) / len(k), 4) if k else None, "roi": round(roi(k), 4) if k else None}
    half = n // 2
    first, second = rows[:half], rows[half:]
    wa = best_w(first)
    report["held_out_check"] = {
        "weight_fit_on_first_half": round(wa, 3), "second_half_n": len(second),
        "second_half_brier_blended": round(brier(second, lambda r: blend(r, wa)), 4),
        "second_half_brier_raw_model": round(brier(second, lambda r: r["p"]), 4),
        "second_half_brier_market": round(brier(second, lambda r: r["q"]), 4)}
    (DATA / "shrinkage_shadow_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    md = ["# Shrinkage shadow test (report only)", "",
          "Does not change any qualification rule or board output. Source: `%s`, %d settled picks. blended = market + w x (model - market)." % (source, n), "",
          "Best-fit weight on the model: **%.2f** (95%% bootstrap range %.2f to %.2f). 1.00 would mean the model's probabilities can be trusted as stated; 0.00 would mean the market price alone is better." % (w_hat, boots[100], boots[3900]), "",
          "| Probabilities | Brier (lower is better) | Log loss |", "|---|---|---|"]
    for name, s in report["scores"].items():
        md.append("| %s | %s | %s |" % (name, s["brier"], s["logloss"]))
    md += ["", "Picks that would still meet the page's +2% edge and +2% expected-return minimums:", "",
           "| Weight | Kept | Share of today's qualifying | Hit rate | ROI at quoted odds |", "|---|---|---|---|---|"]
    for name, q in report["qualifying"].items():
        md.append("| %s | %d of %d | %s | %s | %s |" % (
            name, q["kept"], q["of_picks"], "-" if q["share_of_todays_qualifying"] is None else "%.0f%%" % (100 * q["share_of_todays_qualifying"]),
            "-" if q["hit_rate"] is None else "%.1f%%" % (100 * q["hit_rate"]), "-" if q["roi"] is None else "%+.1f%%" % (100 * q["roi"])))
    h = report["held_out_check"]
    md += ["", "Held-out check: weight fit on the first half (%.2f), scored on the second half (%d picks): blended Brier %s, raw model %s, market %s." % (
        h["weight_fit_on_first_half"], h["second_half_n"], h["second_half_brier_blended"], h["second_half_brier_raw_model"], h["second_half_brier_market"]), "",
        "ROI figures are in-sample on a small number of picks; read them as direction, not proof."]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "SHRINKAGE_SHADOW.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("shrinkage shadow test: n=%d best-fit weight %.2f (%.2f to %.2f)" % (n, w_hat, boots[100], boots[3900]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
