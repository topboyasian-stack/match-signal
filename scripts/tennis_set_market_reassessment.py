"""Exact-current-quote adapter for tennis Player to Win At Least One Set.

The shared set-outcome model is evaluated independently from totals. This
adapter only emits a ticket candidate after its own chronological promotion
gate passes and an exact current SportyBet Yes/No market can be mapped to one
player. Unsupported/ambiguous market shapes remain diagnostics, never guesses.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DATA = Path(__file__).resolve().parents[1] / "data"
MAX_QUOTE_AGE_SECONDS = 900
MIN_PRIOR_MATCHES = 30
_DIAGNOSTICS: dict[str, Any] = {}
_INSTALLED = False


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 and result < float("inf") else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _yes_no(outcomes: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(outcomes, list):
        return None, None
    yes_names = {"yes", "true", "will win", "to win a set", "wins a set", "player wins a set"}
    no_names = {"no", "false", "will not win", "will not win a set", "does not win a set"}
    yes = no = None
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        if outcome.get("isActive") is False:
            continue
        name = _norm(outcome.get("name") or outcome.get("desc") or outcome.get("title"))
        odds = _number(outcome.get("book_odds") or outcome.get("odds"))
        oid = str(outcome.get("id") or "").strip()
        if odds is None or not oid:
            continue
        if name in {_norm(x) for x in yes_names}:
            yes = {"id": oid, "name": str(outcome.get("name") or "Yes"), "odds": odds}
        elif name in {_norm(x) for x in no_names}:
            no = {"id": oid, "name": str(outcome.get("name") or "No"), "odds": odds}
    return yes, no


def _resolve_player(market: dict[str, Any], snapshot: dict[str, Any], prediction: dict[str, Any]) -> str | None:
    """Resolve the proposition subject from exact player names or explicit side metadata."""
    p1 = _norm(prediction.get("player_1"))
    p2 = _norm(prediction.get("player_2"))
    label = " ".join((
        str(market.get("name") or ""),
        str(market.get("specifier") or ""),
    ))
    normalized = _norm(label)
    if p1 and p1 in normalized:
        return "p1"
    if p2 and p2 in normalized:
        return "p2"

    # SportyBet sometimes scopes a generic Yes/No market by an explicit
    # participant/home/away specifier rather than repeating the player's name.
    spec = str(market.get("specifier") or "").lower()
    side_match = re.search(
        r"(?:player|participant|team|competitor|side)\s*[:=_-]\s*(home|away|p?1|p?2|player\s*1|player\s*2)",
        spec,
    )
    token_text = " " + normalized + " "
    token_match = re.search(
        r"\b(home|away|p1|p2|player\s*1|player\s*2|home player|away player)\b",
        token_text,
    )
    side = side_match.group(1) if side_match else (token_match.group(1) if token_match else "")
    side = re.sub(r"\s+", "", side)
    if side in {"home", "away"}:
        method = str((snapshot.get("match") or {}).get("method") or "").lower()
        if method not in {"direct", "reverse"}:
            return None
        home_is_p1 = method == "direct"
        if side == "home":
            return "p1" if home_is_p1 else "p2"
        return "p2" if home_is_p1 else "p1"
    if side in {"1", "p1", "player1"}:
        return "p1"
    if side in {"2", "p2", "player2"}:
        return "p2"
    return None


def _is_player_set_market(market: dict[str, Any]) -> bool:
    label = " ".join((
        str(market.get("name") or ""),
        str(market.get("specifier") or ""),
    )).lower()
    if "first set" in label or "set betting" in label or "set winner" in label:
        return False
    return bool(re.search(r"\bset\b", label) and re.search(r"\bwin(?:s|ner)?\b", label))


def _fresh_snapshot(snapshot: dict[str, Any], now: datetime) -> tuple[bool, str | None]:
    if snapshot.get("available") is not True:
        return False, "sportybet_snapshot_unavailable"
    event_id = str(snapshot.get("event_id") or "").strip()
    if not event_id:
        return False, "sportybet_event_id_missing"
    stamp = _parse_dt(snapshot.get("fetched_at"))
    if stamp is None:
        return False, "quote_timestamp_missing"
    age = (now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
    if age < -30:
        return False, "quote_timestamp_in_future"
    if age > MAX_QUOTE_AGE_SECONDS:
        return False, "quote_older_than_15_minutes"
    return True, None


def _market_candidates(
    prediction: dict[str, Any],
    set_prediction: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    snapshot = prediction.get("sportybet_market") or {}
    fresh, reason = _fresh_snapshot(snapshot, now)
    counts = {"markets_seen": 0, "set_markets_seen": 0, "yes_no_markets": 0, "candidates": 0}
    if not fresh:
        return [], {**counts, "rejected": 1, "last_rejection": reason}
    markets = snapshot.get("markets") or []
    if not isinstance(markets, list):
        return [], {**counts, "rejected": 1, "last_rejection": "market_catalogue_missing"}

    emitted = []
    seen = set()
    for market in markets:
        if not isinstance(market, dict):
            continue
        counts["markets_seen"] += 1
        if not _is_player_set_market(market):
            continue
        counts["set_markets_seen"] += 1
        player_side = _resolve_player(market, snapshot, prediction)
        if player_side not in {"p1", "p2"}:
            continue
        yes, no = _yes_no(market.get("outcomes"))
        if not yes or not no:
            continue
        counts["yes_no_markets"] += 1
        market_id = str(market.get("id") or "").strip()
        if not market_id:
            continue
        specifier = str(market.get("specifier") or "")
        unique = (market_id, specifier, player_side)
        if unique in seen:
            continue
        seen.add(unique)

        probability = (set_prediction.get("player_to_win_at_least_one_set") or {}).get(player_side)
        try:
            probability = float(probability)
        except (TypeError, ValueError):
            continue
        if not 0.0 < probability < 1.0:
            continue
        player_name = prediction.get("player_1" if player_side == "p1" else "player_2")
        candidate = dict(prediction)
        candidate.update({
            "builder_market": "player_to_win_set",
            "builder_pick": "yes",
            "builder_probability": probability,
            "probability": probability,
            "line": None,
            "market_source": "SportyBet NG",
            "odds_timestamp": snapshot.get("fetched_at"),
            "market_odds_timestamp": snapshot.get("fetched_at"),
            "sportybet_event_id": snapshot.get("event_id"),
            "sportybet_market_id": market_id,
            "sportybet_specifier": specifier,
            "sportybet_outcome_id": yes["id"],
            "sportybet_outcome_name": yes["name"],
            "tennis_set_market_quotes": [
                {"side": "yes", "odds": yes["odds"], "outcome_id": yes["id"], "outcome_name": yes["name"]},
                {"side": "no", "odds": no["odds"], "outcome_id": no["id"], "outcome_name": no["name"]},
            ],
            "tennis_set_market": {
                "status": "QUALIFIED_PAPER_RESEARCH",
                "market": "Player to Win At Least One Set",
                "player_side": player_side,
                "player_name": player_name,
                "probability": round(probability, 6),
                "opposite_probability": round(1.0 - probability, 6),
                "market_id": market_id,
                "specifier": specifier,
                "yes_outcome_id": yes["id"],
                "no_outcome_id": no["id"],
                "quote_timestamp": snapshot.get("fetched_at"),
                "model_audit": set_prediction,
                "paper_only": True,
                "real_money_execution": False,
            },
            "model": "Tennis set-outcome simulation v1 + prior-only calibration",
        })
        emitted.append(candidate)
        counts["candidates"] += 1
    return emitted, counts


def build_set_market_candidates(
    core: Any,
    now: datetime,
    *,
    prediction_rows: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    report: dict[str, Any] | None = None,
    baseline_fn: Callable | None = None,
) -> list[dict[str, Any]]:
    """Return only exact, fresh, independently-qualified ATP set-market candidates."""
    global _DIAGNOSTICS
    raw = prediction_rows if isinstance(prediction_rows, list) else core.load(core.PREDICTIONS, [])
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    settled = history if isinstance(history, list) else core.load(DATA / "tennis_prediction_archive.json", [])
    if not isinstance(settled, list):
        settled = []
    from tennis_set_market_model import build_report, predict_target

    validation = report if isinstance(report, dict) else build_report(settled)
    baseline = baseline_fn(now) if baseline_fn else []
    out = [dict(row) for row in baseline if isinstance(row, dict)]
    diag: dict[str, Any] = {
        "status": "RESEARCH_ONLY_HOLD",
        "mode": "PAPER_ONLY",
        "history_rows": len(settled),
        "validation": validation.get("validation") or {},
        "promotion_gate": validation.get("promotion_gate") or {},
        "fixtures_seen": 0,
        "fixtures_with_model": 0,
        "fixtures_with_fresh_snapshot": 0,
        "set_markets_seen": 0,
        "yes_no_markets": 0,
        "candidates_emitted": 0,
        "rejected": {},
        "model": "match-win-to-set-score simulation + strictly prior ATP calibration",
        "market_scope": "SportyBet exact-current Player to Win At Least One Set Yes/No propositions only",
        "paper_only": True,
        "real_money_execution": False,
    }
    gate_passed = (validation.get("promotion_gate") or {}).get("passed") is True
    if not gate_passed:
        diag["rejected"]["independent_set_market_validation_not_passed"] = 1
        _DIAGNOSTICS = diag
        return out

    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for target in rows:
        if target.get("sport") != "tennis" or str(target.get("league") or target.get("tour") or "").upper() != "ATP":
            continue
        if not core.within_builder_horizon(target, now):
            continue
        if str(target.get("prediction_status") or "") == "watch_projection" or str(target.get("qualification_status") or "") == "TENNIS_FORWARD_WATCH_NOT_QUALIFIED":
            continue
        diag["fixtures_seen"] += 1
        set_prediction = predict_target(target, settled, validation)
        if set_prediction.get("promotion_gate_passed") is not True or int(set_prediction.get("prior_matches") or 0) < MIN_PRIOR_MATCHES:
            diag["rejected"]["prior_history_or_fixture_gate_not_passed"] = diag["rejected"].get("prior_history_or_fixture_gate_not_passed", 0) + 1
            continue
        diag["fixtures_with_model"] += 1
        snapshot = target.get("sportybet_market") or {}
        fresh, reason = _fresh_snapshot(snapshot, now_utc)
        if not fresh:
            diag["rejected"][reason or "snapshot_not_fresh"] = diag["rejected"].get(reason or "snapshot_not_fresh", 0) + 1
            continue
        diag["fixtures_with_fresh_snapshot"] += 1
        candidates, counts = _market_candidates(target, set_prediction, now_utc)
        diag["set_markets_seen"] += counts.get("set_markets_seen", 0)
        diag["yes_no_markets"] += counts.get("yes_no_markets", 0)
        if not candidates:
            key = str(counts.get("last_rejection") or "no_exact_player_set_yes_no_market")
            diag["rejected"][key] = diag["rejected"].get(key, 0) + 1
            continue
        out.extend(candidates)

    diag["candidates_emitted"] = len([
        row for row in out
        if row.get("sport") == "tennis" and row.get("builder_market") == "player_to_win_set"
    ])
    diag["status"] = "QUALIFIED_PAPER_RESEARCH" if diag["candidates_emitted"] else "RESEARCH_ONLY_HOLD"
    _DIAGNOSTICS = diag
    return out


def install(core: Any) -> None:
    """Add the set-market lane without changing the existing winner/totals models."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_candidates = core.tennis_candidates
    original_market_rows = core.market_rows
    original_make_leg = core.make_leg
    original_main = core.main

    def expanded_candidates(now):
        active = getattr(core, "ACTIVE_PREDICTION_ROWS", None)
        raw = active if isinstance(active, list) else core.load(core.PREDICTIONS, [])
        history = core.load(DATA / "tennis_prediction_archive.json", [])
        return build_set_market_candidates(
            core,
            now,
            prediction_rows=raw if isinstance(raw, list) else [],
            history=history if isinstance(history, list) else [],
            baseline_fn=original_candidates,
        )

    def exact_set_market_rows(row):
        if row.get("sport") == "tennis" and row.get("builder_market") == "player_to_win_set":
            return [
                {"side": item.get("side"), "odds": item.get("odds")}
                for item in row.get("tennis_set_market_quotes") or []
                if isinstance(item, dict)
            ]
        return original_market_rows(row)

    def audited_make_leg(row):
        result = original_make_leg(row)
        if not isinstance(result, dict) or row.get("builder_market") != "player_to_win_set":
            return result
        detail = row.get("tennis_set_market") or {}
        player = detail.get("player_name") or "Player"
        result.update({
            "market": "player_to_win_set",
            "pick": f"{row.get('player_1')} vs {row.get('player_2')} — {player} to win at least one set",
            "line": None,
            "tennis_set_market": copy.deepcopy(detail),
            "sportybet_market_id": row.get("sportybet_market_id"),
            "sportybet_specifier": row.get("sportybet_specifier"),
            "sportybet_outcome_id": row.get("sportybet_outcome_id"),
            "sportybet_outcome_name": row.get("sportybet_outcome_name"),
            "sportybet_event_id": row.get("sportybet_event_id"),
        })
        return result

    def audited_main():
        result = original_main()
        try:
            artifact = core.load(core.OUTPUT, {})
            if isinstance(artifact, dict):
                diagnostics = artifact.setdefault("candidate_diagnostics", {})
                diagnostics["tennis_set_market_reassessment"] = copy.deepcopy(_DIAGNOSTICS)
                policy = artifact.setdefault("selection_policy", {})
                policy["tennis_player_to_win_set"] = {
                    "enabled": True,
                    "market_scope": "exact current SportyBet Yes/No proposition per named player",
                    "independent_walk_forward_gate_required": True,
                    "minimum_prior_atp_matches": MIN_PRIOR_MATCHES,
                    "quote_freshness_seconds": MAX_QUOTE_AGE_SECONDS,
                    "existing_builder_value_freshness_uncertainty_and_ticket_gates_unchanged": True,
                    "no_market_or_price_substitution": True,
                    "paper_only": True,
                    "real_money_execution": False,
                }
                core.OUTPUT.write_text(
                    __import__("json").dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            print(f"::warning::Could not attach tennis set-market diagnostics: {exc}")
        return result

    core.tennis_candidates = expanded_candidates
    core.market_rows = exact_set_market_rows
    core.make_leg = audited_make_leg
    core.main = audited_main


def diagnostics() -> dict[str, Any]:
    return copy.deepcopy(_DIAGNOSTICS)
