import json
import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from calibration import calibrate_prediction, calibrate_binary_market

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
FOOTBALL_LEAGUES = {
    "EPL": "eng.1",
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Serie A": "ita.1",
    "Ligue 1": "fra.1",
    "Champions League": "uefa.champions",
    "MLS": "usa.1",
    "Primeira Liga": "por.1",
    "Eredivisie": "ned.1",
    "Saudi Pro League": "ksa.1",
}
TENNIS_LEAGUES = {"ATP": "atp", "WTA": "wta"}

# Validated schedule corrections for public-feed timestamps that are stale or
# wrong at the source. Keep these narrow and event-specific; never apply a
# blanket timezone offset to tennis fixtures.
TENNIS_START_TIME_OVERRIDES = {
    # Clara Burel vs Joelle Lilly Sophie Steur — Valencia WTA 125 SF.
    # Current schedule sources list the match at 15:00Z on 2026-09-19.
    "183771": "2026-09-19T15:00:00Z",
}


def tennis_start_time(event):
    event_id = str(event.get("id") or "")
    return TENNIS_START_TIME_OVERRIDES.get(event_id) or event.get("date")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/3.0 (+https://github.com/topboyasian-stack/match-signal)"})


def get_json(url, params=None):
    response = SESSION.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def clamp(value, low=0.01, high=0.99):
    return max(low, min(high, float(value)))


def normalise(values):
    values = [max(0.0001, float(v)) for v in values]
    total = sum(values)
    return [v / total for v in values]


def american_to_prob(odds):
    try:
        odds = float(odds)
        if odds > 0:
            return 100 / (odds + 100)
        return -odds / (-odds + 100)
    except (TypeError, ValueError):
        return None



SPORTYBET_ORIGIN = os.getenv("MATCH_SIGNAL_SPORTYBET_BASE", "https://www.sportybet.com").rstrip("/")
SPORTYBET_PROXY = os.getenv("MATCH_SIGNAL_SPORTYBET_PROXY", "https://match-signal.pages.dev/api/sportybet").rstrip("/")
SPORTYBET_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Current-Country": "NG",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/ng/",
    "User-Agent": "MatchSignal/3.0 SportyBet-Market-Layer (+https://github.com/topboyasian-stack/match-signal)",
}
SPORTYBET_MARKETS = {
    "football": "1,18,10,29,11,14,26,36,60100,186,189,202,204,210",
    "tennis": "186,189,202,204,210",
}


def _sportybet_get(params):
    endpoints = [
        (SPORTYBET_ORIGIN + "/api/ng/factsCenter/pcUpcomingEvents", SPORTYBET_HEADERS),
    ]
    if SPORTYBET_PROXY and SPORTYBET_PROXY != SPORTYBET_ORIGIN:
        endpoints.append((SPORTYBET_PROXY, {"Accept": "application/json"}))
    last_error = None
    for url, headers in endpoints:
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("bizCode") is not None and body.get("bizCode") != 10000:
                raise RuntimeError(f"SportyBet bizCode {body.get('bizCode')}")
            if body.get("ok") is False:
                raise RuntimeError(body.get("error") or "SportyBet proxy returned ok=false")
            return body
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error or "SportyBet request failed"))


def fetch_sportybet_events(sport_id, market_ids, timeline=720, max_pages=20):
    events = []
    seen = set()
    total_num = None
    for page_num in range(1, max_pages + 1):
        body = _sportybet_get({
            "sportId": sport_id,
            "marketId": market_ids,
            "pageSize": 100,
            "pageNum": page_num,
            "todayGames": "false",
            "timeline": timeline,
            "_t": int(datetime.now(timezone.utc).timestamp() * 1000),
        })
        data = body.get("data") or {}
        if total_num is None:
            raw_total = data.get("totalNum") or data.get("totalEvents") or body.get("total_events")
            try:
                total_num = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total_num = None
        page_events = []
        for tournament in data.get("tournaments") or []:
            tournament_name = str(tournament.get("name") or "")
            category_name = str(tournament.get("categoryName") or "")
            for event in tournament.get("events") or []:
                event_id = str(event.get("eventId") or "")
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                page_events.append({
                    "event_id": event_id,
                    "tournament": tournament_name,
                    "category": category_name,
                    "home": str(event.get("homeTeamName") or ""),
                    "away": str(event.get("awayTeamName") or ""),
                    "start_time_ms": _sportybet_time_ms(event.get("estimateStartTime")),
                    "markets": event.get("markets") or [],
                })
        if not page_events:
            break
        events.extend(page_events)
        if total_num is not None and len(events) >= total_num:
            break
        if len(page_events) < 100:
            break
    return events


def _sportybet_time_ms(value):
    try:
        n = float(value)
        if n <= 0:
            return None
        return int(n * 1000 if n < 100000000000 else n)
    except (TypeError, ValueError):
        return None


def _market_line(market):
    raw = market.get("line")
    try:
        if raw is not None and str(raw) != "":
            return float(raw)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(?:total|line)=([0-9]+(?:\.[0-9]+)?)", str(market.get("specifier") or ""), re.I)
    return float(match.group(1)) if match else None


