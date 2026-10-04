"""Shadow research for Match Signal's directional-anchor -> O/U line-ladder strategy.

The current Upcoming Desk is a first-class shadow anchor source; this does not
change qualification, Builder eligibility, or booking behavior.

This module is deliberately outside the Odds Builder qualification path.

It:
- reads the existing Builder's paper-only virtual O/U anchors,
- reads the current SportyBet virtual O/U ladder,
- measures historical exact-line hit/ROI evidence from the append-only Virtual Lab,
- estimates safer-rung probability without copying the anchor probability,
- reports chronological discovery/holdout evidence,
- never changes batch eligibility, thresholds, or booking behavior.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "virtual_lab_history.json"
BUILDER = DATA / "odds_builder.json"
LIVE = DATA / "virtual_lab_live.json"
DESK = DATA / "unified_upcoming.json"
OUTPUT = DATA / "line_ladder_research.json"

LINE_LADDER_RESEARCH_VERSION = "1.0.0-shadow"
MODE = "PAPER_RESEARCH_ONLY"
MIN_EVIDENCE = 50
MIN_HOLDOUT = 30
DISCOVERY_FRACTION = 0.70
ANCHOR_MIN_PROB = 0.80
MAX_SAFE_RUNG_DEPTH = 3
ANCHOR_TRANSFER_WEIGHT = 0.75
SUPPORTED_PRODUCTS = {"efootball_gt", "efootball_adriatic", "vfootball"}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError):
        return float("inf")


def clamp(value, low=0.0005, high=0.9995):
    return max(low, min(high, float(value)))


def side_from_selection(value):
    text = str(value or "").strip().lower()
    if "over" in text or text.startswith("o"):
        return "over"
    if "under" in text or text.startswith("u"):
        return "under"
    return None


def line_from_row(row):
    line = number(row.get("line"))
    if line is not None:
        return line
    text = str(
        row.get("builder_pick")
        or row.get("pick")
        or row.get("selection")
        or ""
    ).lower()
    import re

    match = re.search(r"(?:over|under|o|u)\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(match.group(1)) if match else None


def clean_line(value):
    return int(value) if float(value).is_integer() else float(value)


def outcome_map(market):
    out = {}
    for outcome in market.get("outcomes") or []:
        name = str(outcome.get("name") or "").lower()
        odds = number(outcome.get("odds"))
        if odds is None or odds <= 0:
            continue
        if name.startswith("over"):
            out["over"] = odds
        elif name.startswith("under"):
            out["under"] = odds
    return out


def normalize_history(history):
    """Deduplicate to one earliest captured observation per event/line/side."""
    chosen = {}
    for row in history if isinstance(history, list) else []:
        if not isinstance(row, dict):
            continue
        product = str(row.get("product") or "")
        if product not in SUPPORTED_PRODUCTS:
            continue
        if str(row.get("market") or "").lower() != "ou":
            continue
        event_id = str(row.get("event_id") or "")
        line = line_from_row(row)
        side = side_from_selection(row.get("selection") or row.get("selection_name"))
        odds = number(row.get("odds"))
        if not event_id or line is None or side is None or odds is None:
            continue
        win = row.get("win")
        if not isinstance(win, bool):
            continue

        rec = {
            "product": product,
            "competition": str(row.get("competition") or "Unknown"),
            "event_id": event_id,
            "line": float(line),
            "side": side,
            "odds": float(odds),
            "win": bool(win),
            "model_prob": number(row.get("model_prob")),
            "timestamp": str(row.get("timestamp") or row.get("captured_at") or ""),
        }
        key = (product, event_id, float(line), side)
        old = chosen.get(key)
        if old is None or timestamp(rec["timestamp"]) < timestamp(old["timestamp"]):
            chosen[key] = rec
    return list(chosen.values())


def stats(rows):
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "wins": 0,
            "hit_rate": None,
            "avg_odds": None,
            "roi": None,
        }
    wins = sum(1 for row in rows if row["win"])
    roi = sum(
        (row["odds"] - 1.0) if row["win"] else -1.0
        for row in rows
    ) / n
    return {
        "n": n,
        "wins": wins,
        "hit_rate": wins / n,
        "avg_odds": sum(row["odds"] for row in rows) / n,
        "roi": roi,
    }


def build_indexes(observations):
    exact = defaultdict(list)
    product_side_line = defaultdict(list)
    product_comp_side_line = defaultdict(list)
    by_event = {}

    for row in observations:
        product = row["product"]
        comp = row["competition"]
        line = row["line"]
        side = row["side"]
        exact[(product, comp, line, side)].append(row)
        product_side_line[(product, line, side)].append(row)
        product_comp_side_line[(product, comp, line, side)].append(row)
        by_event[(product, row["event_id"], line, side)] = row

    return exact, product_side_line, product_comp_side_line, by_event


def evidence_for(
    product,
    competition,
    line,
    side,
    exact,
    product_side_line,
    minimum=MIN_EVIDENCE,
):
    scoped = list(exact.get((product, competition, line, side), []))
    if len(scoped) >= minimum:
        return scoped, "product_competition_line"
    fallback = list(product_side_line.get((product, line, side), []))
    return fallback, "product_line"


def chronological_pair_validation(observations):
    """Validate safer-rung hit/ROI chronologically, without user-ticket labels."""
    by_event_side = defaultdict(list)
    for row in observations:
        by_event_side[(row["product"], row["event_id"], row["side"])].append(row)

    pairs = defaultdict(list)
    for anchor in observations:
        event_rows = by_event_side.get(
            (anchor["product"], anchor["event_id"], anchor["side"]), []
        )
        if anchor["side"] == "over":
            target = sorted(
                {row["line"] for row in event_rows if row["line"] < anchor["line"]},
                reverse=True,
            )[:MAX_SAFE_RUNG_DEPTH]
        else:
            target = sorted(
                {row["line"] for row in event_rows if row["line"] > anchor["line"]}
            )[:MAX_SAFE_RUNG_DEPTH]

        for safe_line in target:
            safe = next(
                (row for row in event_rows if row["line"] == safe_line),
                None,
            )
            if safe is None:
                continue
            key = (
                anchor["product"],
                anchor["competition"],
                anchor["line"],
                anchor["side"],
                safe_line,
            )
            pairs[key].append((anchor, safe))

    report = []
    for key, rows in pairs.items():
        rows = sorted(rows, key=lambda pair: timestamp(pair[0]["timestamp"]))
        if len(rows) < MIN_EVIDENCE:
            continue
        cut = max(1, int(len(rows) * DISCOVERY_FRACTION))
        discovery = rows[:cut]
        holdout = rows[cut:]
        if len(holdout) < MIN_HOLDOUT:
            continue

        anchor_discovery = stats([x[0] for x in discovery])
        safe_discovery = stats([x[1] for x in discovery])
        anchor_holdout = stats([x[0] for x in holdout])
        safe_holdout = stats([x[1] for x in holdout])

        report.append(
            {
                "product": key[0],
                "competition": key[1],
                "anchor_line": clean_line(key[2]),
                "side": key[3],
                "safe_line": clean_line(key[4]),
                "discovery": {
                    "anchor": anchor_discovery,
                    "safe": safe_discovery,
                },
                "holdout": {
                    "anchor": anchor_holdout,
                    "safe": safe_holdout,
                    "safe_hit_rate_delta": (
                        safe_holdout["hit_rate"] - anchor_holdout["hit_rate"]
                    ),
                    "safe_roi_delta": (
                        safe_holdout["roi"] - anchor_holdout["roi"]
                    ),
                },
                "evidence_gate": {
                    "discovery_n": len(discovery),
                    "holdout_n": len(holdout),
                    "minimum_discovery_n": MIN_EVIDENCE,
                    "minimum_holdout_n": MIN_HOLDOUT,
                    "hit_rate_pass": (
                        safe_holdout["hit_rate"] >= anchor_holdout["hit_rate"]
                    ),
                    "value_pass": safe_holdout["roi"] >= 0.0,
                },
            }
        )

    report.sort(
        key=lambda row: (
            row["holdout"]["safe"]["n"],
            row["holdout"]["safe"].get("hit_rate") or 0,
        ),
        reverse=True,
    )
    return report

def current_anchors(builder, desk=None):
    rows = []
    desk_events = (desk or {}).get("events") or [] if isinstance(desk, dict) else []
    sources = [
        ("best_available_legs", builder.get("best_available_legs")),
        ("qualified_legs", builder.get("qualified_legs")),
        ("desk_directional_anchors", [
            row
            for row in desk_events
            if isinstance(row, dict)
            and str(row.get("sport") or "") == "virtual"
            and str(row.get("market") or "") == "over_under"
            and number(row.get("probability")) is not None
            and number(row.get("probability")) >= ANCHOR_MIN_PROB
        ]),
        ("batches", [
            leg
            for batch in builder.get("batches") or []
            for leg in batch.get("legs") or []
        ]),
    ]
    seen = set()
    for source, values in sources:
        for row in values or []:
            if not isinstance(row, dict):
                continue
            product = str(row.get("product") or "")
            if product not in SUPPORTED_PRODUCTS:
                continue
            probability = number(row.get("model_probability"))
            if probability is None:
                probability = number(row.get("probability"))
            if probability is None or probability < ANCHOR_MIN_PROB:
                continue
            line = line_from_row(row)
            side = side_from_selection(
                row.get("builder_pick")
                or row.get("pick")
                or row.get("selection")
                or ""
            )
            event_id = str(row.get("event_id") or "")
            if line is None or side is None or not event_id:
                continue
            key = (product, event_id, float(line), side)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "source": source,
                    "product": product,
                    "competition": str(row.get("competition") or "Unknown"),
                    "event_id": event_id,
                    "match": row.get("match") or row.get("fixture") or "",
                    "anchor_line": float(line),
                    "anchor_side": side,
                    "anchor_model_probability": float(probability),
                    "anchor_current_odds": number(
                        row.get("bookmaker_odds")
                        or row.get("sportybet_odds")
                        or row.get("market_odds")
                    ),
                    "start_time": row.get("start_time"),
                    "desk_model_probability": number(row.get("probability")),
                }
            )
    return rows


def live_ladder(live):
    return {
        str(event.get("event_id")): event
        for event in (live.get("events") or [])
        if isinstance(event, dict) and event.get("event_id")
    }


def available_ladder(event, anchor_side, anchor_line):
    markets = []
    for market in event.get("markets") or []:
        if number(market.get("line")) is None:
            continue
        name = str(market.get("name") or "").lower()
        if str(market.get("id") or "") != "18" and "over/under" not in name:
            continue
        outcomes = outcome_map(market)
        if not outcomes:
            continue
        line = float(market["line"])
        if anchor_side == "over" and line < anchor_line:
            markets.append((line, outcomes))
        elif anchor_side == "under" and line > anchor_line:
            markets.append((line, outcomes))
    if anchor_side == "over":
        markets.sort(key=lambda x: x[0], reverse=True)
    else:
        markets.sort(key=lambda x: x[0])
    return markets[:MAX_SAFE_RUNG_DEPTH]


def price_view(outcomes, side, probability):
    odds = outcomes.get(side)
    if odds is None or odds <= 1:
        return {
            "odds": odds,
            "de_vig_probability": None,
            "fair_odds": 1 / probability if probability else None,
            "expected_roi": None,
            "edge_vs_de_vig": None,
        }
    other = outcomes.get("under" if side == "over" else "over")
    de_vig = None
    if other is not None and other > 1:
        a = 1 / odds
        b = 1 / other
        total = a + b
        if total > 0:
            de_vig = a / total
    return {
        "odds": odds,
        "de_vig_probability": de_vig,
        "fair_odds": 1 / probability if probability else None,
        "expected_roi": probability * odds - 1,
        "edge_vs_de_vig": (
            probability - de_vig if de_vig is not None else None
        ),
    }


def finite(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def main():
    history = load_json(HISTORY, [])
    builder = load_json(BUILDER, {})
    live = load_json(LIVE, {})
    desk = load_json(DESK, {})

    observations = normalize_history(history)
    exact, product_side_line, product_comp_side_line, _ = build_indexes(
        observations
    )
    validation = chronological_pair_validation(observations)

    live_by_id = live_ladder(live)
    ladders = []
    for anchor in current_anchors(builder, desk):
        event = live_by_id.get(anchor["event_id"])
        if not event:
            continue

        anchor_rows, anchor_scope = evidence_for(
            anchor["product"],
            anchor["competition"],
            anchor["anchor_line"],
            anchor["anchor_side"],
            exact,
            product_side_line,
        )
        anchor_hist = stats(anchor_rows)

        safe_options = []
        for safe_line, outcomes in available_ladder(
            event, anchor["anchor_side"], anchor["anchor_line"]
        ):
            safe_rows, safe_scope = evidence_for(
                anchor["product"],
                anchor["competition"],
                safe_line,
                anchor["anchor_side"],
                exact,
                product_side_line,
            )
            safe_hist = stats(safe_rows)

            if safe_hist["n"] < MIN_EVIDENCE:
                estimated_probability = safe_hist["hit_rate"]
                method = "historical_safe_line_rate"
            elif (
                anchor_hist["n"] >= MIN_EVIDENCE
                and anchor_hist["hit_rate"] is not None
            ):
                # Transfer only part of the gap between the current anchor
                # probability and historical anchor calibration. This prevents
                # the safer rung from inheriting the anchor probability verbatim.
                gap = anchor["anchor_model_probability"] - anchor_hist["hit_rate"]
                estimated_probability = clamp(
                    safe_hist["hit_rate"] + ANCHOR_TRANSFER_WEIGHT * gap
                )
                method = "historical_safe_line_rate_plus_shrunk_anchor_gap"
            else:
                estimated_probability = safe_hist["hit_rate"]
                method = "historical_safe_line_rate"

            current_price = price_view(
                outcomes,
                anchor["anchor_side"],
                estimated_probability,
            )
            safe_options.append(
                {
                    "line": clean_line(safe_line),
                    "side": anchor["anchor_side"],
                    "sportybet": current_price,
                    "estimated_probability": finite(estimated_probability, 6),
                    "historical_evidence": {
                        "scope": safe_scope,
                        **{
                            k: finite(v, 6) if isinstance(v, float) else v
                            for k, v in safe_hist.items()
                        },
                    },
                    "estimation_method": method,
                    "shadow_value_eligible": bool(
                        safe_hist["n"] >= MIN_EVIDENCE
                        and current_price["expected_roi"] is not None
                        and current_price["expected_roi"] >= 0.02
                        and (
                            current_price["edge_vs_de_vig"] is None
                            or current_price["edge_vs_de_vig"] >= 0.025
                        )
                    ),
                }
            )

        ladders.append(
            {
                **anchor,
                "live_snapshot_at": live.get("updated_at"),
                "anchor_historical_evidence": {
                    "scope": anchor_scope,
                    **{
                        k: finite(v, 6) if isinstance(v, float) else v
                        for k, v in anchor_hist.items()
                    },
                },
                "safe_rungs": safe_options,
            }
        )

    value_candidates = [
        {
            "event_id": row["event_id"],
            "match": row["match"],
            "product": row["product"],
            "anchor_line": row["anchor_line"],
            "anchor_side": row["anchor_side"],
            "safe_line": option["line"],
            "estimated_probability": option["estimated_probability"],
            "odds": option["sportybet"]["odds"],
            "expected_roi": option["sportybet"]["expected_roi"],
            "edge_vs_de_vig": option["sportybet"]["edge_vs_de_vig"],
        }
        for row in ladders
        for option in row["safe_rungs"]
        if option["shadow_value_eligible"]
    ]
    value_candidates.sort(
        key=lambda x: (
            x["expected_roi"] if x["expected_roi"] is not None else -999
        ),
        reverse=True,
    )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": LINE_LADDER_RESEARCH_VERSION,
        "mode": MODE,
        "status": "SHADOW_RESEARCH_ONLY",
        "scope": "virtual_ou_directional_anchor_to_live_ladder",
        "paper_only": True,
        "builder_modified": False,
        "booking_modified": False,
        "training_label_policy": "historical_sportybet_settlements_only; user_ticket_evidence_excluded",
        "inputs": {
            "history_rows": len(history) if isinstance(history, list) else 0,
            "normalized_observations": len(observations),
            "builder_generated_at": builder.get("generated_at"),
            "live_updated_at": live.get("updated_at"),
            "live_status": live.get("status"),
            "live_events": live.get("events_count"),
            "desk_events": len(desk.get("events") or []) if isinstance(desk, dict) else 0,
        },
        "policy": {
            "anchor_min_probability": ANCHOR_MIN_PROB,
            "minimum_historical_evidence": MIN_EVIDENCE,
            "minimum_holdout_evidence": MIN_HOLDOUT,
            "discovery_fraction": DISCOVERY_FRACTION,
            "max_safe_rung_depth": MAX_SAFE_RUNG_DEPTH,
            "anchor_transfer_weight": ANCHOR_TRANSFER_WEIGHT,
            "probability_copying": False,
        },
        "chronological_validation": validation[:200],
        "current_anchor_count": len(ladders),
        "current_anchor_sources": sorted(set(str(x.get("source") or "") for x in ladders)),
        "current_anchors": ladders,
        "shadow_value_candidates": value_candidates[:50],
        "promotion_gate": {
            "status": "HOLD",
            "reason": (
                "Shadow layer only. It must accumulate forward observations and "
                "prove safe-rung probability calibration and price-conditioned value "
                "before any Builder integration."
            ),
            "minimum_future_trials_before_promotion_review": 50,
            "requires_positive_holdout_roi": True,
            "requires_untouched_chronological_holdout": True,
            "requires_no_change_to_existing_builder_gates": True,
        },
    }

    OUTPUT.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": output["status"],
                "normalized_observations": len(observations),
                "current_anchors": len(ladders),
                "shadow_value_candidates": len(value_candidates),
                "validated_pairs": len(validation),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
