"""Build a guarded 3-4 leg Match Signal odds slip from qualified candidates.

The builder is an analysis layer only. It never places or stakes a wager.
SportyBet integration uses the bookmaker's public web endpoints to refresh
pre-match football markets and, when at least three fully qualified selections
match live SportyBet markets, requests a SportyBet share/booking code. Stake is
reported as unsupported for automatic slip creation until a stable supported
betslip/share interface is verified.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CANDIDATES = DATA / "selection_candidates.json"
OUTPUT = DATA / "odds_builder.json"
SPORTY_BASE = "https://www.sportybet.com"
SPORTY_REGION = "ng"
MIN_LEGS = 3
MAX_LEGS = 4
MIN_MODEL_PROB = 0.65
MIN_EDGE = 0.03

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "Content-Type": "application/json", "Current-Country": "NG", "User-Agent": "MatchSignal/odds-builder"})


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def norm(value):
    s = str(value or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    aliases = {
        "man utd": "manchester united", "man united": "manchester united",
        "man city": "manchester city", "psv eindhoven": "psv",
        "sporting lisbon": "sporting cp", "atletico madrid": "atletico madrid",
        "internazionale": "inter milan", "inter": "inter milan",
    }
    return aliases.get(s.strip(), s.strip())


def similarity(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.94
    return difflib.SequenceMatcher(None, a, b).ratio()


def sportyevents():
    url = f"{SPORTY_BASE}/api/{SPORTY_REGION}/factsCenter/pcUpcomingEvents"
    params = {"sportId": "sr:sport:1", "marketId": "1", "pageSize": 100, "pageNum": 1, "todayGames": "false", "timeline": 168, "_t": int(datetime.now(timezone.utc).timestamp() * 1000)}
    r = SESSION.get(url, params=params, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("bizCode") not in (None, 10000):
        raise RuntimeError(f"SportyBet returned bizCode={body.get('bizCode')}")
    tournaments = ((body.get("data") or {}).get("tournaments") or [])
    events = []
    for tournament in tournaments:
        for event in tournament.get("events") or []:
            event["_tournament"] = tournament.get("name")
            event["_category"] = tournament.get("categoryName")
            events.append(event)
    return events


def one_x_two(event):
    for market in event.get("markets") or []:
        if str(market.get("id")) != "1":
            continue
        out = {str(x.get("id")): x for x in market.get("outcomes") or [] if x.get("isActive", True)}
        return market, out
    return None, {}


def match_candidate(candidate, events):
    best = None
    best_score = 0.0
    for event in events:
        hs = similarity(candidate.get("player_1"), event.get("homeTeamName"))
        aw = similarity(candidate.get("player_2"), event.get("awayTeamName"))
        score = (hs + aw) / 2
        if score > best_score:
            best_score, best = score, event
    return best if best_score >= 0.84 else None


def selected_outcome(candidate, market, outcomes):
    pick = candidate.get("pick")
    outcome_id = {"p1": "1", "draw": "2", "p2": "3"}.get(pick)
    if not outcome_id or outcome_id not in outcomes:
        return None
    outcome = outcomes[outcome_id]
    odds = float(outcome.get("odds"))
    model_prob = float((candidate.get("probabilities") or {}).get(pick, candidate.get("confidence", 0)))
    implied = 1 / odds if odds > 1 else 1.0
    edge = model_prob - implied
    if model_prob < MIN_MODEL_PROB or edge < MIN_EDGE:
        return None
    return {
        "sport": "football",
        "league": candidate.get("league"),
        "event_id": candidate.get("event_id"),
        "sporty_event_id": event_id := event_id_value(event=None),
        "home": candidate.get("player_1"),
        "away": candidate.get("player_2"),
        "market": "1X2",
        "pick": pick,
        "selection": outcome.get("desc"),
        "model_probability": round(model_prob, 6),
        "sporty_odds": odds,
        "implied_probability": round(implied, 6),
        "edge": round(edge, 6),
        "market_id": str(market.get("id")),
        "outcome_id": str(outcome.get("id")),
        "specifier": market.get("specifier"),
    }


def event_id_value(event):
    return str(event.get("eventId")) if event else ""


def main():
    candidates = load(CANDIDATES, [])
    if not isinstance(candidates, list):
        candidates = []
    # The research gate is intentionally upstream. Do not weaken it here.
    candidates = [x for x in candidates if isinstance(x, dict) and x.get("candidate_status") == "SELECTED" and x.get("sport") == "football"]
    candidates.sort(key=lambda x: (float(x.get("confidence", 0)), float((x.get("signal_quality") or {}).get("components", 0))), reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "target_legs": "3-4",
        "selection_policy": {"min_model_probability": MIN_MODEL_PROB, "min_model_edge_vs_sporty_implied": MIN_EDGE, "requires_upstream_selection_gate": True, "public_prediction_feed_unchanged": True},
        "sportybet": {"status": "NOT_RUN", "booking_code": None, "share_url": None, "legs": [], "expires_at": None},
        "stake": {"status": "MANUAL_SHARE_INTERFACE_REQUIRED", "booking_url": None, "booking_code": None},
        "candidates_considered": len(candidates),
        "qualified_legs": [],
        "notes": ["No slip is generated unless 3-4 upstream-qualified selections also match live SportyBet 1X2 markets with the required model edge.", "Stake automatic betslip creation is intentionally disabled until a stable supported share interface is verified."]
    }

    if len(candidates) < MIN_LEGS:
        result["sportybet"]["status"] = "NO_3_LEG_QUALIFIED_SET"
        OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return

    try:
        events = sportyevents()
    except Exception as exc:
        result["sportybet"] = {"status": "ODDS_SOURCE_ERROR", "error": str(exc), "booking_code": None, "share_url": None, "legs": []}
        OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return

    legs = []
    for candidate in candidates:
        event = match_candidate(candidate, events)
        if not event:
            continue
        market, outcomes = one_x_two(event)
        if not market:
            continue
        pick = candidate.get("pick")
        outcome_id = {"p1": "1", "draw": "2", "p2": "3"}.get(pick)
        if outcome_id not in outcomes:
            continue
        outcome = outcomes[outcome_id]
        try:
            odds = float(outcome.get("odds"))
            model_prob = float((candidate.get("probabilities") or {}).get(pick, candidate.get("confidence", 0)))
        except (TypeError, ValueError):
            continue
        implied = 1 / odds if odds > 1 else 1.0
        edge = model_prob - implied
        if model_prob < MIN_MODEL_PROB or edge < MIN_EDGE:
            continue
        legs.append({"sport": "football", "league": candidate.get("league"), "event_id": candidate.get("event_id"), "sporty_event_id": event_id_value(event), "home": event.get("homeTeamName"), "away": event.get("awayTeamName"), "market": "1X2", "pick": pick, "selection": outcome.get("desc"), "model_probability": round(model_prob, 6), "sporty_odds": odds, "implied_probability": round(implied, 6), "edge": round(edge, 6), "market_id": str(market.get("id")), "outcome_id": str(outcome.get("id")), "specifier": market.get("specifier")})
        if len(legs) >= MAX_LEGS:
            break

    result["qualified_legs"] = legs
    result["sportybet"]["legs"] = legs
    if len(legs) < MIN_LEGS:
        result["sportybet"]["status"] = "FEWER_THAN_3_LIVE_MATCHES"
    else:
        result["sportybet"]["status"] = "QUALIFIED_BETSLIP"
        result["sportybet"]["combined_odds"] = round(__import__("math").prod(x["sporty_odds"] for x in legs), 4)
        payload = {"selections": [{"eventId": x["sporty_event_id"], "marketId": x["market_id"], "specifier": x["specifier"], "outcomeId": x["outcome_id"]} for x in legs]}
        try:
            response = SESSION.post(f"{SPORTY_BASE}/api/{SPORTY_REGION}/orders/share", json=payload, timeout=30)
            response.raise_for_status()
            body = response.json()
            data = body.get("data") or {}
            unavailable = data.get("unavailableOutcomes") or []
            if unavailable:
                result["sportybet"]["status"] = "BOOKING_PARTIAL_OR_UNAVAILABLE"
                result["sportybet"]["unavailable_outcomes"] = unavailable
            else:
                result["sportybet"]["booking_code"] = data.get("shareCode")
                result["sportybet"]["share_url"] = data.get("shareURL")
                result["sportybet"]["expires_at"] = data.get("deadline")
        except Exception as exc:
            result["sportybet"]["status"] = "BOOKING_ENDPOINT_ERROR"
            result["sportybet"]["error"] = str(exc)

    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
