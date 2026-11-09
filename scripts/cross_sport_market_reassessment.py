"""Cross-sport, exact-quote market reassessment for Match Signal.

This is a paper-research layer. It creates alternative market candidates from
independent model probabilities, sends eligible alternatives through the
existing Odds Builder gates, and stores immutable pre-match quote/probability
snapshots for later settlement and walk-forward evaluation. It never places a
wager and never substitutes bookmaker quotes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fixture_primary_prediction_ledger import build_fixture_ledger, merge_primary_ledger, primary_summary

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PRIVATE_DIR = DATA / "calibration_private"
# These detailed probabilities, prices, edges and settled research remain private.
# The workflow synchronizes the history to the authenticated private KV endpoint.
OUTPUT = PRIVATE_DIR / "cross_sport_market_reassessment_private.json"
HISTORY_OUTPUT = PRIVATE_DIR / "cross_sport_market_reassessment_history.json"
REVISION_PATH = PRIVATE_DIR / ".cross_sport_market_reassessment_revision"
MAX_QUOTE_AGE_SECONDS = 900
ALTERNATIVE_HORIZON_MINUTES = 24 * 60
MAX_HISTORY_RECORDS = 12000
MIN_NBA_EDGE = 0.04
MIN_NBA_EXPECTED_VALUE = 0.03
_INSTALLED = False
_ORIGINALS: dict[str, Any] = {}
_RUN_OPTIONS: list[dict[str, Any]] = []
_RUN_PRIMARY: list[dict[str, Any]] = []
_LAST_DIAGNOSTICS: dict[str, Any] = {}


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _within_alternative_horizon(row: dict[str, Any], now: datetime) -> bool:
    """Allow a one-day alternative preview; accumulator eligibility stays at 12h."""
    start = _dt(row.get("start_time"))
    if start is None:
        return False
    minutes = (start - now).total_seconds() / 60.0
    return 2.0 < minutes <= ALTERNATIVE_HORIZON_MINUTES


def _within_builder_horizon(core: Any, row: dict[str, Any], now: datetime) -> bool:
    """Fail closed when the existing Builder horizon cannot be evaluated."""
    try:
        return bool(core.within_builder_horizon(row, now))
    except Exception:
        return False


def _builder_horizon_candidates(core: Any, rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Keep the existing Builder input restricted to its unchanged native horizon."""
    return [
        row for row in rows
        if isinstance(row, dict) and _within_builder_horizon(core, row, now)
    ]


def _fresh_quote(row: dict[str, Any], now: datetime) -> tuple[bool, float | None, str | None]:
    snapshot = row.get("sportybet_market") or {}
    stamp = (
        row.get("market_odds_timestamp")
        or row.get("odds_timestamp")
        or row.get("quote_timestamp")
        or snapshot.get("fetched_at")
    )
    parsed = _dt(stamp)
    if parsed is None:
        return False, None, str(stamp) if stamp else None
    age = (now - parsed).total_seconds()
    # A timestamp in the future is a clock/data integrity problem, not a fresh quote.
    if age < 0:
        return False, age, parsed.isoformat()
    return age <= MAX_QUOTE_AGE_SECONDS, age, parsed.isoformat()


