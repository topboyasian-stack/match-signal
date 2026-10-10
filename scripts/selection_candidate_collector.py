#!/usr/bin/env python3
"""Collect the live model-selection pool for the Upcoming Prediction Desk.

This is deliberately separate from the betting/value gate. A strong model
prediction is useful research data even when current SportyBet price/value or
settled-ticket evidence is not strong enough for the Odds Builder.

The artifact is a compact current-window candidate pool, not a betting slip.
Settled history remains in the canonical prediction/Virtual Lab archives.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UNIFIED = DATA / "unified_upcoming.json"
PREDICTIONS = DATA / "predictions.json"
OUT = DATA / "selection_candidates.json"
STATUS_OUT = DATA / "selection_candidate_status.json"

MAX_TOTAL = 700
MIN_PROBABILITY = 0.55
ACTIVE_VIRTUAL_PRODUCTS = {"efootball_gt", "efootball_adriatic"}
RESEARCH_ONLY_VIRTUAL_PRODUCTS = {"vfootball", "zoom"}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def dt(value):
    if not value:
        return None
    try:
        x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def probability(row):
    for key in ("probability", "confidence"):
        p = num(row.get(key))
        if p is not None:
            return p
    probs = row.get("probabilities") or {}
    pick = str(row.get("pick") or row.get("selection") or "")
    if isinstance(probs, dict):
        p = num(probs.get(pick))
        if p is not None:
            return p
        if str(row.get("market") or "") == "over_under":
            p = num(probs.get(pick.lower()))
            if p is not None:
                return p
    return None


def market_label(row):
    market = str(row.get("market") or "").lower()
    pick = str(row.get("pick") or row.get("selection") or "")
    line = row.get("line")
    if market == "over_under":
        return f"O/U {pick} {line}" if line is not None else f"O/U {pick}"
    if pick in {"p1", "p2", "draw"}:
        p1 = row.get("player_1") or row.get("home") or "Participant 1"
        p2 = row.get("player_2") or row.get("away") or "Participant 2"
        return p1 if pick == "p1" else p2 if pick == "p2" else "Draw"
    return pick or "Model projection"


def candidate_band(p):
    if p >= 0.90:
        return "MODEL_90_PLUS"
    if p >= 0.80:
        return "MODEL_80_PLUS"
    if p >= 0.70:
        return "MODEL_70_PLUS"
    if p >= 0.65:
        return "MODEL_65_PLUS"
    return "MODEL_RESEARCH_55_PLUS"


def group_for(row):
    product = str(row.get("product") or "").lower()
    sport = str(row.get("sport") or "").lower()
    if sport == "football":
        return "football"
    if sport == "tennis":
        return "tennis"
    if product.startswith("efootball"):
        return "efootball"
    if product == "vfootball":
        return "vfootball"
    if sport == "virtual":
        return "virtual"
    return sport or "other"


def totals_sides_for_line(row):
    """Return the exact line's two SportyBet prices; never borrow a neighboring line."""
    line = num(row.get("line"))
    if line is None:
        return None, None

    over = under = None
    quote_market = str(row.get("sportybet_odds_market") or "").lower()
    quote_line = num(row.get("sportybet_odds_line"))
    if quote_market == "total" and quote_line is not None and abs(quote_line - line) < 1e-6:
        direct_over = num(row.get("sportybet_over_odds"))
        direct_under = num(row.get("sportybet_under_odds"))
        if direct_over is not None and direct_over > 1:
            over = direct_over
        if direct_under is not None and direct_under > 1:
            under = direct_under

    totals = row.get("sportybet_total_games_odds")
    if isinstance(totals, list):
        for item in totals:
            if not isinstance(item, dict):
                continue
            item_line = num(item.get("line"))
            if item_line is None or abs(item_line - line) >= 1e-6:
                continue

            item_over = num(item.get("over"))
            item_under = num(item.get("under"))
            if item_over is not None and item_over > 1:
                over = item_over
            if item_under is not None and item_under > 1:
                under = item_under

            side = str(item.get("side") or "").lower()
            odds = num(item.get("odds"))
            if odds is not None and odds > 1:
                if side == "over":
                    over = odds
                elif side == "under":
                    under = odds

    return over, under


