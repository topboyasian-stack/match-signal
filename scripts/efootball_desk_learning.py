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


def participant_identity(row, keys):
    import re
    value = ""
    for key in keys:
        if row.get(key):
            value = str(row.get(key)).strip()
            break
    embedded = re.search(r"\(([^()]*)\)\s*$", value)
    if embedded and embedded.group(1).strip():
        value = embedded.group(1).strip()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def fixture_key(row):
    """Stable eFootball fixture key; provider event IDs can recur in one session."""
    product = str(row.get("product") or "efootball_gt").strip().lower()
    start = dt(row.get("start_time") or row.get("timestamp"))
    p1 = participant_identity(row, ("participant_1", "player_1", "team_1", "home"))
    p2 = participant_identity(row, ("participant_2", "player_2", "team_2", "away"))
    event_id = str(row.get("event_id") or "")
    if start is not None and p1 and p2:
        minute = int(start.timestamp() // 60)
        return f"{product}|{minute}|{'|'.join(sorted((p1, p2)))}"
    return f"{product}|event:{event_id}" if event_id else None



def score_pair(value):
    """Parse a final virtual score as a canonical pair and total goals."""
    if value is None:
        return None
    parts = str(value).replace(" ", "").split(":")
    if len(parts) != 2:
        return None
    values = [num(part) for part in parts]
    if any(x is None or x < 0 or not float(x).is_integer() for x in values):
        return None
    left, right = (int(x) for x in values)
    return f"{left}:{right}", left + right


def fixture_identity(row):
    product = str(row.get("product") or "efootball_gt").strip().lower()
    p1 = participant_identity(row, ("participant_1", "player_1", "team_1", "home"))
    p2 = participant_identity(row, ("participant_2", "player_2", "team_2", "away"))
    if not p1 or not p2:
        return None
    return product, tuple(sorted((p1, p2)))

def exact_key(row):
    base = fixture_key(row)
    line = num(row.get("line"))
    if not base or line is None:
        return None
    return f"{base}|{line:g}"


def settlement_index(history):
    """Index only settled, score-verifiable O/U outcomes.

    A final score plus an explicit settled_at timestamp is sufficient even if a
    particular market-line row omits its win flag. Older canonical rows without
    settled_at retain the legacy win-flag requirement. Conflicting scores at the
    same latest settlement timestamp are excluded rather than guessed.
    """
    candidates = {}
    for row in history if isinstance(history, list) else []:
        if not isinstance(row, dict) or row.get("market") != "ou":
            continue
        raw_score = row.get("score") or row.get("final_score")
        parsed_score = score_pair(raw_score)
        settled_stamp = dt(row.get("settled_at"))
        stamp = settled_stamp or (dt(row.get("timestamp")) if row.get("win") is not None else None)
        if not parsed_score or stamp is None:
            continue
        if row.get("win") is None and settled_stamp is None:
            continue
        base = fixture_key(row)
        if not base:
            continue
        item = dict(row)
        item["_stamp"] = stamp
        item["_fixture_key"] = base
        item["_score_pair"] = parsed_score[0]
        item["_score_total"] = parsed_score[1]
        item["_identity"] = fixture_identity(row)
        item["_event_time"] = dt(row.get("start_time") or row.get("timestamp"))
        candidates.setdefault(base, []).append(item)

    index = {}
    for base, rows in candidates.items():
        latest_stamp = max(row["_stamp"] for row in rows)
        latest = [row for row in rows if row["_stamp"] == latest_stamp]
        if len({row["_score_pair"] for row in latest}) != 1:
            # Same fixture and same latest settlement time but conflicting
            # scores is not safe evidence for learning or qualification.
            continue
        index[base] = latest[-1]
    return index


def resolve_settlement(row, history_index):
    """Use exact fixture keys first, then a conservative unique 90s fallback.

    The fallback exists for provider kickoff timestamps that straddle a minute
    boundary. Provider event IDs alone are never used for fuzzy matching because
    those IDs can recur between eFootball sessions.
    """
    base = fixture_key(row)
    if base and base in history_index:
        return history_index[base], "EXACT"

    identity = fixture_identity(row)
    event_time = dt(row.get("start_time") or row.get("timestamp"))
    if identity is None or event_time is None:
        return None, "UNMATCHED"
    candidates = []
    for candidate_key, item in history_index.items():
        if item.get("_identity") != identity:
            continue
        candidate_time = item.get("_event_time")
        if candidate_time is None:
            continue
        if abs((candidate_time - event_time).total_seconds()) <= 90:
            candidates.append((candidate_key, item))
    # If recurring participants create more than one plausible fixture, fail
    # closed. Never guess which session a forecast belongs to.
    unique = {key: item for key, item in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), "NEAR_TIME"
    if len(unique) > 1:
        return None, "AMBIGUOUS"
    return None, "UNMATCHED"

def eligible_current_rows(board):
    events = board.get("events") if isinstance(board, dict) else []
    out = []
    # Capture every supported virtual engine separately. Product keys remain
    # isolated in reconciliation/calibration so GT evidence cannot leak into
    # Adriatic, VFootball, or Zoom.
    supported_products = {"efootball_gt", "efootball_adriatic", "vfootball", "zoom"}
    for row in events if isinstance(events, list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("product") or "").strip().lower() not in supported_products:
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
            "product": str(row.get("product") or "efootball_gt"),
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
            (old.get("event_key") == key or exact_key(old) == key)
            and side_of(old) == side_of(record)
            and abs(float(old.get("model_probability") or 0) - float(record.get("model_probability") or 0)) < 1e-6
            and abs(((dt(old.get("observed_at")) or now) - observed).total_seconds()) < 1800
            for old in trace[-1000:]
        )
        if not duplicate:
            trace.append(record)


