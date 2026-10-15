#!/usr/bin/env python3
"""Match Signal paper-record report (stdlib only, PAPER ONLY).

Reads the settled-pick files the system already writes and produces:
  * data/paper_record_report.json  - every number, machine readable
  * docs/PAPER_RECORD.md           - human readable record: where performance was
                                     high / low, calibration, and candidate reasons
  * data/paper_record_ledger.json  - append-only ledger of settled eFootball desk
                                     picks (upstream history files are capped, so
                                     this keeps picks after they roll out)

It never edits predictions, odds or settlements. "Why" sections list observed
associations only; they are not proven causes.
"""
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"
MIN_N = 30          # below this a segment is labelled insufficient
SEG_MIN_N = 150     # market-baseline segments need this many rows to be ranked


def load(name, default=None):
    path = DATA / name
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def day_of(value):
    return str(value or "")[:10]


def week_of(value):
    try:
        y, m, d = (int(x) for x in day_of(value).split("-"))
        iso = date(y, m, d).isocalendar()
        return "%d-W%02d" % (iso[0], iso[1])
    except Exception:
        return None


def mean_sd(values):
    n = len(values)
    if n == 0:
        return 0, 0.0, 0.0
    m = sum(values) / n
    if n < 2:
        return n, m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return n, m, math.sqrt(var)


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - a) / d, (c + a) / d)


def r(x, nd=4):
    return None if x is None else round(x, nd)


def bet_stats(rows, odds_key="odds", win_key="win", prob_key=None):
    """Flat 1-unit stake at the quoted decimal odds. Pushes/voids must be removed first."""
    rois, wins, probs, implied, briers_m, briers_k = [], 0, [], [], [], []
    for row in rows:
        odds = row.get(odds_key)
        win = row.get(win_key)
        if odds is None or win is None or odds <= 1:
            continue
        rois.append((odds - 1) if win else -1.0)
        wins += 1 if win else 0
        implied.append(1.0 / odds)
        if prob_key and row.get(prob_key) is not None:
            probs.append(row[prob_key])
            briers_m.append((row[prob_key] - (1 if win else 0)) ** 2)
        briers_k.append((1.0 / odds - (1 if win else 0)) ** 2)
    n, m, sd = mean_sd(rois)
    out = {"n": n, "wins": wins}
    if n == 0:
        return out
    half = 1.96 * sd / math.sqrt(n) if n > 1 else None
    lo, hi = wilson(wins, n)
    out.update({
        "hit_rate": r(wins / n), "hit_ci95": [r(lo), r(hi)],
        "avg_odds": r(sum(row[odds_key] for row in rows if row.get(odds_key) and row.get(win_key) is not None) / n, 3),
        "implied_prob": r(sum(implied) / n),
        "roi": r(m), "roi_ci95": [r(m - half) if half is not None else None, r(m + half) if half is not None else None],
        "insufficient": n < MIN_N,
    })
    if probs:
        out["mean_model_prob"] = r(sum(probs) / len(probs))
        out["overconfidence_gap"] = r(sum(probs) / len(probs) - wins / n)
        out["brier_model"] = r(sum(briers_m) / len(briers_m))
    out["brier_market"] = r(sum(briers_k) / len(briers_k))
    return out


def group(rows, keyfn):
    buckets = defaultdict(list)
    for row in rows:
        key = keyfn(row)
        if key is not None:
            buckets[key].append(row)
    return buckets


def bucket(value, edges):
    for lo, hi in edges:
        if lo <= value < hi:
            return "%.2f-%.2f" % (lo, hi)
    return None


# ----------------------------------------------------------------- ledger
LEDGER_FIELDS = ["key", "product", "start_time", "competition", "line", "pick", "model_probability",
                 "bookmaker_odds", "model_edge_vs_market", "win", "push", "score", "observed_at",
                 "settled_at", "model_version"]


def update_ledger():
    path = DATA / "paper_record_ledger.json"
    existing = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    by_key = {row["key"]: row for row in existing}
    added = 0
    sources = []
    sources.extend(load("efootball_desk_settled_observations.json", []) or [])
    history = load("efootball_desk_prediction_history.json", []) or []
    sources.extend(row for row in history if row.get("settled"))
    for row in sources:
        if not row.get("settled") or row.get("win") is None:
            continue
        key = row.get("event_key") or row.get("observation_key") or row.get("trace_id")
        if not key or key in by_key:
            continue
        item = {field: row.get(field) for field in LEDGER_FIELDS if field != "key"}
        item["key"] = key
        by_key[key] = item
        added += 1
    merged = sorted(by_key.values(), key=lambda x: (str(x.get("start_time")), x["key"]))
    if added or not path.exists():
        path.write_text(json.dumps(merged, separators=(",", ":")), encoding="utf-8")
    return merged, added


