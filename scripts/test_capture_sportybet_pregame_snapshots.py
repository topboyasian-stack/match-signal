#!/usr/bin/env python3
"""Regressions for immutable SportyBet pregame quote capture."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capture_sportybet_pregame_snapshots import (
    exact_snapshot_from_prediction,
    append_snapshots,
    event_matches_prediction_time,
)


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def football_row():
    return {
        "sport": "football",
        "league": "Champions League",
        "event_id": "football-1",
        "player_1": "Home FC",
        "player_2": "Away FC",
        "start_time": (NOW + timedelta(minutes=10)).isoformat(),
        "pick": "p1",
        "confidence": 0.66,
        "probabilities": {"p1": 0.66, "draw": 0.20, "p2": 0.14},
        "model_version": "test-model",
        "market_source": "SportyBet NG",
        "sportybet_winner_odds": {
            "p1": 1.80, "draw": 3.60, "p2": 4.50,
            "market_id": "1",
        },
        "sportybet_market_snapshot": {
            "source": "SportyBet NG",
            "sportybet_event_id": "sb-1",
            "match_type": "event_id",
        },
    }


good = exact_snapshot_from_prediction(football_row(), NOW.isoformat())
assert good is not None
assert good["market_id"] == "1"
assert good["prices"] == {"p1": 1.8, "p2": 4.5, "draw": 3.6}
assert good["quote_age_seconds"] == 600.0

too_early = football_row()
too_early["start_time"] = (NOW + timedelta(minutes=16)).isoformat()
assert exact_snapshot_from_prediction(too_early, NOW.isoformat()) is None

already_started = football_row()
already_started["start_time"] = (NOW - timedelta(seconds=1)).isoformat()
assert exact_snapshot_from_prediction(already_started, NOW.isoformat()) is None

wrong_market = football_row()
wrong_market["sportybet_winner_odds"]["market_id"] = "18"
assert exact_snapshot_from_prediction(wrong_market, NOW.isoformat()) is None

missing_draw = football_row()
missing_draw["sportybet_winner_odds"].pop("draw")
assert exact_snapshot_from_prediction(missing_draw, NOW.isoformat()) is None

wta = football_row()
wta.update({"sport": "tennis", "league": "WTA"})
wta["sportybet_winner_odds"]["market_id"] = "186"
wta["probabilities"] = {"p1": 0.66, "p2": 0.34}
assert exact_snapshot_from_prediction(wta, NOW.isoformat()) is None

atp = football_row()
atp.update({"sport": "tennis", "league": "ATP"})
atp["sportybet_winner_odds"] = {"p1": 1.8, "p2": 2.1, "market_id": "186"}
atp["probabilities"] = {"p1": 0.66, "p2": 0.34}
atp_snapshot = exact_snapshot_from_prediction(atp, NOW.isoformat())
assert atp_snapshot is not None
assert atp_snapshot["market_id"] == "186"

ledger, added = append_snapshots({"snapshots": []}, [good, good])
assert added == 1
assert len(ledger["snapshots"]) == 1
ledger, added = append_snapshots(ledger, [good])
assert added == 0
assert len(ledger["snapshots"]) == 1


kickoff = datetime.fromisoformat(football_row()["start_time"])
event_ms = int(kickoff.timestamp() * 1000)
same_fixture = {"estimateStartTime": event_ms}
nearby_fixture = {"estimateStartTime": event_ms + 4 * 60 * 1000}
wrong_fixture = {"estimateStartTime": event_ms + 6 * 60 * 1000}
assert event_matches_prediction_time(football_row(), same_fixture)
assert event_matches_prediction_time(football_row(), nearby_fixture)
assert not event_matches_prediction_time(football_row(), wrong_fixture)
assert not event_matches_prediction_time(football_row(), {"estimateStartTime": "bad"})

print("Immutable SportyBet pregame capture regressions passed.")
