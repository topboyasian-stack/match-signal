"""Generate Saudi Pro League live-experimental football signals.

Source: ESPN public soccer scoreboard (league id ksa.1).
The model remains the existing Match Signal football model; this module adds
Saudi-specific publication metadata and scheduling/tier context. It never
fabricates fixtures or odds.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from predict_today import fetch_scoreboard, football_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEAGUE = "Saudi Pro League"
ESPN_LEAGUE = "ksa.1"

LEVELS = {
    "Level A": {"Al Nassr", "Al Hilal", "Al Ahli", "Al Qadsiah", "Al Ittihad"},
    "Level B": {"Al Taawoun", "Al Ettifaq", "Al Fateh", "Al Khaleej", "Al Shabab"},
    "Level C": {"NEOM Sports Club", "NEOM SC", "Al Hazem", "Al Fayha", "Al Kholood"},
    "Level D": {"Al Riyadh", "Abha", "Al Faisaly", "Diriyah FC"},
}


def team_level(name: str | None) -> str | None:
    for level, teams in LEVELS.items():
        if name in teams:
            return level
    return None


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    predictions = []
    errors = []
    try:
        board = fetch_scoreboard("soccer", ESPN_LEAGUE)
        for event in board.get("events", []):
            if event.get("status", {}).get("type", {}).get("completed"):
                continue
            prediction = football_prediction(event, LEAGUE)
            if not prediction:
                continue
            p1 = prediction.get("player_1")
            p2 = prediction.get("player_2")
            prediction.update({
                "mode": "LIVE_EXPERIMENTAL",
                "live_trading_approved": False,
                "competition_source": "ESPN public soccer scoreboard",
                "competition_id": ESPN_LEAGUE,
                "experimental_context": {
                    "team_tier_p1": team_level(p1),
                    "team_tier_p2": team_level(p2),
                    "tier_source": "Saudi Pro League 2026-27 scheduling classification",
                    "notes": "Tier metadata is contextual only; it does not override the base model probabilities.",
                },
            })
            predictions.append(prediction)
    except Exception as exc:
        errors.append(str(exc))

    predictions.sort(key=lambda p: p.get("start_time") or "")
    DATA.joinpath("saudi_pro_league_predictions.json").write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    status = {
        "updated_at": now,
        "league": LEAGUE,
        "competition_id": ESPN_LEAGUE,
        "mode": "LIVE_EXPERIMENTAL",
        "live_trading_approved": False,
        "current_fixtures": len(predictions),
        "prediction_count": len(predictions),
        "errors": errors,
        "source": "ESPN public soccer scoreboard",
        "no_fabricated_fixtures": True,
    }
    DATA.joinpath("saudi_pro_league_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
