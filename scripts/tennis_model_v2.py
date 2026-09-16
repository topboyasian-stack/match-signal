import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS_PATH = DATA / "predictions.json"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
REPORT_PATH = DATA / "tennis_model_v2.json"

V2_VERSION = "2026-09-16-elo-calibration"
INITIAL_ELO = 1500.0
K_FACTOR = 24.0
MIN_TRAIN = 30
RECENT_WINDOW = 80


def parse_dt(value):
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def clamp(p, low=0.02, high=0.98):
    return max(low, min(high, float(p)))


def elo_prob(a, b):
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def outcome_from_record(row):
    actual = row.get("actual")
    if actual == "p1":
        return 1.0
    if actual == "p2":
        return 0.0
    return None


def valid_record(row):
    if row.get("sport") != "tennis" or not row.get("settled"):
        return False
    if row.get("capture_status") == "LATE_CAPTURE" or row.get("evaluation_eligible") is False:
        return False
    if outcome_from_record(row) is None:
        return False
    p1 = str(row.get("player_1") or "").strip().lower()
    p2 = str(row.get("player_2") or "").strip().lower()
    if p1 in {"", "player 1", "tbd", "tba"} or p2 in {"", "player 2", "tbd", "tba"}:
        return False
    return True


def build_walkforward(records, elo_weight):
    ratings = {}
    scored = []
    for row in sorted(records, key=lambda x: parse_dt(x.get("start_time"))):
        p1 = row.get("player_1")
        p2 = row.get("player_2")
        if not p1 or not p2:
            continue
        r1 = ratings.get(p1, INITIAL_ELO)
        r2 = ratings.get(p2, INITIAL_ELO)
        ep = elo_prob(r1, r2)
        base = float((row.get("probabilities") or {}).get("p1", 0.5))
        blend = clamp((1.0 - elo_weight) * base + elo_weight * ep)
        actual = outcome_from_record(row)
        scored.append((row, blend, actual, ep, base))
        change = K_FACTOR * (actual - ep)
        ratings[p1] = r1 + change
        ratings[p2] = r2 - change
    return scored, ratings


def accuracy(items):
    if not items:
        return 0.0
    return sum((p >= 0.5) == bool(actual) for _, p, actual, _, _ in items) / len(items)


def brier(items):
    if not items:
        return 1.0
    return sum((p - actual) ** 2 for _, p, actual, _, _ in items) / len(items)


def choose_elo_weight(records):
    if len(records) < MIN_TRAIN:
        return 0.5, {"reason": "insufficient_history"}
    candidates = [0.25, 0.5, 0.75]
    window = records[-RECENT_WINDOW:]
    results = []
    for weight in candidates:
        items, _ = build_walkforward(window, weight)
        results.append({"elo_weight": weight, "accuracy": round(accuracy(items), 4), "brier": round(brier(items), 4), "n": len(items)})
    best = min(results, key=lambda x: (x["brier"], -x["accuracy"]))
    return best["elo_weight"], {"selection_window": len(window), "candidates": results, "selected": best}


def build_current_ratings(records):
    ratings = {}
    for row in sorted(records, key=lambda x: parse_dt(x.get("start_time"))):
        p1, p2 = row.get("player_1"), row.get("player_2")
        if not p1 or not p2:
            continue
        r1 = ratings.get(p1, INITIAL_ELO)
        r2 = ratings.get(p2, INITIAL_ELO)
        actual = outcome_from_record(row)
        if actual is None:
            continue
        change = K_FACTOR * (actual - elo_prob(r1, r2))
        ratings[p1] = r1 + change
        ratings[p2] = r2 - change
    return ratings


