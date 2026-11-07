"""Fixture-level primary prediction ledger.

A fixture has one official primary prediction. Alternatives remain in the
market-reassessment ledger and can never replace this record retrospectively.
"""
from __future__ import annotations

import hashlib
from typing import Any


def _number(value):
    try:
        value = float(value)
        return value if 0 <= value <= 1 else None
    except (TypeError, ValueError):
        return None


def _sport(value):
    value = str(value or "").lower()
    return "virtual" if value in {"efootball", "efootball_gt", "efootball_adriatic"} else value


def _primary_candidate(row):
    explicit = row.get("primary_prediction")
    if isinstance(explicit, dict):
        market = explicit.get("market")
        pick = explicit.get("pick")
        probability = _number(explicit.get("model_probability", explicit.get("probability")))
        line = explicit.get("line")
        source = "explicit_primary_prediction"
    else:
        market = row.get("primary_market")
        pick = row.get("primary_pick")
        probability = _number(row.get("primary_probability"))
        line = row.get("primary_line")
        source = "explicit_primary_fields"
        if not market and not pick:
            sport = _sport(row.get("sport"))
            if sport == "football" and row.get("pick") in {"p1", "draw", "p2"}:
                market, pick = "1X2", row.get("pick")
                probs = row.get("calibrated_probabilities") or row.get("probabilities") or {}
                probability = _number(probs.get(pick, row.get("calibrated_confidence", row.get("confidence"))))
                source = "published_fixture_pick"
            elif sport == "tennis" and row.get("pick") in {"p1", "p2"}:
                market, pick = "winner", row.get("pick")
                probs = row.get("calibrated_probabilities") or row.get("probabilities") or {}
                probability = _number(probs.get(pick, row.get("calibrated_confidence", row.get("confidence"))))
                source = "published_fixture_pick"
            elif sport == "basketball":
                total = (row.get("markets") or {}).get("total_ou") or {}
                market, pick, line = total.get("market") or "total_ou", total.get("pick") or row.get("pick"), total.get("line")
                probability = _number(total.get("model_probability", total.get("probability")))
                if probability is None and pick:
                    probability = _number((total.get("probabilities") or {}).get(pick))
                source = "published_nba_total_pick"
            elif sport == "tennis":
                total = ((row.get("analytics") or {}).get("total_games") or {})
                if total.get("pick") in {"over", "under"} and total.get("line") is not None:
                    market, pick, line = "total_games", total.get("pick"), total.get("line")
                    probability = _number(total.get("calibrated_" + str(pick), total.get(pick)))
                    source = "published_tennis_total_pick"
    if not isinstance(market, str) or not market.strip() or not isinstance(pick, str) or not pick.strip():
        return None
    return {"market": market.strip(), "pick": pick.strip(), "line": line,
            "model_probability": probability, "primary_source": source}


def build_fixture_ledger(source_rows, now):
    grouped = {}
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        sport = _sport(row.get("sport"))
        event_id = str(row.get("event_id") or "").strip()
        if sport not in {"football", "tennis", "basketball", "virtual"} or not event_id:
            continue
        grouped.setdefault((sport, event_id), []).append(row)

    output = []
    for (sport, event_id), rows in grouped.items():
        candidates = []
        for row in rows:
            candidate = _primary_candidate(row)
            if candidate:
                candidates.append(candidate)
        distinct = {(x["market"], x["pick"], str(x.get("line"))) for x in candidates}
        chosen = candidates[0] if len(distinct) == 1 else None
        identity = hashlib.sha256((sport + "|" + event_id).encode()).hexdigest()[:24]
        first = rows[0]
        stamp = next((r.get("prediction_timestamp") or r.get("published_at") or r.get("created_at") for r in rows
                      if r.get("prediction_timestamp") or r.get("published_at") or r.get("created_at")), None)
        item = {
            "fixture_id": identity, "sport": sport, "event_id": event_id,
            "match": str(first.get("match") or (str(first.get("player_1") or first.get("home_team") or "") +
                     " vs " + str(first.get("player_2") or first.get("away_team") or "")).strip()),
            "start_time": first.get("start_time"), "prediction_timestamp": stamp or now.isoformat(),
            "prediction_timestamp_source": "source_record" if stamp else "ledger_observation_time",
            "prediction_role": "PRIMARY", "primary_status": "FROZEN" if chosen else "UNCLASSIFIED",
            "primary_market": chosen.get("market") if chosen else None,
            "primary_pick": chosen.get("pick") if chosen else None,
            "primary_line": chosen.get("line") if chosen else None,
            "primary_probability": chosen.get("model_probability") if chosen else None,
            "primary_source": chosen.get("primary_source") if chosen else None,
            "classification_reason": None if chosen else ("multiple_conflicting_primary_candidates" if candidates else "no_identifiable_published_primary"),
            "settlement_status": "PENDING" if chosen else "UNCLASSIFIED",
            "settlement_result": None, "settled_at": None,
            "paper_only": True, "real_money_execution": False,
        }
        output.append(item)
    return output


def merge_primary_ledger(existing, incoming, settle_result, settlement_index, now):
    by_id = {str(x.get("fixture_id")): x for x in existing if isinstance(x, dict) and x.get("fixture_id")}
    for row in incoming:
        key = str(row.get("fixture_id") or "")
        if not key:
            continue
        old = by_id.get(key)
        if old is None:
            by_id[key] = dict(row)
        # Frozen primary identity is never replaced by a later run.
    for row in by_id.values():
        if row.get("primary_status") != "FROZEN" or row.get("settlement_status") == "SETTLED":
            continue
        start = row.get("start_time")
        try:
            from datetime import datetime
            kickoff = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            current = datetime.fromisoformat(now.isoformat())
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=current.tzinfo)
            if kickoff > current:
                continue
        except (TypeError, ValueError):
            continue
        settled = settle_result({
            "sport": row["sport"], "event_id": row["event_id"],
            "market": row["primary_market"], "pick": row["primary_pick"],
            "line": row.get("primary_line"),
        }, settlement_index)
        if settled:
            row.update(settled)
    return list(by_id.values())


def primary_summary(rows):
    settled = [x for x in rows if x.get("primary_status") == "FROZEN" and x.get("settlement_status") == "SETTLED"
               and x.get("settlement_result") not in {"push", None}]
    wins = sum(1 for x in settled if (
        (x.get("primary_pick") in {"over", "yes"} and x.get("settlement_result") in {"over", "yes"}) or
        (x.get("primary_pick") in {"under", "no"} and x.get("settlement_result") in {"under", "no"}) or
        (x.get("primary_pick") in {"p1", "p2", "draw"} and x.get("settlement_result") == "yes")
    ))
    classified = [x for x in rows if x.get("primary_status") == "FROZEN"]
    return {
        "fixture_count": len(rows), "classified_primary_count": len(classified),
        "unclassified_fixture_count": len(rows) - len(classified),
        "settled_primary_count": len(settled), "wins": wins,
        "losses": len(settled) - wins,
        "hit_rate": round(wins / len(settled), 4) if settled else None,
        "policy": "one frozen primary per sport/event; alternatives never replace it",
    }
