"""Authoritative Match Signal pipeline runner with production tennis QC and model v3.2."""
import runpy
import math
from datetime import datetime, timedelta, timezone

GENERIC_NAMES = {"", "player 1", "player 2", "tbd", "tba", "unknown", "unknown player", "team 1", "team 2"}
DOUBLES_MARKERS = ("double", "doubles", "mixed", "team")
MIN_TENNIS_CONFIDENCE = 0.52


def athlete_identity(competitor):
    athlete = competitor.get("athlete") or {}
    athlete_id = str(athlete.get("id") or competitor.get("id") or "")
    name = (athlete.get("displayName") or competitor.get("displayName") or "").strip()
    return athlete_id, name


def tennis_fixture_quality(event):
    draw_type = str(event.get("draw_type") or "").strip().lower()
    if any(marker in draw_type for marker in DOUBLES_MARKERS):
        return False, "non-singles draw"
    competitors = event.get("competitors", [])
    if len(competitors) != 2:
        return False, "not exactly two competitors"
    names = []
    for competitor in competitors:
        _, name = athlete_identity(competitor)
        lowered = name.lower()
        if lowered in GENERIC_NAMES or len(name) < 3:
            return False, "missing real player name"
        if " / " in name or " & " in name:
            return False, "non-singles competitor"
        names.append(name)
    if names[0].lower() == names[1].lower():
        return False, "duplicate player names"
    return True, None


def canonical_tennis_key(prediction):
    names = sorted([str(prediction.get("player_1", "")).strip().lower(), str(prediction.get("player_2", "")).strip().lower()])
    start = str(prediction.get("start_time") or "")[:16]
    return (start, tuple(names))


def tennis_rank_quality(prediction):
    rankings = prediction.get("rankings") or {}
    return sum(1 for key in ("p1", "p2") if rankings.get(key) not in (None, "", 0))


def dedupe_tennis_predictions(predictions, qc):
    event_groups = {}
    for prediction in predictions:
        if prediction.get("sport") != "tennis":
            continue
        event_id = str(prediction.get("event_id") or "")
        if event_id:
            event_groups.setdefault(event_id, []).append(prediction)

    collapsed = []
    for group in event_groups.values():
        ranked = sorted(group, key=lambda p: (tennis_rank_quality(p), float(p.get("confidence") or 0)), reverse=True)
        collapsed.append(ranked[0])
        qc["deduplicated_matches"] += max(0, len(group) - 1)

    canonical_groups = {}
    for prediction in collapsed:
        canonical_groups.setdefault(canonical_tennis_key(prediction), []).append(prediction)

    kept = []
    for group in canonical_groups.values():
        ranked = sorted(
            group,
            key=lambda p: (
                tennis_rank_quality(p),
                float(p.get("confidence") or 0),
                1 if p.get("league") in {"ATP", "WTA"} else 0,
            ),
            reverse=True,
        )
        winner = ranked[0]
        kept.append(winner)
        removed = ranked[1:]
        if removed:
            qc["deduplicated_matches"] += len(removed)
            if len(qc["deduplicated_examples"]) < 20:
                qc["deduplicated_examples"].append({
                    "match": f"{winner.get('player_1')} vs {winner.get('player_2')}",
                    "kept_tour": winner.get("league"),
                    "removed_tours": [p.get("league") for p in removed],
                })
    return [p for p in predictions if p.get("sport") != "tennis"] + kept


def recent_tennis_form(tour, fetch_scoreboard, flatten_tennis_board, start_date, end_date):
    form = {}
    if end_date < start_date:
        return form
    try:
        board = fetch_scoreboard("tennis", tour.lower(), f"{start_date:%Y%m%d}-{end_date:%Y%m%d}")
        for event in flatten_tennis_board(board):
            if not event.get("status", {}).get("type", {}).get("completed"):
                continue
            valid, _ = tennis_fixture_quality(event)
            if not valid:
                continue
            pair = event.get("competitors", [])[:2]
            if len(pair) != 2:
                continue
            for competitor in pair:
                athlete_id, name = athlete_identity(competitor)
                key = athlete_id or name.lower()
                if not key:
                    continue
                bucket = form.setdefault(key, [])
                bucket.append("W" if competitor.get("winner") else "L")
        result = {}
        for key, results in form.items():
            recent = results[-10:]
            score = sum(r == "W" for r in recent) / len(recent) if recent else 0.5
            result[key] = {"score": score, "record": "".join(recent), "sample": len(recent)}
        return result
    except Exception:
        return {}


def tennis_market_probs(event, american_to_prob, normalise):
    try:
        competition = event.get("competitions", [{}])[0]
        odds = competition.get("odds") or []
        if not odds:
            return None
        market = odds[0]
        ml = market.get("moneyline") or market.get("moneyLine") or {}
        nodes = []
        for side in ("home", "away"):
            node = ml.get(side) or {}
            close = node.get("close") or node.get("open") or {}
            p = american_to_prob(close.get("odds"))
            nodes.append(p)
        if any(p is None for p in nodes):
            return None
        probs = normalise(nodes)
        return {"p1": probs[0], "p2": probs[1], "source": "ESPN market"}
    except (IndexError, TypeError, AttributeError):
        return None


