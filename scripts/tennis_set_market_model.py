"""Tennis set-outcome probability engine.

Derives a set-level match distribution from the existing pre-match winner
probability, then calibrates the "player to win at least one set" event against
strictly prior, pre-event settled ATP results.  This is a research adapter:
markets remain non-qualifying until the separate walk-forward promotion gate
passes.  No bookmaker price is inferred or substituted.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARCHIVE_PATH = DATA / "tennis_prediction_archive.json"
REPORT_PATH = DATA / "tennis_set_market_model.json"

ACTIVE_TOUR = "ATP"
MIN_PRIOR_MATCHES = 30
MIN_LIVE_PRIOR_MATCHES = 30
MIN_BIN_OBSERVATIONS = 8
CALIBRATION_PRIOR_STRENGTH = 10.0
CALIBRATION_WINDOW = 240
MIN_WALK_FORWARD_MATCHES = 60
MIN_WALK_FORWARD_OBSERVATIONS = 100
MIN_BRIER_IMPROVEMENT = 0.0005
EPSILON = 1e-6


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _tour(row: dict[str, Any]) -> str:
    return str(row.get("league") or row.get("tour") or "").strip().upper()


def _bounded_probability(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        return None
    return min(1.0 - EPSILON, max(EPSILON, number))


def best_of(row: dict[str, Any]) -> int:
    """Use explicit format metadata; otherwise default to ATP best-of-three.

    Grand Slam detection is deliberately narrow. Unknown tournament formats
    are not silently treated as best-of-five.
    """
    for key in ("best_of", "bestOf", "sets_to_win_format"):
        try:
            value = int(row.get(key))
            if value in (3, 5):
                return value
        except (TypeError, ValueError):
            pass
    tournament = " ".join(
        str(row.get(key) or "")
        for key in ("tournament", "event_name", "competition", "league_name")
    ).lower()
    if any(name in tournament for name in (
        "australian open", "roland garros", "french open", "wimbledon", "us open"
    )):
        return 5
    return 3


def _match_win_probability_from_set(p_set: float, format_best_of: int) -> float:
    p = min(1.0, max(0.0, float(p_set)))
    q = 1.0 - p
    if format_best_of == 5:
        return p ** 3 * (1.0 + 3.0 * q + 6.0 * q * q)
    return p * p * (1.0 + 2.0 * q)


def set_win_probability_from_match(p_match: float, format_best_of: int = 3) -> float:
    """Invert the independent-set series to estimate per-set win probability."""
    p_match = min(1.0 - EPSILON, max(EPSILON, float(p_match)))
    low, high = 0.0, 1.0
    for _ in range(70):
        mid = (low + high) / 2.0
        estimate = _match_win_probability_from_set(mid, format_best_of)
        if estimate < p_match:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _raw_any_set_probability(p_match: float, format_best_of: int) -> float:
    per_set = set_win_probability_from_match(p_match, format_best_of)
    sets_to_win = format_best_of // 2 + 1
    # The only way a player wins no set is to lose the match by a shutout.
    return 1.0 - (1.0 - per_set) ** sets_to_win


def simulate_match_markets(p1_match_probability: float, format_best_of: int = 3) -> dict[str, Any]:
    """Derive internally consistent set-score, set-total and set-win markets."""
    p_match = min(1.0 - EPSILON, max(EPSILON, float(p1_match_probability)))
    p_set = set_win_probability_from_match(p_match, format_best_of)
    q_set = 1.0 - p_set
    required = format_best_of // 2 + 1
    any_p1 = 1.0 - q_set ** required
    any_p2 = 1.0 - p_set ** required

    scorelines: dict[str, float] = {}
    total_sets: dict[int, float] = {}
    if format_best_of == 5:
        scorelines = {
            "p1_3_0": p_set ** 3,
            "p1_3_1": 3.0 * p_set ** 3 * q_set,
            "p1_3_2": 6.0 * p_set ** 3 * q_set ** 2,
            "p2_0_3": q_set ** 3,
            "p2_1_3": 3.0 * q_set ** 3 * p_set,
            "p2_2_3": 6.0 * q_set ** 3 * p_set ** 2,
        }
        total_sets = {
            3: scorelines["p1_3_0"] + scorelines["p2_0_3"],
            4: scorelines["p1_3_1"] + scorelines["p2_1_3"],
            5: scorelines["p1_3_2"] + scorelines["p2_2_3"],
        }
    else:
        scorelines = {
            "p1_2_0": p_set ** 2,
            "p1_2_1": 2.0 * p_set ** 2 * q_set,
            "p2_0_2": q_set ** 2,
            "p2_1_2": 2.0 * q_set ** 2 * p_set,
        }
        total_sets = {
            2: scorelines["p1_2_0"] + scorelines["p2_0_2"],
            3: scorelines["p1_2_1"] + scorelines["p2_1_2"],
        }

    return {
        "best_of": format_best_of,
        "p1_set_win_probability": round(p_set, 6),
        "p2_set_win_probability": round(q_set, 6),
        "player_to_win_at_least_one_set": {
            "p1": round(any_p1, 6),
            "p2": round(any_p2, 6),
        },
        "first_set_winner": {"p1": round(p_set, 6), "p2": round(q_set, 6)},
        "match_winner": {"p1": round(p_match, 6), "p2": round(1.0 - p_match, 6)},
        "correct_set_score": {key: round(value, 6) for key, value in scorelines.items()},
        "total_sets": {str(key): round(value, 6) for key, value in total_sets.items()},
        "model": "match-win-to-set-score binomial simulation",
        "assumption": "sets are independent with a constant player-level set-win probability",
    }


def valid_record(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("sport") != "tennis" or not row.get("settled"):
        return False
    if _tour(row) != ACTIVE_TOUR:
        return False
    # Require the same strict provenance boundary used by the active ATP model.
    if row.get("evaluation_eligible") is not True or row.get("capture_status") != "PRE_EVENT":
        return False
    start = _parse_dt(row.get("start_time"))
    calculated = _parse_dt(row.get("calculated_at"))
    if start is None or calculated is None or calculated >= start:
        return False
    markets = row.get("actual_markets") or {}
    try:
        sets_p1 = int(markets.get("sets_won_p1"))
        sets_p2 = int(markets.get("sets_won_p2"))
    except (TypeError, ValueError):
        return False
    if sets_p1 < 0 or sets_p2 < 0 or sets_p1 + sets_p2 < 2:
        return False
    probs = row.get("probabilities") or {}
    return _bounded_probability(probs.get("p1")) is not None


def _observations(row: dict[str, Any]) -> list[tuple[float, int]]:
    p1_match = _bounded_probability((row.get("probabilities") or {}).get("p1"))
    if p1_match is None:
        return []
    simulated = simulate_match_markets(p1_match, best_of(row))
    actual = row.get("actual_markets") or {}
    try:
        p1_won_set = int(actual.get("sets_won_p1")) > 0
        p2_won_set = int(actual.get("sets_won_p2")) > 0
    except (TypeError, ValueError):
        return []
    return [
        (float(simulated["player_to_win_at_least_one_set"]["p1"]), int(p1_won_set)),
        (float(simulated["player_to_win_at_least_one_set"]["p2"]), int(p2_won_set)),
    ]


def _bin_key(probability: float) -> str:
    # Five broad bins avoid overfitting the limited early ATP set-outcome sample.
    index = min(4, max(0, int((float(probability) - 0.5) / 0.1)))
    low = 0.5 + index * 0.1
    return f"{low:.1f}-{low + 0.1:.1f}"


def fit_calibration(records: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [obs for row in records for obs in _observations(row)]
    if not observations:
        return {"n": 0, "base_rate": 0.5, "bins": {}}
    base_rate = sum(label for _, label in observations) / len(observations)
    bins: dict[str, list[int]] = {}
    for probability, label in observations:
        cell = bins.setdefault(_bin_key(probability), [0, 0])
        cell[0] += 1
        cell[1] += label
    return {
        "n": len(observations),
        "base_rate": round(base_rate, 6),
        "bins": {
            key: {"n": count, "wins": wins}
            for key, (count, wins) in bins.items()
        },
    }


def calibrate_any_set_probability(probability: float, calibration: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    key = _bin_key(probability)
    cell = (calibration.get("bins") or {}).get(key) or {}
    n = int(cell.get("n") or 0)
    wins = int(cell.get("wins") or 0)
    if n < MIN_BIN_OBSERVATIONS:
        return float(probability), {
            "applied": False,
            "reason": "insufficient_prior_bin_support",
            "bin": key,
            "bin_n": n,
        }
    # Bayesian shrinkage toward this fixture's own model probability.
    calibrated = (wins + CALIBRATION_PRIOR_STRENGTH * probability) / (n + CALIBRATION_PRIOR_STRENGTH)
    calibrated = min(1.0 - EPSILON, max(EPSILON, calibrated))
    return calibrated, {
        "applied": True,
        "reason": "strictly_prior_bin_calibration",
        "bin": key,
        "bin_n": n,
        "bin_wins": wins,
    }


def _metrics(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy": None}
    brier = 0.0
    log_loss = 0.0
    correct = 0
    for probability, label in items:
        p = min(1.0 - EPSILON, max(EPSILON, probability))
        brier += (p - label) ** 2
        log_loss -= label * math.log(p) + (1 - label) * math.log(1.0 - p)
        correct += int((p >= 0.5) == bool(label))
    n = len(items)
    return {
        "n": n,
        "brier": round(brier / n, 6),
        "log_loss": round(log_loss / n, 6),
        "accuracy": round(correct / n, 6),
    }


def walk_forward_evaluation(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        [row for row in records if valid_record(row)],
        key=lambda row: _parse_dt(row.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    raw_items: list[tuple[float, int]] = []
    calibrated_items: list[tuple[float, int]] = []
    evaluated_matches = 0
    prior: list[dict[str, Any]] = []
    index = 0

    # Score all fixtures at the same kickoff against the same strictly earlier
    # history snapshot; same-time results must never train one another.
    while index < len(ordered):
        target_time = _parse_dt(ordered[index].get("start_time"))
        end = index + 1
        while end < len(ordered) and _parse_dt(ordered[end].get("start_time")) == target_time:
            end += 1
        if len(prior) >= MIN_PRIOR_MATCHES:
            calibration = fit_calibration(prior[-CALIBRATION_WINDOW:])
            for target in ordered[index:end]:
                observations = _observations(target)
                if not observations:
                    continue
                evaluated_matches += 1
                for raw_probability, label in observations:
                    calibrated, _ = calibrate_any_set_probability(raw_probability, calibration)
                    raw_items.append((raw_probability, label))
                    calibrated_items.append((calibrated, label))
        prior.extend(ordered[index:end])
        index = end

    raw_metrics = _metrics(raw_items)
    calibrated_metrics = _metrics(calibrated_items)
    brier_improvement = None
    log_loss_improvement = None
    if raw_metrics["brier"] is not None and calibrated_metrics["brier"] is not None:
        brier_improvement = round(raw_metrics["brier"] - calibrated_metrics["brier"], 6)
    if raw_metrics["log_loss"] is not None and calibrated_metrics["log_loss"] is not None:
        log_loss_improvement = round(raw_metrics["log_loss"] - calibrated_metrics["log_loss"], 6)

    sample_ok = evaluated_matches >= MIN_WALK_FORWARD_MATCHES and len(raw_items) >= MIN_WALK_FORWARD_OBSERVATIONS
    model_improved = (
        brier_improvement is not None
        and brier_improvement >= MIN_BRIER_IMPROVEMENT
        and log_loss_improvement is not None
        and log_loss_improvement > 0.0
    )
    return {
        "evaluated_matches": evaluated_matches,
        "evaluated_player_selections": len(raw_items),
        "minimum_matches": MIN_WALK_FORWARD_MATCHES,
        "minimum_player_selections": MIN_WALK_FORWARD_OBSERVATIONS,
        "raw_model": raw_metrics,
        "calibrated_model": calibrated_metrics,
        "brier_improvement": brier_improvement,
        "log_loss_improvement": log_loss_improvement,
        "sample_gate_passed": sample_ok,
        "calibration_beats_raw": model_improved,
        "method": "strict chronological walk-forward; same-kickoff fixtures share prior-only history",
    }


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in records if valid_record(row)]
    validation = walk_forward_evaluation(eligible)
    promoted = validation["sample_gate_passed"] and validation["calibration_beats_raw"]
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "tennis-set-market-v1",
        "status": "QUALIFIED_PAPER_RESEARCH" if promoted else "RESEARCH_ONLY_HOLD",
        "active_scope": ACTIVE_TOUR,
        "training_matches": len(eligible),
        "validation": validation,
        "promotion_gate": {
            "passed": bool(promoted),
            "requirements": [
                f"at least {MIN_WALK_FORWARD_MATCHES} strictly prequential evaluated matches",
                f"at least {MIN_WALK_FORWARD_OBSERVATIONS} player-market observations",
                f"calibrated Brier improvement >= {MIN_BRIER_IMPROVEMENT}",
                "calibrated log loss must improve over the uncalibrated set-simulation baseline",
            ],
            "reason": (
                "independent set-market walk-forward evidence passed"
                if promoted else
                "set-market qualification held pending independent walk-forward evidence"
            ),
        },
        "model": "match-win-to-set-score binomial simulation + prior-only empirical calibration",
        "guardrails": [
            "ATP history only; no WTA pooling",
            "only settled pre-event records with explicit PRE_EVENT provenance are eligible",
            "same-kickoff fixtures do not train one another",
            "market probabilities are computed before bookmaker prices are considered",
            "exact current SportyBet market and outcome identifiers are required for ticket candidates",
            "existing Odds Builder value, freshness, uncertainty and correlation gates remain unchanged",
            "paper research only; no real-money execution",
        ],
    }


def predict_target(target: dict[str, Any], history: list[dict[str, Any]], report: dict[str, Any] | None = None) -> dict[str, Any]:
    start = _parse_dt(target.get("start_time"))
    prior = [
        row for row in history
        if valid_record(row)
        and _tour(row) == _tour(target)
        and start is not None
        and (_parse_dt(row.get("start_time")) is not None)
        and _parse_dt(row.get("start_time")) < start
    ]
    p1_match = _bounded_probability((target.get("probabilities") or {}).get("p1"))
    if p1_match is None:
        return {"status": "NO_MATCH_WIN_PROBABILITY", "prior_matches": len(prior)}
    simulated = simulate_match_markets(p1_match, best_of(target))
    calibration = fit_calibration(prior[-CALIBRATION_WINDOW:])
    calibrated_probs = {}
    calibration_audit = {}
    for side in ("p1", "p2"):
        raw = float(simulated["player_to_win_at_least_one_set"][side])
        calibrated, audit = calibrate_any_set_probability(raw, calibration)
        calibrated_probs[side] = round(calibrated, 6)
        calibration_audit[side] = audit

    promotion_passed = bool((report or {}).get("promotion_gate", {}).get("passed"))
    live_ready = len(prior) >= MIN_LIVE_PRIOR_MATCHES and promotion_passed
    return {
        "status": "QUALIFIED_PAPER_RESEARCH" if live_ready else "RESEARCH_ONLY_HOLD",
        "prior_matches": len(prior),
        "best_of": best_of(target),
        "simulation": simulated,
        "player_to_win_at_least_one_set": calibrated_probs,
        "raw_player_to_win_at_least_one_set": simulated["player_to_win_at_least_one_set"],
        "calibration": calibration_audit,
        "promotion_gate_passed": promotion_passed,
        "qualification_reason": (
            "independent set-market walk-forward gate passed"
            if live_ready else
            "set-market walk-forward gate or prior-history minimum not met"
        ),
    }


def main() -> None:
    try:
        records = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        records = []
    if not isinstance(records, list):
        records = []
    report = build_report(records)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