def reconcile(trace, history_index):
    stats = {
        "trace_rows": len(trace),
        "history_index_fixtures": len(history_index),
        "forecast_line_groups": 0,
        "matched_line_groups_exact": 0,
        "matched_line_groups_near_time": 0,
        "unmatched_line_groups": 0,
        "ambiguous_line_groups": 0,
        "scored_forecasts": 0,
    }
    for row in trace:
        # Migrate existing trace rows from the old event-ID-only key. Provider
        # IDs can recur across sessions, so product/kickoff/participant identity
        # remains canonical.
        key = exact_key(row)
        if key:
            row["event_key"] = key
            row.setdefault("product", "efootball_gt")

    # Score each fixture + totals line once, selecting the latest strictly
    # pre-kickoff forecast. A different line on the same match remains a
    # separate decision and learns from the same verified final score.
    forecasts_by_exact_key = {}
    for row in trace:
        base = fixture_key(row)
        key = exact_key(row)
        if base and key:
            forecasts_by_exact_key.setdefault(key, []).append(row)
    stats["forecast_line_groups"] = len(forecasts_by_exact_key)

    for exact, forecasts in forecasts_by_exact_key.items():
        if not forecasts:
            continue
        item, match_method = resolve_settlement(forecasts[0], history_index)
        if not item:
            stats["unmatched_line_groups"] += 1
            if match_method == "AMBIGUOUS":
                stats["ambiguous_line_groups"] += 1
            continue
        if match_method == "EXACT":
            stats["matched_line_groups_exact"] += 1
        elif match_method == "NEAR_TIME":
            stats["matched_line_groups_near_time"] += 1

        settled = item.get("_stamp")
        score = item.get("score") or item.get("final_score") or item.get("_score_pair")
        parsed_score = score_pair(score)
        if not parsed_score:
            continue
        total = parsed_score[1]

        scored = []
        for row in forecasts:
            observed = dt(row.get("observed_at"))
            start = dt(row.get("start_time"))
            line = num(row.get("line"))
            side = side_of(row)
            if observed is None or start is None or line is None or not side or settled is None:
                continue
            # Strictly pre-kickoff forecasts only; settlement must be after the
            # observation. A later revision supersedes only the same line.
            if not (observed < start and observed <= settled):
                continue
            scored.append((observed, row, line, side, total))

        if not scored:
            continue
        latest = sorted(scored, key=lambda x: x[0])[-1][1]
        for _, row, line, side, total in scored:
            if row is not latest:
                row["superseded_before_settlement"] = True
                row["scored_forecast"] = False
                continue
            row.pop("superseded_before_settlement", None)
            if total == line:
                row["settled"] = True
                row["push"] = True
                row["actual_result"] = "PUSH"
                row["settled_at"] = item.get("settled_at")
                row["score"] = item.get("score") or item.get("final_score") or item.get("_score_pair")
                row["settlement_source"] = item.get("settlement_source")
                row["scored_forecast"] = False
                continue
            actual_side = "over" if total > line else "under"
            row["settled"] = True
            row["push"] = False
            row["settled_at"] = item.get("settled_at") or item.get("_stamp").isoformat()
            row["actual_result"] = actual_side
            row["win"] = actual_side == side
            row["score"] = item.get("score") or item.get("final_score") or item.get("_score_pair")
            row["settlement_source"] = item.get("settlement_source")
            row["scored_forecast"] = True

    stats["scored_forecasts"] = sum(1 for row in trace if row.get("scored_forecast") is True)
    return stats

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
        b = buckets.setdefault(key, {
            "n": 0, "wins": 0, "brier": 0.0,
            "model_probability_sum": 0.0, "model_probability_n": 0,
        })
        b["n"] += 1
        b["wins"] += 1 if row.get("win") else 0
        b["brier"] += (p - (1.0 if row.get("win") else 0.0)) ** 2
        b["model_probability_sum"] += p
        b["model_probability_n"] += 1

    for key, b in buckets.items():
        n = int(b["n"])
        wins = int(b["wins"])
        empirical = (wins + 4.0) / (n + 8.0)
        weight = n / (n + 30.0)
        model_n = int(b.pop("model_probability_n") or 0)
        model_sum = float(b.pop("model_probability_sum") or 0.0)
        mean_model = model_sum / model_n if model_n else float(key)
        calibrated = (1.0 - weight) * mean_model + weight * empirical
        b["accuracy"] = wins / n if n else 0.0
        b["avg_brier"] = b["brier"] / n if n else None
        b["posterior_probability"] = empirical
        b["mean_model_probability"] = mean_model
        b["calibration_weight"] = weight
        b["calibration_offset"] = empirical - mean_model
        b["calibrated_probability"] = max(0.01, min(0.99, calibrated))

    return buckets


