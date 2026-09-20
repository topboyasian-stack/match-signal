"""V5.1 tennis Total Games model.\n\nProduction QA uses a chronological walk-forward gate before promotion.

Walk-forward, leakage-safe empirical distribution model. It replaces the old
single sigmoid over/under transform with a matchup-conditioned distribution
learned from previously settled singles matches.

Features:
- model confidence (proxy for strength gap)
- ranking gap when both rankings are available
- recent-form gap
- recency of the historical match

Only matches strictly earlier than the target are eligible, so the model never
uses a future result to predict the present.
"""
import math
from datetime import datetime, timezone

MIN_HISTORY = 30
MAX_NEIGHBORS = 60
HALF_LIFE_DAYS = 45.0
CONF_SCALE = 0.08
FORM_SCALE = 0.12
RANK_SCALE = 30.0
UNKNOWN_RANK_PENALTY = 0.70


def _parse_time(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _features(row):
    probabilities = row.get("probabilities") or {}
    confidence = max(
        float(probabilities.get("p1") or 0.5),
        float(probabilities.get("p2") or 0.5),
    )
    rankings = row.get("rankings") or {}
    rank1, rank2 = rankings.get("p1"), rankings.get("p2")
    rank_gap = None
    if rank1 not in (None, "", 0) and rank2 not in (None, "", 0):
        try:
            rank_gap = abs(float(rank1) - float(rank2))
        except (TypeError, ValueError):
            rank_gap = None
    form = row.get("form") or {}
    try:
        form_gap = abs(float(form.get("p1", 0.5)) - float(form.get("p2", 0.5)))
    except (TypeError, ValueError):
        form_gap = 0.25
    return confidence, rank_gap, form_gap


def _eligible(row):
    if row.get("sport") != "tennis" or not row.get("settled"):
        return False
    score = row.get("final_score")
    if not isinstance(score, list) or len(score) != 2:
        return False
    names = {
        str(row.get("player_1") or "").strip().lower(),
        str(row.get("player_2") or "").strip().lower(),
    }
    if names & {"", "tbd", "tba", "player 1", "player 2", "unknown"}:
        return False
    try:
        return sum(float(v) for v in score) > 0
    except (TypeError, ValueError):
        return False


def _weight(target, row):
    tc, tr, tf = _features(target)
    rc, rr, rf = _features(row)
    distance = abs(tc - rc) / CONF_SCALE
    distance += abs(tf - rf) / FORM_SCALE
    if tr is not None and rr is not None:
        distance += abs(tr - rr) / RANK_SCALE
    else:
        distance += UNKNOWN_RANK_PENALTY

    dt_target = _parse_time(target.get("start_time"))
    dt_row = _parse_time(row.get("start_time"))
    if dt_target and dt_row and dt_row < dt_target:
        age_days = max(0.0, (dt_target - dt_row).total_seconds() / 86400.0)
        recency = math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS)
    else:
        recency = 0.05

    return math.exp(-distance) * recency


def predict_total_games(target, history):
    """Return a matchup-conditioned probability distribution for total games."""
    target_time = _parse_time(target.get("start_time"))
    eligible = []
    for row in history or []:
        if not _eligible(row):
            continue
        row_time = _parse_time(row.get("start_time"))
        if target_time and row_time and row_time >= target_time:
            continue
        if not target_time or not row_time:
            continue
        weight = _weight(target, row)
        total = sum(float(v) for v in row["final_score"])
        eligible.append((row, weight, total))

    eligible.sort(key=lambda item: item[1], reverse=True)
    eligible = eligible[:MAX_NEIGHBORS]

    if len(eligible) < MIN_HISTORY:
        return None

    # Small pseudo-count keeps an unseen total from receiving exactly zero mass.
    distribution = {total: 0.05 for total in range(12, 45)}
    weighted_total = sum(total * weight for _, weight, total in eligible)
    weight_sum = sum(weight for _, weight, _ in eligible)

    for _, weight, total in eligible:
        distribution[total] = distribution.get(total, 0.05) + weight

    total_mass = sum(distribution.values())
    distribution = {k: v / total_mass for k, v in distribution.items()}
    expected_total = weighted_total / weight_sum if weight_sum else 22.0

    return {
        "distribution": {str(int(k) if float(k).is_integer() else k): round(v, 6) for k, v in sorted(distribution.items())},
        "expected_total": round(expected_total, 3),
        "neighbors": len(eligible),
        "effective_sample": round(weight_sum, 3),
        "model": "V5.1 matchup-conditioned empirical total-games distribution",
    }


def over_probability(target, history, line):
    result = predict_total_games(target, history)
    if not result:
        return None
    over = sum(prob for total, prob in result["distribution"].items() if float(total) > float(line))
    result["line"] = float(line)
    result["over"] = round(over, 6)
    result["under"] = round(1.0 - over, 6)
    result["pick"] = "over" if over >= 0.5 else "under"
    return result


def walk_forward_backtest(history, min_train=MIN_HISTORY):
    """Compare V5.1 with the stored pre-V5.1 raw Total Games model."""
    rows = sorted(
        [row for row in history or [] if _eligible(row)],
        key=lambda row: _parse_time(row.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    baseline_brier = baseline_correct = v51_brier = v51_correct = 0.0
    tested = 0

    for index, row in enumerate(rows):
        prior = rows[:index]
        if len(prior) < min_train:
            continue
        line = float((row.get("analytics") or {}).get("total_games", {}).get("line") or 22.5)
        actual = 1.0 if sum(float(v) for v in row["final_score"]) > line else 0.0
        baseline = float((row.get("analytics") or {}).get("total_games", {}).get("over") or 0.5)
        result = over_probability(row, prior, line)
        if not result:
            continue
        predicted = result["over"]
        baseline_brier += (baseline - actual) ** 2
        v51_brier += (predicted - actual) ** 2
        baseline_correct += float((baseline >= 0.5) == bool(actual))
        v51_correct += float((predicted >= 0.5) == bool(actual))
        tested += 1

    if not tested:
        return {"status": "insufficient_history", "tested": 0}

    return {
        "status": "ok",
        "tested": tested,
        "baseline_brier": round(baseline_brier / tested, 6),
        "v51_brier": round(v51_brier / tested, 6),
        "baseline_accuracy": round(baseline_correct / tested, 6),
        "v51_accuracy": round(v51_correct / tested, 6),
        "brier_improvement": round((baseline_brier - v51_brier) / tested, 6),
        "accuracy_improvement": round((v51_correct - baseline_correct) / tested, 6),
    }
