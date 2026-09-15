"""Generate Saudi Pro League live-experimental football signals.

Source: ESPN public soccer scoreboard (league id ksa.1).
Fetches a forward window so the Predictions page retains upcoming Saudi fixtures,
while the Live page independently checks ESPN's current scoreboard.
PAPER ONLY; never fabricate fixtures or odds.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predict_today import fetch_scoreboard, football_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEAGUE = "Saudi Pro League"
ESPN_LEAGUE = "ksa.1"
FORWARD_DAYS = 60

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


def main() -> None:
    now = datetime.now(timezone.utc)
    predictions = []
    errors = []
    try:
        end = now + timedelta(days=FORWARD_DAYS)
        date_range = f"{now:%Y%m%d}-{end:%Y%m%d}"
        board = fetch_scoreboard("soccer", ESPN_LEAGUE, date_range)
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
                "paper_only": True,
                "live_experimental": True,
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
        "updated_at": now.isoformat(),
        "league": LEAGUE,
        "competition_id": ESPN_LEAGUE,
        "mode": "LIVE_EXPERIMENTAL",
        "paper_only": True,
        "live_trading_approved": False,
        "forward_window_days": FORWARD_DAYS,
        "current_fixtures": len(predictions),
        "prediction_count": len(predictions),
        "errors": errors,
        "source": "ESPN public soccer scoreboard",
        "no_fabricated_fixtures": True,
    }
    DATA.joinpath("saudi_pro_league_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
