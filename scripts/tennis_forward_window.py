"""Extend tennis fixture discovery beyond the daily 7-day board.

The production tennis model remains limited to ATP/WTA singles. This companion
step looks 14 days ahead so upcoming tour events are not invisible simply because
ESPN has not placed them inside the original 7-day window yet. It never fabricates
fixtures and never adds doubles or placeholder players.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predict_today import (
    TENNIS_LEAGUES,
    build_tennis_form,
    fetch_scoreboard,
    flatten_tennis_board,
    tennis_fixture_quality,
    tennis_prediction,
    tennis_rankings,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main() -> None:
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=14)
    form_start = today - timedelta(days=60)
    predictions = load(DATA / "predictions.json", [])
    if not isinstance(predictions, list):
        predictions = []

    existing = {str(p.get("event_id")) for p in predictions if p.get("event_id")}
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 14,
        "scope": "ATP/WTA singles only",
        "tours": {},
    }

    for tour in TENNIS_LEAGUES:
        bucket = {"source": "ESPN public tennis scoreboard", "events_seen": 0, "valid_singles": 0, "new_predictions": 0, "rejected": {}, "error": None}
        try:
            board = fetch_scoreboard("tennis", tour.lower(), f"{today:%Y%m%d}-{end:%Y%m%d}")
            rankings = tennis_rankings(tour)
            form_map = build_tennis_form(tour, form_start, today - timedelta(days=1))
            for event in flatten_tennis_board(board):
                if event.get("status", {}).get("type", {}).get("completed"):
                    continue
                bucket["events_seen"] += 1
                valid, reason = tennis_fixture_quality(event)
                if not valid:
                    bucket["rejected"][reason] = bucket["rejected"].get(reason, 0) + 1
                    continue
                bucket["valid_singles"] += 1
                event_id = str(event.get("id") or "")
                if not event_id or event_id in existing:
                    continue
                prediction = tennis_prediction(event, tour, rankings, form_map)
                if not prediction:
                    bucket["rejected"]["prediction construction failed"] = bucket["rejected"].get("prediction construction failed", 0) + 1
                    continue
                prediction["coverage"] = {
                    "discovery_window_days": 14,
                    "fixture_source": "ESPN public tennis scoreboard",
                    "model_scope": "ATP/WTA singles only",
                }
                predictions.append(prediction)
                existing.add(event_id)
                bucket["new_predictions"] += 1
        except Exception as exc:
            bucket["error"] = str(exc)
        status["tours"][tour] = bucket

    predictions.sort(key=lambda p: (p.get("start_time") or "", p.get("sport") or "", p.get("player_1") or ""))
    DATA.joinpath("predictions.json").write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    DATA.joinpath("tennis_forward_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
