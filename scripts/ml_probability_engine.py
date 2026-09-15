"""Chronological probability model layer for Match Signal.

The public repository contains the reproducible training/evaluation shell only.
Provider credentials, proprietary feature stores and production calibration
artifacts should be supplied through private infrastructure/secrets.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, float(p)))
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def chronological_split(rows: List[dict], holdout_fraction: float = 0.2) -> Tuple[List[dict], List[dict]]:
    rows = sorted(rows, key=lambda r: r.get("start_time") or r.get("calculated_at") or "")
    cut = max(1, int(len(rows) * (1 - holdout_fraction)))
    return rows[:cut], rows[cut:]


def brier_multiclass(probabilities: Iterable[float], actual_index: int) -> float:
    probs = list(probabilities)
    return sum((p - (1.0 if i == actual_index else 0.0)) ** 2 for i, p in enumerate(probs))


def evaluate(rows: List[dict]) -> dict:
    settled = []
    for row in rows:
        probs = row.get("probabilities") or {}
        actual = row.get("actual")
        if actual not in {"p1", "draw", "p2"}:
            continue
        ordered = [float(probs.get("p1", 0)), float(probs.get("draw", 0)), float(probs.get("p2", 0))]
        idx = {"p1": 0, "draw": 1, "p2": 2}[actual]
        settled.append({"correct": max(range(3), key=lambda i: ordered[i]) == idx,
                        "brier": brier_multiclass(ordered, idx)})
    if not settled:
        return {"sample_size": 0}
    return {
        "sample_size": len(settled),
        "accuracy": round(sum(x["correct"] for x in settled) / len(settled), 6),
        "brier": round(sum(x["brier"] for x in settled) / len(settled), 6),
    }


def load_history() -> List[dict]:
    path = DATA / "prediction_history.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def run() -> dict:
    rows = [r for r in load_history() if r.get("sport") == "football" and r.get("settled")]
    train, holdout = chronological_split(rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "RESEARCH_ONLY" if len(holdout) < 100 else "OOS_READY",
        "method": "chronological_holdout",
        "sample_size": len(rows),
        "train_size": len(train),
        "holdout_size": len(holdout),
        "train_metrics": evaluate(train),
        "holdout_metrics": evaluate(holdout),
        "leakage_guard": True,
        "real_money_approved": False,
    }


if __name__ == "__main__":
    out = DATA / "model_performance.json"
    out.write_text(json.dumps(run(), indent=2), encoding="utf-8")
    print(out)
