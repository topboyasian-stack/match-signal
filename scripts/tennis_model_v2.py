import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests

# Automated prediction-cycle trigger: keep this model in the scheduled pipeline.
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PREDICTIONS_PATH = DATA / "predictions.json"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
REPORT_PATH = DATA / "tennis_model_v2.json"
PRECISION_PATH = DATA / "tennis_precision_gate.json"

V2_VERSION = "2026-09-17-walkforward-calibrated"
INITIAL_ELO = 1500.0
K_FACTOR = 24.0
MIN_TRAIN = 30
RECENT_WINDOW = 80
MIN_CALIBRATION_BIN = 8
MIN_PRECISION_N = 12
RANKINGS_URL = "https://site.web.api.espn.com/apis/site/v2/sports/tennis/{tour}/rankings?region=us&lang=en"


def parse_dt(value):
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def clamp(p, low=0.02, high=0.98):
    return max(low, min(high, float(p)))


def norm_name(value):
    return " ".join(str(value or "").lower().replace("-", " ").split())


def elo_prob(a, b):
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def rank_prob(rank1, rank2):
    if not rank1 or not rank2:
        return None
    edge = math.log((float(rank2) + 4.0) / (float(rank1) + 4.0))
    return clamp(1.0 / (1.0 + math.exp(-1.35 * edge)))


def fetch_current_rankings():
    result = {}
    coverage = {}
    for tour in ("atp", "wta"):
        try:
            response = requests.get(RANKINGS_URL.format(tour=tour), timeout=30, headers={"User-Agent": "MatchSignal/4.0"})
            response.raise_for_status()
            payload = response.json()
            ranks = (payload.get("rankings") or [{}])[0].get("ranks") or []
            count = 0
            for item in ranks:
                athlete = item.get("athlete") or {}
                name = norm_name(athlete.get("displayName") or item.get("displayName") or athlete.get("fullName"))
                current = item.get("current") or item.get("rank")
                if name and current:
                    result[name] = int(current)
                    count += 1
            coverage[tour.upper()] = count
        except Exception as exc:
            coverage[tour.upper()] = f"error:{type(exc).__name__}"
    return result, coverage


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
    p1 = norm_name(row.get("player_1"))
    p2 = norm_name(row.get("player_2"))
    if p1 in {"", "player 1", "tbd", "tba"} or p2 in {"", "player 2", "tbd", "tba"}:
        return False
    return True


def build_walkforward(records, elo_weight):
    ratings = {}
    scored = []
    for row in sorted(records, key=lambda x: parse_dt(x.get("start_time"))):
        p1 = norm_name(row.get("player_1"))
        p2 = norm_name(row.get("player_2"))
        if not p1 or not p2:
            continue
        r1 = ratings.get(p1, INITIAL_ELO)
        r2 = ratings.get(p2, INITIAL_ELO)
        ep = elo_prob(r1, r2)
        base = clamp(float((row.get("probabilities") or {}).get("p1", 0.5)))
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


def baseline_metrics(records):
    items = []
    for row in records:
        p = clamp(float((row.get("probabilities") or {}).get("p1", 0.5)))
        actual = outcome_from_record(row)
        if actual is not None:
            items.append((row, p, actual, 0.5, p))
    return {"accuracy": round(accuracy(items), 4), "brier": round(brier(items), 4), "n": len(items)}


def choose_elo_weight(records):
    if len(records) < MIN_TRAIN:
        return 0.5, {"reason": "insufficient_history", "baseline": baseline_metrics(records)}
    candidates = [0.25, 0.5, 0.75]
    window = records[-RECENT_WINDOW:]
    results = []
    for weight in candidates:
        items, _ = build_walkforward(window, weight)
        results.append({"elo_weight": weight, "accuracy": round(accuracy(items), 4), "brier": round(brier(items), 4), "n": len(items)})
    best = max(results, key=lambda x: (x["accuracy"], -x["brier"]))
    return best["elo_weight"], {"selection_window": len(window), "baseline": baseline_metrics(window), "candidates": results, "selected": best}


