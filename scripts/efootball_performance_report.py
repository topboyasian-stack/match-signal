#!/usr/bin/env python3
"""Build an explainable, paper-only eFootball performance report from frozen ledgers.

This report is diagnostic. It never changes qualification, selects production picks,
or enables live trading. Segment results are exploratory, especially where fixtures
share participants, lines, or tickets.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_PATH = DATA / "efootball_performance_report.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def number(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def rounded(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def wilson_interval(wins: int, n: int) -> list[float] | None:
    if n <= 0:
        return None
    z = 1.959963984540054
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / den
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def mean_interval(values: list[float]) -> list[float] | None:
    """Approximate 95% CI for the arithmetic mean; not a dependence-adjusted interval."""
    if len(values) < 2:
        return None
    avg = mean(values)
    assert avg is not None
    variance = sum((x - avg) ** 2 for x in values) / (len(values) - 1)
    half = 1.959963984540054 * math.sqrt(variance / len(values))
    return [round(avg - half, 4), round(avg + half, 4)]


def outcome_stats(rows: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    """Summarize settled one-unit selections/tickets without counting pending rows."""
    resolved: list[tuple[dict[str, Any], bool, float]] = []
    for row in rows:
        status = str(row.get("settlement_status") or row.get("status") or "").strip().lower()
        if mode == "ou":
            win = row.get("win")
            if row.get("settled") is not True or not isinstance(win, bool) or row.get("push") is True:
                continue
            odds = number(row.get("bookmaker_odds"))
            if odds is None or odds <= 1:
                continue
            profit = odds - 1 if win else -1.0
        elif mode == "market":
            if status != "settled" or not isinstance(row.get("favourite_correct"), bool):
                continue
            win = row["favourite_correct"]
            stored_profit = number(row.get("favourite_net_units"))
            if stored_profit is None:
                odds = number(row.get("favourite_odds"))
                if odds is None or odds <= 1:
                    continue
                stored_profit = odds - 1 if win else -1.0
            profit = stored_profit
        else:
            win_status = status in {"won", "win", "settled_won"}
            loss_status = status in {"lost", "loss", "settled_lost"}
            if not (win_status or loss_status):
                continue
            odds = number(row.get("combined_odds"))
            if odds is None or odds <= 1:
                continue
            win = win_status
            profit = odds - 1 if win else -1.0
        resolved.append((row, win, profit))

    n = len(resolved)
    wins = sum(1 for _, win, _ in resolved if win)
    profits = [profit for _, _, profit in resolved]
    probabilities: list[float] = []
    briers: list[float] = []
    log_losses: list[float] = []
    odds_values: list[float] = []
    for row, win, _ in resolved:
        if mode == "ou":
            p = number(row.get("model_probability"))
            odds = number(row.get("bookmaker_odds"))
            if p is not None and 0 <= p <= 1:
                probabilities.append(p)
                briers.append((p - (1.0 if win else 0.0)) ** 2)
            if odds is not None and odds > 1:
                odds_values.append(odds)
        elif mode == "market":
            odds = number(row.get("favourite_odds"))
            if odds is not None and odds > 1:
                odds_values.append(odds)
            brier = number(row.get("market_brier"))
            log_loss = number(row.get("market_log_loss"))
            if brier is not None:
                briers.append(brier)
            if log_loss is not None:
                log_losses.append(log_loss)
        else:
            odds = number(row.get("combined_odds"))
            if odds is not None and odds > 1:
                odds_values.append(odds)
            p = number(row.get("combined_model_probability"))
            if p is not None and 0 <= p <= 1:
                probabilities.append(p)

    total_profit = sum(profits)
    roi = total_profit / n if n else None
    result: dict[str, Any] = {
        "settled": n,
        "wins": wins,
        "losses": n - wins,
        "hit_rate": rounded(wins / n if n else None),
        "hit_rate_95_wilson": wilson_interval(wins, n),
        "flat_stake_net_units": rounded(total_profit),
        "flat_stake_roi": rounded(roi),
        "flat_stake_roi_95_approx": mean_interval(profits),
        "mean_odds": rounded(mean(odds_values), 3),
        "mean_model_probability": rounded(mean(probabilities)),
        "mean_brier": rounded(mean(briers)),
        "mean_log_loss": rounded(mean(log_losses)),
    }
    return result


def group_rows(rows: list[dict[str, Any]], key_fn) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "unknown")].append(row)
    return dict(sorted(groups.items()))


def confidence_bucket(value: Any) -> str:
    p = number(value)
    if p is None:
        return "unknown"
    if p < 0.60:
        return "<60%"
    if p < 0.70:
        return "60-69.9%"
    if p < 0.80:
        return "70-79.9%"
    if p < 0.90:
        return "80-89.9%"
    return "90%+"


def odds_bucket(value: Any) -> str:
    odds = number(value)
    if odds is None:
        return "unknown"
    if odds < 1.50:
        return "<1.50"
    if odds < 2.00:
        return "1.50-1.99"
    if odds < 2.50:
        return "2.00-2.49"
    if odds < 3.00:
        return "2.50-2.99"
    if odds < 4.00:
        return "3.00-3.99"
    return "4.00+"


def time_bucket(value: Any) -> str:
    dt = parse_time(value)
    if dt is None:
        return "unknown"
    h = dt.hour
    return "00-05 UTC" if h < 6 else "06-11 UTC" if h < 12 else "12-17 UTC" if h < 18 else "18-23 UTC"


def settled_ou_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("settled") is True and isinstance(r.get("win"), bool) and r.get("push") is not True]


def settled_market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("settlement_status") or "").lower() == "settled"
            and isinstance(r.get("favourite_correct"), bool)]


def sorted_chronologically(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (parse_time(r.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc),
                                       str(r.get("sample_id") or r.get("trace_id") or r.get("ticket_id") or "")))


def split_chronological(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    ordered = sorted_chronologically(rows)
    cut = int(len(ordered) * 0.70)
    return {
        "method": "sort by scheduled start time; earliest 70% versus most recent 30%; descriptive only",
        "first_70_percent": outcome_stats(ordered[:cut], mode=mode),
        "latest_30_percent": outcome_stats(ordered[cut:], mode=mode),
    }


def segment_report(rows: list[dict[str, Any]], *, mode: str, selectors: dict[str, Any],
                   min_n: int = 1) -> dict[str, Any]:
    settled = rows if mode == "ou" else rows
    result: dict[str, Any] = {}
    for name, key_fn in selectors.items():
        groups = group_rows(settled, key_fn)
        values = []
        for group, items in groups.items():
            stats = outcome_stats(items, mode=mode)
            if stats["settled"] < min_n:
                continue
            entry = {"group": group, **stats}
            roi = stats.get("flat_stake_roi")
            n = stats["settled"]
            if n < 20:
                entry["screening_label"] = "small sample — inspect only"
            elif roi is not None and roi <= -0.05:
                entry["screening_label"] = "weakness to investigate"
            elif roi is not None and roi >= 0.05:
                entry["screening_label"] = "positive screen — needs holdout confirmation"
            else:
                entry["screening_label"] = "monitor"
            values.append(entry)
        result[name] = sorted(values, key=lambda x: x["group"])
    return result


def extremes(groups: list[dict[str, Any]], *, min_n: int = 10, limit: int = 5) -> dict[str, Any]:
    eligible = [g for g in groups if g.get("settled", 0) >= min_n and g.get("flat_stake_roi") is not None]
    return {
        "minimum_sample_for_exploratory_extremes": min_n,
        "best_observed_roi": sorted(eligible, key=lambda g: g["flat_stake_roi"], reverse=True)[:limit],
        "worst_observed_roi": sorted(eligible, key=lambda g: g["flat_stake_roi"])[:limit],
        "warning": "Post-hoc segments overlap or share events and many comparisons are made; do not promote or blacklist a segment from this ranking alone."
    }


def build_ou_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = settled_ou_rows(rows)
    selectors = {
        "by_line_and_side": lambda r: f'{r.get("pick", "unknown")} {r.get("line", "unknown")}',
        "by_confidence": lambda r: confidence_bucket(r.get("model_probability")),
        "by_competition": lambda r: r.get("competition"),
        "by_scheduled_utc_day": lambda r: str(r.get("start_time") or "")[:10] or "unknown",
        "by_model_family": lambda r: r.get("validated_model_family") or r.get("model_version"),
        "by_kickoff_time": lambda r: time_bucket(r.get("start_time")),
    }
    segments = segment_report(settled, mode="ou", selectors=selectors, min_n=1)
    line_extremes = extremes(segments["by_line_and_side"], min_n=10)
    conf_extremes = extremes(segments["by_confidence"], min_n=10)
    competition_extremes = extremes(segments["by_competition"], min_n=10)
    confidence_60_70 = next((x for x in segments["by_confidence"] if x["group"] == "60-69.9%"), None)
    under_65 = next((x for x in segments["by_line_and_side"] if x["group"] == "under 6.5"), None)
    findings = []
    if confidence_60_70 and confidence_60_70["settled"] >= 20 and (confidence_60_70.get("flat_stake_roi") or 0) < 0:
        findings.append({
            "finding": "The 60-69.9% confidence bucket is materially weaker than its displayed confidence suggests.",
            "evidence": confidence_60_70,
            "possible_explanation": "The confidence scale appears overconfident in this band; this is an association, not proof of the underlying cause."
        })
    if under_65 and under_65["settled"] >= 20 and (under_65.get("flat_stake_roi") or 0) <= -0.10:
        findings.append({
            "finding": "Under 6.5 is a clear loss-heavy line/side cohort in the settled qualified-pick ledger.",
            "evidence": under_65,
            "possible_explanation": "The evidence supports investigating exact-line/side calibration and goal-distribution errors here. It does not by itself justify a blanket line ban."
        })
    return {
        "source_rows": len(rows),
        "eligible_settled_rows": len(settled),
        "metrics": outcome_stats(settled, mode="ou"),
        "chronological_split": split_chronological(settled, "ou"),
        "segments": segments,
        "exploratory_extremes": {
            "line_side": line_extremes,
            "confidence": conf_extremes,
            "competition": competition_extremes,
        },
        "findings": findings,
        "scope_warning": "These are selected Qualified Best/settled line picks, not all forecasts. Multiple line rows can share one fixture, so n is not necessarily an independent-event count.",
    }


def summarize_market_archive(archive: dict[str, Any]) -> dict[str, Any]:
    rows = [r for r in archive.get("observations", []) if isinstance(r, dict)]
    settled = settled_market_rows(rows)
    selectors = {
        "by_competition": lambda r: r.get("competition"),
        "by_favourite_outcome": lambda r: r.get("market_favourite"),
        "by_favourite_odds_band": lambda r: odds_bucket(r.get("favourite_odds")),
        "by_kickoff_time": lambda r: time_bucket(r.get("start_time")),
        "by_scheduled_utc_day": lambda r: str(r.get("start_time") or "")[:10] or "unknown",
    }
    groups = {}
    for key, items in group_rows(settled, lambda r: f'{r.get("product", "unknown")}|{r.get("market_type", "unknown")}').items():
        prod, market = key.split("|", 1)
        market_rows = items
        summary = outcome_stats(market_rows, mode="market")
        segs = segment_report(market_rows, mode="market", selectors=selectors, min_n=1)
        eligible = [g for g in segs["by_competition"] if g.get("settled", 0) >= 10]
        groups[key] = {
            **summary,
            "captured": sum(1 for r in rows if r.get("product") == prod and r.get("market_type") == market),
            "pending": sum(1 for r in rows if r.get("product") == prod and r.get("market_type") == market
                           and str(r.get("settlement_status") or "").lower() == "pending"),
            "chronological_split": split_chronological(market_rows, "market"),
            "segments": segs,
            "exploratory_extremes": extremes(eligible, min_n=10),
            "interpretation": "Bookmaker favourite baseline only; not an independent Match Signal model or proof of edge.",
        }
    promotion_review = {}
    for key, data in groups.items():
        n = int(data.get("settled") or 0)
        latest = data.get("chronological_split", {}).get("latest_30_percent", {})
        latest_roi = latest.get("flat_stake_roi")
        total_roi = data.get("flat_stake_roi")
        if n >= 100:
            if latest_roi is not None and latest_roi < 0:
                status = "REVIEW_NOW_LATEST_30_PERCENT_NEGATIVE"
            else:
                status = "PRELIMINARY_REVIEW_DUE"
        else:
            status = "COLLECT_AND_MONITOR"
        promotion_review[key] = {
            "status": status,
            "settled": n,
            "overall_flat_stake_roi": total_roi,
            "latest_30_percent_flat_stake_roi": latest_roi,
            "automatic_promotion": False,
            "decision": "Review the lane now when n>=100; do not wait for an arbitrary 300 if evidence is already consistently weak. Production promotion still requires an independent forecast model, positive post-margin value and a chronological holdout.",
        }
    coverage = archive.get("market_coverage") or {}
    return {
        "source_rows": len(rows),
        "unique_sample_ids": len({str(r.get("sample_id")) for r in rows if r.get("sample_id")}),
        "duplicate_sample_id_count": len(rows) - len({str(r.get("sample_id")) for r in rows if r.get("sample_id")}),
        "archive_updated_at": archive.get("updated_at"),
        "collector_last_run": archive.get("last_run"),
        "market_coverage": coverage,
        "summary_by_product_market": groups,
        "promotion_review": promotion_review,
        "scope_warning": "These are bookmaker favourite outcomes/returns. They do not test an independent winner/BTTS model. Outcomes from the same event may share match results; do not treat two markets on one event as independent.",
    }




SHADOW_MIN_HISTORY_MATCHES = 30
SHADOW_MIN_PARTICIPANT_MATCHES = 3
SHADOW_PRIOR_STRENGTH = 5.0
SHADOW_MIN_EXPECTED_RETURN = 0.02


def _shadow_participant(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _shadow_score(row: dict[str, Any]) -> tuple[int, int] | None:
    raw = row.get("final_score")
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    a, b = number(raw[0]), number(raw[1])
    if a is None or b is None or a < 0 or b < 0 or not a.is_integer() or not b.is_integer():
        return None
    return int(a), int(b)


def _shadow_event_key(row: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    start = parse_time(row.get("start_time"))
    p1, p2 = _shadow_participant(row.get("participant_1")), _shadow_participant(row.get("participant_2"))
    product = str(row.get("product") or "").strip()
    event_id = str(row.get("event_id") or "").strip()
    if not start or not product or not p1 or not p2 or p1 == p2:
        return None
    return product, event_id, start.isoformat(), p1, p2


def _shadow_settled_events(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Deduplicate scored games; conflicting scores are excluded rather than guessed."""
    chosen: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    conflicting: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if str(row.get("settlement_status") or "").upper() != "SETTLED":
            continue
        score = _shadow_score(row)
        start = parse_time(row.get("start_time"))
        settled_at = parse_time(row.get("settled_at"))
        key = _shadow_event_key(row)
        if score is None or start is None or settled_at is None or key is None:
            continue
        if key in chosen and chosen[key]["score"] != score:
            conflicting.add(key)
            continue
        previous = chosen.get(key)
        candidate = {
            "key": key,
            "product": key[0],
            "event_id": str(row.get("event_id") or "").strip(),
            "start_at": start,
            "settled_at": settled_at,
            "participant_1": key[3],
            "participant_2": key[4],
            "score": score,
        }
        if previous is None or settled_at < previous["settled_at"]:
            chosen[key] = candidate
    events = [v for k, v in chosen.items() if k not in conflicting]
    events.sort(key=lambda e: (e["start_at"], e["settled_at"], e["event_id"]))
    return events, len(conflicting)


