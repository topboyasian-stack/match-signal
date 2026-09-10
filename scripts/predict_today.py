import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

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
}
TENNIS_LEAGUES = {"ATP": "atp", "WTA": "wta"}
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
    expected_total_games = 21.0 + 7.0 * three_sets
    total_line = 22.5
    over_games = 1 / (1 + math.exp(-(expected_total_games - total_line) / 2.0))
    p1_games = 6.2 * q + 5.4 * (1 - q)
    p2_games = 6.2 * (1 - q) + 5.4 * q
    handicap = p1_games - p2_games
    return {
        "sport": "tennis", "league": tour, "event_id": str(event.get("id")), "start_time": event.get("date"),
        "player_1": name1, "player_2": name2, "venue": event.get("venue", {}).get("fullName"),
        "surface": event.get("surface") or "Unknown", "tournament": event.get("tournament_name") or tour,
        "round": event.get("round", {}).get("displayName"), "rankings": {"p1": rank1, "p2": rank2},
        "form": {"p1": round(f1, 3), "p2": round(f2, 3), "p1_last10": form_map.get(id1, {}).get("record", ""), "p2_last10": form_map.get(id2, {}).get("record", "")},
        "probabilities": {"p1": round(p1_prob, 4), "p2": round(p2_prob, 4)}, "pick": "p1" if p1_prob >= p2_prob else "p2", "confidence": round(max(p1_prob, p2_prob), 4),
        "analytics": {
            "set_win_prob": {"p1": round(q, 4), "p2": round(1 - q, 4)},
            "straight_sets": {"p1": round(straight1, 4), "p2": round(straight2, 4)},
            "three_sets": round(three_sets, 4), "expected_sets": round(expected_sets, 2),
            "total_games": {"line": total_line, "over": round(over_games, 4), "under": round(1 - over_games, 4), "pick": "over" if over_games >= 0.5 else "under"},
            "games_handicap": {"estimated_margin_p1": round(handicap, 2), "pick": "p1" if handicap >= 0 else "p2"},
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

    for label, league in FOOTBALL_LEAGUES.items():
        try:
            board = fetch_scoreboard("soccer", league)
            for event in board.get("events", []):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                prediction = football_prediction(event, label)
                if prediction:
                    predictions.append(prediction)
        except Exception as exc:
            errors.append(f"football:{label}:{exc}")
    today = datetime.now(timezone.utc).date()
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
    dates = sorted({p["start_time"][:10] for p in pending if p["start_time"][:10] < today.isoformat()})[-10:]
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
                c1, c2 = competitors[0], competitors[1]
                s1 = sum(float(x.get("value", 0)) for x in c1.get("linescores", []))
                s2 = sum(float(x.get("value", 0)) for x in c2.get("linescores", []))
                actual = "p1" if c1.get("winner") else "p2"
                prediction["actual_markets"] = {"total_games": s1 + s2, "sets": len(c1.get("linescores", []))}
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
    now = datetime.now(timezone.utc).isoformat()
    for prediction in predictions:
        prediction["calculated_at"] = now
    existing_ids = {p.get("event_id") for p in history if not p.get("settled")}
    for prediction in predictions:
        if prediction["event_id"] not in existing_ids:
            history.append(prediction.copy())
    history = history[-2500:]
    summary = accuracy_summary(history)
    save_json(DATA / "predictions.json", predictions)
    save_json(history_path, history)
    save_json(accuracy_path, {"updated_at": now, "summary": summary, "recent_settled": [p for p in history if p.get("settled")][-50:]})
    save_json(DATA / "pipeline_status.json", {"updated_at": now, "prediction_count": len(predictions), "football_count": sum(p.get("sport") == "football" for p in predictions), "tennis_count": sum(p.get("sport") == "tennis" for p in predictions), "errors": errors, "quality_control": qc, "data_source": "ESPN public scoreboards + ESPN ATP/WTA rankings", "free_server_cost": True, "model_version": "3.0 analytical markets"})
    print(f"Predictions: {len(predictions)} | Football: {sum(p.get('sport') == 'football' for p in predictions)} | Tennis: {sum(p.get('sport') == 'tennis' for p in predictions)} | Settled: {summary['settled']} | QC rejected: {qc['rejected_total']}")
    for error in errors:
        print(" -", error)


if __name__ == "__main__":
    main()