def winner_market_sides(row):
    """Copy the three current winner prices used for exact-market de-vigging."""
    raw = row.get("sportybet_winner_odds")
    if not isinstance(raw, dict):
        return None
    result = {}
    for side in ("p1", "draw", "p2"):
        odds = num(raw.get(side))
        if odds is not None and odds > 1:
            result[side] = odds
    return result or None


def compact(row, now):
    start = dt(row.get("start_time"))
    if start is None or start <= now or start > now + timedelta(days=7):
        return None
    p = probability(row)
    if p is None or p < MIN_PROBABILITY or p > 1:
        return None
    p1 = str(row.get("player_1") or row.get("home") or row.get("participant_1") or "").strip()
    p2 = str(row.get("player_2") or row.get("away") or row.get("participant_2") or "").strip()
    if not p1 or not p2 or p1.upper() == "TBD" or p2.upper() == "TBD":
        return None
    product = str(row.get("product") or "").strip() or None
    sport = str(row.get("sport") or "").strip() or ("virtual" if product else None)
    qualified = bool(row.get("betting_qualified") or row.get("qualified_for_builder"))
    status = "BETTING_QUALIFIED_PAPER" if qualified else candidate_band(p)
    sportybet_over_odds, sportybet_under_odds = totals_sides_for_line(row)
    sportybet_winner_odds = winner_market_sides(row)
    candidate_id = "|".join([
        str(row.get("event_id") or ""),
        str(row.get("market") or "winner"),
        "" if row.get("line") is None else str(row.get("line")),
        str(row.get("pick") or row.get("selection") or "")
    ])
    return {
        "candidate_id": candidate_id,
        "event_id": row.get("event_id"),
        "start_time": start.isoformat(),
        "sport": sport,
        "product": product,
        "league": row.get("league") or row.get("competition") or row.get("tournament"),
        "player_1": p1,
        "player_2": p2,
        "market": str(row.get("market") or "winner"),
        "line": row.get("line"),
        "selection": market_label(row),
        "pick": row.get("pick") or row.get("selection"),
        "model_probability": round(p, 6),
        "model_rating": round(p * 100, 2),
        "model_fair_odds": num(row.get("model_fair_odds") or row.get("fair_odds")),
        "bookmaker_odds": num(row.get("bookmaker_odds") or row.get("sportybet_odds") or row.get("book_odds")),
        "sportybet_odds_market": row.get("sportybet_odds_market"),
        "sportybet_odds_line": num(row.get("sportybet_odds_line")),
        "sportybet_odds_side": row.get("sportybet_odds_side"),
        # Preserve both current market sides: the browser independently de-vigs
        # these prices and will fail closed if either side is missing.
        "sportybet_over_odds": sportybet_over_odds,
        "sportybet_under_odds": sportybet_under_odds,
        "sportybet_winner_odds": sportybet_winner_odds,
        "market_odds_timestamp": row.get("market_odds_timestamp") or row.get("odds_timestamp"),
        "model_edge_vs_market": num(row.get("model_edge_vs_market") or row.get("model_edge") or row.get("edge")),
        "walkforward_exact_line_n": num(row.get("walkforward_exact_line_n")),
        "walkforward_exact_line_hit_rate": num(row.get("walkforward_exact_line_hit_rate")),
        "walkforward_exact_line_brier": num(row.get("walkforward_exact_line_brier")),
        "walkforward_exact_line_model_variant": row.get("walkforward_exact_line_model_variant"),
        "walkforward_exact_line_status": row.get("walkforward_exact_line_status"),
        "projection_tier": row.get("projection_tier"),
        "evidence_depth": row.get("evidence_depth"),
        "candidate_status": status,
        "betting_qualified": qualified,
        "candidate_qualification_scope": "upstream_prediction_flags_only" if qualified else "model_estimate_only",
        "qualification_status": row.get("qualification_status"),
        "qualified_for_builder": bool(row.get("qualified_for_builder")),
        "participant_status": row.get("participant_status"),
        "participant_history_rows": row.get("participant_history_rows"),
        "source_engine": row.get("source_engine"),
        "model": row.get("model"),
        "model_version": row.get("model_version"),
        "paper_only": True,
        "candidate_group": group_for(row)
    }