def build_current_ratings(records):
    ratings = {}
    for row in sorted(records, key=lambda x: parse_dt(x.get("start_time"))):
        p1, p2 = norm_name(row.get("player_1")), norm_name(row.get("player_2"))
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


def build_probability_calibration(items):
    bins = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.001]
    rows = []
    for low, high in zip(bins[:-1], bins[1:]):
        selected = [item for item in items if low <= max(item[1], 1.0 - item[1]) < high]
        n = len(selected)
        correct = sum(((item[1] >= 0.5) == bool(item[2])) for item in selected)
        if n >= MIN_CALIBRATION_BIN:
            raw_conf = sum(max(item[1], 1.0 - item[1]) for item in selected) / n
            observed = (correct + 2.0 * raw_conf) / (n + 2.0)
            rows.append({"low": low, "high": high, "n": n, "accuracy": round(correct / n, 4), "calibrated_confidence": round(observed, 4)})
        else:
            rows.append({"low": low, "high": high, "n": n, "accuracy": None, "calibrated_confidence": None})
    return rows


def calibrate_probability(p, calibration):
    confidence = max(p, 1.0 - p)
    for item in calibration:
        if item["low"] <= confidence < item["high"] and item["calibrated_confidence"] is not None:
            calibrated_conf = 0.60 * item["calibrated_confidence"] + 0.40 * confidence
            return clamp(calibrated_conf if p >= 0.5 else 1.0 - calibrated_conf)
    return clamp(p)


def wilson_lower(successes, n, z=1.645):
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) / n) + (z * z / (4.0 * n * n)))
    return (centre - margin) / denom


def build_precision_gate(items):
    thresholds = [0.60, 0.65, 0.70, 0.75, 0.80]
    rows = []
    for threshold in thresholds:
        selected = [item for item in items if max(item[1], 1.0 - item[1]) >= threshold]
        n = len(selected)
        correct = sum(((item[1] >= 0.5) == bool(item[2])) for item in selected)
        acc = correct / n if n else 0.0
        rows.append({"threshold": threshold, "n": n, "correct": correct, "accuracy": round(acc, 4) if n else None, "wilson_lower_90": round(wilson_lower(correct, n), 4) if n else None})
    eligible = [r for r in rows if r["n"] >= MIN_PRECISION_N]
    selected = max(eligible, key=lambda r: (r["wilson_lower_90"], r["accuracy"], r["n"])) if eligible else {"threshold": 0.65, "reason": "insufficient_sample"}
    return {"minimum_sample": MIN_PRECISION_N, "candidates": rows, "selected": selected, "mode": "PAPER_ONLY"}


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
    rates = {key: (over + 2) / (n + 4) if n else 0.5 for key, (n, over) in bins.items()}
    return {"bins": bins, "over_rates": rates}


