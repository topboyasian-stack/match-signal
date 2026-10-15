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
        "efootball_related_tickets": report["ticket_performance"]["efootball_related_ticket_count"],
        "collector_stale_over_30_minutes": report["source_freshness"]["collector_stale_over_30_minutes"],
        "automatic_promotion": False,
    }, indent=2))


if __name__ == "__main__":
    main()