def _shadow_poisson(lam: float, max_goals: int = 15) -> list[float]:
    lam = min(8.0, max(0.05, float(lam)))
    values = [math.exp(-lam)]
    for k in range(1, max_goals + 1):
        values.append(values[-1] * lam / k)
    total = sum(values)
    return [v / total for v in values] if total > 0 else [1.0] + [0.0] * max_goals


def _shadow_participant_counts(history: list[dict[str, Any]], p1: str, p2: str) -> tuple[int, int]:
    """Number of unique prior games for each participant in the already-deduplicated history."""
    n1 = n2 = 0
    for event in history:
        names = {event["participant_1"], event["participant_2"]}
        if p1 in names:
            n1 += 1
        if p2 in names:
            n2 += 1
    return n1, n2


def _shadow_score_probabilities(history: list[dict[str, Any]], p1: str, p2: str,
                                market_type: str) -> dict[str, float] | None:
    """Participant-form Poisson shadow model with a league-prior fallback; odds never enter its forecast."""
    if len(history) < SHADOW_MIN_HISTORY_MATCHES or not p1 or not p2 or p1 == p2:
        return None
    participants: dict[str, dict[str, float]] = {}
    total_p1 = total_p2 = 0.0
    for event in history:
        g1, g2 = event["score"]
        total_p1 += g1
        total_p2 += g2
        for name, scored, conceded in (
            (event["participant_1"], g1, g2),
            (event["participant_2"], g2, g1),
        ):
            stats = participants.setdefault(name, {"played": 0, "for": 0.0, "against": 0.0})
            stats["played"] += 1
            stats["for"] += scored
            stats["against"] += conceded
    # A participant with little/no history falls back toward the same-product scoring prior.
    # Their forecast is still evaluated, but the report tags its history coverage separately.
    empty_stats = {"played": 0, "for": 0.0, "against": 0.0}
    s1, s2 = participants.get(p1, empty_stats), participants.get(p2, empty_stats)

    global_side_mean = (total_p1 + total_p2) / (2 * len(history))
    home_mean, away_mean = total_p1 / len(history), total_p2 / len(history)
    if global_side_mean <= 0:
        return None

    k = SHADOW_PRIOR_STRENGTH
    def shrunk(stat: dict[str, float], field: str) -> float:
        return (float(stat[field]) + k * global_side_mean) / (float(stat["played"]) + k)

    attack1, concede1 = shrunk(s1, "for"), shrunk(s1, "against")
    attack2, concede2 = shrunk(s2, "for"), shrunk(s2, "against")
    lam_home = home_mean * (attack1 / global_side_mean) * (concede2 / global_side_mean)
    lam_away = away_mean * (attack2 / global_side_mean) * (concede1 / global_side_mean)
    ph, pa = _shadow_poisson(lam_home), _shadow_poisson(lam_away)

    home = draw = away = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            mass = pi * pj
            if i > j:
                home += mass
            elif i == j:
                draw += mass
            else:
                away += mass
    total = home + draw + away
    if total <= 0:
        return None
    if market_type == "match_winner":
        return {"home": home / total, "draw": draw / total, "away": away / total}
    if market_type == "btts":
        yes = (1.0 - ph[0]) * (1.0 - pa[0])
        return {"yes": yes, "no": 1.0 - yes}
    return None


