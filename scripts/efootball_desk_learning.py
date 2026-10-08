#!/usr/bin/env python3
"""Learn and score the eFootball Upcoming Prediction Desk.

This is a paper-only instrumentation/calibration layer. It records the desk's
pre-kickoff eFootball forecasts, scores only the latest pre-kickoff forecast
against the independent Virtual Lab settlement ledger, and learns a conservative
probability calibration from earlier settled desk forecasts.

It never changes canonical settlement history and never uses future outcomes to
calibrate a forecast made before kickoff.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UNIFIED = DATA / "unified_upcoming.json"
HISTORY = DATA / "virtual_lab_history.json"
TRACE = DATA / "efootball_desk_prediction_history.json"
OUTPUT = DATA / "efootball_desk_learning.json"

BUCKET_WIDTH = 0.05
MIN_CALIBRATION_N = 30
EXACT_MIN_N = 20
RECENT_WINDOW = 50
TRACE_CAP = 50000


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def dt(v):
    if not v:
        return None
    try:
        x = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def bucket_key(p):
    p = max(0.0, min(0.9999, float(p)))
    lo = math.floor(p / BUCKET_WIDTH) * BUCKET_WIDTH
    return f"{lo:.2f}".rstrip("0").rstrip(".")


def side_of(row):
    side = str(row.get("pick") or row.get("selection") or "").strip().lower()
    if side in {"over", "under"}:
        return side
    return ""


def exact_key(row):
    event_id = str(row.get("event_id") or "")
    line = num(row.get("line"))
    side = side_of(row)
    if not event_id or line is None or not side:
        return None
    return f"{event_id}|{line:g}|{side}"


def settlement_index(history):
    index = {}
    for row in history if isinstance(history, list) else []:
        if not isinstance(row, dict) or row.get("market") != "ou" or row.get("win") is None:
            continue
        key = exact_key(row)
        stamp = dt(row.get("timestamp") or row.get("settled_at"))
        if not key or stamp is None:
            continue
        # Event IDs can recur. Keep the latest settled occurrence for this
        # exact event/line/side key.
        previous = index.get(key)
        if previous is None or stamp > previous["_stamp"]:
            item = dict(row)
            item["_stamp"] = stamp
            index[key] = item
    return index


def eligible_current_rows(board):
    events = board.get("events") if isinstance(board, dict) else []
    out = []
    for row in events if isinstance(events, list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("product") or "") != "efootball_gt":
            continue
        if str(row.get("market") or "") != "over_under":
            continue
        p = num(row.get("probability"))
        line = num(row.get("line"))
        side = side_of(row)
        start = dt(row.get("start_time"))
        if p is None or line is None or not side or start is None:
            continue
        if start <= datetime.now(timezone.utc):
            continue
        out.append(row)
    return out


def capture(trace, board):
    now = datetime.now(timezone.utc)
    generated_at = board.get("generated_at") if isinstance(board, dict) else None
    for row in eligible_current_rows(board):
        key = exact_key(row)
        if not key:
            continue
        observed = dt(row.get("desk_observed_at")) or now
        record = {
            "trace_id": f"{key}|{observed.isoformat()}",
            "event_key": key,
            "event_id": str(row.get("event_id") or ""),
            "start_time": row.get("start_time"),
            "competition": row.get("league") or row.get("competition"),
            "participant_1": row.get("player_1"),
            "participant_2": row.get("player_2"),
            "line": num(row.get("line")),
            "pick": side_of(row),
            "model_probability": p if (p := num(row.get("probability"))) is not None else None,
            "raw_model_probability": num(row.get("raw_model_probability")),
            "model_version": row.get("model_version"),
            "validated_model_family": row.get("validated_model_family"),
            "bookmaker_odds": num(row.get("bookmaker_odds")),
            "model_edge_vs_market": num(row.get("model_edge_vs_market")),
            "observed_at": observed.isoformat(),
            "board_generated_at": generated_at,
            "paper_only": True,
            "settled": False,
        }
        # Keep every materially different forecast revision, but avoid writing
        # identical snapshots every five minutes.
        duplicate = any(
            old.get("event_key") == key
            and abs(float(old.get("model_probability") or 0) - float(record.get("model_probability") or 0)) < 1e-6
            and abs((dt(old.get("observed_at")) or now - observed).total_seconds()) < 1800
            for old in trace[-1000:]
        )
        if not duplicate:
            trace.append(record)


def reconcile(trace, history_index):
    for key, item in history_index.items():
        scored = []
        for row in trace:
            if row.get("event_key") != key:
                continue
            observed = dt(row.get("observed_at"))
            start = dt(row.get("start_time"))
            settled = item.get("_stamp")
            if observed is None or start is None or settled is None:
                continue
            if observed < start and observed <= settled:
                scored.append((observed, row))
        if not scored:
            continue
        latest = sorted(scored, key=lambda x: x[0])[-1][1]
        for _, row in scored:
            if row is latest:
                row["settled"] = True
                row["settled_at"] = item.get("settled_at")
                row["actual_result"] = item.get("result") or item.get("actual_result")
                row["win"] = bool(item.get("win"))
                row["score"] = item.get("score") or item.get("final_score")
                row["settlement_source"] = item.get("settlement_source")
                row["scored_forecast"] = True
            else:
                row["superseded_before_settlement"] = True
                row["scored_forecast"] = False


def settled_forecasts(trace):
    rows = []
    for row in trace:
        if row.get("scored_forecast") is not True:
            continue
        p = num(row.get("model_probability"))
        if p is None:
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("settled_at") or ""))
    return rows


def calibration(forecasts):
    buckets = {}
    for row in forecasts:
        p = num(row.get("model_probability"))
        if p is None:
            continue
        key = bucket_key(p)
        b = buckets.setdefault(key, {"n": 0, "wins": 0, "brier": 0.0})
        b["n"] += 1
        b["wins"] += 1 if row.get("win") else 0
        b["brier"] += (p - (1.0 if row.get("win") else 0.0)) ** 2

    for key, b in buckets.items():
        n = int(b["n"])
        wins = int(b["wins"])
        empirical = (wins + 4.0) / (n + 8.0)
        weight = n / (n + 30.0)
        center = float(key)
        calibrated = (1.0 - weight) * center + weight * empirical
        b["accuracy"] = wins / n if n else 0.0
        b["avg_brier"] = b["brier"] / n if n else None
        b["posterior_probability"] = empirical
        b["calibrated_probability"] = max(0.01, min(0.99, calibrated))

    return buckets


def exact_profiles(forecasts):
    groups = {}
    for row in forecasts:
        key = f"{num(row.get('line')):g}|{side_of(row)}"
        g = groups.setdefault(key, {"n": 0, "wins": 0})
        g["n"] += 1
        g["wins"] += 1 if row.get("win") else 0
    for g in groups.values():
        n = g["n"]
        g["accuracy"] = g["wins"] / n if n else 0.0
        g["posterior_probability"] = ((g["wins"] + 4.0) / (n + 8.0)) if n else None
    return groups


def main():
    board = load(UNIFIED, {})
    history = load(HISTORY, [])
    trace = load(TRACE, [])
    if not isinstance(trace, list):
        trace = []

    capture(trace, board)
    history_index = settlement_index(history)
    reconcile(trace, history_index)

    # Bound the learning ledger while retaining all currently relevant and
    # recently settled forecasts.
    trace.sort(key=lambda r: str(r.get("observed_at") or ""))
    trace = trace[-TRACE_CAP:]

    settled = settled_forecasts(trace)
    recent = settled[-RECENT_WINDOW:]
    buckets = calibration(settled)
    exact = exact_profiles(settled)

    recent_accuracy = (
        sum(1 for r in recent if r.get("win")) / len(recent)
        if recent else 0.0
    )
    recent_brier = (
        sum(
            (float(r.get("model_probability") or 0)
             - (1.0 if r.get("win") else 0.0)) ** 2
            for r in recent
        ) / len(recent)
        if recent else None
    )

    active = len(settled) >= MIN_CALIBRATION_N
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "active": active,
        "policy": {
            "minimum_calibration_predictions": MIN_CALIBRATION_N,
            "exact_selection_min_predictions": EXACT_MIN_N,
            "bucket_width": BUCKET_WIDTH,
            "recent_window": RECENT_WINDOW,
            "future_leakage_protection": "only observations strictly before kickoff can become the scored forecast; settlement is read from independent virtual_lab_history",
        },
        "settled_predictions": len(settled),
        "pending_forecasts": sum(1 for r in trace if not r.get("settled")),
        "recent_window": {
            "n": len(recent),
            "accuracy": recent_accuracy,
            "brier": recent_brier,
        },
        "calibration": {
            "active": active,
            "settled_predictions": len(settled),
            "buckets": buckets,
        },
        "exact_selection": exact,
        "trace_artifact": "data/efootball_desk_prediction_history.json",
        "source_settlement": "data/virtual_lab_history.json",
    }

    save(TRACE, trace)
    save(OUTPUT, report)
    print(json.dumps({
        "status": "ACTIVE" if active else "WARMUP",
        "settled_predictions": len(settled),
        "pending_forecasts": report["pending_forecasts"],
        "recent_accuracy": recent_accuracy,
        "recent_brier": recent_brier,
    }, indent=2))


if __name__ == "__main__":
    main()
