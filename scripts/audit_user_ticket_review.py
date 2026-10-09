"""Validate and summarize private user-selected O/U evidence without changing it.

This audit keeps a user's actual selections separate from Match Signal's desk
predictions and from model-training history. By default it emits aggregate counts
only; it never writes the input file or returns fixture/ticket identifiers.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_TICKET_OUTCOMES = {"PENDING", "WON", "LOST", "VOID"}
VALID_PICKS = {"over", "under"}
VALID_MARKET = "total_goals_over_under"


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def parse_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _validate_selection(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return
    if value.get("market") != VALID_MARKET:
        errors.append(f"{where}.market must be {VALID_MARKET}")
    if value.get("pick") not in VALID_PICKS:
        errors.append(f"{where}.pick must be over or under")
    if not finite_number(value.get("line")) or float(value.get("line", -1)) < 0:
        errors.append(f"{where}.line must be a finite non-negative number")
    if not finite_number(value.get("odds")) or float(value.get("odds", 0)) <= 1:
        errors.append(f"{where}.odds must be a finite number greater than 1")


def validate_document(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["root must be an object"]
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if document.get("record_type") != "private_user_ticket_review":
        errors.append("record_type must be private_user_ticket_review")
    if document.get("mode") != "PRIVATE_USER_EVIDENCE":
        errors.append("mode must be PRIVATE_USER_EVIDENCE")
    if not parse_datetime(document.get("updated_at")):
        errors.append("updated_at must be an ISO date-time")
    tickets = document.get("tickets")
    if not isinstance(tickets, list):
        return errors + ["tickets must be an array"]

    ticket_refs: set[str] = set()
    for ti, ticket in enumerate(tickets):
        where = f"tickets[{ti}]"
        if not isinstance(ticket, dict):
            errors.append(f"{where} must be an object")
            continue
        ref = ticket.get("ticket_ref")
        if not isinstance(ref, str) or not ref or len(ref) > 80 or not all(c.isalnum() or c in "_-" for c in ref):
            errors.append(f"{where}.ticket_ref must be a non-identifying internal reference")
        elif ref in ticket_refs:
            errors.append(f"{where} has a duplicate ticket_ref")
        else:
            ticket_refs.add(ref)
        if not parse_datetime(ticket.get("captured_at")):
            errors.append(f"{where}.captured_at must be an ISO date-time")
        if ticket.get("reported_ticket_outcome") not in VALID_TICKET_OUTCOMES:
            errors.append(f"{where}.reported_ticket_outcome is invalid")
        for key, minimum, exclusive in (("stake", 0, False), ("total_return", 0, False), ("total_odds", 1, True)):
            if key in ticket and ticket[key] is not None:
                value = ticket[key]
                if not finite_number(value) or (float(value) <= minimum if exclusive else float(value) < minimum):
                    errors.append(f"{where}.{key} is invalid")
        legs = ticket.get("legs")
        if not isinstance(legs, list) or not legs:
            errors.append(f"{where}.legs must be a non-empty array")
            continue
        leg_refs: set[str] = set()
        for li, leg in enumerate(legs):
            lw = f"{where}.legs[{li}]"
            if not isinstance(leg, dict):
                errors.append(f"{lw} must be an object")
                continue
            leg_ref = leg.get("leg_ref")
            if not isinstance(leg_ref, str) or not leg_ref or len(leg_ref) > 80:
                errors.append(f"{lw}.leg_ref is required")
            elif leg_ref in leg_refs:
                errors.append(f"duplicate leg_ref in {where}: {leg_ref}")
            else:
                leg_refs.add(leg_ref)
            if not isinstance(leg.get("product"), str) or not leg["product"].strip():
                errors.append(f"{lw}.product is required")
            if not isinstance(leg.get("match"), str) or not leg["match"].strip():
                errors.append(f"{lw}.match is required")
            _validate_selection(leg.get("actual_selection"), f"{lw}.actual_selection", errors)
            if "desk_snapshot" in leg and leg["desk_snapshot"] is not None:
                desk = leg["desk_snapshot"]
                if not isinstance(desk, dict):
                    errors.append(f"{lw}.desk_snapshot must be an object")
                else:
                    _validate_selection(
                        {
                            "market": desk.get("market"),
                            "pick": desk.get("pick"),
                            "line": desk.get("line"),
                            "odds": desk.get("odds", 2.0),
                        },
                        f"{lw}.desk_snapshot",
                        errors,
                    )
                    probability = desk.get("model_probability")
                    if probability is not None and (
                        not finite_number(probability) or not 0 <= float(probability) <= 1
                    ):
                        errors.append(f"{lw}.desk_snapshot.model_probability must be between 0 and 1")
                    if not parse_datetime(desk.get("captured_at")):
                        errors.append(f"{lw}.desk_snapshot.captured_at must be an ISO date-time")
            score = leg.get("final_score")
            if score is not None:
                if not isinstance(score, dict):
                    errors.append(f"{lw}.final_score must be an object")
                else:
                    for side in ("home", "away"):
                        if not finite_number(score.get(side)) or float(score.get(side, -1)) < 0:
                            errors.append(f"{lw}.final_score.{side} must be a finite non-negative number")
            if leg.get("settled_at") is not None and not parse_datetime(leg.get("settled_at")):
                errors.append(f"{lw}.settled_at must be an ISO date-time")
    return errors


def evaluate_pick(pick: str, line: float, final_score: dict[str, Any] | None) -> str | None:
    """Return WON, LOST or PUSH for an exact O/U selection, or None without a score."""
    if not isinstance(final_score, dict):
        return None
    home, away = final_score.get("home"), final_score.get("away")
    if not finite_number(home) or not finite_number(away):
        return None
    total = float(home) + float(away)
    line = float(line)
    if math.isclose(total, line, abs_tol=1e-9):
        return "PUSH"
    if pick == "over":
        return "WON" if total > line else "LOST"
    if pick == "under":
        return "WON" if total < line else "LOST"
    return None


def classify_line_adjustment(desk: dict[str, Any] | None, actual: dict[str, Any]) -> str:
    if not isinstance(desk, dict):
        return "desk_snapshot_missing"
    desk_pick, actual_pick = desk.get("pick"), actual.get("pick")
    try:
        desk_line, actual_line = float(desk["line"]), float(actual["line"])
    except (KeyError, TypeError, ValueError):
        return "desk_snapshot_incomplete"
    if desk_pick != actual_pick:
        return "side_changed"
    if math.isclose(desk_line, actual_line, abs_tol=1e-9):
        return "unchanged"
    # For Over, a lower line is easier; for Under, a higher line is easier.
    easier = actual_line < desk_line if actual_pick == "over" else actual_line > desk_line
    if easier:
        return "user_line_easier"
    return "user_line_harder"


def analyze_leg(leg: dict[str, Any]) -> dict[str, Any]:
    actual = leg["actual_selection"]
    desk = leg.get("desk_snapshot")
    actual_result = evaluate_pick(actual["pick"], actual["line"], leg.get("final_score"))
    desk_result = None
    if isinstance(desk, dict):
        desk_result = evaluate_pick(desk.get("pick"), desk.get("line"), leg.get("final_score"))
    adjustment = classify_line_adjustment(desk, actual)
    if actual_result is None or desk_result is None:
        counterfactual = "not_comparable"
    elif actual_result == "WON" and desk_result != "WON":
        counterfactual = "actual_selection_won_desk_did_not"
    elif desk_result == "WON" and actual_result != "WON":
        counterfactual = "desk_selection_won_actual_did_not"
    else:
        counterfactual = "both_won" if actual_result == "WON" else "neither_won"
    return {
        "product": str(leg.get("product") or "unknown").strip().lower(),
        "actual_pick": actual["pick"],
        "actual_line": float(actual["line"]),
        "actual_odds": float(actual["odds"]),
        "actual_result": actual_result,
        "desk_pick": desk.get("pick") if isinstance(desk, dict) else None,
        "desk_line": float(desk["line"]) if isinstance(desk, dict) and finite_number(desk.get("line")) else None,
        "desk_result": desk_result,
        "line_adjustment": adjustment,
        "counterfactual": counterfactual,
    }


def summarize_document(document: dict[str, Any]) -> dict[str, Any]:
    tickets = document.get("tickets") or []
    analyses: list[dict[str, Any]] = []
    for ticket in tickets:
        for leg in ticket.get("legs") or []:
            analyses.append(analyze_leg(leg))

    outcomes = {"WON": 0, "LOST": 0, "PUSH": 0, "UNSETTLED_OR_MISSING_SCORE": 0}
    line_edits: dict[str, int] = defaultdict(int)
    groups: dict[tuple[str, str, float], dict[str, int]] = defaultdict(
        lambda: {"settled_non_push": 0, "wins": 0, "losses": 0, "pushes": 0}
    )
    comparisons: dict[str, int] = defaultdict(int)

    for item in analyses:
        result = item["actual_result"]
        if result is None:
            outcomes["UNSETTLED_OR_MISSING_SCORE"] += 1
        else:
            outcomes[result] += 1
        line_edits[item["line_adjustment"]] += 1
        key = (item["product"], item["actual_pick"], item["actual_line"])
        if result == "WON":
            groups[key]["settled_non_push"] += 1
            groups[key]["wins"] += 1
        elif result == "LOST":
            groups[key]["settled_non_push"] += 1
            groups[key]["losses"] += 1
        elif result == "PUSH":
            groups[key]["pushes"] += 1
        if item["counterfactual"] != "not_comparable":
            comparisons["comparable_legs"] += 1
            comparisons[item["counterfactual"]] += 1

    exact_line_summary = []
    for (product, pick, line), counts in sorted(groups.items()):
        n = counts["settled_non_push"]
        exact_line_summary.append({
            "product": product,
            "pick": pick,
            "line": line,
            **counts,
            "hit_rate_excluding_pushes": round(counts["wins"] / n, 4) if n else None,
        })

    scored_non_push = outcomes["WON"] + outcomes["LOST"]
    return {
        "schema_version": 1,
        "mode": "PRIVATE_USER_EVIDENCE",
        "privacy": "AGGREGATE_ONLY",
        "ticket_count": len(tickets),
        "leg_count": len(analyses),
        "scored_leg_count": sum(outcomes[k] for k in ("WON", "LOST", "PUSH")),
        "actual_selection_outcomes": outcomes,
        "actual_leg_hit_rate_excluding_pushes": round(outcomes["WON"] / scored_non_push, 4) if scored_non_push else None,
        "line_adjustments": dict(sorted(line_edits.items())),
        "desk_vs_actual_same_score_comparison": dict(sorted(comparisons.items())),
        "exact_product_pick_line": exact_line_summary,
        "interpretation_guard": (
            "Descriptive evidence from user-selected tickets only; selection-biased and not a "
            "standalone model-validation sample. Do not update model parameters from this summary alone."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Private JSON file matching schemas/user-ticket-review.schema.json")
    args = parser.parse_args()
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
    except OSError as exc:
        print(json.dumps({"status": "ERROR", "error": "cannot read input file"}), file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "ERROR", "error": f"invalid JSON at line {exc.lineno}, column {exc.colno}"}), file=sys.stderr)
        return 2

    errors = validate_document(document)
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "VALID", "summary": summarize_document(document)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