def build_ou_empirical(records):
    bins = {"low": [0, 0], "mid": [0, 0], "high": [0, 0]}
    for row in records:
        actual_markets = row.get("actual_markets") or {}
        result = actual_markets.get("total_games_result")
        analytics = row.get("analytics") or {}
        three = analytics.get("three_sets")
        if result not in {"over", "under"} or three is None:
            continue
        key = "low" if float(three) < 0.46 else "high" if float(three) > 0.56 else "mid"
        bucket = bins[key]
        bucket[0] += 1
        bucket[1] += result == "over"
    rates = {}
    for key, (n, over) in bins.items():
        rates[key] = (over + 2) / (n + 4) if n else 0.5
    return {"bins": bins, "over_rates": rates}


def apply_model(predictions, ratings, elo_weight, ou_model):
    changed = 0
    for row in predictions:
        if row.get("sport") != "tennis":
            continue
        p1, p2 = row.get("player_1"), row.get("player_2")
        r1 = ratings.get(p1, INITIAL_ELO)
        r2 = ratings.get(p2, INITIAL_ELO)
        ep = elo_prob(r1, r2)
        probs = row.get("probabilities") or {}
        base = clamp(float(probs.get("p1", 0.5)))
        has_history = p1 in ratings or p2 in ratings
        if has_history:
            updated = clamp((1.0 - elo_weight) * base + elo_weight * ep)
        else:
            updated = base
        row.setdefault("probabilities", {})["p1"] = round(updated, 4)
        row["probabilities"]["p2"] = round(1.0 - updated, 4)
        row["pick"] = "p1" if updated >= 0.5 else "p2"
        row["confidence"] = round(max(updated, 1.0 - updated), 4)
        row["analytics"] = row.get("analytics") or {}
        row["analytics"]["elo"] = {"p1": round(r1, 1), "p2": round(r2, 1), "p1_win_prob": round(ep, 4), "weight": elo_weight}
        quality = row.get("signal_quality") or {}
        quality["elo_available"] = has_history
        quality["elo_gap"] = round(r1 - r2, 1) if has_history else None
        quality["components"] = max(int(quality.get("components") or 0), 1 + int(has_history))
        row["signal_quality"] = quality
        row["model"] = "ESPN + ranking/form base + walk-forward player Elo"
        row["model_version"] = V2_VERSION
        changed += 1

        total = row["analytics"].get("total_games") or {}
        line = total.get("line")
        if line == 22.5:
            three = float((row["analytics"].get("three_sets") or 0.5))
            key = "low" if three < 0.46 else "high" if three > 0.56 else "mid"
            over = float(ou_model["over_rates"].get(key, 0.5))
            total["over"] = round(over, 4)
            total["under"] = round(1.0 - over, 4)
            total["pick"] = "over" if over >= 0.5 else "under"
            total["source"] = "empirical settled-tennis calibration"
            total["calibration_status"] = "PAPER_RESEARCH"
            row["analytics"]["total_games"] = total
    return changed


def main():
    predictions = json.loads(PREDICTIONS_PATH.read_text())
    archive = json.loads(ARCHIVE_PATH.read_text()) if ARCHIVE_PATH.exists() else []
    records = [r for r in archive if valid_record(r)]
    records.sort(key=lambda x: parse_dt(x.get("start_time")))
    elo_weight, selection = choose_elo_weight(records)
    ratings = build_current_ratings(records)
    ou_model = build_ou_empirical(records)
    changed = apply_model(predictions, ratings, elo_weight, ou_model)
    PREDICTIONS_PATH.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n")
    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": V2_VERSION,
        "status": "PAPER_RESEARCH_ONLY",
        "training_records": len(records),
        "elo_weight": elo_weight,
        "weight_selection": selection,
        "players_in_elo": len(ratings),
        "ou_calibration": ou_model,
        "current_tennis_predictions_rewritten": changed,
        "guardrails": [
            "No future results are used for a fixture before its start time.",
            "Late-captured predictions are excluded from walk-forward model evaluation.",
            "Unseen players retain the existing model probability.",
            "O/U calibration is research-only and remains separate from live-money execution."
        ]
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