def exact_profiles(forecasts):
    # Never pool products: eFootball GT and VFootball have different score
    # distributions and each needs its own line/direction evidence.
    products = {}
    for row in forecasts:
        line = num(row.get("line"))
        side = side_of(row)
        if line is None or not side:
            continue
        product = str(row.get("product") or "efootball_gt").strip().lower()
        key = f"{line:g}|{side}"
        by_line = products.setdefault(product, {})
        g = by_line.setdefault(key, {"n": 0, "wins": 0, "model_probability_sum": 0.0, "model_probability_n": 0})
        g["n"] += 1
        g["wins"] += 1 if row.get("win") else 0
        p = num(row.get("model_probability"))
        if p is not None:
            g["model_probability_sum"] += p
            g["model_probability_n"] += 1

    for by_line in products.values():
        for g in by_line.values():
            n = g["n"]
            wins = g["wins"]
            posterior = (wins + 4.0) / (n + 8.0) if n else None
            p_n = int(g.pop("model_probability_n"))
            p_sum = float(g.pop("model_probability_sum"))
            mean_p = p_sum / p_n if p_n else None
            weight = n / (n + 30.0) if n else 0.0
            g["accuracy"] = wins / n if n else 0.0
            g["posterior_probability"] = posterior
            g["mean_model_probability"] = mean_p
            g["calibration_weight"] = weight
            g["calibration_offset"] = (posterior - mean_p) if posterior is not None and mean_p is not None else 0.0
    return products