def rank_probability(rank1, rank2):
    if rank1 and rank2:
        edge = math.log((float(rank2) + 5.0) / (float(rank1) + 5.0))
        return 1.0 / (1.0 + math.exp(-1.15 * edge)), 1.0
    if rank1 and not rank2:
        edge = math.log(105.0 / (float(rank1) + 5.0))
        return 1.0 / (1.0 + math.exp(-0.75 * edge)), 0.55
    if rank2 and not rank1:
        edge = math.log((float(rank2) + 5.0) / 105.0)
        return 1.0 / (1.0 + math.exp(-0.75 * edge)), 0.55
    return 0.5, 0.0


def enhanced_tennis_prediction(event, tour, rankings, form_map, base_tennis_prediction, american_to_prob, normalise):
    pair = event.get("competitors", [])[:2]
    if len(pair) != 2:
        return None
    p1, p2 = pair
    id1, name1 = athlete_identity(p1)
    id2, name2 = athlete_identity(p2)
    if not name1 or not name2:
        return None

    rank1 = rankings.get(id1) or p1.get("rank") or (p1.get("athlete") or {}).get("rank")
    rank2 = rankings.get(id2) or p2.get("rank") or (p2.get("athlete") or {}).get("rank")
    f1 = form_map.get(id1) or form_map.get(name1.lower()) or {"score": 0.5, "record": "", "sample": 0}
    f2 = form_map.get(id2) or form_map.get(name2.lower()) or {"score": 0.5, "record": "", "sample": 0}
    form1, form2 = float(f1.get("score", 0.5)), float(f2.get("score", 0.5))

    rank_p, rank_weight = rank_probability(rank1, rank2)
    form_p = 0.5 + 0.20 * (form1 - form2)
    market = tennis_market_probs(event, american_to_prob, normalise)

    if market:
        probability = 0.65 * market["p1"] + 0.25 * rank_p + 0.10 * form_p
        source = "ESPN market + ranking + recent form"
    elif rank_weight >= 1.0:
        probability = 0.80 * rank_p + 0.20 * form_p
        source = "ATP/WTA ranking + recent form"
    elif rank_weight > 0:
        probability = 0.60 * rank_p + 0.40 * form_p
        source = "partial ranking + recent form"
    else:
        probability = form_p
        source = "recent form only"

    probability = max(0.05, min(0.95, probability))
    # Calibration shrinkage keeps small-data signals from becoming fake certainty.
    probability = 0.5 + 0.92 * (probability - 0.5)
    p1_prob, p2_prob = probability, 1 - probability

    # Convert match probability into a per-set win probability for best-of-three analytics.
    lo, hi = 0.001, 0.999
    for _ in range(70):
        q = (lo + hi) / 2
        match_from_set = 3 * q * q - 2 * q * q * q
        if match_from_set < p1_prob:
            lo = q
        else:
            hi = q
    q = (lo + hi) / 2
    straight1, straight2 = q * q, (1 - q) ** 2
    three_sets = 2 * q * (1 - q)
    expected_sets = 2 + three_sets
    expected_total_games = 20.8 + 6.6 * three_sets

    market_line = None
    try:
        market_node = (event.get("competitions", [{}])[0].get("odds") or [])[0]
        market_line = market_node.get("overUnder")
        if market_line is None:
            total = market_node.get("total") or {}
            for side in ("over", "under"):
                close = (total.get(side) or {}).get("close") or (total.get(side) or {}).get("open") or {}
                if close.get("line"):
                    market_line = float(str(close["line"]).replace("+", ""))
                    break
        if market_line is not None:
            market_line = float(market_line)
    except (IndexError, TypeError, ValueError):
        market_line = None
    total_line = market_line or 22.5
    over_games = 1 / (1 + math.exp(-(expected_total_games - total_line) / 1.8))
    games_margin = (6.2 * q + 5.4 * (1 - q)) - (6.2 * (1 - q) + 5.4 * q)

    ranking_gap = None
    if rank1 and rank2:
        ranking_gap = abs(float(rank1) - float(rank2))
    form_gap = abs(form1 - form2)
    signal_components = sum([
        1 if rank1 else 0,
        1 if rank2 else 0,
        1 if f1.get("sample", 0) >= 3 else 0,
        1 if f2.get("sample", 0) >= 3 else 0,
        1 if market else 0,
    ])

    return {
        "sport": "tennis", "league": tour, "event_id": str(event.get("id")), "start_time": event.get("date"),
        "player_1": name1, "player_2": name2, "venue": event.get("venue", {}).get("fullName"),
        "surface": event.get("surface") or "Unknown", "tournament": event.get("tournament_name") or tour,
        "round": event.get("round", {}).get("displayName"),
        "rankings": {"p1": rank1, "p2": rank2, "gap": ranking_gap},
        "form": {"p1": round(form1, 3), "p2": round(form2, 3), "p1_last10": f1.get("record", ""), "p2_last10": f2.get("record", "")},
        "probabilities": {"p1": round(p1_prob, 4), "p2": round(p2_prob, 4)},
        "pick": "p1" if p1_prob >= p2_prob else "p2", "confidence": round(max(p1_prob, p2_prob), 4),
        "analytics": {
            "set_win_prob": {"p1": round(q, 4), "p2": round(1 - q, 4)},
            "straight_sets": {"p1": round(straight1, 4), "p2": round(straight2, 4)},
            "three_sets": round(three_sets, 4), "expected_sets": round(expected_sets, 2),
            "total_games": {"line": total_line, "over": round(over_games, 4), "under": round(1 - over_games, 4), "pick": "over" if over_games >= 0.5 else "under"},
            "games_handicap": {"estimated_margin_p1": round(games_margin, 2), "pick": "p1" if games_margin >= 0 else "p2"},
        },
        "model": source,
        "signal_quality": {"components": signal_components, "max_components": 5, "ranking_gap": ranking_gap, "form_gap": round(form_gap, 3), "market_available": bool(market)},
    }


