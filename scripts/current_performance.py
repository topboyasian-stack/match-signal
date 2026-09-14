"""Summarize current empirical prediction performance from settled history.

This is an evaluation/diagnostic layer. It never rewrites historical predictions
and never changes probabilities. The production model can use the resulting
status as evidence about readiness, while the frozen ledger remains authoritative.
PAPER ONLY.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "current_performance.json"


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def metric(rows):
    settled = [r for r in rows if r.get("settled") and r.get("correct") is not None]
    briers = []
    for r in settled:
        try:
            briers.append(float(r.get("brier")))
        except (TypeError, ValueError):
            pass
    accuracy = sum(bool(r.get("correct")) for r in settled) / len(settled) if settled else None
    return {
        "settled": len(settled),
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "brier": round(sum(briers) / len(briers), 6) if briers else None,
    }


def main():
    history = load("prediction_history.json", [])
    rows = [r for r in history if isinstance(r, dict) and r.get("settled")]
    rows.sort(key=lambda r: str(r.get("start_time") or r.get("settled_at") or ""))

    overall = metric(rows)
    windows = {str(n): metric(rows[-n:]) for n in (20, 50, 100)}
    by_sport = {}
    by_league = {}
    grouped = defaultdict(list)
    league_grouped = defaultdict(list)
    for r in rows:
        grouped[str(r.get("sport") or "unknown")].append(r)
        league_grouped[(str(r.get("sport") or "unknown"), str(r.get("league") or "unknown"))].append(r)
    for sport, group in grouped.items():
        by_sport[sport] = metric(group)
    for key, group in league_grouped.items():
        by_league[f"{key[0]}|{key[1]}"] = metric(group)

    recent = rows[-20:]
    recent_losses = 0
    for r in reversed(recent):
        if r.get("correct") is False:
            recent_losses += 1
        else:
            break

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "source": "prediction_history.json authoritative settled outcomes",
        "overall": overall,
        "rolling_windows": windows,
        "by_sport": by_sport,
        "by_league": by_league,
        "recent_20_consecutive_losses": recent_losses,
        "readiness": {
            "status": "insufficient_evidence" if overall["settled"] < 100 else "monitor",
            "live_trading_approved": False,
            "note": "Historical results inform evaluation and calibration; they do not get rewritten or retrofitted into past predictions.",
        },
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