def _shadow_vector(raw: Any, outcomes: list[str]) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    values: dict[str, float] = {}
    for outcome in outcomes:
        p = number(raw.get(outcome))
        if p is None or p < 0 or p > 1:
            return None
        values[outcome] = p
    total = sum(values.values())
    if total <= 0 or abs(total - 1.0) > 0.12:
        return None
    return {k: v / total for k, v in values.items()}


def _shadow_brier(probs: dict[str, float] | None, actual: str) -> float | None:
    if not probs or actual not in probs:
        return None
    return sum((p - (1.0 if outcome == actual else 0.0)) ** 2 for outcome, p in probs.items())


def _shadow_log_loss(probs: dict[str, float] | None, actual: str) -> float | None:
    if not probs or actual not in probs:
        return None
    return -math.log(max(1e-15, probs[actual]))


def _shadow_pick(row: dict[str, Any], probs: dict[str, float], actual: str) -> dict[str, Any]:
    odds_raw = row.get("odds")
    odds = odds_raw if isinstance(odds_raw, dict) else {}
    offers = []
    for outcome, probability in probs.items():
        price = number(odds.get(outcome))
        if price is not None and price > 1.0:
            offers.append((probability * price - 1.0, outcome, price))
    if not offers:
        return {"picked_side": None, "picked_odds": None, "picked_probability": None,
                "expected_return": None, "pick_correct": None, "net_units": None}
    expected_return, side, price = max(offers, key=lambda item: item[0])
    if expected_return < SHADOW_MIN_EXPECTED_RETURN:
        return {"picked_side": None, "picked_odds": None, "picked_probability": rounded(probs[side]),
                "expected_return": rounded(expected_return), "pick_correct": None, "net_units": None}
    correct = side == actual
    return {
        "picked_side": side,
        "picked_odds": price,
        "picked_probability": rounded(probs[side]),
        "expected_return": rounded(expected_return),
        "pick_correct": correct,
        "net_units": rounded(price - 1.0 if correct else -1.0),
    }