ns = runpy.run_path("scripts/predict_today.py")
fetch_scoreboard = ns["fetch_scoreboard"]
flatten_tennis_board = ns["flatten_tennis_board"]
tennis_rankings = ns["tennis_rankings"]
base_tennis_prediction = ns["tennis_prediction"]
football_prediction = ns["football_prediction"]
settle_predictions = ns["settle_predictions"]
accuracy_summary = ns["accuracy_summary"]
load_json = ns["load_json"]
save_json = ns["save_json"]
DATA = ns["DATA"]
FOOTBALL_LEAGUES = ns["FOOTBALL_LEAGUES"]
TENNIS_LEAGUES = ns["TENNIS_LEAGUES"]
amercan_to_prob = ns["american_to_prob"]
normalise = ns["normalise"]


def fetch_current_predictions():
    predictions, errors = [], []
    qc = {
        "rejected_total": 0,
        "rejected_by_reason": {},
        "rejected_by_tour": {},
        "deduplicated_matches": 0,
        "deduplicated_examples": [],
        "filtered_low_confidence": 0,
        "filtered_low_confidence_examples": [],
    }

    def reject(tour, reason):
        qc["rejected_total"] += 1
        qc["rejected_by_reason"][reason] = qc["rejected_by_reason"].get(reason, 0) + 1
        bucket = qc["rejected_by_tour"].setdefault(tour, {})
        bucket[reason] = bucket.get(reason, 0) + 1

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
            form_map = recent_tennis_form(tour, fetch_scoreboard, flatten_tennis_board, form_start, today - timedelta(days=1))
            accepted = 0
            for event in flatten_tennis_board(board):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                valid, reason = tennis_fixture_quality(event)
                if not valid:
                    reject(tour, reason)
                    continue
                prediction = enhanced_tennis_prediction(event, tour, rankings, form_map, base_tennis_prediction, amercan_to_prob, normalise)
                if not prediction:
                    reject(tour, "prediction construction failed")
                    continue
                confidence = float(prediction.get("confidence") or 0)
                # A low confidence record is retained only when the model has enough independent signals.
                quality = prediction.get("signal_quality", {}).get("components", 0)
                threshold = 0.52 if quality >= 3 else 0.55
                if confidence < threshold:
                    qc["filtered_low_confidence"] += 1
                    if len(qc["filtered_low_confidence_examples"]) < 20:
                        qc["filtered_low_confidence_examples"].append({
                            "match": f"{prediction.get('player_1')} vs {prediction.get('player_2')}",
                            "tour": tour,
                            "confidence": round(confidence, 4),
                            "signal_components": quality,
                        })
                    continue
                predictions.append(prediction)
                accepted += 1
            if accepted == 0:
                errors.append(f"tennis:{tour}:no actionable singles matches in next 7 days")
        except Exception as exc:
            errors.append(f"tennis:{tour}:{exc}")

    predictions = dedupe_tennis_predictions(predictions, qc)
    predictions.sort(key=lambda p: (p.get("start_time") or "", p["sport"], p["player_1"]))
    return predictions, errors, qc


def main():
    print("Match Signal 3.2 — analytical Football + Tennis pipeline with calibrated tennis signals")
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
    save_json(DATA / "pipeline_status.json", {
        "updated_at": now,
        "prediction_count": len(predictions),
        "football_count": sum(p.get("sport") == "football" for p in predictions),
        "tennis_count": sum(p.get("sport") == "tennis" for p in predictions),
        "errors": errors,
        "quality_control": qc,
        "data_source": "ESPN public scoreboards + ESPN ATP/WTA rankings + recent 60-day results",
        "free_server_cost": True,
        "model_version": "3.2 calibrated tennis signals + fixture QC",
    })
    print(f"Predictions: {len(predictions)} | Football: {sum(p.get('sport') == 'football' for p in predictions)} | Tennis: {sum(p.get('sport') == 'tennis' for p in predictions)} | Settled: {summary['settled']} | QC rejected: {qc['rejected_total']} | Low-confidence filtered: {qc['filtered_low_confidence']} | Deduplicated: {qc['deduplicated_matches']}")
    for error in errors:
        print(" -", error)


if __name__ == "__main__":
    main()
