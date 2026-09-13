"""Validate candidate behavioral features without changing production probabilities.

This is a leakage-resistant research layer: each match is scored only from team history
available before that match. It compares a simple behavior-only model with a uniform
1X2 baseline. It is not a betting recommendation and remains PAPER_ONLY.
"""
from __future__ import annotations
import json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "behavior_validation.json"
MIN_HISTORY = 5


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def clip(x, lo=0.02, hi=0.96):
    return max(lo, min(hi, x))


def softmax(xs):
    m = max(xs)
    es = [math.exp(x - m) for x in xs]
    s = sum(es)
    return [x / s for x in es]


def outcome(h, a):
    return 0 if h > a else 1 if h == a else 2


def team_snapshot(rows):
    """Build pre-match rolling snapshots. Rows must already be chronological."""
    state = defaultdict(list)
    snapshots = []
    for r in rows:
        score = r.get("final_score")
        if not isinstance(score, (list, tuple)) or len(score) < 2:
            continue
        h, a = f(score[0]), f(score[1])
        if h is None or a is None:
            continue
        home, away = r.get("player_1"), r.get("player_2")
        league = r.get("league") or "global"
        if not home or not away:
            continue

        def snap(team):
            hist = state[(league, team)]
            if len(hist) < MIN_HISTORY:
                return None
            recent = hist[-10:]
            n = len(recent)
            gf = sum(x[0] for x in recent) / n
            ga = sum(x[1] for x in recent) / n
            wins = sum(x[0] > x[1] for x in recent) / n
            draws = sum(x[0] == x[1] for x in recent) / n
            blanks = sum(x[0] == 0 for x in recent) / n
            clean = sum(x[1] == 0 for x in recent) / n
            return {"gf": gf, "ga": ga, "goal_diff": gf-ga, "win_rate": wins,
                    "draw_rate": draws, "blank_rate": blanks, "clean_sheet_rate": clean,
                    "n": n}

        hs, aws = snap(home), snap(away)
        if hs and aws:
            snapshots.append({
                "event_id": str(r.get("event_id") or ""),
                "league": league, "start_time": r.get("start_time"),
                "features": {k: hs[k] - aws[k] for k in ("gf", "ga", "goal_diff", "win_rate", "draw_rate", "blank_rate", "clean_sheet_rate")},
                "home": hs, "away": aws, "actual": outcome(h, a),
            })

        state[(league, home)].append((h, a))
        state[(league, away)].append((a, h))
    return snapshots


def behavior_prob(features):
    """Small, fixed, monotonic behavior-only benchmark; no fitted future information."""
    # Goal difference and win rate carry the strongest directional signal; defensive
    # behavior contributes more softly. This is deliberately a benchmark, not V4.
    z = 1.35 * features["goal_diff"] + 0.95 * features["win_rate"] - 0.35 * features["draw_rate"] - 0.25 * features["blank_rate"] + 0.25 * features["clean_sheet_rate"]
    p_home = 1.0 / (1.0 + math.exp(-z))
    draw_signal = 0.18 + 0.45 * max(0.0, 1.0 - abs(features["win_rate"]))
    p_draw = clip(draw_signal * (1.0 - abs(features["goal_diff"]) * 0.18), 0.08, 0.32)
    p_home = clip(p_home * (1.0 - p_draw), 0.02, 0.94)
    p_away = clip(1.0 - p_draw - p_home, 0.02, 0.94)
    s = p_home + p_draw + p_away
    return [p_home/s, p_draw/s, p_away/s]


def brier(rows, probs):
    vals = []
    for r, p in zip(rows, probs):
        vals.append(sum((p[i] - (1.0 if r["actual"] == i else 0.0)) ** 2 for i in range(3)) / 3.0)
    return sum(vals) / len(vals) if vals else None


def main():
    history = load("football_team_history.json", [])
    rows = [r for r in history if isinstance(r, dict) and r.get("settled") and r.get("final_score")]
    rows.sort(key=lambda r: r.get("start_time") or "")
    samples = team_snapshot(rows)
    probs = [behavior_prob(x["features"]) for x in samples]
    uniform = [[1/3, 1/3, 1/3] for _ in samples]

    feature_report = {}
    for feature in ("gf", "ga", "goal_diff", "win_rate", "draw_rate", "blank_rate", "clean_sheet_rate"):
        vals = [x["features"][feature] for x in samples]
        pairs = [(v, x["actual"]) for v, x in zip(vals, samples) if v is not None]
        if len(pairs) < 20:
            feature_report[feature] = {"n": len(pairs), "status": "insufficient_sample"}
            continue
        pairs.sort(key=lambda z: z[0])
        mid = len(pairs) // 2
        low, high = pairs[:mid], pairs[mid:]
        def home_rate(g): return sum(y == 0 for _, y in g) / len(g) if g else None
        def away_rate(g): return sum(y == 2 for _, y in g) / len(g) if g else None
        feature_report[feature] = {
            "n": len(pairs), "low_home_win_rate": round(home_rate(low), 4),
            "high_home_win_rate": round(home_rate(high), 4),
            "low_away_win_rate": round(away_rate(low), 4),
            "high_away_win_rate": round(away_rate(high), 4),
            "status": "candidate" if len(pairs) >= 50 else "exploratory",
        }

    behavior_brier = brier(samples, probs)
    baseline_brier = brier(samples, uniform)
    improvement = (baseline_brier - behavior_brier) if behavior_brier is not None else None
    report = {
        "version": "behavior-validation-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "production_probability_adjustment": False,
        "samples": len(samples),
        "minimum_team_history": MIN_HISTORY,
        "behavior_only_brier": round(behavior_brier, 6) if behavior_brier is not None else None,
        "uniform_baseline_brier": round(baseline_brier, 6) if baseline_brier is not None else None,
        "brier_improvement_vs_uniform": round(improvement, 6) if improvement is not None else None,
        "feature_relationships": feature_report,
        "promotion_gate": {
            "required_samples": 200,
            "required_positive_brier_improvement": 0.01,
            "required_out_of_sample_only": True,
            "required_ablation": True,
            "current_status": "research_only",
            "reason": "Behavior features must beat a baseline out of sample before they can alter V4 probabilities.",
        },
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