def _shadow_value_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    picks = [r for r in rows if r.get("picked_side") and isinstance(r.get("pick_correct"), bool)]
    returns = [float(r.get("net_units") or 0.0) for r in picks]
    wins = sum(bool(r["pick_correct"]) for r in picks)
    losses = len(picks) - wins
    hit_rate = wins / len(picks) if picks else None
    mean_expected = mean([float(r["expected_return"]) for r in picks if number(r.get("expected_return")) is not None])
    return {
        "selected_picks": len(picks),
        "wins": wins,
        "losses": losses,
        "hit_rate": rounded(hit_rate),
        "flat_stake_net_units": rounded(sum(returns)),
        "flat_stake_roi": rounded(mean(returns)),
        "flat_stake_roi_95_approx": mean_interval(returns),
        "mean_selected_odds": rounded(mean([float(r["picked_odds"]) for r in picks if number(r.get("picked_odds")) is not None])),
        "mean_selected_probability": rounded(mean([float(r["picked_probability"]) for r in picks if number(r.get("picked_probability")) is not None])),
        "selected_probability_minus_hit_rate": rounded(mean([float(r["picked_probability"]) for r in picks if number(r.get("picked_probability")) is not None]) - hit_rate) if picks and hit_rate is not None and any(number(r.get("picked_probability")) is not None for r in picks) else None,
        "mean_estimated_expected_return": rounded(mean_expected),
        "estimated_return_minus_realised_roi": rounded(mean_expected - mean(returns)) if mean_expected is not None and returns else None,
    }


def _shadow_probability_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model_brier = [float(r["model_brier"]) for r in rows if number(r.get("model_brier")) is not None]
    market_brier = [float(r["market_brier"]) for r in rows if number(r.get("market_brier")) is not None]
    model_log = [float(r["model_log_loss"]) for r in rows if number(r.get("model_log_loss")) is not None]
    market_log = [float(r["market_log_loss"]) for r in rows if number(r.get("market_log_loss")) is not None]
    mb, qb = mean(model_brier), mean(market_brier)
    ml, ql = mean(model_log), mean(market_log)
    return {
        "forecasted_observations": len(rows),
        "unique_events": len({str(r.get("event_id") or r.get("sample_id") or "") for r in rows}),
        "mean_training_matches": rounded(mean([float(r["training_matches"]) for r in rows if number(r.get("training_matches")) is not None])),
        "model_mean_brier": rounded(mb),
        "market_mean_brier_same_forecasts": rounded(qb),
        "model_minus_market_brier": rounded(mb - qb) if mb is not None and qb is not None else None,
        "model_mean_log_loss": rounded(ml),
        "market_mean_log_loss_same_forecasts": rounded(ql),
        "model_minus_market_log_loss": rounded(ml - ql) if ml is not None and ql is not None else None,
        "value_picks": _shadow_value_stats(rows),
    }