def main():
    now = datetime.now(timezone.utc)
    sources = []
    unified = load(UNIFIED, {})
    if isinstance(unified, dict):
        sources.extend(unified.get("events") or [])
    core = load(PREDICTIONS, [])
    if isinstance(core, list):
        sources.extend(core)

    research_only_virtual_event_ids = {product: set() for product in RESEARCH_ONLY_VIRTUAL_PRODUCTS}
    for row in sources:
        if not isinstance(row, dict):
            continue
        source_product = str(row.get("product") or "").strip().lower()
        if source_product in RESEARCH_ONLY_VIRTUAL_PRODUCTS:
            event_id = str(row.get("event_id") or "")
            if event_id:
                research_only_virtual_event_ids[source_product].add(event_id)

    seen = {}
    for row in sources:
        if not isinstance(row, dict):
            continue
        item = compact(row, now)
        if not item:
            continue
        product = str(item.get("product") or "").strip().lower()
        sport = str(item.get("sport") or "").strip().lower()
        # Research-only virtual products are not part of the active candidate pool.
        # Keep source feed and history intact; this is a publication boundary only.
        if product in RESEARCH_ONLY_VIRTUAL_PRODUCTS:
            continue
        if sport == "virtual" and product not in ACTIVE_VIRTUAL_PRODUCTS:
            continue
        key = item["candidate_id"]
        previous = seen.get(key)
        if previous is None or float(item["model_probability"]) > float(previous["model_probability"]):
            seen[key] = item

    rows = list(seen.values())
    quotas = {"football": 180, "tennis": 140, "efootball": 180, "other": 60}
    selected = []
    for group, quota in quotas.items():
        pool = [x for x in rows if x["candidate_group"] == group]
        pool.sort(key=lambda x: (-float(x["model_probability"]), x["start_time"], str(x["event_id"])))
        selected.extend(pool[:quota])

    selected_ids = {x["candidate_id"] for x in selected}
    remainder = [x for x in rows if x["candidate_id"] not in selected_ids]
    remainder.sort(key=lambda x: (-float(x["model_probability"]), x["start_time"], str(x["event_id"])))
    selected.extend(remainder[:max(0, MAX_TOTAL - len(selected))])
    selected = selected[:MAX_TOTAL]
    selected.sort(key=lambda x: (x["start_time"], -float(x["model_probability"]), str(x["event_id"])))

    qualified = sum(1 for x in selected if x["betting_qualified"])
    high = sum(1 for x in selected if float(x["model_probability"]) >= 0.80)
    OUT.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "generated_at": now.isoformat(),
        "status": "ok",
        "mode": "PAPER_ONLY",
        "input_rows": len(sources),
        "deduplicated_candidates": len(rows),
        "published_candidates": len(selected),
        "strong_model_candidates_80_plus": high,
        "betting_qualified_candidates": qualified,
        "upstream_flagged_betting_qualified_candidates": qualified,
        "qualification_semantics": "Counts candidates carrying an upstream betting_qualified/qualified_for_builder flag; this is not the selective prediction gate count and does not override current exact-line price, value, freshness, results, or Odds Builder gates.",
        "selection_gate_artifact": "data/selection_gate_selected.json",
        "minimum_model_probability": MIN_PROBABILITY,
        "max_candidates": MAX_TOTAL,
        "artifact": "data/selection_candidates.json",
        "purpose": "model-first current candidate pool; independent from Odds Builder value/results qualification",
        "virtual_scope_policy": {
            "active_products": sorted(ACTIVE_VIRTUAL_PRODUCTS),
            "research_only_products": sorted(RESEARCH_ONLY_VIRTUAL_PRODUCTS),
            "research_only_source_events": {product: len(event_ids) for product, event_ids in research_only_virtual_event_ids.items()},
            "research_only_candidates_published": 0,
            "preservation": "VFootball/Zoom remain in source feeds, Virtual Lab observation and settlement collection, and historical archives; no old records are deleted."
        }
    }
    STATUS_OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