def _snapshot_markets(row: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = row.get("sportybet_market") or {}
    if snapshot.get("available") is not True:
        return []
    markets = snapshot.get("markets") or []
    return [market for market in markets if isinstance(market, dict)]


def _market_name(market: dict[str, Any]) -> str:
    return str(market.get("name") or market.get("desc") or market.get("title") or "").strip().lower()


def _market_is_winner(market: dict[str, Any], sport: str) -> bool:
    label = _market_name(market)
    market_id = str(market.get("id") or "")
    accepted = {"1", "186"} if sport == "football" else {"186"}
    return market_id in accepted or any(token in label for token in ("winner", "1x2", "match result"))


def _market_is_total(market: dict[str, Any], sport: str) -> bool:
    label = _market_name(market)
    market_id = str(market.get("id") or "")
    accepted = {"18"} if sport == "football" else {"189"}
    return market_id in accepted or "total" in label or "over/under" in label or "over under" in label


def _market_is_btts(market: dict[str, Any]) -> bool:
    label = _market_name(market)
    return "both teams to score" in label or "btts" in label


def _market_is_double_chance(market: dict[str, Any]) -> bool:
    return "double chance" in _market_name(market)


def _market_line(market: dict[str, Any]) -> float | None:
    line = _num(market.get("line"))
    if line is not None:
        return line
    match = re.search(r"(?:total|line)\s*=\s*([0-9]+(?:\.[0-9]+)?)", str(market.get("specifier") or ""), re.I)
    return _num(match.group(1)) if match else None


def _outcomes(market: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for outcome in market.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        odds = _num(outcome.get("book_odds", outcome.get("odds")))
        if odds is None or odds <= 1 or outcome.get("isActive") is False:
            continue
        result.append({
            "name": str(outcome.get("name") or outcome.get("desc") or outcome.get("title") or ""),
            "id": str(outcome.get("id") or ""),
            "odds": odds,
        })
    return result


def _find_outcome(market: dict[str, Any], side: str, row: dict[str, Any]) -> dict[str, Any] | None:
    outcomes = _outcomes(market)
    p1 = _norm(row.get("player_1") or row.get("home_team"))
    p2 = _norm(row.get("player_2") or row.get("away_team"))
    for outcome in outcomes:
        name = _norm(outcome["name"])
        if side == "p1" and (name in {"1", "home", "hometeam", "player1"} or (p1 and (name == p1 or name in p1 or p1 in name))):
            return outcome
        if side == "p2" and (name in {"2", "away", "awayteam", "player2"} or (p2 and (name == p2 or name in p2 or p2 in name))):
            return outcome
        if side == "draw" and name in {"x", "draw", "tie"}:
            return outcome
        if side in {"over", "under"} and name.startswith(side):
            return outcome
        if side in {"yes", "no"} and name in {side, "yes" if side == "yes" else "no"}:
            return outcome
        if side in {"1x", "12", "x2"}:
            if name == side:
                return outcome
            if side == "1x" and any(x in name for x in ("homeordraw", "homedraw", "1ordraw", "1x")):
                return outcome
            if side == "12" and any(x in name for x in ("homeoraway", "homeaway", "1or2", "12")):
                return outcome
            if side == "x2" and any(x in name for x in ("draworaway", "drawaway", "xortwo", "x2")):
                return outcome
    return None


def _find_market(row: dict[str, Any], predicate, *, line: float | None = None, market_id: str | None = None) -> dict[str, Any] | None:
    found = []
    for market in _snapshot_markets(row):
        if not predicate(market):
            continue
        if market_id and str(market.get("id") or "") != str(market_id):
            continue
        if line is not None:
            exact_line = _market_line(market)
            if exact_line is None or abs(exact_line - line) > 1e-9:
                continue
        found.append(market)
    return found[0] if found else None


def _poisson_over_probability(expected_total: float, line: float) -> float | None:
    # A half-line has no push. Integer lines are excluded from this lane.
    if abs(line - round(line)) < 1e-9 or expected_total <= 0 or expected_total > 12:
        return None
    cutoff = math.floor(line)
    probability = math.exp(-expected_total)
    cumulative = probability
    for goals in range(1, cutoff + 1):
        probability *= expected_total / goals
        cumulative += probability
    return max(0.0, min(1.0, 1.0 - cumulative))


def _decorate_candidate(
    row: dict[str, Any],
    *,
    sport: str,
    market: str,
    side: str,
    probability: float,
    market_obj: dict[str, Any],
    odds_rows: list[dict[str, Any]],
    line: float | None = None,
    outcome: dict[str, Any] | None = None,
    model_source: str,
    exact_market_id: str | None = None,
) -> dict[str, Any]:
    candidate = dict(row)
    # Preserve the original fixture pick before mutating builder_* fields for
    # the alternative. The public publisher uses this to avoid labelling the
    # primary as its own alternative and to verify the alternative is more
    # likely than that primary when a comparable probability exists.
    original_pick = str(row.get("builder_pick") or row.get("pick") or row.get("selection") or "").strip().lower()
    original_market = str(row.get("builder_market") or row.get("market") or "").strip()
    original_line = row.get("line")
    original_probability = None
    original_probabilities = row.get("calibrated_probabilities") or row.get("probabilities") or {}
    if isinstance(original_probabilities, dict) and original_pick:
        original_probability = _num(original_probabilities.get(original_pick))
    if original_probability is None and original_pick in {"over", "under"}:
        original_total = ((row.get("analytics") or {}).get("total_games") or {})
        original_probability = _num(original_total.get("calibrated_" + original_pick, original_total.get(original_pick)))
    if original_probability is None:
        original_probability = _num(row.get("builder_probability", row.get("model_probability", row.get("probability"))))
    if original_pick:
        candidate["original_primary_pick"] = original_pick
    if original_market:
        candidate["original_primary_market"] = original_market
    if original_line is not None:
        candidate["original_primary_line"] = original_line
    if original_probability is not None:
        candidate["original_primary_probability"] = round(float(original_probability), 6)
    candidate["builder_market"] = market
    candidate["builder_pick"] = side
    candidate["builder_probability"] = round(float(probability), 6)
    candidate["probability"] = round(float(probability), 6)
    candidate["reassessment_market_rows"] = [
        {"side": str(item.get("side") or ""), "odds": _num(item.get("odds"))}
        for item in odds_rows
        if _num(item.get("odds")) is not None and float(item.get("odds")) > 1
    ]
    if line is not None:
        candidate["line"] = line
        candidate["reassessment_line"] = line
    market_id = exact_market_id or str(market_obj.get("id") or "")
    candidate["sportybet_market_id"] = market_id or None
    candidate["sportybet_event_id"] = (
        (candidate.get("sportybet_market") or {}).get("event_id")
        or candidate.get("sportybet_event_id")
        or candidate.get("event_id")
    )
    # SportyBet's non-line markets are identified by market/outcome IDs; adding
    # a made-up specifier can make an otherwise valid selection unbookable.
    candidate["sportybet_specifier"] = (
        f"total={line:g}"
        if line is not None and market in {"total_goals", "total_games"}
        else None
    )
    candidate["sportybet_outcome_id"] = str((outcome or {}).get("id") or "") or None
    candidate["sportybet_outcome_name"] = str((outcome or {}).get("name") or "") or None
    candidate["market_source"] = "SportyBet NG exact live market"
    candidate["market_reassessment"] = {
        "strategy": "cross_sport_market_reassessment_v1",
        "status": "EXACT_CURRENT_MARKET_ALTERNATIVE",
        "sport": sport,
        "market": market,
        "side": side,
        "line": line,
        "model_probability": round(float(probability), 6),
        "model_probability_source": model_source,
        "sportybet_market_id": market_id or None,
        "quote_timestamp": (
            candidate.get("market_odds_timestamp")
            or candidate.get("odds_timestamp")
            or (candidate.get("sportybet_market") or {}).get("fetched_at")
        ),
        "paper_only": True,
        "real_money_execution": False,
    }
    return candidate


def _record_options(options: list[dict[str, Any]]) -> None:
    _RUN_OPTIONS.extend(copy.deepcopy(options))


def _dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        line = _num(row.get("line"))
        key = (
            str(row.get("sport") or ""),
            str(row.get("event_id") or ""),
            str(row.get("builder_market") or ""),
            "" if line is None else f"{line:g}",
            str(row.get("builder_pick") or ""),
        )
        current = indexed.get(key)
        new_meta = row.get("market_reassessment") or {}
        old_meta = (current or {}).get("market_reassessment") or {}
        new_is_cross_sport = new_meta.get("strategy") == "cross_sport_market_reassessment_v1"
        old_is_cross_sport = old_meta.get("strategy") == "cross_sport_market_reassessment_v1"
        if current is None or (new_is_cross_sport and not old_is_cross_sport) or (
            bool(new_meta) and not bool(old_meta)
        ):
            indexed[key] = row
    return list(indexed.values())

def _football_options(core: Any, now: datetime, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("sport") != "football" or not _within_alternative_horizon(row, now):
            continue
        is_fresh, _, quote_stamp = _fresh_quote(row, now)
        snapshot = row.get("sportybet_market") or {}
        if snapshot.get("available") is not True:
            continue
        probabilities = row.get("calibrated_probabilities") or row.get("probabilities") or {}
        winner_market = _find_market(row, lambda m: _market_is_winner(m, "football"))
        if winner_market:
            published_winner_odds = row.get("sportybet_winner_odds") or {}
            winner_market_complete = all(
                (_num(published_winner_odds.get(side)) or 0) > 1
                for side in ("p1", "draw", "p2")
            )
            winner_sides = []
            for side in ("p1", "draw", "p2"):
                p = _num(probabilities.get(side))
                outcome = _find_outcome(winner_market, side, row)
                price = outcome.get("odds") if outcome else _num((row.get("sportybet_winner_odds") or {}).get(side))
                if p is None or not 0 < p < 1 or price is None or price <= 1:
                    continue
                winner_sides.append({"side": side, "odds": price})
                candidate = _decorate_candidate(
                    row, sport="football", market="1X2", side=side, probability=p,
                    market_obj=winner_market, odds_rows=winner_sides,
                    outcome=outcome, model_source="football calibrated 1X2 probability",
                )
                # Each candidate must expose the complete same-market price set for de-vig.
                candidate["reassessment_market_rows"] = [
                    {"side": s, "odds": _num((row.get("sportybet_winner_odds") or {}).get(s))}
                    for s in ("p1", "draw", "p2")
                    if _num((row.get("sportybet_winner_odds") or {}).get(s)) is not None
                ]
                if not candidate["reassessment_market_rows"] or not any(x["side"] == side for x in candidate["reassessment_market_rows"]):
                    candidate["reassessment_market_rows"] = [
                        {"side": s["side"], "odds": s["odds"]} for s in winner_sides
                    ]
                audit.append(candidate)
                if (
                    is_fresh and winner_market_complete
                    and p >= float(core.MIN_PROB)
                    and outcome and outcome.get("id")
                ):
                    active.append(candidate)

        # Full-match football goal totals: compare every exact currently offered half-line.
        expected_total = _num((row.get("expected_goals") or {}).get("total"))
        if expected_total is not None:
            quote_list = row.get("sportybet_total_games_odds") or []
            for quote in quote_list:
                if not isinstance(quote, dict):
                    continue
                line = _num(quote.get("line"))
                over_odds, under_odds = _num(quote.get("over")), _num(quote.get("under"))
                market_id = str(quote.get("market_id") or "")
                if line is None or over_odds is None or under_odds is None or over_odds <= 1 or under_odds <= 1:
                    continue
                if market_id not in {"18"}:
                    continue
                over_probability = _poisson_over_probability(expected_total, line)
                if over_probability is None:
                    continue
                market_obj = _find_market(
                    row, lambda m: _market_is_total(m, "football"), line=line, market_id=market_id
                )
                if not market_obj:
                    continue
                outcomes = {
                    side: _find_outcome(market_obj, side, row)
                    for side in ("over", "under")
                }
                if not all(outcomes.values()):
                    continue
                complete_rows = [{"side": "over", "odds": over_odds}, {"side": "under", "odds": under_odds}]
                for side, probability in (("over", over_probability), ("under", 1.0 - over_probability)):
                    candidate = _decorate_candidate(
                        row, sport="football", market="total_goals", side=side, probability=probability,
                        market_obj=market_obj, odds_rows=complete_rows, line=line,
                        outcome=outcomes[side], model_source="Poisson total-goals probability from existing published expected-goals projection",
                        exact_market_id=market_id,
                    )
                    candidate["reassessment_market_rows"] = complete_rows
                    candidate["line"] = line
                    audit.append(candidate)
                    if is_fresh and probability >= float(core.MIN_PROB) and outcomes[side].get("id"):
                        active.append(candidate)

        # Both-teams-to-score alternatives use the model's already published BTTS probabilities.
        btts = ((row.get("markets") or {}).get("btts") or {})
        btts_market = _find_market(row, _market_is_btts)
        if btts_market:
            outcomes = {side: _find_outcome(btts_market, side, row) for side in ("yes", "no")}
            complete_rows = [
                {"side": side, "odds": outcomes[side].get("odds")}
                for side in ("yes", "no") if outcomes[side] is not None
            ]
            if len(complete_rows) == 2:
                for side in ("yes", "no"):
                    p = _num(btts.get(side))
                    outcome = outcomes[side]
                    if p is None or not 0 < p < 1 or not outcome:
                        continue
                    candidate = _decorate_candidate(
                        row, sport="football", market="btts", side=side, probability=p,
                        market_obj=btts_market, odds_rows=complete_rows,
                        outcome=outcome, model_source="published Poisson xG both-teams-to-score probability",
                    )
                    candidate["reassessment_market_rows"] = complete_rows
                    audit.append(candidate)
                    if is_fresh and p >= float(core.MIN_PROB) and outcome.get("id"):
                        active.append(candidate)

        # Double chance is an explicit alternative derived from the independent 1X2 probabilities.
        dc_market = _find_market(row, _market_is_double_chance)
        p1, pd, p2 = (_num(probabilities.get(k)) for k in ("p1", "draw", "p2"))
        if dc_market and all(x is not None for x in (p1, pd, p2)):
            dc_probs = {"1x": float(p1) + float(pd), "12": float(p1) + float(p2), "x2": float(pd) + float(p2)}
            found = {side: _find_outcome(dc_market, side, row) for side in dc_probs}
            complete_rows = [
                {"side": side, "odds": found[side].get("odds")}
                for side in dc_probs if found[side] is not None
            ]
            for side, p in dc_probs.items():
                outcome = found[side]
                if not outcome or not 0 < p < 1:
                    continue
                candidate = _decorate_candidate(
                    row, sport="football", market="double_chance", side=side, probability=p,
                    market_obj=dc_market, odds_rows=complete_rows,
                    outcome=outcome, model_source="sum of independently published 1X2 probabilities",
                )
                candidate["reassessment_market_rows"] = complete_rows
                audit.append(candidate)
                if is_fresh and p >= float(core.MIN_PROB) and outcome.get("id") and len(complete_rows) == 3:
                    active.append(candidate)
    return active, audit


def _tennis_options(core: Any, now: datetime, rows: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    base_by_key = {
        (
            str(x.get("event_id") or ""),
            str(x.get("builder_market") or ""),
            "" if x.get("line") is None else f"{_num(x.get('line')):g}",
            str(x.get("builder_pick") or ""),
        ): x
        for x in baseline if isinstance(x, dict)
    }
    history = core.load(DATA / "tennis_prediction_archive.json", [])
    if not isinstance(history, list):
        history = []
    try:
        from tennis_market_reassessment import exact_full_match_total_quotes
        from tennis_total_model import MIN_HISTORY, predict_total_games
    except Exception:
        exact_full_match_total_quotes = None
        MIN_HISTORY = 999999
        predict_total_games = None

    for row in rows:
        if not isinstance(row, dict) or row.get("sport") != "tennis" or not _within_alternative_horizon(row, now):
            continue
        # Forward-window watch projections are useful research visibility, but
        # are not the calibrated tennis prediction source for Builder reassessment.
        if str(row.get("prediction_status") or "") == "watch_projection" or str(row.get("qualification_status") or "") == "TENNIS_FORWARD_WATCH_NOT_QUALIFIED":
            continue
        is_fresh, _, _ = _fresh_quote(row, now)
        snapshot = row.get("sportybet_market") or {}
        if snapshot.get("available") is not True:
            continue
        probs = row.get("calibrated_probabilities") or row.get("probabilities") or {}
        winner_market = _find_market(row, lambda m: _market_is_winner(m, "tennis"))
        if winner_market:
            published_winner_odds = row.get("sportybet_winner_odds") or {}
            winner_market_complete = all(
                (_num(published_winner_odds.get(side)) or 0) > 1
                for side in ("p1", "p2")
            )
            winner_rows = []
            for side in ("p1", "p2"):
                p = _num(probs.get(side))
                outcome = _find_outcome(winner_market, side, row)
                price = outcome.get("odds") if outcome else _num((row.get("sportybet_winner_odds") or {}).get(side))
                if p is None or not 0 < p < 1 or price is None or price <= 1:
                    continue
                winner_rows.append({"side": side, "odds": price})
                candidate = _decorate_candidate(
                    row, sport="tennis", market="winner", side=side, probability=p,
                    market_obj=winner_market, odds_rows=winner_rows,
                    outcome=outcome, model_source="published tennis winner probability",
                )
                candidate["reassessment_market_rows"] = [
                    {"side": s, "odds": _num((row.get("sportybet_winner_odds") or {}).get(s))}
                    for s in ("p1", "p2") if _num((row.get("sportybet_winner_odds") or {}).get(s)) is not None
                ] or winner_rows
                audit.append(candidate)
                if (
                    is_fresh and winner_market_complete
                    and 0 < p < 1.0 and p >= float(core.MIN_PROB)
                    and outcome and outcome.get("id")
                ):
                    active.append(candidate)

        # Recalculate every current full-match half-line, not the model's legacy single line.
        if exact_full_match_total_quotes and predict_total_games:
            quotes = exact_full_match_total_quotes(row)
            distribution = None
            try:
                distribution = predict_total_games(row, history)
            except Exception:
                distribution = None
            dist = (distribution or {}).get("distribution") or {}
            neighbors = int((distribution or {}).get("neighbors") or 0)
            if isinstance(dist, dict) and dist and neighbors >= max(30, int(MIN_HISTORY)):
                for line, quote in quotes.items():
                    over_odds, under_odds = _num(quote.get("over")), _num(quote.get("under"))
                    market_id = str(quote.get("market_id") or "189")
                    if over_odds is None or under_odds is None:
                        continue
                    market_obj = _find_market(
                        row, lambda m: _market_is_total(m, "tennis"), line=float(line), market_id=market_id
                    )
                    if not market_obj:
                        continue
                    outcomes = {side: _find_outcome(market_obj, side, row) for side in ("over", "under")}
                    if not all(outcomes.values()):
                        continue
                    over_p = sum(
                        float(prob)
                        for score, prob in dist.items()
                        if _num(score) is not None and _num(prob) is not None and float(score) > float(line)
                    )
                    over_p = max(0.0, min(1.0, over_p))
                    complete_rows = [{"side": "over", "odds": over_odds}, {"side": "under", "odds": under_odds}]
                    for side, p in (("over", over_p), ("under", 1.0 - over_p)):
                        meta = _decorate_candidate(
                            row, sport="tennis", market="total_games", side=side, probability=p,
                            market_obj=market_obj, odds_rows=complete_rows, line=float(line),
                            outcome=outcomes[side], model_source="V5.1 prior-only matchup-conditioned total-games distribution",
                            exact_market_id=market_id,
                        )
                        total = dict(((row.get("analytics") or {}).get("total_games") or {}))
                        total.update({
                            "line": float(line), "pick": side,
                            "over": round(over_p, 6), "under": round(1.0 - over_p, 6),
                            "base_model_over": round(over_p, 6), "base_model_under": round(1.0 - over_p, 6),
                            "model": (distribution or {}).get("model") or "V5.1 prior-only matchup-conditioned total-games distribution",
                            "neighbors": neighbors,
                            "market_alignment_status": "EXACT_SPORTYBET_TOTAL_LINE_RECALCULATED",
                        })
                        meta["analytics"] = dict(row.get("analytics") or {})
                        meta["analytics"]["total_games"] = total
                        meta["reassessment_market_rows"] = complete_rows
                        meta["line"] = float(line)
                        audit.append(meta)
                        if is_fresh and 0 < p < 1.0 and p >= float(core.MIN_PROB) and outcomes[side].get("id"):
                            active.append(meta)

    # Reuse the existing tennis recalculation output, preferring it where it already has the same exact option.
    all_rows = _dedupe_candidates(baseline + active)
    for candidate in all_rows:
        if candidate.get("sport") == "tennis":
            if not any(
                x.get("sport") == "tennis"
                and x.get("event_id") == candidate.get("event_id")
                and x.get("builder_market") == candidate.get("builder_market")
                and x.get("line") == candidate.get("line")
                and x.get("builder_pick") == candidate.get("builder_pick")
                for x in audit
            ):
                audit.append(candidate)
    tennis_rows = [x for x in all_rows if x.get("sport") == "tennis"]
    # The 24h list is for alternatives; only the original 12h window feeds tickets.
    return _builder_horizon_candidates(core, tennis_rows, now), audit


def _virtual_options(now: datetime):
    # The core calls this as virtual_candidates(now); keep the wrapped function's
    # public signature identical to the existing Builder contract.
    result = _ORIGINALS["virtual_candidates"](now)
    rows = result[0] if isinstance(result, tuple) and result else result
    if isinstance(rows, list):
        alternatives = []
        for source in rows:
            if not isinstance(source, dict):
                continue
            row = copy.deepcopy(source)
            # virtual_candidates emits explicit directional candidates for both
            # eFootball O/U sides. Preserve the feed's original preferred side so
            # the public lane can exclude the primary and compare probabilities.
            primary_pick = str(row.get("source_model_pick") or row.get("pick") or "").strip().lower()
            primary_probabilities = row.get("probabilities") if isinstance(row.get("probabilities"), dict) else {}
            primary_probability = _num(primary_probabilities.get(primary_pick)) if primary_pick else None
            if primary_pick:
                row["original_primary_pick"] = primary_pick
            row["original_primary_market"] = "virtual_total"
            row["original_primary_line"] = row.get("line")
            if primary_probability is not None:
                row["original_primary_probability"] = round(float(primary_probability), 6)
            alternatives.append(row)
        _record_options(alternatives)
        _RUN_PRIMARY.extend(copy.deepcopy(alternatives))
    return result


def _settled_rows(path: Path) -> list[dict[str, Any]]:
    value = None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("records", "history", "predictions", "rows", "settlements", "results"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
    return []


def _nba_options(now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Research both sides of the exact current NBA market-225 line.

    NBA alternatives remain in the dedicated paper-evidence lane and do not
    enter the general ticket pool until the NBA release gate authorizes them.
    """
    predictions = _settled_rows(DATA / "nba_predictions.json")
    diagnostics = {
        "status": "RESEARCH_ONLY",
        "model_market_blind": True,
        "market_id": "225",
        "prediction_rows": len(predictions),
        "upcoming_rows": 0,
        "fresh_exact_price_rows": 0,
        "options_evaluated": 0,
        "calibration_status": "UNAVAILABLE",
        "promotion_allowed": False,
        "promotion_reason": "NBA dedicated publication/value release gate remains authoritative",
    }
    if not predictions:
        return [], diagnostics
    has_fresh_pair = False
    for row in predictions:
        if str(row.get("sport") or "").lower() != "basketball":
            continue
        start = _dt(row.get("start_time"))
        if start is None or start <= now or (start - now).total_seconds() > 12 * 3600:
            continue
        market = (row.get("markets") or {}).get("total_ou") or {}
        quote_stamp = _dt(market.get("quote_timestamp"))
        if (
            str(market.get("market_id") or "") == "225"
            and "sportybet" in str(market.get("source") or "").lower()
            and quote_stamp is not None
            and 0 <= (now - quote_stamp).total_seconds() <= MAX_QUOTE_AGE_SECONDS
            and (_num(market.get("over_odds")) or 0) > 1
            and (_num(market.get("under_odds")) or 0) > 1
            and _num(market.get("line")) is not None
            and _num(row.get("expected_total")) is not None
        ):
            has_fresh_pair = True
            break
    if not has_fresh_pair:
        diagnostics["calibration_status"] = "SKIPPED_NO_FRESH_EXACT_QUOTES"
        diagnostics["promotion_reason"] = "No upcoming NBA fixture currently has a fresh exact market-225 price pair"
        return [], diagnostics
    calibrated = None
    residuals: list[float] = []
    try:
        # Reuse the existing time-ordered, market-blind calibration protocol.
        import nba_totals_probability_value_experiment as nba_prob
        from nba_totals_walk_forward import HISTORY
        raw_history = json.loads(HISTORY.read_text(encoding="utf-8"))
        calibration = nba_prob.fit_residual_distribution(raw_history)
        residuals = list(calibration.get("calibration_residuals") or [])
        score = calibration.get("historical_probability_validation") or {}
        clustered = score.get("event_clustered_score_diagnostics") or {}
        calibrated = (
            calibration.get("coverage_check") == "PASS"
            and clustered.get("model_brier_improves_with_95pct_clustered_support") is True
            and clustered.get("model_log_loss_improves_with_95pct_clustered_support") is True
            and len(residuals) >= 150
        )
        diagnostics["calibration_status"] = "PASS" if calibrated else "HOLD_VALIDATION"
        diagnostics["calibration_sample"] = len(residuals)
    except Exception as exc:
        diagnostics["calibration_status"] = "UNAVAILABLE"
        diagnostics["calibration_error"] = str(exc)[:180]
        return [], diagnostics

    if not residuals:
        return [], diagnostics
    try:
        from nba_totals_probability_value_experiment import _settlement_probabilities
    except Exception:
        return [], diagnostics

    alternatives = []
    for row in predictions:
        if str(row.get("sport") or "").lower() != "basketball":
            continue
        start = _dt(row.get("start_time"))
        if start is None or start <= now or (start - now).total_seconds() > 12 * 3600:
            continue
        diagnostics["upcoming_rows"] += 1
        market = (row.get("markets") or {}).get("total_ou") or {}
        if str(market.get("market_id") or "") != "225" or str(market.get("source") or "").lower().find("sportybet") < 0:
            continue
        quote_stamp = _dt(market.get("quote_timestamp"))
        if quote_stamp is None or (now - quote_stamp).total_seconds() < 0 or (now - quote_stamp).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            continue
        line = _num(market.get("line"))
        over_odds, under_odds = _num(market.get("over_odds")), _num(market.get("under_odds"))
        forecast = _num(row.get("expected_total"))
        if line is None or over_odds is None or under_odds is None or forecast is None or over_odds <= 1 or under_odds <= 1:
            continue
        diagnostics["fresh_exact_price_rows"] += 1
        probs = _settlement_probabilities(forecast, line, residuals)
        no_vig_over = (1 / over_odds) / ((1 / over_odds) + (1 / under_odds))
        no_vig_under = 1.0 - no_vig_over
        for side, odds in (("over", over_odds), ("under", under_odds)):
            probability = float(probs.get(side) or 0.0)
            fair_prob = no_vig_over if side == "over" else no_vig_under
            edge = probability - fair_prob
            ev = probability * (odds - 1.0) - float(probs.get("under" if side == "over" else "over") or 0.0)
            side_candidate = {
                "sport": "basketball",
                "league": "NBA",
                "event_id": str(row.get("event_id") or ""),
                "start_time": row.get("start_time"),
                "player_1": row.get("player_1"),
                "player_2": row.get("player_2"),
                "market": "total_ou",
                "line": line,
                "pick": side,
                "model_probability": round(probability, 6),
                "bookmaker_odds": odds,
                "market_fair_probability": round(fair_prob, 6),
                "model_edge": round(edge, 6),
                "expected_value": round(ev, 6),
                "market_id": "225",
                "sportybet_event_id": market.get("sportybet_event_id"),
                "quote_timestamp": quote_stamp.isoformat(),
                "quote_age_seconds": round((now - quote_stamp).total_seconds(), 1),
                "model_version": row.get("totals_model_version"),
                "probability_method": "fixed-cutoff calibration residual distribution from prior completed NBA games",
                "calibration_status": diagnostics["calibration_status"],
                "market_blind_projection": row.get("model_is_market_blind", True),
                "fresh_exact_quote": True,
                "paper_only": True,
                "real_money_execution": False,
                "nba_dedicated_gate_required": True,
                "builder_eligible": False,
                "candidate_status": (
                    "VALUE_RESEARCH_CANDIDATE"
                    if calibrated and edge >= MIN_NBA_EDGE and ev >= MIN_NBA_EXPECTED_VALUE
                    else "RESEARCH_ONLY_NOT_QUALIFIED"
                ),
                "better_side_by_value": None,
            }
            alternatives.append(side_candidate)
            diagnostics["options_evaluated"] += 1
        if len(alternatives) >= 2:
            latest = alternatives[-2:]
            qualified = [x for x in latest if x["candidate_status"] == "VALUE_RESEARCH_CANDIDATE"]
            best = max(qualified, key=lambda x: x["expected_value"]) if qualified else None
            for item in latest:
                item["better_side_by_value"] = best["pick"] if best else "NO_BET"
    diagnostics["promotion_allowed"] = False
    diagnostics["promotion_reason"] = "NBA dedicated release gate remains authoritative; this lane records both exact-line sides only"
    return alternatives, diagnostics


def _settle_result(record: dict[str, Any], settled_by_event: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    key = (str(record.get("sport") or ""), str(record.get("event_id") or ""))
    source = settled_by_event.get(key)
    if not source:
        return None
    market = str(record.get("market") or "")
    side = str(record.get("pick") or "")
    line = _num(record.get("line"))
    actual_markets = source.get("actual_markets") if isinstance(source.get("actual_markets"), dict) else {}
    final_score = source.get("final_score")
    actual = str(source.get("actual") or source.get("result") or "").lower()
    result = None
    if record.get("sport") == "basketball":
        total = _num(source.get("final_total"))
        if total is None and isinstance(final_score, list) and len(final_score) >= 2:
            a, b = _num(final_score[0]), _num(final_score[1])
            total = a + b if a is not None and b is not None else None
        if total is not None and line is not None:
            result = "over" if total > line else "under" if total < line else "push"
    elif market in {"total_goals", "total_games"} or market in {"total_ou", "virtual_total", "over_under"}:
        total = _num(actual_markets.get("total_games") if market == "total_games" else None)
        if total is None:
            total = _num(actual_markets.get("total_goals"))
        if total is None and isinstance(final_score, list) and len(final_score) >= 2:
            vals = [_num(x) for x in final_score]
            if all(x is not None for x in vals):
                total = sum(float(x) for x in vals)
        if total is not None and line is not None:
            result = "over" if total > line else "under" if total < line else "push"
    elif market == "btts":
        btts_actual = actual_markets.get("btts") or actual_markets.get("both_teams_to_score")
        if isinstance(btts_actual, bool):
            result = "yes" if btts_actual else "no"
        elif final_score and isinstance(final_score, list) and len(final_score) >= 2:
            vals = [_num(x) for x in final_score]
            if all(x is not None for x in vals):
                result = "yes" if min(vals) > 0 else "no"
    elif market == "double_chance":
        outcome = actual
        if outcome in {"home", "1", "p1", "team1"}:
            outcome = "p1"
        elif outcome in {"away", "2", "p2", "team2"}:
            outcome = "p2"
        elif outcome in {"x", "tie"}:
            outcome = "draw"
        if final_score and isinstance(final_score, list) and len(final_score) >= 2:
            vals = [_num(x) for x in final_score]
            if all(x is not None for x in vals):
                outcome = "p1" if vals[0] > vals[1] else "p2" if vals[1] > vals[0] else "draw"
        if outcome in {"p1", "draw", "p2"}:
            result = "yes" if (side == "1x" and outcome in {"p1", "draw"}) or (side == "12" and outcome in {"p1", "p2"}) or (side == "x2" and outcome in {"draw", "p2"}) else "no"
    else:
        if record.get("sport") == "football" and market in {"1X2", "winner"} and isinstance(final_score, list) and len(final_score) >= 2:
            vals = [_num(x) for x in final_score]
            if all(x is not None for x in vals):
                actual = "p1" if vals[0] > vals[1] else "p2" if vals[1] > vals[0] else "draw"
        if actual in {"p1", "p2", "draw", "1", "2", "x", "home", "away"}:
            if actual in {"1", "home"}:
                actual = "p1"
            elif actual in {"2", "away"}:
                actual = "p2"
            elif actual == "x":
                actual = "draw"
            result = "yes" if actual == side else "no"
    if result is None:
        return None
    return {
        "settlement_status": "SETTLED",
        "settlement_result": result,
        "settled_at": source.get("settled_at") or source.get("updated_at"),
        "settlement_source": source.get("settlement_source") or source.get("source") or "existing Match Signal settlement artifact",
    }


def _settlement_index() -> dict[tuple[str, str], dict[str, Any]]:
    sources = [
        ("football", DATA / "prediction_history.json"),
        ("football", DATA / "expansion_prediction_history.json"),
        ("tennis", DATA / "tennis_prediction_archive.json"),
        ("virtual", DATA / "virtual_lab_history.json"),
        ("virtual", DATA / "efootball_desk_prediction_history.json"),
        ("basketball", DATA / "nba_totals_ledger.json"),
    ]
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for default_sport, path in sources:
        for row in _settled_rows(path):
            event_id = str(row.get("event_id") or "")
            if not event_id:
                continue
            status = str(row.get("status") or "").lower()
            settled = row.get("settled") is True or status in {"settled", "won", "lost", "final"} or row.get("final_total") is not None
            if not settled:
                continue
            sport = str(row.get("sport") or default_sport).lower()
            if sport in {"efootball", "efootball_gt", "efootball_adriatic"}:
                sport = "virtual"
            # Prefer a row with the richer final score / actual market details.
            key = (sport, event_id)
            existing = index.get(key)
            if existing is None or len(row) > len(existing):
                index[key] = row
    return index


def _make_audit_record(core: Any, row: dict[str, Any], now: datetime) -> dict[str, Any]:
    p = _num(row.get("builder_probability", row.get("model_probability", row.get("probability"))))
    side = str(row.get("builder_pick") or row.get("pick") or "")
    market = str(row.get("builder_market") or row.get("market") or "")
    line = _num(row.get("line"))
    price = None
    market_rows = []
    try:
        market_rows = core.market_rows(row)
    except Exception:
        market_rows = []
    for market_row in market_rows or []:
        if str(market_row.get("side") or "") == side:
            price = _num(market_row.get("odds"))
            break
    if price is None:
        price = _num(row.get("bookmaker_odds"))
    fresh, age, stamp = _fresh_quote(row, now)
    try:
        leg = core.make_leg(row)
    except Exception as exc:
        leg = {"builder_eligible": False, "status": "REJECTED", "audit_error": str(exc)[:160]}
    model_floor = p is not None and p >= float(core.MIN_PROB)
    if str(row.get("sport") or "").lower() == "virtual":
        # Virtual products lack bookmaker outcome IDs in some feeds; exact product
        # plus line/side and direct settled-line evidence is their identity contract.
        quote_exact = (
            price is not None and price > 1
            and bool(row.get("product"))
            and line is not None
            and side in {"over", "under"}
            and bool(row.get("evidence_source") or row.get("evidence_sample_n") or row.get("direct_exact_sample_n"))
        )
    else:
        # Real-sport evidence must bind both the exact market and its exact outcome.
        quote_exact = (
            price is not None and price > 1
            and bool(row.get("sportybet_market_id"))
            and bool(row.get("sportybet_outcome_id"))
            and bool(row.get("sportybet_event_id"))
        )
    in_builder_horizon = _within_builder_horizon(core, row, now)
    in_alternative_horizon = _within_alternative_horizon(row, now)
    if not model_floor:
        status = "BELOW_MODEL_PROBABILITY_FLOOR"
    elif not quote_exact:
        status = "NO_EXACT_CURRENT_QUOTE"
    elif not fresh:
        status = "STALE_OR_UNTIMESTAMPED_QUOTE"
    elif in_alternative_horizon and not in_builder_horizon:
        status = "ALTERNATIVE_ONLY_OUTSIDE_BUILDER_HORIZON"
    elif leg.get("builder_eligible") is True and in_builder_horizon:
        status = "PASS_EXISTING_BUILDER_GATES"
    else:
        status = str(leg.get("status") or "REJECTED")
    match = f"{row.get('player_1') or row.get('home_team') or row.get('home') or ''} vs {row.get('player_2') or row.get('away_team') or row.get('away') or ''}".strip()
    market_assessment = row.get("market_reassessment") or {}
    sport = str(row.get("sport") or "").lower()
    if sport in {"efootball", "efootball_gt", "efootball_adriatic"}:
        sport = "virtual"
    event_id = str(row.get("event_id") or "")
    primary_id = hashlib.sha256((sport + "|" + event_id).encode("utf-8")).hexdigest()[:24] if sport and event_id else None
    return {
        "sport": sport,
        "product": row.get("product"),
        "league": row.get("league"),
        "event_id": event_id,
        "prediction_role": "ALTERNATIVE",
        "primary_prediction_id": primary_id,
        "alternative_source": "SYSTEM_RECOMMENDED",
        "start_time": row.get("start_time"),
        "match": match,
        "market": market,
        "line": line,
        "pick": side,
        "original_pick": row.get("original_primary_pick") or row.get("pick"),
        "original_primary_pick": row.get("original_primary_pick"),
        "original_primary_market": row.get("original_primary_market"),
        "original_primary_line": row.get("original_primary_line"),
        "original_primary_probability": row.get("original_primary_probability"),
        "model_probability": round(p, 6) if p is not None else None,
        "bookmaker_odds": price,
        "market_implied_probability": leg.get("market_implied_probability"),
        "de_vig_probability": leg.get("de_vig_probability"),
        "model_edge": leg.get("model_edge"),
        "expected_value": leg.get("expected_value"),
        "selection_score": leg.get("selection_score"),
        "quote_timestamp": stamp,
        "quote_age_seconds": round(age, 1) if age is not None else None,
        "fresh_exact_quote": bool(fresh and quote_exact),
        "sportybet_event_id": row.get("sportybet_event_id"),
        "sportybet_market_id": row.get("sportybet_market_id") or market_assessment.get("sportybet_market_id"),
        "sportybet_specifier": row.get("sportybet_specifier"),
        "sportybet_outcome_id": row.get("sportybet_outcome_id"),
        "sportybet_outcome_name": row.get("sportybet_outcome_name"),
        "model_source": market_assessment.get("model_probability_source") or row.get("model"),
        "reassessment_status": market_assessment.get("status") or "EXISTING_EXACT_EVIDENCE_CANDIDATE",
        "candidate_status": status,
        "passed_model_floor": bool(model_floor),
        "passed_builder_gates": bool(leg.get("builder_eligible") and in_builder_horizon),
        "in_builder_pool": bool(in_builder_horizon and (row.get("market_reassessment") or row.get("sport") == "virtual")),
        "alternative_only": bool(in_alternative_horizon and not in_builder_horizon),
        "evidence_source": row.get("evidence_source"),
        "evidence_sample_n": row.get("evidence_sample_n"),
        "paper_only": True,
        "real_money_execution": False,
        "settlement_status": "PENDING",
        "settlement_result": None,
        "settled_at": None,
        "settlement_source": None,
        "observed_at": now.isoformat(),
    }


def _fingerprint(row: dict[str, Any]) -> str:
    identity = "|".join(str(row.get(key) or "") for key in (
        "sport", "event_id", "market", "line", "pick", "quote_timestamp",
        "bookmaker_odds", "model_probability", "model_source", "sportybet_market_id",
        "sportybet_outcome_id",
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _append_history(new_records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    payload = None
    try:
        payload = json.loads(HISTORY_OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        payload = {
            "record_type": "cross_sport_market_reassessment",
            "generated_at": now.isoformat(),
            "mode": "PAPER_ONLY",
            "records": [],
        }
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    seen = {str(x.get("snapshot_id")) for x in records if isinstance(x, dict)}
    added = 0
    for row in new_records:
        if not row.get("fresh_exact_quote") or not row.get("event_id"):
            continue
        start = _dt(row.get("start_time"))
        if start is None or start <= now:
            continue
        key = _fingerprint(row)
        if key in seen:
            continue
        frozen = dict(row)
        frozen["snapshot_id"] = key
        frozen["settlement_status"] = "PENDING"
        records.append(frozen)
        seen.add(key)
        added += 1
    settlement_index = _settlement_index()
    settled_updated = 0
    for row in records:
        if not isinstance(row, dict) or row.get("settlement_status") == "SETTLED":
            continue
        start = _dt(row.get("start_time"))
        if start is None or start > now:
            continue
        resolved = _settle_result(row, settlement_index)
        if resolved:
            row.update(resolved)
            settled_updated += 1
    if len(records) > MAX_HISTORY_RECORDS:
        records = records[-MAX_HISTORY_RECORDS:]
    payload.update({
        "generated_at": now.isoformat(),
        "mode": "PAPER_ONLY",
        "record_count": len(records),
        "new_snapshots_added": added,
        "new_settlements_recorded": settled_updated,
        "records": records,
        "collection_policy": {
            "immutable_forecast_and_quote_fields": True,
            "deduplicates_unchanged_market_snapshots": True,
            "settlement_sources": [
                "data/prediction_history.json", "data/expansion_prediction_history.json",
                "data/tennis_prediction_archive.json", "data/virtual_lab_history.json",
                "data/efootball_desk_prediction_history.json", "data/nba_totals_ledger.json",
            ],
            "paper_only": True,
        },
    })
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"record_count": len(records), "new_snapshots_added": added, "new_settlements_recorded": settled_updated, "path": str(HISTORY_OUTPUT.relative_to(ROOT))}


def _evidence_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        line = _num(row.get("line"))
        line_key = "none" if line is None else f"{line:g}"
        key = f"{row.get('sport')}:{row.get('market')}:{line_key}:{row.get('pick')}"
        groups.setdefault(key, []).append(row)
    summary = {}
    for key, rows in groups.items():
        # Repeated 15-minute snapshots of one fixture are not independent samples.
        settled_by_event: dict[str, dict[str, Any]] = {}
        # Score the latest pre-match snapshot for each event/market/line/side,
        # while retaining every revision in the ledger for movement analysis.
        for row in sorted(rows, key=lambda x: str(x.get("quote_timestamp") or x.get("observed_at") or ""), reverse=True):
            result = row.get("settlement_result")
            if row.get("settlement_status") != "SETTLED" or result not in {"yes", "no", "over", "under", "push"}:
                continue
            event_id = str(row.get("event_id") or "")
            if event_id and event_id not in settled_by_event:
                settled_by_event[event_id] = row
        settled = [x for x in settled_by_event.values() if x.get("settlement_result") != "push"]
        wins = 0
        brier_values = []
        for row in settled:
            pick = str(row.get("pick") or "").lower()
            result = str(row.get("settlement_result") or "").lower()
            won = (
                (pick in {"yes", "over"} and result in {"yes", "over"})
                or (pick in {"no", "under"} and result in {"no", "under"})
                or (pick in {"p1", "p2", "draw"} and result == "yes")
            )
            wins += int(won)
            probability = _num(row.get("model_probability"))
            if probability is not None:
                brier_values.append((probability - (1.0 if won else 0.0)) ** 2)
        all_events = {str(x.get("event_id") or "") for x in rows if x.get("event_id")}
        settled_events = set(settled_by_event)
        summary[key] = {
            "snapshot_rows": len(rows),
            "unique_events": len(all_events),
            "settled_unique_events": len(settled),
            "wins": wins,
            "losses": max(0, len(settled) - wins),
            "hit_rate": round(wins / len(settled), 4) if settled else None,
            "brier_score": round(sum(brier_values) / len(brier_values), 6) if brier_values else None,
            "pending_unique_events": len(all_events - settled_events),
            "note": "One earliest scored snapshot per event/market/line/side; alternatives from the same fixture remain correlated across different lines and markets.",
        }
    return summary

def _write_reassessment_artifact(core: Any, now: datetime) -> dict[str, Any]:
    global _LAST_DIAGNOSTICS
    raw_options = _dedupe_candidates(_RUN_OPTIONS)
    nba_rows, nba_diag = _nba_options(now)
    records = []
    seen = set()
    for row in raw_options:
        if not isinstance(row, dict):
            continue
        record = _make_audit_record(core, row, now)
        record["snapshot_id"] = _fingerprint(record)
        if record["snapshot_id"] in seen:
            continue
        seen.add(record["snapshot_id"])
        records.append(record)
    nba_records = []
    for row in nba_rows:
        item = dict(row)
        sport = str(row.get("sport") or "basketball").lower()
        event_id = str(row.get("event_id") or "")
        primary_id = hashlib.sha256((sport + "|" + event_id).encode("utf-8")).hexdigest()[:24] if event_id else None
        item.update({
            "prediction_role": "ALTERNATIVE",
            "primary_prediction_id": primary_id,
            "alternative_source": "SYSTEM_RECOMMENDED",
            "match": f"{row.get('player_1')} vs {row.get('player_2')}",
            "market": "total_ou",
            "sport": "basketball",
            "candidate_status": row.get("candidate_status"),
            "market_odds_timestamp": row.get("quote_timestamp"),
            "fresh_exact_quote": True,  # _nba_options only emits verified fresh exact market-225 price pairs.
            "sportybet_market_id": "225",
            "sportybet_event_id": row.get("sportybet_event_id"),
            "exact_market_pair": True,
            "settlement_status": "PENDING",
            "settlement_result": None,
            "observed_at": now.isoformat(),
        })
        item["snapshot_id"] = _fingerprint(item)
        nba_records.append(item)
        records.append(item)

    history_summary = _append_history(records, now)
    history_payload = {}
    try:
        history_payload = json.loads(HISTORY_OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        history_payload = {}
    history_records = history_payload.get("records") if isinstance(history_payload, dict) else []
    if not isinstance(history_records, list):
        history_records = []

    # One official primary is frozen per fixture. Ambiguous/missing source picks
    # are explicitly unclassified; no alternative is promoted after the fact.
    primary_sources = core.load(core.PREDICTIONS, [])
    if not isinstance(primary_sources, list):
        primary_sources = []
    primary_sources = list(primary_sources) + list(_RUN_PRIMARY)
    nba_primary_sources = _settled_rows(DATA / "nba_predictions.json")
    primary_sources.extend(nba_primary_sources)
    primary_existing = history_payload.get("primary_predictions", []) if isinstance(history_payload, dict) else []
    if not isinstance(primary_existing, list):
        primary_existing = []
    primary_incoming = build_fixture_ledger(primary_sources, now)
    primary_records = merge_primary_ledger(primary_existing, primary_incoming, _settle_result, _settlement_index(), now)
    history_payload["primary_predictions"] = primary_records
    history_payload["primary_summary"] = primary_summary(primary_records)
    history_payload["generated_at"] = now.isoformat()
    HISTORY_OUTPUT.write_text(json.dumps(history_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sport_summary: dict[str, dict[str, int]] = {}
    for row in records:
        sport = str(row.get("sport") or "unknown")
        group = sport_summary.setdefault(sport, {"evaluated_options": 0, "fresh_exact_quotes": 0, "builder_gate_pass": 0, "below_model_floor": 0})
        group["evaluated_options"] += 1
        group["fresh_exact_quotes"] += int(row.get("fresh_exact_quote") is True)
        group["builder_gate_pass"] += int(row.get("passed_builder_gates") is True or row.get("candidate_status") == "VALUE_RESEARCH_CANDIDATE")
        group["below_model_floor"] += int(row.get("candidate_status") == "BELOW_MODEL_PROBABILITY_FLOOR")

    eligible_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        if row.get("passed_builder_gates") is True and row.get("event_id"):
            eligible_by_event.setdefault(str(row["event_id"]), []).append(row)
    preferred = []
    for event_id, options in eligible_by_event.items():
        options.sort(key=lambda x: (
            _num(x.get("selection_score")) or -1,
            _num(x.get("model_edge")) or -1,
            _num(x.get("expected_value")) or -1,
        ), reverse=True)
        best = options[0]
        preferred.append({
            "event_id": event_id,
            "sport": best.get("sport"),
            "match": best.get("match"),
            "market": best.get("market"),
            "line": best.get("line"),
            "pick": best.get("pick"),
            "model_probability": best.get("model_probability"),
            "bookmaker_odds": best.get("bookmaker_odds"),
            "model_edge": best.get("model_edge"),
            "expected_value": best.get("expected_value"),
            "why_preferred": "Highest selection score among alternatives that passed the existing Builder gates; not proof of a winning prediction.",
        })
    _LAST_DIAGNOSTICS = {
        "status": "ACTIVE_PAPER_REASSESSMENT",
        "strategy": "Reassess supported markets for each upcoming fixture, compare exact current alternatives, then let existing probability/value/freshness/uncertainty/correlation/ticket gates decide.",
        "mode": "PAPER_ONLY",
        "recheck_cadence": "Every Odds Builder run (15-minute schedule and upstream publication triggers)",
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "sports": sport_summary,
        "preferred_alternative_count": len(preferred),
        "preferred_alternatives": preferred[:100],
        "nba_dedicated_lane": nba_diag,
        "history": history_summary,
        "settled_evidence": _evidence_summary(history_records),
        "primary_predictions": primary_summary(primary_records),
        "no_quote_substitution": True,
        "unvalidated_alternative_markets_are_flagged": True,
        "real_money_execution": False,
    }
    artifact = {
        "generated_at": now.isoformat(),
        "mode": "PAPER_ONLY",
        "status": "ACTIVE_PAPER_REASSESSMENT",
        "strategy": "Evaluate current exact market alternatives from independent model probabilities; capture immutable snapshots and settle them from existing Match Signal result sources.",
        "sports": sport_summary,
        "candidate_options": records[:1200],
        "preferred_alternatives": preferred[:100],
        "nba_dedicated_lane": nba_diag,
        "history": history_summary,
        "settled_evidence": _evidence_summary(history_records),
        "primary_predictions": primary_summary(primary_records),
        "policy": {
            "exact_current_sportybet_prices_only": True,
            "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
            "football_markets": ["1X2", "full-match half-line total goals", "both teams to score", "double chance"],
            "tennis_markets": ["winner", "exact full-match half-line total games"],
            "virtual_markets": ["exact-line over/under candidates only when existing settled-evidence lane supplies them"],
            "basketball_markets": ["NBA full-game total market 225, both sides at the exact captured line"],
            "nba_promotion_requires_dedicated_release_gate": True,
            "all_current_builder_gates_preserved": True,
            "append_only_pre_match_snapshots": True,
            "one_frozen_primary_prediction_per_fixture": True,
            "alternatives_settled_independently_and_never_promoted": True,
            "missing_or_ambiguous_primary_is_unclassified": True,
            "settlement_join_is_event_scoped": True,
            "paper_only": True,
            "real_money_execution": False,
        },
    }
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return _LAST_DIAGNOSTICS


def install(core: Any) -> None:
    """Install wrappers around candidate generation without changing core gates."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _ORIGINALS.update({
        "football_candidates": core.football_candidates,
        "tennis_candidates": core.tennis_candidates,
        "virtual_candidates": core.virtual_candidates,
        "market_rows": core.market_rows,
        "make_leg": core.make_leg,
        "main": core.main,
    })

    def reassessed_football_candidates(now):
        base = _ORIGINALS["football_candidates"](now)
        active_rows = getattr(core, "ACTIVE_PREDICTION_ROWS", None)
        rows = active_rows if isinstance(active_rows, list) else core.load(core.PREDICTIONS, [])
        options, audit = _football_options(core, now, rows if isinstance(rows, list) else [])
        _record_options(audit)
        # Expanded horizon feeds the alternative preview only; leave the native
        # accumulator Builder input inside its original 12-hour window.
        builder_options = _builder_horizon_candidates(core, options, now)
        return _dedupe_candidates((base if isinstance(base, list) else []) + builder_options)

    def reassessed_tennis_candidates(now):
        base = _ORIGINALS["tennis_candidates"](now)
        active_rows = getattr(core, "ACTIVE_PREDICTION_ROWS", None)
        rows = active_rows if isinstance(active_rows, list) else core.load(core.PREDICTIONS, [])
        result, audit = _tennis_options(core, now, rows if isinstance(rows, list) else [], base if isinstance(base, list) else [])
        _record_options(audit)
        return _builder_horizon_candidates(core, result, now)

    def exact_market_rows(row):
        rows = row.get("reassessment_market_rows")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
        return _ORIGINALS["market_rows"](row)

    def audited_make_leg(row):
        leg = _ORIGINALS["make_leg"](row)
        if isinstance(leg, dict) and isinstance(row.get("market_reassessment"), dict):
            leg["market_reassessment"] = copy.deepcopy(row["market_reassessment"])
            match = leg.get("match") or f"{row.get('player_1') or row.get('home_team') or ''} vs {row.get('player_2') or row.get('away_team') or ''}"
            leg["match"] = match
            if row.get("sport") == "football":
                market = str(row.get("builder_market") or "")
                line = row.get("line")
                side = str(row.get("builder_pick") or "")
                label = {
                    "1X2": {"p1": "Home", "draw": "Draw", "p2": "Away"}.get(side, side),
                    "total_goals": f"Total Goals {side.upper()} {line}",
                    "btts": f"Both Teams To Score {side.upper()}",
                    "double_chance": f"Double Chance {side.upper()}",
                }.get(market, f"{market} {side}")
                leg["pick"] = f"{match} — {label}"
                leg["market"] = market
                leg["line"] = line
        return leg

    def audited_main():
        _RUN_OPTIONS.clear()
        _RUN_PRIMARY.clear()
        result = _ORIGINALS["main"]()
        now = datetime.now(timezone.utc)
        try:
            artifact = core.load(core.OUTPUT, {})
            summary = _write_reassessment_artifact(core, now)
            if isinstance(artifact, dict):
                diagnostics = artifact.setdefault("candidate_diagnostics", {})
                # This artifact is served to clients; expose status only, never raw
                # prices, model probabilities, edge/EV, outcome IDs or candidate lists.
                diagnostics["cross_sport_market_reassessment"] = {
                    "status": "ACTIVE_PAPER_REASSESSMENT",
                    "mode": "PAPER_ONLY",
                }
                policy = artifact.setdefault("selection_policy", {})
                policy["cross_sport_market_reassessment"] = {
                    "enabled": True,
                    "mode": "PAPER_ONLY",
                    "all_existing_builder_gates_preserved": True,
                    "real_money_execution": False,
                }
                core.OUTPUT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            print(f"::warning::Could not publish cross-sport market reassessment: {exc}")
        return result

    core.football_candidates = reassessed_football_candidates
    core.tennis_candidates = reassessed_tennis_candidates
    core.virtual_candidates = _virtual_options
    core.market_rows = exact_market_rows
    core.make_leg = audited_make_leg
    core.main = audited_main


def diagnostics() -> dict[str, Any]:
    return copy.deepcopy(_LAST_DIAGNOSTICS)


if __name__ == "__main__":
    raise SystemExit("Import this module through scripts/odds_builder.py; it is not a standalone collector.")
