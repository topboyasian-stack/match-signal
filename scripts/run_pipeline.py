"""Authoritative Match Signal pipeline runner with production tennis QC."""
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


ns = runpy.run_path("scripts/predict_today.py")
fetch_scoreboard = ns["fetch_scoreboard"]
flatten_tennis_board = ns["flatten_tennis_board"]
tennis_rankings = ns["tennis_rankings"]
build_tennis_form = ns["build_tennis_form"]
tennis_prediction = ns["tennis_prediction"]
football_prediction = ns["football_prediction"]
settle_predictions = ns["settle_predictions"]
accuracy_summary = ns["accuracy_summary"]
load_json = ns["load_json"]
save_json = ns["save_json"]
DATA = ns["DATA"]
FOOTBALL_LEAGUES = ns["FOOTBALL_LEAGUES"]
TENNIS_LEAGUES = ns["TENNIS_LEAGUES"]


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


def main():
    print("Match Signal 3.0 — analytical Football + Tennis pipeline with fixture QC")
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
        "data_source": "ESPN public scoreboards + ESPN ATP/WTA rankings",
        "free_server_cost": True,
        "model_version": "3.0 analytical markets",
    })
    print(f"Predictions: {len(predictions)} | Football: {sum(p.get('sport') == 'football' for p in predictions)} | Tennis: {sum(p.get('sport') == 'tennis' for p in predictions)} | Settled: {summary['settled']} | QC rejected: {qc['rejected_total']}")
    for error in errors:
        print(" -", error)


if __name__ == "__main__":
    main()
