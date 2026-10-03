"""VFootball time-safe ticket walk-forward audit (PAPER / RESEARCH ONLY).

Diagnostic only. This script does NOT change Odds Builder selection, gates, data,
archives or settlement records. It reads data/virtual_lab_history.json and writes
data/vfootball_walkforward_audit.json.

What it does
------------
1. Rebuilds VFootball O/U events from settled history (VFootball only; no eFootball).
2. Walks forward in kickoff order. For every 60-minute kickoff window it freezes the
   odds snapshots (captured_at) and uses ONLY events whose result was knowable
   before the earliest snapshot in the window (kickoff + RESULT_LAG_SECONDS).
3. Builds the best 2/3/4-leg ticket per window under the intended constraint
   (combined odds >= MIN_COMBINED_ODDS) using each method's own probabilities:
     A  proxy of current VFootball lane: product of Poisson leg probabilities x 0.90
     B  naive independent product of Poisson leg probabilities
     C  walk-forward calibrated leg probabilities, independent product
     D  C + pairwise dependence factor estimated from earlier events only
     D91 C + fixed 0.91 per-pair decay (hypothesis test, not fitted)
     E  conservative market-referenced: legs need calibrated >= de-vigged market,
        ticket probability uses min(calibrated, market)
4. Scores each method: tickets, accuracy, mean predicted probability, Brier, average
   odds, flat-stake ROI, max drawdown, calibration bins, Wilson 95% interval, for the
   full walk-forward and for the last-30% chronological holdout.
5. Reports reachability: in how many windows is a 2.70+ ticket reachable at all for a
   given per-leg probability tier.
6. Reports pairwise co-occurrence (observed joint vs multiplied marginals).

Tiers 0.90 and 0.80 are the production safety tiers. Tiers 0.70 and 0.60 are
DIAGNOSTIC ONLY to show the accuracy/odds trade-off; they are never eligible.

Run:
    python scripts/vfootball_walkforward_audit.py
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "virtual_lab_history.json"
OUTPUT = DATA / "vfootball_walkforward_audit.json"

MIN_COMBINED_ODDS = 2.70
SPAN_SECONDS = 3600
RESULT_LAG_SECONDS = 600
HOLDOUT_FRACTION = 0.30
CAL_PRIOR_STRENGTH = 100.0
ACCURACY_PRESERVATION_RATIO = 0.90
FIXED_PAIR_DECAY = 0.91
MIN_PAIRS_FOR_FACTOR = 2000
PAIR_FACTOR_BOUNDS = (0.5, 1.05)
PAIR_MIN_MARGINAL = 0.60
PRODUCTION_TIERS = (0.90, 0.80)
DIAGNOSTIC_TIERS = (0.70, 0.60)
TIERS = PRODUCTION_TIERS + DIAGNOSTIC_TIERS
SHAPES = (2, 3, 4)
METHODS = ("A", "B", "C", "D", "D91", "E")


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def clamp(p):
    return max(0.0005, min(0.9995, float(p)))


def poisson_over(lam, line):
    k = math.floor(line)
    pmf = math.exp(-lam)
    cdf = pmf
    for i in range(1, k + 1):
        pmf *= lam / i
        cdf += pmf
    return clamp(1.0 - cdf)


def fit_lambda(points):
    best_lam, best_loss = 2.5, float("inf")
    for i in range(10, 1201):
        lam = i / 50.0
        loss = sum((poisson_over(lam, line) - p) ** 2 for line, p in points)
        if loss < best_loss:
            best_lam, best_loss = lam, loss
    return best_lam


def wilson(wins, n, z=1.96):
    if n <= 0:
        return None
    phat = wins / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    spread = z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))
    return [round((centre - spread) / denom, 4), round((centre + spread) / denom, 4)]


def load_events(path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    groups = {}
    for r in rows:
        if r.get("product") != "vfootball" or r.get("market") != "ou":
            continue
        if r.get("win") is None or r.get("line") is None or r.get("model_prob") is None:
            continue
        try:
            odds = float(r["odds"])
            p_mkt = float(r["model_prob"])
            line = float(r["line"])
        except (TypeError, ValueError, KeyError):
            continue
        ts = parse_ts(r.get("timestamp"))
        cap = parse_ts(r.get("captured_at"))
        if ts is None or cap is None or odds <= 1.0 or cap >= ts:
            continue
        sel = str(r.get("selection") or "").upper()[:1]
        if sel not in {"O", "U"}:
            continue
        key = f"{r.get('event_id')}|{r.get('timestamp')}"
        g = groups.setdefault(key, {"key": key, "ts": ts, "cap": cap, "rows": [], "total": None})
        g["cap"] = min(g["cap"], cap)
        score = str(r.get("score") or "").replace(" ", "").split(":")
        if g["total"] is None and len(score) == 2:
            try:
                g["total"] = float(score[0]) + float(score[1])
            except ValueError:
                pass
        g["rows"].append({
            "line": line, "sel": sel, "odds": odds, "p_mkt": clamp(p_mkt),
            "win": bool(r["win"]),
        })
    events = []
    for g in groups.values():
        if g["total"] is None or len(g["rows"]) < 3:
            continue
        pts = [(x["line"], x["p_mkt"] if x["sel"] == "O" else 1.0 - x["p_mkt"]) for x in g["rows"]]
        lam = fit_lambda(pts)
        for x in g["rows"]:
            over = poisson_over(lam, x["line"])
            x["p_pois"] = over if x["sel"] == "O" else clamp(1.0 - over)
        events.append(g)
    events.sort(key=lambda e: e["ts"])
    return events


class Knowledge:
    """Everything learnable from events whose results were known before a cutoff."""

    def __init__(self, events):
        self.events = events
        self.idx = 0
        self.counts = defaultdict(lambda: [0, 0])
        self.recent = deque()
        self.pair_obs = 0.0
        self.pair_exp = 0.0
        self.pair_n = 0

    def advance(self, cutoff):
        while self.idx < len(self.events) and self.events[self.idx]["ts"] + RESULT_LAG_SECONDS < cutoff:
            self._add(self.events[self.idx])
            self.idx += 1

    def _add(self, ev):
        for x in ev["rows"]:
            c = self.counts[(x["line"], x["sel"])]
            c[0] += 1
            c[1] += 1 if x["win"] else 0
        while self.recent and ev["ts"] - self.recent[0]["ts"] > SPAN_SECONDS:
            self.recent.popleft()
        for old in self.recent:
            for a in ev["rows"]:
                if a["p_mkt"] < PAIR_MIN_MARGINAL:
                    continue
                for b in old["rows"]:
                    if b["p_mkt"] < PAIR_MIN_MARGINAL:
                        continue
                    self.pair_n += 1
                    self.pair_exp += a["p_mkt"] * b["p_mkt"]
                    self.pair_obs += 1.0 if (a["win"] and b["win"]) else 0.0
        self.recent.append(ev)

    def calibrated(self, leg):
        n, w = self.counts[(leg["line"], leg["sel"])]
        return clamp((w + CAL_PRIOR_STRENGTH * leg["p_pois"]) / (n + CAL_PRIOR_STRENGTH))

    def pair_factor(self):
        if self.pair_n < MIN_PAIRS_FOR_FACTOR or self.pair_exp <= 0:
            return 1.0, False
        f = self.pair_obs / self.pair_exp
        return max(PAIR_FACTOR_BOUNDS[0], min(PAIR_FACTOR_BOUNDS[1], f)), True


def make_windows(events):
    windows, i = [], 0
    while i < len(events):
        start = events[i]["ts"]
        j = i
        while j < len(events) and events[j]["ts"] - start <= SPAN_SECONDS:
            j += 1
        windows.append(events[i:j])
        i = j
    return windows


def leg_pool(window, know):
    """One best-supported leg per event, per probability source, frozen at decision time."""
    legs = []
    for ev in window:
        for x in ev["rows"]:
            legs.append({
                "event": ev["key"], "line": x["line"], "sel": x["sel"], "odds": x["odds"],
                "p_pois": x["p_pois"], "p_mkt": x["p_mkt"], "p_cal": know.calibrated(x),
                "win": x["win"],
            })
    return legs


def method_prob(method, leg):
    if method in {"A", "B"}:
        return leg["p_pois"]
    if method in {"C", "D", "D91"}:
        return leg["p_cal"]
    if method == "E":
        return min(leg["p_cal"], leg["p_mkt"]) if leg["p_cal"] >= leg["p_mkt"] else 0.0
    return 0.0


def ticket_prob(method, probs, n, pair_f):
    raw = math.prod(probs)
    pairs = n * (n - 1) // 2
    if method == "A":
        return clamp(raw * ACCURACY_PRESERVATION_RATIO)
    if method == "D":
        return clamp(raw * (pair_f ** pairs))
    if method == "D91":
        return clamp(raw * (FIXED_PAIR_DECAY ** pairs))
    return clamp(raw)


def best_ticket(method, legs, tier, n, min_odds, pair_f):
    """Exact-ish search: maximise ticket probability subject to combined odds >= min_odds.

    Every eligible leg (probability >= tier) is a candidate; at most one leg per event.
    Dynamic programme over events on discretised log-odds (bin 0.002). The feasibility
    test uses the true odds product, so discretisation can only miss, never invent, a ticket.
    """
    by_event = defaultdict(list)
    for leg in legs:
        p = method_prob(method, leg)
        if p >= tier:
            by_event[leg["event"]].append((p, leg))
    if len(by_event) < n:
        return None, False
    target = math.log(min_odds)
    step = 0.002
    cap = int(math.log(12.0) / step)
    # states[k] maps odds-bin -> (sum log p, combo list)
    states = [dict() for _ in range(n + 1)]
    states[0][0] = (0.0, [])
    for ev_legs in by_event.values():
        for k in range(n - 1, -1, -1):
            for b, (lp, combo) in list(states[k].items()):
                for p, leg in ev_legs:
                    nb = min(cap, b + int(round(math.log(leg["odds"]) / step)))
                    cand = (lp + math.log(p), combo + [(p, leg)])
                    cur = states[k + 1].get(nb)
                    if cur is None or cand[0] > cur[0]:
                        states[k + 1][nb] = cand
    best, reachable = None, False
    for lp, combo in states[n].values():
        odds = math.prod(l["odds"] for _, l in combo)
        if odds < min_odds:
            continue
        reachable = True
        tp = ticket_prob(method, [p for p, _ in combo], n, pair_f)
        if best is None or tp > best["p"]:
            best = {"p": tp, "odds": odds, "won": all(l["win"] for _, l in combo), "n": n}
    return best, reachable


def summarise(tickets):
    n = len(tickets)
    if n == 0:
        return {"tickets": 0}
    wins = sum(1 for t in tickets if t["won"])
    pnl = [(t["odds"] - 1.0) if t["won"] else -1.0 for t in tickets]
    peak = cum = dd = 0.0
    for v in pnl:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    bins = defaultdict(lambda: [0, 0, 0.0])
    for t in tickets:
        b = "<0.40" if t["p"] < 0.4 else "0.40-0.60" if t["p"] < 0.6 else "0.60-0.80" if t["p"] < 0.8 else ">=0.80"
        bins[b][0] += 1
        bins[b][1] += 1 if t["won"] else 0
        bins[b][2] += t["p"]
    return {
        "tickets": n, "wins": wins, "accuracy": round(wins / n, 4),
        "accuracy_wilson95": wilson(wins, n),
        "mean_predicted_probability": round(sum(t["p"] for t in tickets) / n, 4),
        "brier": round(sum(((1.0 if t["won"] else 0.0) - t["p"]) ** 2 for t in tickets) / n, 4),
        "avg_odds": round(sum(t["odds"] for t in tickets) / n, 4),
        "break_even_accuracy": round(1.0 / (sum(t["odds"] for t in tickets) / n), 4),
        "flat_roi": round(sum(pnl) / n, 4),
        "max_drawdown_units": round(dd, 3),
        "calibration": {k: {"n": v[0], "mean_pred": round(v[2] / v[0], 4), "hit": round(v[1] / v[0], 4)}
                        for k, v in sorted(bins.items())},
    }


def pair_diagnostics(events):
    """In-sample co-occurrence diagnostic (descriptive; not used for decisions)."""
    by_day = defaultdict(lambda: [0.0, 0.0, 0])
    classes = {"both>=0.90": [0.0, 0.0, 0], "0.60-0.90": [0.0, 0.0, 0]}
    recent = deque()
    for ev in events:
        while recent and ev["ts"] - recent[0]["ts"] > SPAN_SECONDS:
            recent.popleft()
        day = datetime.fromtimestamp(ev["ts"], timezone.utc).strftime("%Y-%m-%d")
        for old in recent:
            for a in ev["rows"]:
                for b in old["rows"]:
                    if a["p_mkt"] < PAIR_MIN_MARGINAL or b["p_mkt"] < PAIR_MIN_MARGINAL:
                        continue
                    e = a["p_mkt"] * b["p_mkt"]
                    o = 1.0 if (a["win"] and b["win"]) else 0.0
                    d = by_day[day]
                    d[0] += o; d[1] += e; d[2] += 1
                    c = classes["both>=0.90"] if min(a["p_mkt"], b["p_mkt"]) >= 0.90 else classes["0.60-0.90"]
                    c[0] += o; c[1] += e; c[2] += 1
        recent.append(ev)
    tot_o = sum(v[0] for v in by_day.values())
    tot_e = sum(v[1] for v in by_day.values())
    ratio = tot_o / tot_e if tot_e else None
    jack = []
    for day in by_day:
        o = tot_o - by_day[day][0]
        e = tot_e - by_day[day][1]
        if e > 0:
            jack.append(o / e)
    se = None
    if len(jack) > 2 and ratio is not None:
        m = sum(jack) / len(jack)
        se = math.sqrt((len(jack) - 1) / len(jack) * sum((x - m) ** 2 for x in jack))
    return {
        "note": "cross-event pairs within 60 min, marginals >= 0.60; ratio = observed joint / product of de-vigged marginals",
        "pairs": sum(v[2] for v in by_day.values()),
        "observed_over_expected": round(ratio, 4) if ratio is not None else None,
        "day_jackknife_se": round(se, 4) if se is not None else None,
        "days": len(by_day),
        "by_class": {k: {"pairs": v[2], "ratio": round(v[0] / v[1], 4) if v[1] else None} for k, v in classes.items()},
    }


def run(history, min_odds):
    events = load_events(history)
    if len(events) < 200:
        raise SystemExit("insufficient settled VFootball O/U events")
    holdout_ts = events[int(len(events) * (1.0 - HOLDOUT_FRACTION))]["ts"]
    windows = make_windows(events)
    know = Knowledge(events)
    tickets = {(m, t, s): [] for m in METHODS for t in TIERS for s in SHAPES}
    reach = {(t, s): [0, 0] for t in TIERS for s in SHAPES}
    cutoff_floor = 0.0
    factor_log = []
    for window in windows:
        cutoff = max(cutoff_floor, min(ev["cap"] for ev in window))
        cutoff_floor = cutoff
        know.advance(cutoff)
        pair_f, fitted = know.pair_factor()
        factor_log.append(pair_f if fitted else None)
        legs = leg_pool(window, know)
        start = window[0]["ts"]
        for tier in TIERS:
            for n in SHAPES:
                for method in METHODS:
                    t, ok = best_ticket(method, legs, tier, n, min_odds, pair_f)
                    if method == "B":
                        reach[(tier, n)][0] += 1
                        reach[(tier, n)][1] += 1 if ok else 0
                    if t is not None:
                        t["start"] = start
                        tickets[(method, tier, n)].append(t)
    result = {}
    for (method, tier, n), rows in tickets.items():
        hold = [r for r in rows if r["start"] >= holdout_ts]
        result.setdefault(method, {}).setdefault(f"tier_{tier:.2f}", {})[f"{n}_leg"] = {
            "production_eligible_tier": tier in PRODUCTION_TIERS,
            "walk_forward_all": summarise(rows),
            "untouched_holdout_last_30pct": summarise(hold),
        }
    fitted_f = [f for f in factor_log if f is not None]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY_DIAGNOSTIC",
        "production_selection_changed": False,
        "scope": "VFootball only; eFootball not mixed",
        "assumptions": [
            "decision time = earliest odds snapshot (captured_at) in the 60-minute kickoff window",
            f"results count as known {RESULT_LAG_SECONDS}s after kickoff and only if before that decision time",
            "recorded SportyBet snapshot odds are assumed available at decision time and bettable",
            "method A is a proxy for the VFootball holdout lane (Poisson product x 0.90); the Wilson lower bound and live evidence counters are not reproduced",
            "history stores only one side per line, so opposite-side legs cannot be tested",
        ],
        "events": len(events), "windows": len(windows),
        "holdout_starts_at": datetime.fromtimestamp(holdout_ts, timezone.utc).isoformat(),
        "min_combined_odds": min_odds,
        "reachability_2_70": {
            f"tier_{t:.2f}_{n}_leg": {"windows": v[0], "windows_with_ticket_at_min_odds": v[1]}
            for (t, n), v in reach.items()
        },
        "pair_factor_walk_forward": {
            "windows_with_fitted_factor": len(fitted_f),
            "last_factor": round(fitted_f[-1], 4) if fitted_f else None,
            "mean_factor": round(sum(fitted_f) / len(fitted_f), 4) if fitted_f else None,
        },
        "pair_cooccurrence_diagnostic": pair_diagnostics(events),
        "methods": result,
    }


def print_summary(report):
    print(f"events={report['events']} windows={report['windows']} min_odds={report['min_combined_odds']}")
    print("reachability (windows with a 2.70+ ticket / windows):")
    for k, v in report["reachability_2_70"].items():
        print(f"  {k}: {v['windows_with_ticket_at_min_odds']}/{v['windows']}")
    print("pair diagnostic:", json.dumps(report["pair_cooccurrence_diagnostic"]))
    print("pair factor:", json.dumps(report["pair_factor_walk_forward"]))
    for method, tiers in report["methods"].items():
        for tier, shapes in tiers.items():
            for shape, body in shapes.items():
                a = body["walk_forward_all"]
                h = body["untouched_holdout_last_30pct"]
                if a.get("tickets", 0) == 0:
                    continue
                print(f"{method:3s} {tier} {shape}: all n={a['tickets']} acc={a['accuracy']} "
                      f"pred={a['mean_predicted_probability']} brier={a['brier']} odds={a['avg_odds']} "
                      f"roi={a['flat_roi']} dd={a['max_drawdown_units']} | "
                      f"holdout n={h.get('tickets', 0)} acc={h.get('accuracy')} roi={h.get('flat_roi')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(HISTORY))
    ap.add_argument("--output", default=str(OUTPUT))
    ap.add_argument("--min-odds", type=float, default=MIN_COMBINED_ODDS)
    args = ap.parse_args()
    report = run(Path(args.history), args.min_odds)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(report)


if __name__ == "__main__":
    main()