def main():
    board = load(UNIFIED, {})
    history = load(HISTORY, [])
    trace = load(TRACE, [])
    if not isinstance(trace, list):
        trace = []

    capture(trace, board)
    history_index = settlement_index(history)
    reconciliation = reconcile(trace, history_index)

    # Bound the learning ledger while retaining all currently relevant and
    # recently settled forecasts.
    trace.sort(key=lambda r: str(r.get("observed_at") or ""))
    trace = trace[-TRACE_CAP:]

    settled = settled_forecasts(trace)
    products = sorted({str(r.get("product") or "efootball_gt").strip().lower() for r in settled})
    by_product = {}
    for product in products:
        product_settled = [r for r in settled if str(r.get("product") or "efootball_gt").strip().lower() == product]
        recent = product_settled[-RECENT_WINDOW:]
        buckets = calibration(product_settled)
        exact = exact_profiles(product_settled).get(product, {})
        bucket_active = any(int(b.get("n") or 0) >= MIN_CALIBRATION_N for b in buckets.values())
        exact_active = any(int(x.get("n") or 0) >= EXACT_MIN_N for x in exact.values())
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
        by_product[product] = {
            "active": bucket_active or exact_active,
            "settled_predictions": len(product_settled),
            "pending_forecasts": sum(
                1 for r in trace
                if str(r.get("product") or "efootball_gt").strip().lower() == product
                and not r.get("settled")
                and not r.get("superseded_before_settlement")
            ),
            "recent_window": {
                "n": len(recent),
                "accuracy": recent_accuracy,
                "brier": recent_brier,
            },
            "calibration": {
                "active": bucket_active,
                "minimum_bucket_predictions": MIN_CALIBRATION_N,
                "buckets": buckets,
            },
            "exact_selection_active": exact_active,
            "exact_selection": exact,
        }

    # Keep the original top-level fields compatible with existing readers:
    # they describe eFootball GT only. New readers should use by_product.
    gt = by_product.get("efootball_gt", {})
    gt_calibration = gt.get("calibration") or {"active": False, "buckets": {}}
    gt_exact = gt.get("exact_selection") or {}
    active = bool(gt.get("active"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "active": active,
        "policy": {
            "minimum_calibration_predictions": MIN_CALIBRATION_N,
            "exact_selection_min_predictions": EXACT_MIN_N,
            "bucket_width": BUCKET_WIDTH,
            "recent_window": RECENT_WINDOW,
            "exact_scoring_granularity": "latest pre-kickoff forecast per product + fixture + totals line; different lines are scored independently",
            "future_leakage_protection": "only observations strictly before kickoff can become the scored forecast; settlement is read from independent virtual_lab_history",
            "products_are_never_pooled": True,
        },
        "settled_predictions": int(gt.get("settled_predictions") or 0),
        "total_settled_predictions": len(settled),
        "pending_forecasts": int(gt.get("pending_forecasts") or 0),
        "recent_window": gt.get("recent_window") or {"n": 0, "accuracy": 0.0, "brier": None},
        "calibration": {
            **gt_calibration,
            "settled_predictions": int(gt.get("settled_predictions") or 0),
        },
        "exact_selection": gt_exact,
        "by_product": by_product,
        "trace_artifact": "data/efootball_desk_prediction_history.json",
        "source_settlement": "data/virtual_lab_history.json",
        "reconciliation_diagnostics": reconciliation,
    }

    save(TRACE, trace)
    save(OUTPUT, report)
    print(json.dumps({
        "status": "ACTIVE" if active else "WARMUP",
        "settled_predictions": report["settled_predictions"],
        "total_settled_predictions": report["total_settled_predictions"],
        "by_product": {
            product: {
                "settled_predictions": metrics["settled_predictions"],
                "active": metrics["active"],
                "exact_selection_active": metrics["exact_selection_active"],
                "recent_accuracy": metrics["recent_window"]["accuracy"],
            }
            for product, metrics in by_product.items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
