"""Live exact-line tennis market reassessment for the Match Signal Odds Builder.

This adapter recalculates every currently quoted SportyBet full-match Total
Games half-line from the prior-only V5.1 matchup-conditioned distribution.
It contributes candidates only; the existing Odds Builder gates remain the
sole authority for value and ticket qualification.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DATA = Path(__file__).resolve().parents[1] / "data"
MIN_TENNIS_HISTORY = 30
TENNIS_TOTAL_MARKET_ID = "189"

_DIAGNOSTICS: dict[str, Any] = {}
_INSTALLED = False


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso_now(value: Any) -> str:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat()


def _exact_full_match_total_quotes(row: dict[str, Any]) -> dict[float, dict[str, Any]]:
    """Return only two-sided SportyBet market-189 full-match total quotes."""
    grouped: dict[float, dict[str, Any]] = {}
    for item in row.get("sportybet_total_games_odds") or []:
        if not isinstance(item, dict):
            continue
        market_id = str(item.get("market_id") or "")
        if market_id != TENNIS_TOTAL_MARKET_ID:
            continue
        specifier = str(item.get("specifier") or "")
        if re.search(r"(?:^|[|,;\s])setnr\s*=", specifier, re.I):
            continue
        line = _num(item.get("line"))
        if line is None or line <= 0:
            continue
        # Whole-game lines can push. This ticket lane settles binary Over/Under
        # outcomes, so only half-lines are considered for automatic selection.
        if abs(line - round(line)) < 1e-9:
            continue
        over = _num(item.get("over"))
        under = _num(item.get("under"))
        if over is None or under is None:
            side = str(item.get("side") or "").lower()
            odds = _num(item.get("odds"))
            if side in {"over", "under"} and odds is not None:
                existing = grouped.setdefault(line, {"line": line, "market_id": market_id})
                existing[side] = odds
                existing["specifier"] = specifier
                continue
        if over is None or under is None or over <= 1 or under <= 1:
            continue
        grouped[line] = {
            "line": line,
            "over": over,
            "under": under,
            "market_id": market_id,
            "specifier": specifier,
        }

    return {
        line: quote
        for line, quote in grouped.items()
        if _num(quote.get("over")) is not None
        and _num(quote.get("under")) is not None
        and float(quote["over"]) > 1
        and float(quote["under"]) > 1
    }


def _market_rows(core: Any, row: dict[str, Any], original: Callable):
    """Normalize the exact selected line into side/odds rows for de-vigging."""
    if row.get("sport") != "tennis" or row.get("builder_market") != "total_games":
        return original(row)

    total = (row.get("analytics") or {}).get("total_games") or {}
    line = _num(total.get("line"))
    if line is None:
        line = _num(row.get("line"))
    if line is None:
        return []

    matched = []
    for quote in _exact_full_match_total_quotes(row).values():
        quote_line = _num(quote.get("line"))
        if quote_line is None or abs(quote_line - line) >= 1e-9:
            continue
        matched = [
            {"side": "over", "odds": quote.get("over")},
            {"side": "under", "odds": quote.get("under")},
        ]
        break
    return matched


def _build_candidates(
    core: Any,
    now: datetime,
    *,
    prediction_rows: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    baseline_fn: Callable | None = None,
) -> list[dict[str, Any]]:
    """Recalculate exact current lines and retain the normal winner lane."""
    global _DIAGNOSTICS

    raw = prediction_rows if isinstance(prediction_rows, list) else core.load(core.PREDICTIONS, [])
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    settled_history = history if isinstance(history, list) else core.load(DATA / "tennis_prediction_archive.json", [])
    if not isinstance(settled_history, list):
        settled_history = []

    baseline = baseline_fn(now) if baseline_fn else []
    if not isinstance(baseline, list):
        baseline = []
    # Keep existing winner candidates. Legacy single-line totals are retained
    # only for fixtures where the V5.1 history is not yet sufficient.
    out = [
        dict(candidate)
        for candidate in baseline
        if isinstance(candidate, dict)
        and not (
            candidate.get("sport") == "tennis"
            and candidate.get("builder_market") == "total_games"
        )
    ]

    diag = {
        "status": "RECALCULATED",
        "mode": "PAPER_ONLY",
        "history_rows": len(settled_history),
        "minimum_prior_matches": MIN_TENNIS_HISTORY,
        "market_id": TENNIS_TOTAL_MARKET_ID,
        "market_scope": "SportyBet NG full-match Total Games only; exact quoted half-lines; both sides required",
        "model": "V5.1 matchup-conditioned empirical total-games distribution; strictly prior settled matches",
        "events_seen": 0,
        "events_with_exact_full_match_ladder": 0,
        "events_recalculated": 0,
        "exact_lines_recalculated": 0,
        "candidate_options_emitted": 0,
        "events_held_for_history": 0,
        "events_without_exact_market": 0,
        "events_without_model_distribution": 0,
        "baseline_total_fallbacks": 0,
        "rejection_policy": "No quoted line is substituted; whole-game push lines, incomplete two-sided quotes, stale prices, and probabilities below the existing Builder floor are excluded.",
        "automatic_selection_policy": "All recalculated line/side options enter the existing Builder; exact price, de-vig edge, expected value, freshness, uncertainty, correlation and ticket gates decide which option survives.",
        "paper_only": True,
        "real_money_execution": False,
    }

    from tennis_total_model import MIN_HISTORY, predict_total_games

    for target in rows:
        if target.get("sport") != "tennis" or not core.within_builder_horizon(target, now):
            continue
        diag["events_seen"] += 1
        quotes = _exact_full_match_total_quotes(target)
        if not quotes:
            diag["events_without_exact_market"] += 1
            continue
        diag["events_with_exact_full_match_ladder"] += 1

        original_total = (target.get("analytics") or {}).get("total_games") or {}
        original_line = _num(original_total.get("line"))
        original_pick = str(original_total.get("pick") or "").lower()
        original_probability = _num(original_total.get(original_pick)) if original_pick in {"over", "under"} else None

        try:
            distribution = predict_total_games(target, settled_history)
        except Exception:
            distribution = None

        neighbors = int((distribution or {}).get("neighbors") or 0)
        distribution_values = (distribution or {}).get("distribution") or {}
        if (
            not isinstance(distribution, dict)
            or neighbors < max(MIN_TENNIS_HISTORY, MIN_HISTORY)
            or not isinstance(distribution_values, dict)
            or not distribution_values
        ):
            diag["events_without_model_distribution"] += 1
            diag["events_held_for_history"] += 1
            # Retain the prior exact-line candidate only when it still exists
            # at the current bookmaker and was previously marked as an exact
            # SportyBet recalculation. Never carry a disappeared line forward.
            prior_status = str(original_total.get("market_alignment_status") or "")
            if (
                original_line in quotes
                and original_pick in {"over", "under"}
                and original_probability is not None
                and original_probability >= float(core.MIN_PROB)
                and prior_status == "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED"
            ):
                fallback = dict(target)
                fallback["line"] = original_line
                fallback["builder_market"] = "total_games"
                fallback["builder_pick"] = original_pick
                fallback["builder_probability"] = original_probability
                fallback["model"] = original_total.get("model") or target.get("model")
                fallback["market_reassessment"] = {
                    "status": "PRIOR_EXACT_LINE_RETAINED_HISTORY_REFRESH_UNAVAILABLE",
                    "market_id": TENNIS_TOTAL_MARKET_ID,
                    "line": original_line,
                    "side": original_pick,
                    "reason": "V5.1 could not recalculate from the available prior history; retained only the previously recalculated line while it remains currently quoted.",
                    "paper_only": True,
                }
                out.append(fallback)
                diag["baseline_total_fallbacks"] += 1
                diag["candidate_options_emitted"] += 1
            continue

        diag["events_recalculated"] += 1
        diag["exact_lines_recalculated"] += len(quotes)
        recalculated_at = _iso_now(now)
        analytics = target.get("analytics") if isinstance(target.get("analytics"), dict) else {}
        model_total = {
            "line": original_line,
            "pick": original_pick or None,
            "over": original_total.get("over"),
            "under": original_total.get("under"),
            "expected_total": distribution.get("expected_total"),
            "model": distribution.get("model") or "V5.1 matchup-conditioned empirical total-games distribution",
            "model_line_before_market_reassessment": original_line,
            "market_alignment_status": "LIVE_EXACT_SPORTYBET_LINE_RECALCULATED",
            "market_alignment_updated_at": recalculated_at,
            "neighbors": neighbors,
            "effective_sample": distribution.get("effective_sample"),
        }

        for line, quote in sorted(quotes.items()):
            over_probability = sum(
                float(probability)
                for score, probability in distribution_values.items()
                if _num(score) is not None and _num(probability) is not None and float(score) > line
            )
            over_probability = max(0.0, min(1.0, over_probability))
            under_probability = 1.0 - over_probability
            model_total["market_available_lines"] = sorted(quotes)
            for side, probability in (("over", over_probability), ("under", under_probability)):
                if probability < float(core.MIN_PROB) or probability >= 1.0:
                    continue
                candidate = dict(target)
                candidate_analytics = dict(analytics)
                candidate_total = dict(model_total)
                candidate_total.update({
                    "line": line,
                    "pick": side,
                    "over": round(over_probability, 6),
                    "under": round(under_probability, 6),
                    "base_model_over": round(over_probability, 6),
                    "base_model_under": round(under_probability, 6),
                    "recommended_line": line,
                    "recommended_pick": side,
                    "recommended_probability": round(probability, 6),
                })
                candidate_analytics["total_games"] = candidate_total
                candidate["analytics"] = candidate_analytics
                candidate["line"] = line
                candidate["builder_market"] = "total_games"
                candidate["builder_pick"] = side
                candidate["builder_probability"] = round(probability, 6)
                candidate["probability"] = round(probability, 6)
                candidate["model"] = candidate_total["model"]
                candidate["market_assessment"] = "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED"
                candidate["market_reassessment"] = {
                    "status": "RECALCULATED_EXACT_CURRENT_MARKET_LINE",
                    "market_id": TENNIS_TOTAL_MARKET_ID,
                    "line": line,
                    "side": side,
                    "model_probability": round(probability, 6),
                    "opposite_probability": round(1.0 - probability, 6),
                    "history_neighbors": neighbors,
                    "effective_sample": distribution.get("effective_sample"),
                    "model_version": "V5.1 matchup-conditioned empirical total-games distribution",
                    "recalculated_at": recalculated_at,
                    "quote_source": "SportyBet NG",
                    "quote_line_exact": True,
                    "quote_sides_complete": True,
                    "original_published_line": original_line,
                    "original_published_pick": original_pick or None,
                    "original_published_probability": original_probability,
                    "candidate_type": "current_line_recalculation" if original_line is not None and abs(original_line - line) < 1e-9 else "alternative_market_line",
                    "candidate_policy": "The existing Builder compares every exact-line option against its current price; this candidate does not bypass any qualification gate.",
                    "paper_only": True,
                }
                quote_stamp = target.get("market_odds_timestamp") or target.get("odds_timestamp")
                if quote_stamp:
                    candidate["market_odds_timestamp"] = quote_stamp
                    candidate["odds_timestamp"] = quote_stamp
                out.append(candidate)
                diag["candidate_options_emitted"] += 1

    _DIAGNOSTICS = diag
    return out


def install(core: Any) -> None:
    """Patch the stable, small Odds Builder entry point without rewriting its core."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_candidates = core.tennis_candidates
    original_market_rows = core.market_rows
    original_make_leg = core.make_leg
    original_main = core.main

    def reassessed_candidates(now):
        active_rows = getattr(core, "ACTIVE_PREDICTION_ROWS", None)
        raw = active_rows if isinstance(active_rows, list) else core.load(core.PREDICTIONS, [])
        history = core.load(DATA / "tennis_prediction_archive.json", [])
        return _build_candidates(
            core,
            now,
            prediction_rows=raw if isinstance(raw, list) else [],
            history=history if isinstance(history, list) else [],
            baseline_fn=original_candidates,
        )

    def exact_market_rows(row):
        return _market_rows(core, row, original_market_rows)

    def reassessed_make_leg(row):
        result = original_make_leg(row)
        if isinstance(result, dict) and isinstance(row.get("market_reassessment"), dict):
            result["market_reassessment"] = row["market_reassessment"]
        if isinstance(result, dict) and result.get("sport") == "tennis" and result.get("market") == "total_games" and result.get("line") is None:
            result["line"] = _num(((row.get("analytics") or {}).get("total_games") or {}).get("line"))
        return result

    def audited_main():
        result = original_main()
        try:
            artifact = core.load(core.OUTPUT, {})
            if isinstance(artifact, dict):
                diagnostics = artifact.setdefault("candidate_diagnostics", {})
                diagnostics["tennis_market_reassessment"] = copy.deepcopy(_DIAGNOSTICS)
                policy = artifact.setdefault("selection_policy", {})
                policy["tennis_alternative_market_reassessment"] = {
                    "enabled": True,
                    "market_id": TENNIS_TOTAL_MARKET_ID,
                    "model": "V5.1 matchup-conditioned empirical total-games distribution",
                    "recheck_cadence": "Every Odds Builder run (15-minute schedule plus upstream refresh triggers)",
                    "exact_current_lines_only": True,
                    "compares_all_available_lines_and_sides": True,
                    "existing_value_and_ticket_gates_unchanged": True,
                    "no_quote_substitution": True,
                    "paper_only": True,
                    "real_money_execution": False,
                }
                core.OUTPUT.write_text(
                    __import__("json").dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            print(f"::warning::Could not attach tennis market-reassessment diagnostics: {exc}")
        return result

    core.tennis_candidates = reassessed_candidates
    core.market_rows = exact_market_rows
    core.make_leg = reassessed_make_leg
    core.main = audited_main


# The helper is public for focused regression tests.
build_tennis_candidates = _build_candidates
exact_full_match_total_quotes = _exact_full_match_total_quotes
diagnostics = lambda: copy.deepcopy(_DIAGNOSTICS)