def _shadow_review_status(forecast_count: int, selected_count: int,
                          overall_brier_delta: float | None, overall_logloss_delta: float | None,
                          latest_brier_delta: float | None, latest_logloss_delta: float | None,
                          latest_roi: float | None) -> str:
    """Rule-based decision support; never enables production or auto-promotes a lane."""
    if forecast_count < 100:
        return "COLLECT_AND_MONITOR"
    consistently_worse = all(
        value is not None and value > 0
        for value in (overall_brier_delta, overall_logloss_delta, latest_brier_delta, latest_logloss_delta)
    )
    if consistently_worse:
        return "REJECT_CURRENT_SHADOW_MODEL_VS_MARKET"
    if selected_count < 30:
        return "REVIEW_NOW_LOW_ACTIONABLE_PICK_COUNT"
    if latest_roi is not None and latest_roi < 0:
        return "REVIEW_NOW_LATEST_30_PERCENT_NEGATIVE"
    consistently_better = all(
        value is not None and value < 0
        for value in (overall_brier_delta, overall_logloss_delta, latest_brier_delta, latest_logloss_delta)
    )
    if consistently_better and latest_roi is not None and latest_roi > 0:
        return "ELIGIBLE_FOR_PAPER_PROMOTION_REVIEW"
    return "PRELIMINARY_REVIEW_INCONCLUSIVE"


