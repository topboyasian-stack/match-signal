#!/usr/bin/env python3
"""Match Signal Virtual Lab collector.

Collects public SportyBet virtual/eFootball/SRL fixtures before start, computes
the live bookmaker no-vig baseline, and later settles those observations from
SportyBet's public event-result feed.

This is an observation/research pipeline only. It never places or submits a wager.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PENDING_PATH = DATA / "virtual_lab_pending.json"
HISTORY_PATH = DATA / "virtual_lab_history.json"
STATUS_PATH = DATA / "virtual_lab_status.json"

SPORTY = "https://www.sportybet.com"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Current-Country": "NG",
    "Origin": SPORTY,
    "Referer": SPORTY + "/ng/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0 Safari/537.36",
}
MARKET_IDS = "1,18,10,29,11,26,36,14,60100,186,189,202,204,210"
PENDING_CAP = 12000
HISTORY_CAP = 30000
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )


def num(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def request_json(path: str, params: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = SESSION.get(SPORTY + path, params=params, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError(f"{path} returned non-object JSON")
            if body.get("bizCode") not in (None, 10000):
                raise RuntimeError(f"{path} bizCode={body.get('bizCode')}")
            return body
        except Exception as exc:
            last = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"{path} failed: {last}")


def tournaments_from(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("tournaments"), list):
        return [x for x in data["tournaments"] if isinstance(x, dict)]
    return []


def classify(source: str, tournament: str, category: str, home: str, away: str) -> str | None:
    blob = f"{source} {tournament} {category} {home} {away}".lower()
    if source == "vfootball":
        return "zoom" if ("zoom" in blob or "turbo" in blob) else "vfootball"
    if source == "efootball":
        return "efootball_adriatic" if "eadriatic" in blob else "efootball_gt"
    if source == "srl" and (
        "simulated reality" in blob or "simulated" in blob or " srl" in blob
    ):
        return "srl"
    if "zoom" in blob or "turbo" in blob:
        return "zoom"
    return None


def line_from_specifier(value: Any) -> float | None:
    text = str(value or "")
    lowered = text.lower()
    for token in ("total=", "line="):
        if token in lowered:
            try:
                return float(lowered.split(token, 1)[1].split("&", 1)[0])
            except (TypeError, ValueError):
                pass
    return None


def market_name(market: dict[str, Any]) -> str:
    return str(
        market.get("desc") or market.get("name") or market.get("title") or ""
    ).strip()


def outcome_name(outcome: dict[str, Any]) -> str:
    return str(
        outcome.get("name") or outcome.get("desc") or outcome.get("title") or ""
    ).strip()


def is_winner(market: dict[str, Any]) -> bool:
    mid = str(market.get("id") or "")
    name = market_name(market).lower()
    return mid in {"1", "186"} or "1x2" in name or "winner" in name or "match result" in name


def is_ou(market: dict[str, Any]) -> bool:
    mid = str(market.get("id") or "")
    name = market_name(market).lower()
    return mid in {"18", "189"} or "over/under" in name or "total" in name


def normalize_market(raw: dict[str, Any]) -> dict[str, Any] | None:
    outcomes = []
    for outcome in raw.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        odds = num(outcome.get("odds"))
        name = outcome_name(outcome)
        if odds is None or odds <= 1 or not name:
            continue
        outcomes.append({
            "id": str(outcome.get("id") or ""),
            "name": name,
            "odds": odds,
            "active": outcome.get("isActive") is not False,
        })
    if len(outcomes) < 2:
        return None
    implied_sum = sum(1 / x["odds"] for x in outcomes)
    if implied_sum <= 0:
        return None
    for outcome in outcomes:
        outcome["implied_probability"] = 1 / outcome["odds"]
        outcome["fair_probability"] = outcome["implied_probability"] / implied_sum
    pick = max(outcomes, key=lambda x: x["fair_probability"])
    line = line_from_specifier(raw.get("specifier"))
    return {
        "id": str(raw.get("id") or ""),
        "name": market_name(raw),
        "specifier": raw.get("specifier"),
        "line": line,
        "status": raw.get("status"),
        "overround": max(0.0, implied_sum - 1.0),
        "outcomes": outcomes,
        "pick": pick,
        "market_type": "winner" if is_winner(raw) else "ou",
    }


def normalize_event(event: dict[str, Any], source: str, tournament: dict[str, Any]) -> dict[str, Any] | None:
    event_id = str(event.get("eventId") or "").strip()
    home = str(event.get("homeTeamName") or "").strip()
    away = str(event.get("awayTeamName") or "").strip()
    if not event_id or not home or not away:
        return None

    tournament_name = str(tournament.get("name") or "").strip()
    category_name = str(tournament.get("categoryName") or "").strip()
    product = classify(source, tournament_name, category_name, home, away)
    if not product:
        return None

    start_ms = num(event.get("estimateStartTime"))
    start_time = (
        datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat()
        if start_ms is not None else None
    )
    markets = []
    for raw_market in event.get("markets") or []:
        if not isinstance(raw_market, dict):
            continue
        if not (is_winner(raw_market) or is_ou(raw_market)):
            continue
        market = normalize_market(raw_market)
        if market:
            markets.append(market)
    if not markets:
        return None

    return {
        "product": product,
        "provider": "SportyBet NG",
        "source": source,
        "event_id": event_id,
        "competition": tournament_name or "Unclassified",
        "category": category_name,
        "tournament_id": str(tournament.get("id") or ""),
        "category_id": str(tournament.get("categoryId") or ""),
        "participant_1": home,
        "participant_2": away,
        "start_time_ms": int(start_ms) if start_ms is not None else None,
        "start_time": start_time,
        "match_status": event.get("matchStatus"),
        "markets": markets,
        "captured_at": now_iso(),
    }


def fetch_source(source: str, sport_id: str, endpoint: str) -> tuple[list[dict[str, Any]], str | None]:
    output = []
    seen = set()
    try:
        for page_num in range(1, 3):
            body = request_json(endpoint, {
                "sportId": sport_id,
                "marketId": MARKET_IDS,
                "pageSize": 100,
                "pageNum": page_num,
                "todayGames": "false",
                "timeline": 168,
                "_t": int(time.time() * 1000),
            })
            page_added = 0
            for tournament in tournaments_from(body):
                for event in tournament.get("events") or []:
                    normalized = normalize_event(event, source, tournament)
                    if not normalized or normalized["event_id"] in seen:
                        continue
                    start_ms = normalized["start_time_ms"]
                    if start_ms is not None and start_ms < int(time.time() * 1000) - 120000:
                        continue
                    seen.add(normalized["event_id"])
                    output.append(normalized)
                    page_added += 1
            if page_added < 100:
                break
        return output, None
    except Exception as exc:
        return output, f"{source}: {exc}"


def fetch_upcoming() -> tuple[list[dict[str, Any]], list[str]]:
    jobs = [
        ("srl", "sr:sport:1", "/api/ng/factsCenter/pcUpcomingEvents"),
        ("efootball", "sr:sport:137", "/api/ng/factsCenter/pcUpcomingEvents"),
        ("vfootball", "sr:sport:202120001", "/api/ng/factsCenter/wapConfigurableUpcomingEvents"),
    ]
    all_events = []
    errors = []
    for source, sport_id, endpoint in jobs:
        events, error = fetch_source(source, sport_id, endpoint)
        all_events.extend(events)
        if error:
            errors.append(error)
    unique = {}
    for event in all_events:
        unique.setdefault(event["event_id"], event)
    return list(unique.values()), errors


def outcome_code(market: dict[str, Any], outcome: dict[str, Any]) -> str:
    name = outcome["name"].strip().lower()
    line = market.get("line")
    line_text = "" if line is None else str(line).replace(".0", "")
    if name.startswith("over"):
        return "O" + line_text
    if name.startswith("under"):
        return "U" + line_text
    if name == "home":
        return "1"
    if name == "draw":
        return "X"
    if name == "away":
        return "2"
    return outcome["name"].strip()


def build_predictions(event: dict[str, Any]) -> list[dict[str, Any]]:
    predictions = []
    winner_seen = False
    for market in event["markets"]:
        if market["market_type"] == "winner" and not winner_seen:
            pick = market["pick"]
            predictions.append({
                "observation_id": f'{event["event_id"]}|winner|{market.get("specifier") or ""}|{pick["id"]}',
                "market": "winner",
                "market_id": market["id"],
                "specifier": market.get("specifier"),
                "line": None,
                "selection": outcome_code(market, pick),
                "selection_name": pick["name"],
                "odds": pick["odds"],
                "model_prob": pick["fair_probability"],
                "overround": market["overround"],
                "prediction_source": "sportybet_de_vig_market_baseline",
            })
            winner_seen = True
        elif market["market_type"] == "ou" and market.get("line") is not None:
            pick = market["pick"]
            predictions.append({
                "observation_id": f'{event["event_id"]}|ou|{market.get("specifier") or market["line"]}|{pick["id"]}',
                "market": "ou",
                "market_id": market["id"],
                "specifier": market.get("specifier"),
                "line": market.get("line"),
                "selection": outcome_code(market, pick),
                "selection_name": pick["name"],
                "odds": pick["odds"],
                "model_prob": pick["fair_probability"],
                "overround": market["overround"],
                "prediction_source": "sportybet_de_vig_market_baseline",
            })
    return predictions


def capture(events: list[dict[str, Any]], pending: dict[str, dict[str, Any]]) -> int:
    added = 0
    for event in events:
        for prediction in build_predictions(event):
            key = prediction["observation_id"]
            if key in pending:
                continue
            pending[key] = {
                **prediction,
                "product": event["product"],
                "provider": event["provider"],
                "source": event["source"],
                "event_id": event["event_id"],
                "competition": event["competition"],
                "category": event["category"],
                "tournament_id": event.get("tournament_id"),
                "category_id": event.get("category_id"),
                "participant_1": event["participant_1"],
                "participant_2": event["participant_2"],
                "start_time": event.get("start_time"),
                "start_time_ms": event.get("start_time_ms"),
                "captured_at": event["captured_at"],
                "settled": False,
            }
            added += 1
    return added


def result_events(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("tournaments"), list):
        rows = []
        for tournament in data["tournaments"]:
            if isinstance(tournament, dict):
                rows.extend(x for x in tournament.get("events") or [] if isinstance(x, dict))
        return rows
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    events = body.get("events")
    return [x for x in events if isinstance(x, dict)] if isinstance(events, list) else []


def score(event: dict[str, Any]) -> tuple[float, float] | None:
    def pair(a: Any, b: Any) -> tuple[float, float] | None:
        ha, aa = num(a), num(b)
        return (ha, aa) if ha is not None and aa is not None else None

    for key in ("setScore", "score", "finalScore"):
        value = event.get(key)
        if isinstance(value, str) and ":" in value:
            left, right = value.replace(" ", "").rsplit(":", 1)
            hit = pair(left, right)
            if hit:
                return hit
        elif isinstance(value, dict):
            hit = pair(
                value.get("home") or value.get("homeScore") or value.get("home_score"),
                value.get("away") or value.get("awayScore") or value.get("away_score"),
            )
            if hit:
                return hit
        elif isinstance(value, list) and len(value) >= 2:
            hit = pair(value[0], value[1])
            if hit:
                return hit

    for home_key in ("homeTeamScore", "homeScore", "home_score", "homeGoals", "homeGoalsCount"):
        for away_key in ("awayTeamScore", "awayScore", "away_score", "awayGoals", "awayGoalsCount"):
            hit = pair(event.get(home_key), event.get(away_key))
            if hit:
                return hit

    nested = event.get("result") or event.get("resultScore")
    if isinstance(nested, dict):
        hit = pair(nested.get("home") or nested.get("homeScore"), nested.get("away") or nested.get("awayScore"))
        if hit:
            return hit
    return None


def actual_code(item: dict[str, Any], final_score: tuple[float, float]) -> str:
    home, away = final_score
    if item["market"] == "winner":
        return "1" if home > away else "2" if away > home else "X"
    line = num(item.get("line"))
    if line is None:
        return ""
    total = home + away
    line_text = str(line).replace(".0", "")
    if total > line:
        return "O" + line_text
    if total < line:
        return "U" + line_text
    return "PUSH"


def settle(pending: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int, list[str]]:
    unresolved = [x for x in pending.values() if not x.get("settled") and x.get("event_id")]
    if not unresolved:
        return [], 0, []

    source_sport = {
        "srl": "sr:sport:1",
        "efootball": "sr:sport:137",
        "vfootball": "sr:sport:202120001",
    }
    ranges: dict[str, tuple[int, int]] = {}
    for item in unresolved:
        source = str(item.get("source") or "")
        start = int(num(item.get("start_time_ms")) or int(time.time() * 1000) - 86400000)
        previous = ranges.get(source)
        ranges[source] = (start, start) if previous is None else (min(previous[0], start), max(previous[1], start))

    index: dict[str, dict[str, Any]] = {}
    errors = []
    for source, (start, end) in ranges.items():
        sport_id = source_sport.get(source)
        if not sport_id:
            continue
        start_q = start - 6 * 3600000
        end_q = max(end + 6 * 3600000, int(time.time() * 1000))
        for page_num in range(1, 9):
            try:
                body = request_json("/api/ng/factsCenter/eventResultList", {
                    "sportId": sport_id,
                    "pageNum": page_num,
                    "pageSize": 100,
                    "startTime": start_q,
                    "endTime": end_q,
                })
            except Exception as exc:
                errors.append(f"{source} results page {page_num}: {exc}")
                break
            batch = result_events(body)
            if not batch:
                break
            for event in batch:
                event_id = str(event.get("eventId") or event.get("event_id") or "").strip()
                if event_id:
                    index[event_id] = event
            if len(batch) < 100:
                break

    history_rows = []
    newly_settled = 0
    for item in pending.values():
        if item.get("settled"):
            continue
        result = index.get(str(item.get("event_id")))
        if not result:
            continue
        final_score = score(result)
        if final_score is None:
            continue
        actual = actual_code(item, final_score)
        win = None if actual == "PUSH" else actual == item.get("selection")
        settled_at = now_iso()
        item.update({
            "settled": True,
            "settled_at": settled_at,
            "actual_result": actual,
            "final_score": [final_score[0], final_score[1]],
            "win": win,
            "settlement_source": "SportyBet NG eventResultList",
        })
        history_rows.append({
            "product": item["product"],
            "provider": item["provider"],
            "event_id": item["event_id"],
            "timestamp": item.get("start_time"),
            "competition": item["competition"],
            "participant_1": item["participant_1"],
            "participant_2": item["participant_2"],
            "market": item["market"],
            "market_id": item.get("market_id"),
            "specifier": item.get("specifier"),
            "selection": item["selection"],
            "selection_name": item.get("selection_name"),
            "odds": item.get("odds"),
            "model_prob": item.get("model_prob"),
            "result": actual,
            "win": win,
            "line": item.get("line"),
            "score": f"{int(final_score[0])}:{int(final_score[1])}",
            "captured_at": item.get("captured_at"),
            "settled_at": settled_at,
            "settlement_source": item["settlement_source"],
            "prediction_source": item.get("prediction_source"),
            "overround": item.get("overround"),
            "source": item.get("source"),
        })
        newly_settled += 1
    return history_rows, newly_settled, errors


def merge_history(existing: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {
        (str(x.get("event_id")), str(x.get("market")), str(x.get("line")), str(x.get("selection")))
        for x in existing if isinstance(x, dict)
    }
    for row in new_rows:
        key = (str(row.get("event_id")), str(row.get("market")), str(row.get("line")), str(row.get("selection")))
        if key not in seen:
            existing.append(row)
            seen.add(key)
    existing.sort(key=lambda x: str(x.get("timestamp") or ""))
    return existing[-HISTORY_CAP:]


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    pending_raw = load_json(PENDING_PATH, [])
    history = load_json(HISTORY_PATH, [])
    pending_raw = pending_raw if isinstance(pending_raw, list) else []
    history = history if isinstance(history, list) else []

    pending = {
        str(item["observation_id"]): item
        for item in pending_raw
        if isinstance(item, dict) and item.get("observation_id")
    }

    events, capture_errors = fetch_upcoming()
    added = capture(events, pending)
    settled_rows, newly_settled, settle_errors = settle(pending)
    history = merge_history(history, settled_rows)

    pending = {key: item for key, item in pending.items() if not item.get("settled")}
    if len(pending) > PENDING_CAP:
        ordered = sorted(pending.values(), key=lambda x: str(x.get("start_time") or ""))
        pending = {str(x["observation_id"]): x for x in ordered[-PENDING_CAP:]}

    settled = [x for x in history if x.get("win") is not None]
    wins = sum(bool(x.get("win")) for x in settled)
    products = {}
    for event in events:
        products[event["product"]] = products.get(event["product"], 0) + 1

    errors = capture_errors + settle_errors
    status = {
        "updated_at": now_iso(),
        "collector_version": "1.0",
        "upcoming_events": len(events),
        "upcoming_by_product": products,
        "pending_observations": len(pending),
        "settled_observations": len(history),
        "settled_decisions": len(settled),
        "settled_wins": wins,
        "settled_accuracy": round(wins / len(settled), 4) if settled else None,
        "new_observations": added,
        "newly_settled": newly_settled,
        "result_source": "SportyBet NG eventResultList",
        "prediction_source": "SportyBet live no-vig market baseline",
        "errors": errors[-20:],
        "paper_only": True,
    }

    save_json(PENDING_PATH, list(pending.values()))
    save_json(HISTORY_PATH, history)
    save_json(STATUS_PATH, status)

    print(
        f"Virtual Lab collector: {len(events)} upcoming events | "
        f"+{added} observations | +{newly_settled} settled | "
        f"{len(history)} history rows | {len(pending)} pending"
    )
    for error in errors[-10:]:
        print("WARNING:", error)


if __name__ == "__main__":
    main()
