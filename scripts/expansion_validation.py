"""Deep walk-forward validation for NBA + Eredivisie expansion.

Uses only information available before each historical kickoff. It evaluates
recent form and season-to-date performance without pretending that a tiny
sample proves a betting edge. All outputs are research-only.
"""
import json, math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from expansion_pipeline import collect, nba_predict, ere_predict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NOW = datetime.now(timezone.utc)


def dt(x):
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def brier(probs, actual):
    return sum((float(probs.get(k, 0.0)) - (1.0 if k == actual else 0.0)) ** 2 for k in probs)


def logloss(p, actual, eps=1e-6):
    return -math.log(max(eps, min(1.0 - eps, float(p.get(actual, 0.0)))))


def calib(rows, key="p", actual="actual"):
    bins = []
    for lo in [0.0, .5, .6, .7, .8, .9]:
        hi = lo + .1 if lo else .5
        part = [r for r in rows if lo <= r[key] < hi or (lo == .9 and r[key] <= 1)]
        if part:
            bins.append({"range": f"{lo:.1f}-{hi:.1f}", "n": len(part), "mean_probability": round(sum(r[key] for r in part)/len(part), 4), "empirical_rate": round(sum(1 for r in part if r[actual])/len(part), 4)})
    return bins


def nba_walkforward(hist):
    rows = []
    for r in hist:
        if not r.get("date"):
            continue
        p = nba_predict(r, hist)
        actual = "home" if r["home_score"] > r["away_score"] else "away"
        probs = p.get("independent_moneyline") or p.get("moneyline") or {}
        pred = "home" if probs.get("home", 0) >= .5 else "away"
        rows.append({"event_id": r["event_id"], "date": r["date"], "home": r["home"], "away": r["away"], "actual": actual, "p_home": probs.get("home", .5), "prediction": pred, "correct": pred == actual, "brier": brier(probs, actual), "logloss": logloss(probs, actual), "market": p.get("market", {})})
    return rows


def ere_walkforward(hist):
    rows = []
    for r in hist:
        p = ere_predict(r, hist)
        if not p:
            continue
        hg, ag = r["home_score"], r["away_score"]
        actual = "home" if hg > ag else "draw" if hg == ag else "away"
        probs = {"home": p["p1"], "draw": p["draw"], "away": p["p2"]}
        pred = max(probs, key=probs.get)
        rows.append({"event_id": r["event_id"], "date": r["date"], "home": r["home"], "away": r["away"], "actual": actual, "p_home": p["p1"], "prediction": pred, "correct": pred == actual, "brier": brier(probs, actual), "logloss": logloss(probs, actual), "market": r.get("markets", {})})
    return rows


def summarize(rows):
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "wins": sum(r["correct"] for r in rows), "accuracy": round(sum(r["correct"] for r in rows)/len(rows), 4), "brier": round(sum(r["brier"] for r in rows)/len(rows), 4), "logloss": round(sum(r["logloss"] for r in rows)/len(rows), 4), "last_14d": sum(1 for r in rows if dt(r["date"]) and NOW-dt(r["date"]) <= timedelta(days=14)), "last_21d": sum(1 for r in rows if dt(r["date"]) and NOW-dt(r["date"]) <= timedelta(days=21))}


def team_snapshot(hist, days=21):
    cutoff = NOW - timedelta(days=days)
    out = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "draws": 0, "for": 0, "against": 0})
    for r in hist:
        d = dt(r.get("date"))
        if not d or d < cutoff:
            continue
        h, a = r["home"], r["away"]; hs, as_ = r["home_score"], r["away_score"]
        out[h]["games"] += 1; out[h]["for"] += hs; out[h]["against"] += as_
        out[a]["games"] += 1; out[a]["for"] += as_; out[a]["against"] += hs
        if hs > as_: out[h]["wins"] += 1; out[a]["losses"] += 1
        elif hs < as_: out[a]["wins"] += 1; out[h]["losses"] += 1
        else: out[h]["draws"] += 1; out[a]["draws"] += 1
    return {k: {**v, "win_rate": round(v["wins"]/v["games"], 4) if v["games"] else 0, "net_per_game": round((v["for"]-v["against"])/v["games"], 2) if v["games"] else 0} for k,v in sorted(out.items())}


def main():
    nba_hist = collect("usa.nba", days=365)
    ere_hist = collect("ned.1", days=365)
    nba_rows = nba_walkforward(nba_hist)
    ere_rows = ere_walkforward(ere_hist)
    payload = {
        "generated_at": NOW.isoformat(),
        "paper_only": True,
        "nba": {"history_events": len(nba_hist), "walkforward": summarize(nba_rows), "recent_form_21d": team_snapshot(nba_hist, 21), "recent_form_14d": team_snapshot(nba_hist, 14)},
        "eredivisie": {"history_events": len(ere_hist), "walkforward": summarize(ere_rows), "recent_form_21d": team_snapshot(ere_hist, 21), "recent_form_14d": team_snapshot(ere_hist, 14)},
        "release_decision": {"NBA": "RESEARCH_ONLY", "Eredivisie": "RESEARCH_ONLY"},
        "reasons": ["Walk-forward evidence is being built from completed games.", "No signal is promoted without positive out-of-sample evidence, calibration and market benchmark coverage.", "NBA 2026-27 has not started yet; validation therefore uses the most recent completed NBA season available in the 365-day history window."],
    }
    (DATA / "expansion_validation.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))

if __name__ == "__main__": main()