def _shadow_diagnostic_findings(stats: dict[str, Any], latest: dict[str, Any],
                                participant_tiers: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    brier_delta = stats.get("model_minus_market_brier")
    logloss_delta = stats.get("model_minus_market_log_loss")
    latest_brier_delta = latest.get("model_minus_market_brier")
    latest_logloss_delta = latest.get("model_minus_market_log_loss")
    value = stats.get("value_picks") or {}
    roi = value.get("flat_stake_roi")
    mean_ev = value.get("mean_estimated_expected_return")
    if brier_delta is not None and logloss_delta is not None and brier_delta > 0 and logloss_delta > 0:
        findings.append("The shadow probability forecast scores worse than the same-sample no-vig market baseline on both Brier score and log loss.")
    if latest_brier_delta is not None and latest_logloss_delta is not None and latest_brier_delta > 0 and latest_logloss_delta > 0:
        findings.append("The latest chronological 30% repeats the probability-score weakness; this is not just an early-history-only result.")
    if mean_ev is not None and roi is not None and mean_ev > 0 and roi < 0:
        gap = value.get("estimated_return_minus_realised_roi")
        findings.append(f"The selected paper picks estimated {mean_ev:.1%} average return but realised {roi:.1%} ROI" + (f" (estimate-to-result gap {gap:.1%});" if gap is not None else ";") + " treat the model's edge estimate as overconfident.")
    total = int(stats.get("forecasted_observations") or 0)
    established = next((int(t.get("forecasted_observations") or 0) for t in participant_tiers if t.get("tier") == "both_3plus_prior_games"), 0)
    if total and established / total < 0.10:
        findings.append(f"Only {established}/{total} forecasts ({established / total:.1%}) had 3+ prior matches for both participants, so most results rely heavily on a product-level scoring prior rather than established participant form.")
    if not findings:
        findings.append("No single diagnosis clears the report's descriptive screen; keep the lane in paper research and inspect the chronological/segment breakdown before any promotion review.")
    return findings


def build_independent_market_shadow(archive: dict[str, Any]) -> dict[str, Any]:
    """Chronological independent score-form research; never feeds production selection."""
    rows = [r for r in archive.get("observations", []) if isinstance(r, dict)]
    events, conflicting_events = _shadow_settled_events(rows)
    forecasts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = {"unsettled_or_invalid_target": 0, "not_pre_kickoff": 0,
               "insufficient_global_history": 0, "invalid_participant_identity": 0,
               "invalid_outcome_or_market": 0}
    participant_history_tier_counts: dict[str, int] = defaultdict(int)
    for target in rows:
        product = str(target.get("product") or "")
        kind = str(target.get("market_type") or "")
        if product not in {"efootball_gt", "efootball_adriatic"} or kind not in {"match_winner", "btts"}:
            continue
        if str(target.get("settlement_status") or "").upper() != "SETTLED":
            skipped["unsettled_or_invalid_target"] += 1
            continue
        start = parse_time(target.get("start_time"))
        captured = parse_time(target.get("captured_at"))
        score = _shadow_score(target)
        if start is None or captured is None or score is None:
            skipped["unsettled_or_invalid_target"] += 1
            continue
        if captured >= start:
            skipped["not_pre_kickoff"] += 1
            continue
        p1, p2 = _shadow_participant(target.get("participant_1")), _shadow_participant(target.get("participant_2"))
        if not p1 or not p2 or p1 == p2:
            skipped["invalid_participant_identity"] += 1
            continue
        actual = ("home" if score[0] > score[1] else "away" if score[0] < score[1] else "draw") if kind == "match_winner" else ("yes" if score[0] > 0 and score[1] > 0 else "no")
        recorded = str(target.get("actual_outcome") or "").strip().lower()
        if kind == "match_winner" and actual not in {"home", "away", "draw"}:
            skipped["invalid_outcome_or_market"] += 1
            continue
        if kind == "btts" and actual not in {"yes", "no"}:
            skipped["invalid_outcome_or_market"] += 1
            continue
        if recorded and recorded != actual:
            skipped["invalid_outcome_or_market"] += 1
            continue
        outcomes = ["home", "draw", "away"] if kind == "match_winner" else ["yes", "no"]
        event_id = str(target.get("event_id") or "").strip()
        history = [
            event for event in events
            if event["product"] == product
            and event["start_at"] < start
            and event["settled_at"] <= captured
            and not (event_id and event["event_id"] == event_id)
        ]
        if len(history) < SHADOW_MIN_HISTORY_MATCHES:
            skipped["insufficient_global_history"] += 1
            continue
        probs = _shadow_score_probabilities(history, p1, p2, kind)
        if probs is None:
            skipped["insufficient_global_history"] += 1
            continue
        p1_prior_games, p2_prior_games = _shadow_participant_counts(history, p1, p2)
        if p1_prior_games >= SHADOW_MIN_PARTICIPANT_MATCHES and p2_prior_games >= SHADOW_MIN_PARTICIPANT_MATCHES:
            participant_tier = "both_3plus_prior_games"
        elif p1_prior_games > 0 and p2_prior_games > 0:
            participant_tier = "both_seen_under_3_or_one_under_3"
        elif p1_prior_games > 0 or p2_prior_games > 0:
            participant_tier = "one_participant_unseen_or_low_history"
        else:
            participant_tier = "neither_participant_seen"
        participant_history_tier_counts[participant_tier] += 1
        probs = _shadow_vector(probs, outcomes)
        market_probs = _shadow_vector(target.get("market_probabilities_no_vig"), outcomes)
        row = {
            "sample_id": str(target.get("sample_id") or ""),
            "event_id": event_id,
            "product": product,
            "market_type": kind,
            "competition": str(target.get("competition") or "unknown"),
            "start_time": start.isoformat(),
            "captured_at": captured.isoformat(),
            "actual_outcome": actual,
            "training_matches": len(history),
            "participant_1_prior_games": p1_prior_games,
            "participant_2_prior_games": p2_prior_games,
            "participant_history_tier": participant_tier,
            "model_probabilities": probs,
            "market_probabilities_no_vig": market_probs,
            "model_brier": _shadow_brier(probs, actual),
            "market_brier": _shadow_brier(market_probs, actual),
            "model_log_loss": _shadow_log_loss(probs, actual),
            "market_log_loss": _shadow_log_loss(market_probs, actual),
        }
        row.update(_shadow_pick(target, probs or {}, actual))
        forecasts[f"{product}|{kind}"].append(row)

    lane_report: dict[str, Any] = {}
    for key, lane_rows in sorted(forecasts.items()):
        ordered = sorted(lane_rows, key=lambda r: (r["start_time"], r["sample_id"]))
        cut = int(len(ordered) * 0.70)
        first = ordered[:cut]
        latest = ordered[cut:]
        stats = _shadow_probability_stats(ordered)
        latest_stats = _shadow_probability_stats(latest)
        selected_n = stats["value_picks"]["selected_picks"]
        latest_roi = latest_stats["value_picks"]["flat_stake_roi"]
        readiness = _shadow_review_status(
            len(ordered), selected_n,
            stats.get("model_minus_market_brier"), stats.get("model_minus_market_log_loss"),
            latest_stats.get("model_minus_market_brier"), latest_stats.get("model_minus_market_log_loss"),
            latest_roi,
        )

        participant_tier_groups = []
        for tier, segment in group_rows(ordered, lambda r: r.get("participant_history_tier")).items():
            tier_ordered = sorted(segment, key=lambda r: (r["start_time"], r["sample_id"]))
            tier_cut = int(len(tier_ordered) * 0.70)
            participant_tier_groups.append({
                "tier": tier,
                **_shadow_probability_stats(tier_ordered),
                "chronological_split": {
                    "method": "Sort within this participant-history tier by scheduled kickoff; earliest 70% versus latest 30%.",
                    "first_70_percent": _shadow_probability_stats(tier_ordered[:tier_cut]),
                    "latest_30_percent": _shadow_probability_stats(tier_ordered[tier_cut:]),
                },
            })
        selected_rows = [r for r in ordered if r.get("picked_side")]
        side_groups = [
            {"side": name, **_shadow_value_stats(segment)}
            for name, segment in group_rows(selected_rows, lambda r: r.get("picked_side")).items()
        ]
        odds_groups = [
            {"odds_band": name, **_shadow_value_stats(segment)}
            for name, segment in group_rows(selected_rows, lambda r: odds_bucket(r.get("picked_odds"))).items()
        ]
        competition_groups = []
        for name, segment in group_rows(selected_rows, lambda r: r.get("competition")).items():
            summary = _shadow_value_stats(segment)
            competition_groups.append({"group": name, **summary})
        competition_groups.sort(key=lambda s: (s.get("flat_stake_roi") if s.get("flat_stake_roi") is not None else -999, s.get("selected_picks", 0)))
        time_groups = []
        for name, segment in group_rows(selected_rows, lambda r: time_bucket(r.get("start_time"))).items():
            time_groups.append({"group": name, **_shadow_value_stats(segment)})
        time_groups.sort(key=lambda s: s.get("group", ""))
        lane_report[key] = {
            **stats,
            "method": "Participant-form Poisson goals model using only unique earlier same-product games settled by each target's captured_at; requires 30 prior matches globally, shrinks participants with limited history toward that product's scoring prior, and reports performance by participant-history tier; probabilities do not use bookmaker odds.",
            "chronological_split": {
                "method": "Sort forecasted observations by scheduled kickoff; earliest 70% versus latest 30%.",
                "first_70_percent": _shadow_probability_stats(first),
                "latest_30_percent": latest_stats,
            },
            "by_participant_history_tier": participant_tier_groups,
            "by_picked_side_value_picks": side_groups,
            "by_selected_odds_band_value_picks": odds_groups,
            "by_competition_value_picks": competition_groups,
            "by_kickoff_time_value_picks": time_groups,
            "diagnostic_findings": _shadow_diagnostic_findings(stats, latest_stats, participant_tier_groups),
            "promotion_review": {
                "status": readiness,
                "automatic_promotion": False,
                "production_qualification_enabled": False,
                "decision": "Review starts at 100 forecasts, not an arbitrary 300. Reject this specific shadow-model configuration when its probabilities score worse than the no-vig baseline overall and in the latest chronological 30%. A better subsegment is only a research candidate until its own chronological holdout, calibrated probability and positive post-margin value are demonstrated. No output changes the regular Qualified Best gate.",
            },
        }
    return {
        "mode": "PAPER_SHADOW_ONLY",
        "automatic_promotion": False,
        "production_qualification_enabled": False,
        "minimum_prior_matches": SHADOW_MIN_HISTORY_MATCHES,
        "minimum_matches_per_participant": SHADOW_MIN_PARTICIPANT_MATCHES,
        "minimum_estimated_expected_return_for_shadow_pick": SHADOW_MIN_EXPECTED_RETURN,
        "scored_unique_history_events": len(events),
        "conflicting_history_events_excluded": conflicting_events,
        "skipped_target_counts": skipped,
        "forecasts_by_participant_history_tier": dict(sorted(participant_history_tier_counts.items())),
        "lanes": lane_report,
        "limitations": "Exploratory model, not an approved predictor. Results can be dependent because participants recur; the walk-forward split and probability-score comparison are informative screens, not proof of durable profit. No forecast from this report is sent to Qualified Best or Odds Builder.",
    }



def _ticket_scope(ticket: dict[str, Any]) -> str:
    products = ticket.get("products")
    if not isinstance(products, list):
        products = []
    if not products:
        products = [str(leg.get("product") or "") for leg in ticket.get("legs", []) if isinstance(leg, dict)]
    values = sorted({str(p) for p in products if p})
    if values == ["efootball_gt"]:
        return "efootball_gt_only"
    if values and all(p in {"efootball_gt", "efootball_adriatic"} for p in values):
        return "efootball_only_multiple_products"
    if "efootball_gt" in values or "efootball_adriatic" in values:
        return "mixed_with_efootball"
    return "other_or_unknown"


def unique_tickets(tracker: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in ("archived_tickets", "tickets"):
        arr = tracker.get(key, [])
        if isinstance(arr, list):
            rows.extend(x for x in arr if isinstance(x, dict))
    chosen: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        key = str(row.get("ticket_id") or row.get("snapshot_fingerprint") or f"anonymous-{i}")
        old = chosen.get(key)
        if old is None:
            chosen[key] = row
            continue
        old_settled = str(old.get("status") or "").lower() in {"won", "win", "lost", "loss", "settled_won", "settled_lost"}
        new_settled = str(row.get("status") or "").lower() in {"won", "win", "lost", "loss", "settled_won", "settled_lost"}
        if (new_settled and not old_settled) or (new_settled == old_settled and str(row.get("last_seen_at") or "") > str(old.get("last_seen_at") or "")):
            chosen[key] = row
    return list(chosen.values())


def build_ticket_report(tracker: dict[str, Any]) -> dict[str, Any]:
    rows = unique_tickets(tracker)
    efootball_rows = [r for r in rows if _ticket_scope(r) != "other_or_unknown"]
    selectors = {
        "by_construction_lane": lambda r: r.get("primary_lane"),
        "by_leg_count": lambda r: r.get("leg_count") or len(r.get("legs", []) or []) or "unknown",
        "by_ticket_status": lambda r: str(r.get("status") or "unknown").upper(),
    }
    segments = segment_report(efootball_rows, mode="ticket", selectors=selectors, min_n=1)
    scope_rows = group_rows(efootball_rows, _ticket_scope)
    scope = {key: outcome_stats(value, mode="ticket") | {
        "tracked": len(value),
        "pending_or_unsettled": sum(1 for r in value if str(r.get("status") or "").lower() not in {"won", "win", "lost", "loss", "settled_won", "settled_lost"}),
    } for key, value in scope_rows.items()}
    return {
        "source_updated_at": tracker.get("updated_at"),
        "source_summary": tracker.get("summary"),
        "unique_ticket_count": len(rows),
        "efootball_related_ticket_count": len(efootball_rows),
        "metrics_by_efootball_scope": scope,
        "segments": segments,
        "interpretation": "Ticket outcomes are dependent when tickets reuse the same legs. Compare them separately from single-pick accuracy; do not interpret the raw ticket hit rate as per-leg performance.",
    }


def build_report(ou_rows: list[dict[str, Any]], market_archive: dict[str, Any],
                 tracker: dict[str, Any], lab_eval: dict[str, Any],
                 generated_at: datetime | None = None) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    market_last = parse_time(market_archive.get("updated_at"))
    last_run = market_archive.get("last_run") or {}
    last_capture = parse_time(last_run.get("captured_at"))
    age_minutes = ((generated_at - market_last).total_seconds() / 60) if market_last else None
    collector_age_minutes = ((generated_at - last_capture).total_seconds() / 60) if last_capture else None

    lab_gt = (lab_eval.get("by_product") or {}).get("efootball_gt") or {}
    model_eval = {
        "generated_at": lab_eval.get("generated_at"),
        "method": lab_eval.get("method"),
        "holdout_definition": lab_eval.get("holdout"),
        "efootball_gt_walk_forward_metrics_by_variant": lab_gt,
        "overall_chronological_holdout_metrics": lab_eval.get("holdout_metrics"),
        "overall_participant_holdout_metrics": lab_eval.get("participant_holdout_metrics"),
        "note": "Full-line O/U replay evaluation is a different population from Qualified Best picks and bookmaker-favourite 1X2/BTTS research.",
    }

    coverage = market_archive.get("market_coverage") or {}
    product_coverage = coverage.get("products") or {}
    gt_coverage = product_coverage.get("efootball_gt") or {}
    adriatic_coverage = product_coverage.get("efootball_adriatic") or {}
    research_summary = summarize_market_archive(market_archive)
    independent_shadow = build_independent_market_shadow(market_archive)
    gt_winner = research_summary["summary_by_product_market"].get("efootball_gt|match_winner") or {}
    gt_btts = research_summary["summary_by_product_market"].get("efootball_gt|btts") or {}
    adriatic_winner = research_summary["summary_by_product_market"].get("efootball_adriatic|match_winner") or {}

    market_status = {
        "efootball_gt_match_winner": {
            "observations_settled": gt_winner.get("settled", 0),
            "status": "WEAK_BOOKMAKER_FAVOURITE_BASELINE" if (gt_winner.get("flat_stake_roi") is not None and gt_winner["flat_stake_roi"] < 0) else "MONITOR",
            "reason": "The favourite baseline has negative returns; this argues against promoting the favourite-only rule, not against researching an independent model.",
        },
        "efootball_gt_gg_ng": {
            "observations_settled": gt_btts.get("settled", 0),
            "status": "REVIEW_NOW_NOT_PROMOTED" if gt_btts.get("settled", 0) >= 100 else "COLLECT_AND_REVIEW",
            "reason": "The sample is large enough for a preliminary review, but the latest chronological segment must be considered and the archive contains market-favourite results, not independent Match Signal BTTS forecasts.",
        },
        "efootball_adriatic_match_winner": {
            "observations_settled": adriatic_winner.get("settled", 0),
            "status": "PRELIMINARY_REVIEW" if adriatic_winner.get("settled", 0) >= 100 else "COLLECT_AND_MONITOR",
            "reason": "Close-to-break-even favourite returns with wide uncertainty are not proof of value; recheck the latest chronological split.",
        },
        "efootball_adriatic_gg_ng": {
            "observations_settled": 0,
            "status": "MARKET_COVERAGE_NOT_CONFIRMED" if not adriatic_coverage.get("market_id_29_rows") else "COVERAGE_PRESENT_REVIEW_DATA",
            "reason": "Do not infer an Adriatic GG/NG record from eFootball GT; the latest stored coverage inventory showed no market ID 29 rows for Adriatic.",
        },
    }

    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "mode": "PAPER_RESEARCH_ONLY",
        "live_trading_approved": False,
        "production_qualification_enabled": False,
        "odds_builder_eligible": False,
        "source_freshness": {
            "market_archive_updated_at": market_archive.get("updated_at"),
            "market_archive_age_minutes": rounded(age_minutes, 1),
            "collector_last_capture_at": last_run.get("captured_at"),
            "collector_age_minutes": rounded(collector_age_minutes, 1),
            "collector_stale_over_30_minutes": bool(collector_age_minutes is None or collector_age_minutes > 30),
            "market_archive_last_run_errors": last_run.get("settlement_errors", []),
            "market_archive_last_run_warnings": last_run.get("settlement_warnings", []),
            "market_archive_last_run_snapshot_fresh": last_run.get("feed_snapshot_fresh"),
            "note": "Stale research collection must raise a monitoring warning; it must never stop the normal Qualified Best forecast/deployment workflow.",
        },
        "qualified_best_ou_single_picks": build_ou_report(ou_rows),
        "winner_and_gg_ng_market_baselines": research_summary,
        "independent_winner_ggng_shadow": independent_shadow,
        "ticket_performance": build_ticket_report(tracker),
        "walk_forward_ou_model_evaluation": model_eval,
        "market_review_status": market_status,
        "promotion_policy": {
            "preliminary_market_review_threshold": 100,
            "preferred_range": "200-300+ settled observations plus a chronological holdout, not a mandatory waiting period",
            "automatic_promotion": False,
            "requirements": [
                "independent Match Signal probabilities for the exact market and side",
                "positive post-margin expected value on frozen pre-event quotes",
                "adequate calibration versus the no-vig baseline",
                "positive chronological holdout evidence and uncertainty disclosed",
                "stable exact-event settlement; ambiguous or stale rows excluded",
                "paper-only shadow comparison before any change to production qualification",
            ],
        },
        "method_warning": "All slices are descriptive and exploratory. Many groups are tested; group results can share events, participants, market quotes, and accumulator legs. Strong/weak cohorts are investigation leads, not causal explanations or automatic promotion/blacklist rules.",
    }


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    ou_rows = load_json(DATA / "efootball_desk_settled_observations.json", [])
    market_archive = load_json(DATA / "efootball_market_research.json", {"observations": []})
    tracker = load_json(DATA / "odds_ticket_tracker.json", {})
    lab_eval = load_json(DATA / "virtual_lab_model_eval.json", {})
    if not isinstance(ou_rows, list):
        raise SystemExit("eFootball settled-observation ledger must be a JSON list")
    if not isinstance(market_archive, dict) or not isinstance(tracker, dict) or not isinstance(lab_eval, dict):
        raise SystemExit("An eFootball report input has an invalid top-level JSON shape")
    report = build_report(ou_rows, market_archive, tracker, lab_eval)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "report": str(OUT_PATH.relative_to(ROOT)),
        "paper_only": True,
        "ou_settled": report["qualified_best_ou_single_picks"]["metrics"]["settled"],
        "market_lanes": {k: v.get("settled", 0) for k, v in report["winner_and_gg_ng_market_baselines"]["summary_by_product_market"].items()},
        "independent_shadow_lanes": {k: {"forecasts": v.get("forecasted_observations", 0), "promotion_review": v.get("promotion_review", {}).get("status")} for k, v in report["independent_winner_ggng_shadow"]["lanes"].items()},
        "efootball_related_tickets": report["ticket_performance"]["efootball_related_ticket_count"],
        "collector_stale_over_30_minutes": report["source_freshness"]["collector_stale_over_30_minutes"],
        "automatic_promotion": False,
    }, indent=2))


if __name__ == "__main__":
    main()