def _sportybet_fair_market(market):
    usable = []
    for outcome in market.get("outcomes") or []:
        try:
            odds = float(outcome.get("odds"))
        except (TypeError, ValueError):
            continue
        if odds <= 1 or outcome.get("isActive") is False:
            continue
        inv = 1.0 / odds
        usable.append({
            "id": str(outcome.get("id") or ""),
            "name": str(outcome.get("desc") or outcome.get("name") or outcome.get("title") or ""),
            "book_odds": odds,
            "implied": inv,
        })
    if len(usable) < 2:
        return None
    denom = sum(x["implied"] for x in usable)
    for item in usable:
        item["fair_prob"] = item["implied"] / denom
        item["fair_odds"] = 1.0 / item["fair_prob"]
    return {
        "id": str(market.get("id") or ""),
        "name": str(market.get("desc") or market.get("name") or market.get("title") or ""),
        "line": _market_line(market),
        "overround": max(0.0, denom - 1.0),
        "outcomes": usable,
    }


def _sportybet_market_snapshot(event, sport):
    winner_ids = {"1", "186"} if sport == "football" else {"186"}
    total_ids = {"18", "189"}
    winner = None
    totals = []
    all_markets = []
    for market in event.get("markets") or []:
        fair = _sportybet_fair_market(market)
        if not fair:
            continue
        mid = fair["id"]
        label = fair["name"].lower()
        all_markets.append({
            "id": mid,
            "name": fair["name"],
            "line": fair["line"],
            "overround": round(fair["overround"], 6),
            "outcomes": fair["outcomes"],
        })
        if mid in winner_ids or "winner" in label or "1x2" in label or label in {"win", "match result"}:
            if winner is None:
                winner = fair
        if mid in total_ids or "total" in label or "over/under" in label:
            names = {x["name"].lower(): x for x in fair["outcomes"]}
            over = next((x for x in fair["outcomes"] if x["name"].lower().startswith("over")), None)
            under = next((x for x in fair["outcomes"] if x["name"].lower().startswith("under")), None)
            if over and under:
                totals.append({
                    "line": fair["line"],
                    "over": over["book_odds"],
                    "under": under["book_odds"],
                    "over_fair_prob": over["fair_prob"],
                    "under_fair_prob": under["fair_prob"],
                    "over_fair_odds": over["fair_odds"],
                    "under_fair_odds": under["fair_odds"],
                    "overround": fair["overround"],
                    "market_id": mid,
                })
    if winner:
        by_name = {x["name"].lower(): x for x in winner["outcomes"]}
        def _find_winner(*patterns):
            for x in winner["outcomes"]:
                low = x["name"].lower()
                if any(low == p or low.startswith(p) for p in patterns):
                    return x
            return None
        home = _find_winner("home", "1")
        draw = _find_winner("draw", "x")
        away = _find_winner("away", "2")
        winner_summary = {
            "p1_book": home["book_odds"] if home else None,
            "draw_book": draw["book_odds"] if draw else None,
            "p2_book": away["book_odds"] if away else None,
            "p1_fair_prob": home["fair_prob"] if home else None,
            "draw_fair_prob": draw["fair_prob"] if draw else None,
            "p2_fair_prob": away["fair_prob"] if away else None,
            "p1_fair_odds": home["fair_odds"] if home else None,
            "draw_fair_odds": draw["fair_odds"] if draw else None,
            "p2_fair_odds": away["fair_odds"] if away else None,
            "market_id": winner["id"],
            "overround": winner["overround"],
            "raw_outcomes": winner["outcomes"],
        }
        if sport == "tennis":
            pair = winner["outcomes"][:2]
            if pair:
                winner_summary["p1_book"] = pair[0]["book_odds"]
                winner_summary["p2_book"] = pair[-1]["book_odds"]
                winner_summary["p1_fair_prob"] = pair[0]["fair_prob"]
                winner_summary["p2_fair_prob"] = pair[-1]["fair_prob"]
                winner_summary["p1_fair_odds"] = pair[0]["fair_odds"]
                winner_summary["p2_fair_odds"] = pair[-1]["fair_odds"]
                winner_summary["draw_book"] = None
                winner_summary["draw_fair_prob"] = None
                winner_summary["draw_fair_odds"] = None
    else:
        winner_summary = None
    return {
        "provider": "SportyBet NG",
        "event_id": event["event_id"],
        "tournament": event["tournament"],
        "category": event["category"],
        "start_time": (
            datetime.fromtimestamp(event["start_time_ms"] / 1000, tz=timezone.utc).isoformat()
            if event.get("start_time_ms") else None
        ),
        "winner": winner_summary,
        "totals": sorted(totals, key=lambda x: (x["line"] is None, x["line"] or 999)),
        "market_count": len(all_markets),
        "markets": all_markets,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _market_name_key(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    stop = {"fc", "afc", "sc", "cf", "club", "the"}
    return " ".join(token for token in text.split() if token not in stop)


def _name_similarity(left, right):
    a = _market_name_key(left)
    b = _market_name_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    at = set(a.split())
    bt = set(b.split())
    overlap = len(at & bt) / max(1, len(at | bt))
    return max(ratio, 0.75 * overlap + 0.25 * ratio)


def _pair_match_score(pred, event):
    p1 = pred.get("player_1") or ""
    p2 = pred.get("player_2") or ""
    e1 = event.get("home") or ""
    e2 = event.get("away") or ""
    direct = (_name_similarity(p1, e1) + _name_similarity(p2, e2)) / 2
    reverse = (_name_similarity(p1, e2) + _name_similarity(p2, e1)) / 2
    name_score = max(direct, reverse)
    start_a = _parse_dt(pred.get("start_time"))
    start_b = _parse_dt(
        datetime.fromtimestamp(event["start_time_ms"] / 1000, tz=timezone.utc).isoformat()
        if event.get("start_time_ms") else None
    )
    if start_a and start_b:
        hours = abs((start_a - start_b).total_seconds()) / 3600.0
        time_score = max(0.0, 1.0 - min(hours, 48.0) / 48.0)
    else:
        time_score = 0.35
    return 0.82 * name_score + 0.18 * time_score, direct, reverse


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_sportybet_match(pred, events):
    ranked = []
    for event in events:
        score, direct, reverse = _pair_match_score(pred, event)
        ranked.append((score, direct, reverse, event))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked:
        return None, None
    score, direct, reverse, event = ranked[0]
    # Exact or near-exact names can safely tolerate larger scheduling differences;
    # fuzzy matches still require stronger name agreement.
    threshold = 0.78 if max(direct, reverse) >= 0.94 else 0.86
    if score < threshold:
        return None, None
    side_map = "direct" if direct >= reverse else "reverse"
    return event, {
        "score": round(score, 4),
        "method": side_map,
        "name_direct": round(direct, 4),
        "name_reverse": round(reverse, 4),
    }


def _pick_sporty_total(snapshot, prediction):
    totals = snapshot.get("totals") or []
    if not totals:
        return None
    existing = None
    if prediction.get("sport") == "football":
        existing = ((prediction.get("markets") or {}).get("over_under") or {}).get("line")
    else:
        existing = ((prediction.get("analytics") or {}).get("total_games") or {}).get("line")
    try:
        target = float(existing) if existing is not None else None
    except (TypeError, ValueError):
        target = None
    usable = [x for x in totals if x.get("line") is not None]
    if target is None:
        return usable[0] if usable else totals[0]
    return min(usable or totals, key=lambda x: abs(float(x.get("line") or 0) - target))


def attach_sportybet_market_layer(predictions):
    """
    Add a current SportyBet NG market snapshot without replacing the independent
    Match Signal model. This is a market-baseline/enrichment layer only.
    """
    stats = {
        "provider": "SportyBet NG",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "football_events": 0,
        "tennis_events": 0,
        "matched": 0,
        "unmatched": 0,
        "match_errors": [],
        "fetch_errors": [],
    }
    batches = {}
    for sport, sport_id in (("football", "sr:sport:1"), ("tennis", "sr:sport:5")):
        try:
            events = fetch_sportybet_events(sport_id, SPORTYBET_MARKETS[sport])
            batches[sport] = events
            stats[f"{sport}_events"] = len(events)
        except Exception as exc:
            batches[sport] = []
            stats["fetch_errors"].append(f"{sport}: {exc}")

    fetched_at = stats["fetched_at"]
    for prediction in predictions:
        sport = prediction.get("sport")
        events = batches.get(sport) or []
        if not events:
            prediction["sportybet_market"] = {
                "available": False,
                "provider": "SportyBet NG",
                "reason": "market feed unavailable for this pipeline run",
                "fetched_at": fetched_at,
            }
            prediction["market_insights"] = {"provider": "SportyBet NG", "available": False}
            stats["unmatched"] += 1
            continue
        try:
            event, match = _find_sportybet_match(prediction, events)
            if not event:
                prediction["sportybet_market"] = {
                    "available": False,
                    "provider": "SportyBet NG",
                    "reason": "no sufficiently confident fixture match",
                    "fetched_at": fetched_at,
                }
                prediction["market_insights"] = {"provider": "SportyBet NG", "available": False}
                stats["unmatched"] += 1
                continue
            snapshot = _sportybet_market_snapshot(event, sport)
            snapshot["available"] = True
            snapshot["match"] = match
            prediction["sportybet_market"] = snapshot
            prediction["sportybet_winner_odds"] = {}
            winner = snapshot.get("winner") or {}
            if winner:
                p1_book = winner.get("p1_book")
                p2_book = winner.get("p2_book")
                draw_book = winner.get("draw_book")
                if match["method"] == "reverse":
                    p1_book, p2_book = p2_book, p1_book
                    p1_fair = winner.get("p2_fair_prob")
                    p2_fair = winner.get("p1_fair_prob")
                    p1_fair_odds = winner.get("p2_fair_odds")
                    p2_fair_odds = winner.get("p1_fair_odds")
                else:
                    p1_fair = winner.get("p1_fair_prob")
                    p2_fair = winner.get("p2_fair_prob")
                    p1_fair_odds = winner.get("p1_fair_odds")
                    p2_fair_odds = winner.get("p2_fair_odds")
                prediction["sportybet_winner_odds"] = {
                    "p1": round(p1_book, 3) if p1_book else None,
                    "draw": round(draw_book, 3) if draw_book else None,
                    "p2": round(p2_book, 3) if p2_book else None,
                    "fair_p1": round(p1_fair, 6) if p1_fair is not None else None,
                    "fair_draw": round(winner.get("draw_fair_prob"), 6) if winner.get("draw_fair_prob") is not None else None,
                    "fair_p2": round(p2_fair, 6) if p2_fair is not None else None,
                    "fair_odds_p1": round(p1_fair_odds, 3) if p1_fair_odds else None,
                    "fair_odds_draw": round(winner.get("draw_fair_odds"), 3) if winner.get("draw_fair_odds") else None,
                    "fair_odds_p2": round(p2_fair_odds, 3) if p2_fair_odds else None,
                    "market_id": winner.get("market_id"),
                    "overround": round(float(winner.get("overround") or 0), 6),
                }
            model_probs = prediction.get("probabilities") or {}
            market_winner = prediction.get("sportybet_winner_odds") or {}
            pick = prediction.get("pick")
            model_pick_prob = model_probs.get(pick)
            if pick == "p1":
                fair_prob = market_winner.get("fair_p1")
            elif pick == "p2":
                fair_prob = market_winner.get("fair_p2")
            else:
                fair_prob = market_winner.get("fair_draw")
            total = _pick_sporty_total(snapshot, prediction)
            total_insight = None
            if total:
                total_pick = "over" if ((prediction.get("markets") or {}).get("over_under") or {}).get("pick") == "over" else "under"
                if sport == "tennis":
                    total_pick = ((prediction.get("analytics") or {}).get("total_games") or {}).get("pick") or total_pick
                model_total_prob = (
                    ((prediction.get("markets") or {}).get("over_under") or {}).get("over")
                    if total_pick == "over" and sport == "football"
                    else ((prediction.get("markets") or {}).get("over_under") or {}).get("under")
                    if sport == "football"
                    else ((prediction.get("analytics") or {}).get("total_games") or {}).get("over")
                    if total_pick == "over"
                    else ((prediction.get("analytics") or {}).get("total_games") or {}).get("under")
                )
                market_fair_prob = total.get("over_fair_prob") if total_pick == "over" else total.get("under_fair_prob")
                total_insight = {
                    "line": total.get("line"),
                    "pick": total_pick,
                    "book_odds": total.get("over") if total_pick == "over" else total.get("under"),
                    "fair_prob": market_fair_prob,
                    "fair_odds": total.get("over_fair_odds") if total_pick == "over" else total.get("under_fair_odds"),
                    "model_prob": model_total_prob,
                    "model_edge_vs_market": round(float(model_total_prob) - float(market_fair_prob), 6)
                    if model_total_prob is not None and market_fair_prob is not None else None,
                    "overround": total.get("overround"),
                    "market_id": total.get("market_id"),
                }
            prediction["sportybet_total_market"] = total_insight
            prediction["market_insights"] = {
                "provider": "SportyBet NG",
                "available": True,
                "matched_event_id": snapshot.get("event_id"),
                "match_score": match.get("score"),
                "winner_model_edge_vs_market": (
                    round(float(model_pick_prob) - float(fair_prob), 6)
                    if model_pick_prob is not None and fair_prob is not None else None
                ),
                "winner_model_pick": pick,
                "winner_market_fair_prob": fair_prob,
                "total": total_insight,
                "snapshot_at": snapshot.get("fetched_at"),
            }
            stats["matched"] += 1
        except Exception as exc:
            prediction["sportybet_market"] = {
                "available": False,
                "provider": "SportyBet NG",
                "reason": f"market enrichment error: {exc}",
                "fetched_at": fetched_at,
            }
            prediction["market_insights"] = {"provider": "SportyBet NG", "available": False, "error": str(exc)}
            stats["match_errors"].append(f"{prediction.get('sport')}:{prediction.get('event_id')}: {exc}")
            stats["unmatched"] += 1
    stats["coverage"] = round(stats["matched"] / max(1, len(predictions)), 4)
    return stats


def form_score(form):
    if not form:
        return 0.5
    weights = {"W": 1.0, "D": 0.5, "L": 0.0}
    chars = [c for c in str(form)[-5:] if c in weights]
    return sum(weights[c] for c in chars) / len(chars) if chars else 0.5


def get_odds_market(event):
    try:
        odds = event.get("competitions", [{}])[0].get("odds") or []
        return odds[0] if odds else None
    except (IndexError, TypeError):
        return None


def moneyline_probs(event):
    market = get_odds_market(event)
    if not market:
        return None
    ml = market.get("moneyline") or market.get("moneyLine") or {}
    values = []
    for side in ("home", "draw", "away"):
        node = ml.get(side) or {}
        close = node.get("close") or node.get("open") or {}
        values.append(american_to_prob(close.get("odds")))
    if any(v is None for v in values):
        return None
    return normalise(values)


def total_market(event):
    market = get_odds_market(event)
    if not market:
        return None
    total = market.get("total") or {}
    over = total.get("over") or {}
    under = total.get("under") or {}
    over_close = over.get("close") or over.get("open") or {}
    under_close = under.get("close") or under.get("open") or {}
    line = market.get("overUnder")
    if line is None:
        line_text = over_close.get("line") or under_close.get("line")
        if line_text:
            try:
                line = float(str(line_text)[1:])
            except ValueError:
                line = None
    op = american_to_prob(over_close.get("odds"))
    up = american_to_prob(under_close.get("odds"))
    if line is None or op is None or up is None:
        return None
    probs = normalise([op, up])
    return {"line": float(line), "over_prob": probs[0], "under_prob": probs[1]}


def spread_market(event):
    market = get_odds_market(event)
    if not market:
        return None
    spread = market.get("pointSpread") or {}
    home = spread.get("home") or {}
    away = spread.get("away") or {}
    h = home.get("close") or home.get("open") or {}
    a = away.get("close") or away.get("open") or {}
    try:
        return {"line": float(h.get("line")), "home_odds": h.get("odds"), "away_odds": a.get("odds")}
    except (TypeError, ValueError):
        return None


def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_total_over(line, lam):
    threshold = math.floor(float(line))
    return 1 - sum(poisson_pmf(k, lam) for k in range(threshold + 1))


def infer_total_xg(total):
    if not total:
        return 2.55, "modeled prior"
    target = total["over_prob"]
    lo, hi = 0.4, 5.5
    for _ in range(70):
        mid = (lo + hi) / 2
        if poisson_total_over(total["line"], mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, "market O/U calibrated"


def outcome_probs(lam_home, lam_away, max_goals=10):
    home_probs = [poisson_pmf(k, lam_home) for k in range(max_goals + 1)]
    away_probs = [poisson_pmf(k, lam_away) for k in range(max_goals + 1)]
    home = draw = away = 0.0
    for i, hp in enumerate(home_probs):
        for j, ap in enumerate(away_probs):
            if i > j:
                home += hp * ap
            elif i == j:
                draw += hp * ap
            else:
                away += hp * ap
    return normalise([home, draw, away])


def fit_goal_split(total_xg, target_probs):
    best = (0.5, 0.5, float("inf"))
    for i in range(101):
        share = 0.15 + i * 0.007
        lh = max(0.15, total_xg * share)
        la = max(0.15, total_xg - lh)
        probs = outcome_probs(lh, la)
        err = sum((probs[j] - target_probs[j]) ** 2 for j in range(3))
        if err < best[2]:
            best = (lh, la, err)
    return best[0], best[1]


def btts_probability(lam_home, lam_away):
    return (1 - math.exp(-lam_home)) * (1 - math.exp(-lam_away))


def football_prediction(event, label):
    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])
    if len(competitors) < 2:
        return None
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    market_ml = moneyline_probs(event)
    home_form = form_score(home.get("form"))
    away_form = form_score(away.get("form"))
    if market_ml:
        hp, dp, ap = market_ml
        hp += 0.08 * (home_form - away_form) + 0.015
        ap += 0.08 * (away_form - home_form)
        dp -= 0.02 * abs(home_form - away_form)
        probs = normalise([clamp(hp), clamp(dp), clamp(ap)])
        source = "ESPN market + form + home edge"
    else:
        edge = 0.58 * (home_form - away_form) + 0.10
        hp = 0.46 + edge
        ap = 0.28 - edge * 0.35
        dp = 1 - hp - ap
        probs = normalise([clamp(hp), clamp(dp), clamp(ap)])
        source = "ESPN form model"
    total = total_market(event)
    total_xg, total_source = infer_total_xg(total)
    lh, la = fit_goal_split(total_xg, probs)
    ou_line = total["line"] if total else 2.5
    over_prob = poisson_total_over(ou_line, total_xg)
    under_prob = 1 - over_prob
    btts = btts_probability(lh, la)
    spread = spread_market(event)
    handicap_prob = None
    if spread:
        line = spread["line"]
        cover = 0.0
        hp_dist = [poisson_pmf(k, lh) for k in range(11)]
        ap_dist = [poisson_pmf(k, la) for k in range(11)]
        for i, hprob in enumerate(hp_dist):
            for j, aprob in enumerate(ap_dist):
                if i + line > j:
                    cover += hprob * aprob
        handicap_prob = clamp(cover)
    return {
        "sport": "football", "league": label, "event_id": str(event["id"]), "start_time": event.get("date"),
        "player_1": home.get("team", {}).get("displayName", "Home"), "player_2": away.get("team", {}).get("displayName", "Away"),
        "venue": competition.get("venue", {}).get("fullName"), "surface": "Grass",
        "probabilities": {"p1": round(probs[0], 4), "draw": round(probs[1], 4), "p2": round(probs[2], 4)},
        "pick": ["p1", "draw", "p2"][probs.index(max(probs))], "confidence": round(max(probs), 4),
        "expected_goals": {"p1": round(lh, 2), "p2": round(la, 2), "total": round(total_xg, 2)},
        "markets": {
            "over_under": {"line": ou_line, "over": round(over_prob, 4), "under": round(under_prob, 4), "pick": "over" if over_prob >= under_prob else "under", "source": total_source},
            "btts": {"yes": round(btts, 4), "no": round(1 - btts, 4), "pick": "yes" if btts >= 0.5 else "no", "source": "Poisson xG model"},
        },
        "handicap": {"line": spread["line"] if spread else None, "home_cover": round(handicap_prob, 4) if handicap_prob is not None else None, "away_cover": round(1 - handicap_prob, 4) if handicap_prob is not None else None},
        "model": source,
    }


def flatten_tennis_board(board):
    matches = []
    for tournament in board.get("events", []):
        tournament_name = tournament.get("name") or tournament.get("shortName") or "Tennis"
        for grouping in tournament.get("groupings", []):
            grouping_meta = grouping.get("grouping", {})
            for comp in grouping.get("competitions", []):
                comp["tournament_name"] = tournament_name
                comp["draw_type"] = grouping_meta.get("displayName") or grouping_meta.get("slug")
                matches.append(comp)
    return matches


def tennis_rankings(tour):
    try:
        board = get_json(f"{ESPN}/tennis/{tour.lower()}/rankings")
        ranks = {}
        for ranking in board.get("rankings", []):
            for item in ranking.get("ranks", []):
                athlete = item.get("athlete", {})
                if athlete.get("id"):
                    ranks[str(athlete["id"])] = int(item.get("current"))
        return ranks
    except Exception:
        return {}


GENERIC_TENNIS_NAMES = {"", "player 1", "player 2", "tbd", "tba", "unknown", "unknown player", "team 1", "team 2"}
DOUBLES_DRAW_MARKERS = ("double", "doubles", "mixed", "team")


def tennis_fixture_quality(event):
    draw_type = str(event.get("draw_type") or "").strip().lower()
    if any(marker in draw_type for marker in DOUBLES_DRAW_MARKERS):
        return False, "non-singles draw"
    competitors = event.get("competitors", [])
    if len(competitors) != 2:
        return False, "not exactly two competitors"
    names = []
    for competitor in competitors:
        athlete = competitor.get("athlete") or {}
        name = (athlete.get("displayName") or competitor.get("displayName") or "").strip()
        if not athlete.get("id"):
            return False, "missing athlete id"
        if name.lower() in GENERIC_TENNIS_NAMES or len(name) < 3:
            return False, "missing real player name"
        names.append(name)
    if names[0].lower() == names[1].lower():
        return False, "duplicate player names"
    return True, None


def tennis_competitors(event):
    competitors = event.get("competitors", [])
    return competitors[:2] if len(competitors) >= 2 else None


def tennis_match_probability(rank1, rank2, form1=0.5, form2=0.5):
    if rank1 and rank2:
        rank_edge = math.log((rank2 + 4) / (rank1 + 4))
        rank_prob = 1 / (1 + math.exp(-1.35 * rank_edge))
    else:
        rank_prob = 0.5
    form_edge = 0.12 * (form1 - form2)
    return clamp(0.88 * rank_prob + form_edge + 0.06)


def solve_set_probability(match_prob):
    lo, hi = 0.001, 0.999
    for _ in range(70):
        q = (lo + hi) / 2
        p = 3 * q * q - 2 * q * q * q
        if p < match_prob:
            lo = q
        else:
            hi = q
    return (lo + hi) / 2


def tennis_prediction(event, tour, rankings, form_map):
    pair = tennis_competitors(event)
    if not pair:
        return None
    p1, p2 = pair
    a1, a2 = p1.get("athlete", {}), p2.get("athlete", {})
    id1, id2 = str(p1.get("id", "")), str(p2.get("id", ""))
    name1 = a1.get("displayName") or p1.get("displayName")
    name2 = a2.get("displayName") or p2.get("displayName")
    if not name1 or not name2:
        return None
    rank1 = rankings.get(id1) or p1.get("rank") or a1.get("rank")
    rank2 = rankings.get(id2) or p2.get("rank") or a2.get("rank")
    f1 = form_map.get(id1, {}).get("score", 0.5)
    f2 = form_map.get(id2, {}).get("score", 0.5)
    probability = tennis_match_probability(rank1, rank2, f1, f2)
    p1_prob, p2_prob = probability, 1 - probability
    q = solve_set_probability(p1_prob)
    straight1 = q * q
    straight2 = (1 - q) ** 2
    three_sets = 2 * q * (1 - q)
    expected_sets = 2 + three_sets
    competitiveness = 1.0 - 2.0 * abs(q - 0.5)
    expected_games_per_set = 9.5 + 1.5 * competitiveness
    expected_total_games = expected_games_per_set * expected_sets
    total_line = 22.5
    over_games = 1 / (1 + math.exp(-(expected_total_games - total_line) / 2.5))
    p1_games = 6.2 * q + 5.4 * (1 - q)
    p2_games = 6.2 * (1 - q) + 5.4 * q
    handicap = p1_games - p2_games
    # ESPN's tennis competitor order is not a reliable display order for our
    # public feed. Keep the model calculation above exactly as-is, then swap the
    # player slots as a presentation/data-mapping correction. Every player-linked
    # probability, ranking, form and handicap value moves with that player, so the
    # prediction itself is not recalculated or changed.
    return {
        "sport": "tennis", "league": tour, "event_id": str(event.get("id")), "start_time": event.get("date"),
        "player_1": name2, "player_2": name1, "venue": event.get("venue", {}).get("fullName"),
        "surface": event.get("surface") or "Unknown", "tournament": event.get("tournament_name") or tour,
        "round": event.get("round", {}).get("displayName"), "rankings": {"p1": rank2, "p2": rank1},
        "form": {"p1": round(f2, 3), "p2": round(f1, 3), "p1_last10": form_map.get(id2, {}).get("record", ""), "p2_last10": form_map.get(id1, {}).get("record", "")},
        "probabilities": {"p1": round(p2_prob, 4), "p2": round(p1_prob, 4)}, "pick": "p1" if p2_prob >= p1_prob else "p2", "confidence": round(max(p1_prob, p2_prob), 4),
        "analytics": {
            "set_win_prob": {"p1": round(1 - q, 4), "p2": round(q, 4)},
            "straight_sets": {"p1": round(straight2, 4), "p2": round(straight1, 4)},
            "three_sets": round(three_sets, 4), "expected_sets": round(expected_sets, 2), "expected_games": round(expected_total_games, 2),
            "total_games": {"line": total_line, "over": round(over_games, 4), "under": round(1 - over_games, 4), "pick": "over" if over_games >= 0.5 else "under", "base_model_over": round(over_games, 4), "base_model_under": round(1 - over_games, 4), "source": "fixture-specific continuous set/game model"},
            "games_handicap": {"estimated_margin_p1": round(-handicap, 2), "pick": "p1" if handicap <= 0 else "p2"},
        },
        "model": "ESPN fixture + ATP/WTA ranking + recent form",
    }


def fetch_scoreboard(sport, league, date_range=None):
    params = {"dates": date_range} if date_range else None
    return get_json(f"{ESPN}/{sport}/{league}/scoreboard", params=params)


def build_tennis_form(tour, start_date, end_date):
    form = {}
    if end_date < start_date:
        return form
    try:
        board = fetch_scoreboard("tennis", tour.lower(), f"{start_date:%Y%m%d}-{end_date:%Y%m%d}")
        for event in flatten_tennis_board(board):
            if not event.get("status", {}).get("type", {}).get("completed"):
                continue
            if not tennis_fixture_quality(event)[0]:
                continue
            pair = tennis_competitors(event)
            if not pair:
                continue
            for c in pair:
                pid = str(c.get("id", ""))
                if not pid:
                    continue
                bucket = form.setdefault(pid, {"results": []})
                bucket["results"].append("W" if c.get("winner") else "L")
        for bucket in form.values():
            recent = bucket["results"][-10:]
            bucket["score"] = sum(r == "W" for r in recent) / len(recent) if recent else 0.5
            bucket["record"] = "".join(recent)
    except Exception:
        pass
    return form


def fetch_current_predictions():
    predictions, errors = [], []
    qc = {"rejected_total": 0, "rejected_by_reason": {}, "rejected_by_tour": {}}

    def record_rejection(tour, reason):
        qc["rejected_total"] += 1
        qc["rejected_by_reason"][reason] = qc["rejected_by_reason"].get(reason, 0) + 1
        tour_bucket = qc["rejected_by_tour"].setdefault(tour, {})
        tour_bucket[reason] = tour_bucket.get(reason, 0) + 1

    # Football uses an extended 22-day forward-planning window so the desk can
    # calculate the next scheduled league round even across international breaks.
    today = datetime.now(timezone.utc).date()
    football_end = today + timedelta(days=21)
    for label, league in FOOTBALL_LEAGUES.items():
        try:
            seen_events = set()
            for day_offset in range(22):
                date = today + timedelta(days=day_offset)
                board = fetch_scoreboard("soccer", league, date.strftime("%Y%m%d"))
                for event in board.get("events", []):
                    event_id = str(event.get("id") or "")
                    if event_id and event_id in seen_events:
                        continue
                    if event_id:
                        seen_events.add(event_id)
                    if event.get("status", {}).get("type", {}).get("completed"):
                        continue
                    prediction = football_prediction(event, label)
                    if prediction:
                        predictions.append(prediction)
        except Exception as exc:
            errors.append(f"football:{label}:{exc}")
    tennis_end = today + timedelta(days=7)
    form_start = today - timedelta(days=60)
    for tour in TENNIS_LEAGUES:
        try:
            board = fetch_scoreboard("tennis", tour.lower(), f"{today:%Y%m%d}-{tennis_end:%Y%m%d}")
            rankings = tennis_rankings(tour)
            form_map = build_tennis_form(tour, form_start, today - timedelta(days=1))
            accepted_for_tour = 0
            for event in flatten_tennis_board(board):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                valid, reason = tennis_fixture_quality(event)
                if not valid:
                    record_rejection(tour, reason)
                    continue
                prediction = tennis_prediction(event, tour, rankings, form_map)
                if prediction:
                    predictions.append(prediction)
                    accepted_for_tour += 1
                else:
                    record_rejection(tour, "prediction construction failed")
            if accepted_for_tour == 0:
                errors.append(f"tennis:{tour}:no valid singles matches in next 7 days")
        except Exception as exc:
            errors.append(f"tennis:{tour}:{exc}")
    predictions.sort(key=lambda p: (p.get("start_time") or "", p["sport"], p["player_1"]))
    return predictions, errors, qc


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def settle_predictions(history):
    today = datetime.now(timezone.utc).date()
    pending = [p for p in history if not p.get("settled") and p.get("start_time")]
    # Settle finished events from today as well as prior days. The previous
    # < today guard left same-day finished tennis matches pending until the
    # following day, which made the Odds Builder show completed matches as LIVE.
    dates = sorted({p["start_time"][:10] for p in pending if p["start_time"][:10] <= today.isoformat()})[-10:]
    if not dates:
        return history
    boards = {}
    for date in dates:
        for label, league in FOOTBALL_LEAGUES.items():
            try:
                for event in fetch_scoreboard("soccer", league, date).get("events", []):
                    boards["football:" + str(event["id"])] = event
            except Exception:
                pass
        for tour in TENNIS_LEAGUES:
            try:
                for event in flatten_tennis_board(fetch_scoreboard("tennis", tour.lower(), date)):
                    boards["tennis:" + str(event["id"])] = event
            except Exception:
                pass
    for prediction in history:
        if prediction.get("settled"):
            continue
        event = boards.get(f"{prediction['sport']}:{prediction['event_id']}")
        if not event or not event.get("status", {}).get("type", {}).get("completed"):
            continue
        competitors = event.get("competitors", [])
        if len(competitors) < 2:
            continue
        try:
            if prediction["sport"] == "football":
                home = next(c for c in competitors if c.get("homeAway") == "home")
                away = next(c for c in competitors if c.get("homeAway") == "away")
                hs, ass = float(home.get("score", 0)), float(away.get("score", 0))
                actual = "p1" if hs > ass else "p2" if ass > hs else "draw"
                line = float(prediction.get("markets", {}).get("over_under", {}).get("line", 2.5))
                prediction["actual_markets"] = {"over_under": "over" if hs + ass > line else "under", "btts": "yes" if hs > 0 and ass > 0 else "no"}
                prediction["final_score"] = [hs, ass]
            else:
                # Tennis public-feed player slots are corrected at prediction time,
                # so settlement must resolve the winner by player identity rather
                # than assuming ESPN competitor[0] is prediction p1.
                def tennis_name(competitor):
                    athlete = competitor.get("athlete") or {}
                    return str(athlete.get("displayName") or competitor.get("displayName") or "").strip().lower()

                pred_p1 = str(prediction.get("player_1") or "").strip().lower()
                pred_p2 = str(prediction.get("player_2") or "").strip().lower()
                score_by_name = {}
                winner_name = None
                for competitor in competitors[:2]:
                    name = tennis_name(competitor)
                    score = sum(float(x.get("value", 0)) for x in competitor.get("linescores", []))
                    score_by_name[name] = score
                    if competitor.get("winner"):
                        winner_name = name
                if winner_name == pred_p1:
                    actual = "p1"
                elif winner_name == pred_p2:
                    actual = "p2"
                else:
                    # Backward-compatible fallback for legacy records whose names
                    # still followed the raw ESPN competitor order.
                    actual = "p1" if competitors[0].get("winner") else "p2"
                s1 = score_by_name.get(pred_p1, 0.0)
                s2 = score_by_name.get(pred_p2, 0.0)
                total_games = s1 + s2
                total_info = prediction.get("analytics", {}).get("total_games", {})
                line = float(total_info.get("line", 22.5))
                total_result = "over" if total_games > line else "under"
                prediction["actual_markets"] = {
                    "total_games": total_games,
                    "total_games_line": line,
                    "total_games_result": total_result,
                    "total_games_correct": (total_info.get("pick") == total_result),
                    "sets": len(competitors[0].get("linescores", [])),
                }
                prediction["final_score"] = [s1, s2]
            probs = prediction.get("probabilities", {})
            brier = sum((probs.get(k, 0) - (1 if actual == k else 0)) ** 2 for k in probs)
            prediction.update({"settled": True, "settled_at": datetime.now(timezone.utc).isoformat(), "actual": actual, "correct": prediction["pick"] == actual, "brier": round(brier, 6)})
        except (TypeError, ValueError, KeyError):
            continue
    return history


def accuracy_summary(history):
    settled = [p for p in history if p.get("settled")]
    summary = {"settled": len(settled), "correct": sum(bool(p.get("correct")) for p in settled), "accuracy": 0.0, "brier_score": 0.0, "markets": {}}
    if settled:
        summary["accuracy"] = round(summary["correct"] / len(settled), 4)
        summary["brier_score"] = round(sum(float(p.get("brier", 0)) for p in settled) / len(settled), 4)
    for sport in ("football", "tennis"):
        group = [p for p in settled if p.get("sport") == sport]
        summary[sport] = {"settled": len(group), "correct": sum(bool(p.get("correct")) for p in group), "accuracy": round(sum(bool(p.get("correct")) for p in group) / len(group), 4) if group else 0.0}
    return summary


def main():
    print("Match Signal 3.0 — analytical Football + Tennis pipeline")
    history_path = DATA / "prediction_history.json"
    accuracy_path = DATA / "accuracy.json"
    history = load_json(history_path, [])
    history = settle_predictions(history)
    predictions, errors, qc = fetch_current_predictions()
    sportybet_market_status = attach_sportybet_market_layer(predictions)
    calibration_now = datetime.now(timezone.utc)

    # V5: calibrate every new prediction strictly against already-settled
    # historical records. No current/unsettled prediction is allowed into the
    # calibration sample, preventing future-result leakage.
    for prediction in predictions:
        calibrate_prediction(prediction, history, calibration_now)

        if prediction.get("sport") == "tennis":
            total = (prediction.get("analytics") or {}).get("total_games") or {}
            raw_pick = total.get("pick")
            if raw_pick in {"over", "under"}:
                raw_total = float(total.get(raw_pick, 0.5))
                calibrated_total, total_diag = calibrate_binary_market(
                    prediction,
                    raw_total,
                    history,
                    "tennis:total_games",
                    calibration_now,
                )
                total["raw_over"] = round(float(total.get("over", 0.5)), 4)
                total["raw_under"] = round(float(total.get("under", 0.5)), 4)
                total["calibrated_over"] = round(calibrated_total if raw_pick == "over" else 1.0 - calibrated_total, 4)
                total["calibrated_under"] = round(1.0 - total["calibrated_over"], 4)
                total["calibration"] = total_diag
                total["over"] = total["calibrated_over"]
                total["under"] = total["calibrated_under"]
                total["pick"] = "over" if total["over"] >= total["under"] else "under"

        prediction["calculated_at"] = calibration_now.isoformat()
    existing_ids = {p.get("event_id") for p in history if not p.get("settled")}
    for prediction in predictions:
        if prediction["event_id"] not in existing_ids:
            history.append(prediction.copy())
    history = history[-2500:]
    summary = accuracy_summary(history)
    save_json(DATA / "predictions.json", predictions)
    save_json(history_path, history)
    save_json(accuracy_path, {"updated_at": now, "summary": summary, "recent_settled": [p for p in history if p.get("settled")][-50:]})
    if sportybet_market_status.get("fetch_errors"):
        errors.extend("sportybet:" + str(x) for x in sportybet_market_status["fetch_errors"])
    save_json(DATA / "pipeline_status.json", {
        "updated_at": now,
        "prediction_count": len(predictions),
        "football_count": sum(p.get("sport") == "football" for p in predictions),
        "tennis_count": sum(p.get("sport") == "tennis" for p in predictions),
        "errors": errors,
        "quality_control": qc,
        "market_data": sportybet_market_status,
        "data_source": "ESPN public scoreboards + ESPN ATP/WTA rankings + recent 60-day results + SportyBet NG live market layer",
        "free_server_cost": True,
        "model_version": "5.0 historical-calibrated analytical markets + SportyBet market baseline",
    })
    print(f"Predictions: {len(predictions)} | Football: {sum(p.get('sport') == 'football' for p in predictions)} | Tennis: {sum(p.get('sport') == 'tennis' for p in predictions)} | Settled: {summary['settled']} | QC rejected: {qc['rejected_total']}")
    for error in errors:
        print(" -", error)


if __name__ == "__main__":
    main()