# ------------------------------------------------------------ eFootball picks
def efootball_section(ledger, market_rows):
    rows = [x for x in ledger if x.get("win") is not None and not x.get("push") and x.get("bookmaker_odds")]
    for x in rows:
        x["_day"] = day_of(x.get("start_time"))
    section = {"coverage": {
        "settled_picks": len(rows),
        "first_day": min((x["_day"] for x in rows), default=None),
        "last_day": max((x["_day"] for x in rows), default=None),
    }}
    section["overall"] = bet_stats(rows, "bookmaker_odds", "win", "model_probability")
    days = {x["_day"] for x in rows}
    base = [m for m in market_rows if m.get("product") == "efootball_gt" and m.get("market") == "ou" and day_of(m.get("timestamp")) in days]
    section["baseline_bet_every_efootball_ou_price_same_days"] = bet_stats(base, "odds", "win")
    section["by_day"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability") for k, v in sorted(group(rows, lambda x: x["_day"]).items())}
    section["by_side"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability") for k, v in sorted(group(rows, lambda x: x.get("pick")).items())}
    section["by_line_side"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability")
                               for k, v in sorted(group(rows, lambda x: "%s %s" % (x.get("pick"), x.get("line"))).items())}
    section["by_product"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability") for k, v in sorted(group(rows, lambda x: x.get("product")).items())}
    edge_edges = [(-1, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 1.01)]
    section["by_claimed_edge"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability")
                                  for k, v in sorted(group(rows, lambda x: bucket(x.get("model_edge_vs_market") or 0, edge_edges)).items())}
    prob_edges = [(0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    section["calibration_by_model_prob"] = {k: bet_stats(v, "bookmaker_odds", "win", "model_probability")
                                            for k, v in sorted(group(rows, lambda x: bucket(x.get("model_probability") or 0, prob_edges)).items())}
    return section


# --------------------------------------------------- football / tennis win picks
def winprob_section():
    history = load("prediction_history.json", []) or []
    settled = [x for x in history if x.get("settled") and x.get("correct") is not None and x.get("confidence") is not None]
    for x in settled:
        x["_week"] = week_of(x.get("start_time"))
        x["_day"] = day_of(x.get("start_time"))

    def stats(rows):
        n = len(rows)
        if n == 0:
            return {"n": 0}
        wins = sum(1 for x in rows if x["correct"])
        lo, hi = wilson(wins, n)
        conf = sum(x["confidence"] for x in rows) / n
        brier = [x["brier"] for x in rows if x.get("brier") is not None]
        return {"n": n, "accuracy": r(wins / n), "accuracy_ci95": [r(lo), r(hi)], "mean_confidence": r(conf),
                "overconfidence_gap": r(conf - wins / n),
                "brier": r(sum(brier) / len(brier)) if brier else None, "insufficient": n < MIN_N}

    conf_edges = [(0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)]
    days = sorted(group(settled, lambda x: x["_day"]).keys())
    gaps = []
    if days:
        d0 = date.fromisoformat(days[0])
        d1 = date.fromisoformat(days[-1])
        counts = {d: len(v) for d, v in group(settled, lambda x: x["_day"]).items()}
        have = {d for d, c in counts.items() if c >= 5}
        cur = d0
        run = []
        while cur <= d1:
            iso = cur.isoformat()
            if iso not in have:
                run.append(iso)
            elif run:
                if len(run) >= 3:
                    gaps.append({"from": run[0], "to": run[-1], "days": len(run)})
                run = []
            cur = date.fromordinal(cur.toordinal() + 1)
        if len(run) >= 3:
            gaps.append({"from": run[0], "to": run[-1], "days": len(run)})
    return {
        "coverage": {"settled_picks": len(settled), "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
                     "thin_data_runs_3plus_days_with_under_5_settled_picks": gaps},
        "overall": stats(settled),
        "by_sport": {k: stats(v) for k, v in sorted(group(settled, lambda x: x.get("sport")).items())},
        "by_week": {k: stats(v) for k, v in sorted(group(settled, lambda x: x["_week"]).items())},
        "by_league": {k: stats(v) for k, v in sorted(group(settled, lambda x: "%s / %s" % (x.get("sport"), x.get("league"))).items())},
        "by_model": {k: stats(v) for k, v in sorted(group(settled, lambda x: "%s / %s" % (x.get("sport"), x.get("model"))).items())},
        "calibration_by_confidence": {k: stats(v) for k, v in sorted(group(settled, lambda x: bucket(x["confidence"], conf_edges)).items())},
    }


# ----------------------------------------------------------------- tickets
def tickets_section():
    tracker = load("odds_ticket_tracker.json", {}) or {}
    tickets = list(tracker.get("tickets", [])) + list(tracker.get("archived_tickets", []))
    rows = []
    for t in tickets:
        if t.get("status") not in ("WON", "LOST") or not t.get("combined_odds"):
            continue
        rows.append({"odds": t["combined_odds"], "win": t["status"] == "WON", "p": t.get("combined_model_probability"),
                     "lane": t.get("primary_lane"), "legs": t.get("leg_count"), "week": week_of(t.get("created_at"))})
    st = lambda rs: bet_stats(rs, "odds", "win", "p")
    return {
        "note": "Tickets reuse the same legs, so they are not independent; confidence ranges are optimistic.",
        "overall": st(rows),
        "by_week_created": {k: st(v) for k, v in sorted(group(rows, lambda x: x["week"]).items())},
        "by_lane": {k: st(v) for k, v in sorted(group(rows, lambda x: x["lane"]).items())},
        "by_leg_count": {str(k): st(v) for k, v in sorted(group(rows, lambda x: x["legs"]).items())},
    }


def tennis_trial_section():
    trials = (load("value_trial_ledger.json", {}) or {}).get("trials", [])
    rows = [{"odds": t.get("frozen_odds"), "win": t.get("won"), "p": t.get("model_probability")} for t in trials]
    return {"overall": bet_stats(rows, "odds", "win", "p"), "approval_hurdle": "30 trials and positive realized ROI (from the ledger)"}


# ------------------------------------------------------- market baseline
def market_baseline_section(history):
    rows = [x for x in history if x.get("win") is not None and x.get("odds")]
    for x in rows:
        x["_day"] = day_of(x.get("timestamp"))
        x["_half"] = None
    overall = {}
    for product, v in sorted(group(rows, lambda x: x.get("product")).items()):
        overall[product] = bet_stats(v, "odds", "win", "model_prob")
    segs = {}
    for (product, market, name), v in group(rows, lambda x: (x.get("product"), x.get("market"), x.get("selection_name"))).items():
        if len(v) < SEG_MIN_N:
            continue
        v = sorted(v, key=lambda x: x["_day"])
        mid = len(v) // 2
        s = bet_stats(v, "odds", "win")
        s["first_half_roi"] = bet_stats(v[:mid], "odds", "win").get("roi")
        s["second_half_roi"] = bet_stats(v[mid:], "odds", "win").get("roi")
        segs["%s / %s / %s" % (product, market, name)] = s
    ranked = sorted(segs.items(), key=lambda kv: kv[1].get("roi", -9))
    by_day = {}
    for product, v in group(rows, lambda x: x.get("product")).items():
        by_day[product] = {k: bet_stats(d, "odds", "win") for k, d in sorted(group(v, lambda x: x["_day"]).items())}
    return {
        "note": "Flat 1-unit stakes on EVERY quoted price. This is the bookmaker baseline, not the model's picks. "
                "model_prob in this file is the de-vigged market price, so Brier here compares price to itself.",
        "coverage": {"rows": len(rows), "first_day": min((x["_day"] for x in rows), default=None), "last_day": max((x["_day"] for x in rows), default=None)},
        "segments_tested": len(segs),
        "expected_false_positives_at_5pct": round(len(segs) * 0.05, 1),
        "overall_by_product": overall,
        "lowest_roi_segments": [dict(segment=k, **v) for k, v in ranked[:8]],
        "highest_roi_segments": [dict(segment=k, **v) for k, v in ranked[::-1][:8]],
        "by_day": by_day,
    }


# ------------------------------------------------------------- narrative
def findings(report):
    out = []
    ef = report["efootball_desk_picks"]["overall"]
    if ef.get("n"):
        out.append("eFootball desk singles: %d settled, hit %.1f%% vs %.1f%% implied by the odds, ROI %+.1f%% (95%% range %+.0f%% to %+.0f%%). Model claimed %.1f%% on average (gap %+.1f points)." % (
            ef["n"], 100 * ef["hit_rate"], 100 * ef["implied_prob"], 100 * ef["roi"], 100 * ef["roi_ci95"][0], 100 * ef["roi_ci95"][1],
            100 * ef["mean_model_prob"], 100 * ef["overconfidence_gap"]))
    base = report["efootball_desk_picks"].get("baseline_bet_every_efootball_ou_price_same_days", {})
    if base.get("n") and ef.get("n"):
        out.append("Same days, same product: betting EVERY eFootball over/under price returned %+.1f%% (n=%d). The model's picks returned %+.1f%%. That gap of %.1f points is the model's selection value so far, but the picks' own range (%+.0f%% to %+.0f%%) still includes the blanket result." % (
            100 * base["roi"], base["n"], 100 * ef["roi"], 100 * (ef["roi"] - base["roi"]), 100 * ef["roi_ci95"][0], 100 * ef["roi_ci95"][1]))
    days = report["efootball_desk_picks"]["by_day"]
    ranked = sorted(((k, v) for k, v in days.items() if v.get("n", 0) >= MIN_N), key=lambda kv: kv[1]["roi"])
    if len(ranked) >= 2:
        out.append("Best day (n>=%d): %s ROI %+.1f%% (n=%d). Worst day: %s ROI %+.1f%% (n=%d)." % (
            MIN_N, ranked[-1][0], 100 * ranked[-1][1]["roi"], ranked[-1][1]["n"], ranked[0][0], 100 * ranked[0][1]["roi"], ranked[0][1]["n"]))
    elif len(ranked) == 1:
        out.append("Only one day has %d+ settled eFootball picks (%s), so there is no high/low comparison between days yet." % (MIN_N, ranked[0][0]))
    wp = report["football_tennis_win_picks"]
    if wp["overall"].get("n"):
        o = wp["overall"]
        out.append("Football/tennis win picks: %d settled, accuracy %.1f%%, mean confidence %.1f%% (gap %+.1f points), Brier %s." % (
            o["n"], 100 * o["accuracy"], 100 * o["mean_confidence"], 100 * o["overconfidence_gap"], o["brier"]))
    weeks = sorted(((k, v) for k, v in wp["by_week"].items() if v.get("n", 0) >= MIN_N), key=lambda kv: kv[1]["accuracy"] - kv[1]["mean_confidence"])
    if len(weeks) >= 2:
        w_lo, w_hi = weeks[0], weeks[-1]
        out.append("Win picks, weakest week vs its own confidence: %s (n=%d) accuracy %.1f%% vs %.1f%% stated. Strongest: %s (n=%d) accuracy %.1f%% vs %.1f%% stated." % (
            w_lo[0], w_lo[1]["n"], 100 * w_lo[1]["accuracy"], 100 * w_lo[1]["mean_confidence"],
            w_hi[0], w_hi[1]["n"], 100 * w_hi[1]["accuracy"], 100 * w_hi[1]["mean_confidence"]))
    models = sorted(((k, v) for k, v in wp["by_model"].items() if v.get("n", 0) >= MIN_N), key=lambda kv: kv[1]["overconfidence_gap"])
    if len(models) >= 2:
        out.append("Most honest model line (n>=%d): %s, gap %+.1f points. Most overconfident: %s, gap %+.1f points." % (
            MIN_N, models[0][0], 100 * models[0][1]["overconfidence_gap"], models[-1][0], 100 * models[-1][1]["overconfidence_gap"]))
    leagues = sorted(((k, v) for k, v in wp["by_league"].items() if v.get("n", 0) >= MIN_N), key=lambda kv: kv[1]["accuracy"])
    if len(leagues) >= 2:
        out.append("League extremes (n>=%d): lowest accuracy %s %.1f%% (n=%d); highest %s %.1f%% (n=%d)." % (
            MIN_N, leagues[0][0], 100 * leagues[0][1]["accuracy"], leagues[0][1]["n"], leagues[-1][0], 100 * leagues[-1][1]["accuracy"], leagues[-1][1]["n"]))
    for gap in wp["coverage"]["thin_data_runs_3plus_days_with_under_5_settled_picks"]:
        out.append("Thin data: fewer than 5 settled football/tennis picks per day from %s to %s (%d days). Trends across that stretch are not comparable." % (gap["from"], gap["to"], gap["days"]))
    mb = report["market_baseline_virtual_lab"]
    out.append("Market baseline: %d rows, %d segments ranked, ~%s would look 'significant' by chance alone." % (
        mb["coverage"]["rows"], mb["segments_tested"], mb["expected_false_positives_at_5pct"]))
    return out


def fmt(x, pct=False, signed=False):
    if x is None:
        return "-"
    if pct:
        return ("%+.1f%%" if signed else "%.1f%%") % (100 * x)
    return str(x)


def table(rows, header):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def bet_rows(d, keep_small=True):
    rows = []
    for k, v in d.items():
        if not v.get("n"):
            continue
        if not keep_small and v.get("insufficient"):
            continue
        ci = v.get("roi_ci95") or [None, None]
        rows.append([k, v["n"], fmt(v.get("hit_rate"), True), fmt(v.get("implied_prob"), True), fmt(v.get("mean_model_prob"), True),
                     fmt(v.get("roi"), True, True), "%s to %s" % (fmt(ci[0], True, True), fmt(ci[1], True, True)),
                     "small n" if v.get("insufficient") else ""])
    return rows


BET_HEAD = ["Segment", "n", "Hit", "Odds imply", "Model said", "ROI", "95% range", "Note"]


def win_rows(d):
    rows = []
    for k, v in d.items():
        if not v.get("n"):
            continue
        rows.append([k, v["n"], fmt(v.get("accuracy"), True), fmt(v.get("mean_confidence"), True),
                     fmt(v.get("overconfidence_gap"), True, True), v.get("brier"), "small n" if v.get("insufficient") else ""])
    return rows


WIN_HEAD = ["Segment", "n", "Accuracy", "Mean confidence", "Gap", "Brier", "Note"]


def markdown(report):
    md = ["# Match Signal paper record", "",
          "Generated %s. PAPER ONLY. Numbers come from settled results in this repo; nothing here edits predictions, odds or settlements." % report["generated_at"], "",
          "ROI = flat 1-unit stake at the quoted decimal odds. 'Model said' is the model's average stated win probability; a large positive gap means overconfidence. "
          "Ranges are 95% normal-approximation intervals and are wide on small samples. 'Why' lines are observed associations, not proven causes.", "",
          "## Headline", ""]
    md += ["- " + line for line in report["findings"]]
    md += ["", "## Coverage (how far back each record goes)", ""]
    cov = [["eFootball desk singles (ledger)", report["efootball_desk_picks"]["coverage"]["settled_picks"], report["efootball_desk_picks"]["coverage"]["first_day"], report["efootball_desk_picks"]["coverage"]["last_day"]],
           ["Football/tennis win picks", report["football_tennis_win_picks"]["coverage"]["settled_picks"], report["football_tennis_win_picks"]["coverage"]["first_day"], report["football_tennis_win_picks"]["coverage"]["last_day"]],
           ["Market baseline (Virtual Lab history)", report["market_baseline_virtual_lab"]["coverage"]["rows"], report["market_baseline_virtual_lab"]["coverage"]["first_day"], report["market_baseline_virtual_lab"]["coverage"]["last_day"]]]
    md += [table(cov, ["Record", "Settled rows", "First day", "Last day"]), "",
           "Older Virtual Lab history was frozen before the 2026-09-22 rebuild (see `data/virtual_lab_archive/2026-09-22/manifest.json`); it is not part of these numbers.", ""]
    ef = report["efootball_desk_picks"]
    md += ["## eFootball desk single picks (what Qualified Best shows)", "", "### Overall and by segment", "",
           table(bet_rows({"ALL": ef["overall"]}) + bet_rows(ef["by_product"]) + bet_rows(ef["by_side"]), BET_HEAD), "",
           "### By day (high and low periods)", "", table(bet_rows(ef["by_day"]), BET_HEAD), "",
           "### By line and side", "", table(bet_rows(ef["by_line_side"]), BET_HEAD), "",
           "### Does a bigger claimed edge pay more?", "", table(bet_rows(ef["by_claimed_edge"]), BET_HEAD), "",
           "If realized ROI does not rise with the claimed edge, the edge number is not informative.", "",
           "### Calibration: model probability vs how often it won", "", table(bet_rows(ef["calibration_by_model_prob"]), BET_HEAD), ""]
    wp = report["football_tennis_win_picks"]
    md += ["## Football and tennis win picks", "", table(win_rows({"ALL": wp["overall"]}) + win_rows(wp["by_sport"]), WIN_HEAD), "",
           "### By week", "", table(win_rows(wp["by_week"]), WIN_HEAD), "",
           "### By league", "", table(win_rows(wp["by_league"]), WIN_HEAD), "",
           "### By model (changes in model line up with changes in results only as an association)", "", table(win_rows(wp["by_model"]), WIN_HEAD), "",
           "### Calibration by stated confidence", "", table(win_rows(wp["calibration_by_confidence"]), WIN_HEAD), ""]
    tk = report["accumulator_tickets"]
    md += ["## Accumulator tickets", "", tk["note"], "", table(bet_rows({"ALL": tk["overall"]}) + bet_rows(tk["by_lane"]) + bet_rows({"%s legs" % k: v for k, v in tk["by_leg_count"].items()}), BET_HEAD), "",
           "### By week created", "", table(bet_rows(tk["by_week_created"]), BET_HEAD), ""]
    tt = report["tennis_value_trial"]
    md += ["## Tennis value trial", "", table(bet_rows({"ALL": tt["overall"]}), BET_HEAD), "", "Approval hurdle: " + tt["approval_hurdle"], ""]
    mb = report["market_baseline_virtual_lab"]
    md += ["## Market baseline (bookmaker prices, not the model)", "", mb["note"], "",
           "Segments ranked: %d. About %s would appear significant by chance." % (mb["segments_tested"], mb["expected_false_positives_at_5pct"]), "",
           table(bet_rows(mb["overall_by_product"]), BET_HEAD), "",
           "### Lowest-ROI segments (n>=%d)" % SEG_MIN_N, "",
           table([[s["segment"], s["n"], fmt(s["hit_rate"], True), fmt(s["implied_prob"], True), fmt(s["roi"], True, True), fmt(s["first_half_roi"], True, True), fmt(s["second_half_roi"], True, True)] for s in mb["lowest_roi_segments"]],
                 ["Segment", "n", "Hit", "Odds imply", "ROI", "1st half", "2nd half"]), "",
           "### Highest-ROI segments (n>=%d)" % SEG_MIN_N, "",
           table([[s["segment"], s["n"], fmt(s["hit_rate"], True), fmt(s["implied_prob"], True), fmt(s["roi"], True, True), fmt(s["first_half_roi"], True, True), fmt(s["second_half_roi"], True, True)] for s in mb["highest_roi_segments"]],
                 ["Segment", "n", "Hit", "Odds imply", "ROI", "1st half", "2nd half"]), "",
           "A segment is only interesting if both halves are positive and the range excludes zero; with this many segments, a few good-looking ones are expected by chance.", ""]
    return "\n".join(md)


def main():
    ledger, added = update_ledger()
    history = load("virtual_lab_history.json", []) or []
    market_rows = [x for x in history if x.get("win") is not None and x.get("odds")]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
        "mode": "PAPER_ONLY",
        "ledger_rows": len(ledger),
        "ledger_rows_added_this_run": added,
        "efootball_desk_picks": efootball_section(ledger, market_rows),
        "football_tennis_win_picks": winprob_section(),
        "accumulator_tickets": tickets_section(),
        "tennis_value_trial": tennis_trial_section(),
        "market_baseline_virtual_lab": market_baseline_section(history),
    }
    report["findings"] = findings(report)
    out_json = DATA / "paper_record_report.json"
    out_md = DOCS / "PAPER_RECORD.md"
    if out_json.exists() and out_md.exists():
        try:
            previous = json.loads(out_json.read_text(encoding="utf-8"))
            if {k: v for k, v in previous.items() if k != "generated_at"} == {k: v for k, v in report.items() if k != "generated_at"}:
                print("paper record unchanged; leaving files as they are")
                return 0
        except Exception:
            pass
    out_json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    DOCS.mkdir(exist_ok=True)
    out_md.write_text(markdown(report), encoding="utf-8")
    print("paper record: ledger=%d (+%d), efootball=%d, win_picks=%d" % (
        len(ledger), added, report["efootball_desk_picks"]["overall"].get("n", 0), report["football_tennis_win_picks"]["overall"].get("n", 0)))


if __name__ == "__main__":
    sys.exit(main())