def apply_model(predictions, ratings, elo_weight, current_rankings, calibration):
    changed = 0
    ranking_enriched = 0
    for row in predictions:
        if row.get("sport") != "tennis":
            continue
        p1, p2 = norm_name(row.get("player_1")), norm_name(row.get("player_2"))
        r1 = ratings.get(p1, INITIAL_ELO)
        r2 = ratings.get(p2, INITIAL_ELO)
        ep = elo_prob(r1, r2)
        probs = row.get("probabilities") or {}
        base = clamp(float(probs.get("p1", 0.5)))
        rank1 = current_rankings.get(norm_name(p1))
        rank2 = current_rankings.get(norm_name(p2))
        rp = rank_prob(rank1, rank2)
        has_history = p1 in ratings or p2 in ratings
        if rp is not None and has_history:
            raw = clamp(0.50 * base + 0.30 * ep + 0.20 * rp)
            ranking_enriched += 1
        elif has_history:
            raw = clamp((1.0 - elo_weight) * base + elo_weight * ep)
        elif rp is not None:
            raw = clamp(0.70 * base + 0.30 * rp)
            ranking_enriched += 1
        else:
            raw = base
        updated = calibrate_probability(raw, calibration)
        row.setdefault("probabilities", {})["p1"] = round(updated, 4)
        row["probabilities"]["p2"] = round(1.0 - updated, 4)
        row["pick"] = "p1" if updated >= 0.5 else "p2"
        row["confidence"] = round(max(updated, 1.0 - updated), 4)
        row["rankings"] = {"p1": rank1, "p2": rank2, "gap": (rank2 - rank1) if rank1 and rank2 else None}
        row.setdefault("analytics", {})["elo"] = {"p1": round(r1, 1), "p2": round(r2, 1), "p1_win_prob": round(ep, 4), "weight": elo_weight}
        row["analytics"]["walkforward_raw_p1"] = round(raw, 4)
        row["analytics"]["walkforward_calibrated_p1"] = round(updated, 4)
        if rp is not None:
            row["analytics"]["ranking_probability"] = round(rp, 4)
        quality = row.get("signal_quality") or {}
        quality["elo_available"] = has_history
        quality["elo_gap"] = round(r1 - r2, 1) if has_history else None
        quality["ranking_available"] = rp is not None
        quality["components"] = max(int(quality.get("components") or 0), 1 + int(has_history) + int(rp is not None))
        row["signal_quality"] = quality
        row["model"] = "ESPN + ranking/form base + walk-forward player Elo + current ATP/WTA rank + walk-forward probability calibration"
        row["model_version"] = V2_VERSION
        changed += 1
        total = row.get("analytics", {}).get("total_games") or {}
        if total.get("line") == 22.5:
            prior = float(total.get("base_model_over", total.get("over", 0.5)) or 0.5)
            total["base_model_over"] = round(prior, 4)
            total["base_model_under"] = round(1.0 - prior, 4)
            total["pre_calibration_source"] = "walk-forward tennis set/game model"
            row["analytics"]["total_games"] = total
    return changed, ranking_enriched


def main():
    predictions = json.loads(PREDICTIONS_PATH.read_text())
    archive = json.loads(ARCHIVE_PATH.read_text()) if ARCHIVE_PATH.exists() else []
    records = sorted([r for r in archive if valid_record(r)], key=lambda x: parse_dt(x.get("start_time")))
    elo_weight, selection = choose_elo_weight(records)
    ratings = build_current_ratings(records)
    current_rankings, ranking_coverage = fetch_current_rankings()
    walkforward_items, _ = build_walkforward(records, elo_weight)
    calibration = build_probability_calibration(walkforward_items)
    precision_gate = build_precision_gate(walkforward_items)
    changed, ranking_enriched = apply_model(predictions, ratings, elo_weight, current_rankings, calibration)
    PREDICTIONS_PATH.write_text(json.dumps(predictions, indent=2, ensure_ascii=False) + "\n")
    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": V2_VERSION,
        "status": "PAPER_RESEARCH_ONLY",
        "training_records": len(records),
        "elo_weight": elo_weight,
        "weight_selection": selection,
        "players_in_elo": len(ratings),
        "ranking_coverage": ranking_coverage,
        "current_predictions_with_rank_enrichment": ranking_enriched,
        "walkforward_probability_calibration": calibration,
        "precision_gate": precision_gate,
        "current_tennis_predictions_rewritten": changed,
        "guardrails": [
            "No future results are used for a fixture before its start time.",
            "Late-captured predictions are excluded from walk-forward model evaluation.",
            "Unseen players retain the existing model probability unless a current official ESPN rank is available.",
            "Current rankings are used only for future fixtures and are not used to score the historical walk-forward test.",
            "Probability calibration is learned only from historical walk-forward predictions and is conservatively shrunk toward raw model probabilities.",
            "Precision thresholds are research filters, not guarantees of future accuracy.",
            "O/U calibration remains research-only and separate from live-money execution."
        ]
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    PRECISION_PATH.write_text(json.dumps(precision_gate, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
