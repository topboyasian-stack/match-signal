"""Production pipeline entrypoint with ESPN-aware tennis quality control."""
import runpy
from datetime import datetime, timedelta, timezone

GENERIC_NAMES = {"", "player 1", "player 2", "tbd", "tba", "unknown", "unknown player", "team 1", "team 2"}
DOUBLES_MARKERS = ("double", "doubles", "mixed", "team")


def tennis_fixture_quality(event):
    draw_type = str(event.get("draw_type") or "").strip().lower()
    if any(marker in draw_type for marker in DOUBLES_MARKERS):
        return False, "non-singles draw"
    competitors = event.get("competitors", [])
    if len(competitors) != 2:
        return False, "not exactly two competitors"
    names = []
    for competitor in competitors:
        athlete = competitor.get("athlete") or {}
        name = (athlete.get("displayName") or competitor.get("displayName") or "").strip()
        lowered = name.lower()
        if lowered in GENERIC_NAMES or len(name) < 3:
            return False, "missing real player name"
        if " / " in name or " & " in name:
            return False, "non-singles competitor"
        names.append(name)
    if names[0].lower() == names[1].lower():
        return False, "duplicate player names"
    return True, None


namespace = runpy.run_path("scripts/predict_today.py")
fetch_scoreboard = namespace["fetch_scoreboard"]
flatten_tennis_board = namespace["flatten_tennis_board"]
tennis_rankings = namespace["tennis_rankings"]
build_tennis_form = namespace["build_tennis_form"]
tennis_prediction = namespace["tennis_prediction"]
football_prediction = namespace["football_prediction"]
FOOTBALL_LEAGUES = namespace["FOOTBALL_LEAGUES"]
TENNIS_LEAGUES = namespace["TENNIS_LEAGUES"]


def fetch_current_predictions():
    predictions, errors = [], []
    qc = {"rejected_total": 0, "rejected_by_reason": {}, "rejected_by_tour": {}}

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
            form_map = build_tennis_form(tour, form_start, today - timedelta(days=1))
            accepted = 0
            for event in flatten_tennis_board(board):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                valid, reason = tennis_fixture_quality(event)
                if not valid:
                    reject(tour, reason)
                    continue
                prediction = tennis_prediction(event, tour, rankings, form_map)
                if prediction:
                    predictions.append(prediction)
                    accepted += 1
                else:
                    reject(tour, "prediction construction failed")
            if accepted == 0:
                errors.append(f"tennis:{tour}:no valid singles matches in next 7 days")
        except Exception as exc:
            errors.append(f"tennis:{tour}:{exc}")

    predictions.sort(key=lambda p: (p.get("start_time") or "", p["sport"], p["player_1"]))
    return predictions, errors, qc


namespace["fetch_current_predictions"] = fetch_current_predictions
namespace["main"]()
