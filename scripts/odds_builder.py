"""Match Signal V6 market-calibrated value engine.

Research/paper-trading only. A candidate is eligible only when:
- calibrated model probability clears the minimum threshold,
- a fresh SportyBet price is actually present,
- bookmaker margin is removed where a complete market is available,
- model edge clears the V6 threshold,
- data/price freshness and uncertainty gates pass,
- correlated selections are not duplicated in the same accumulator.

No wager is placed and no 3-4 leg target is forced.
"""
from __future__ import annotations
import json, math, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
CANDIDATES=DATA/"selection_candidates.json"
PREDICTIONS=DATA/"predictions.json"
OUTPUT=DATA/"odds_builder.json"
HISTORY=DATA/"prediction_history.json"
SELECTION_GATE=DATA/"selection_gate.json"
RISK_GATE=DATA/"risk_gate.json"

MIN_PROB=0.60
MIN_EDGE=0.025
MAX_ODDS_AGE_SECONDS=900
MAX_UNCERTAINTY=0.22
MIN_DATA_QUALITY=0.70
MIN_LEGS,MAX_LEGS=1,16
# Accuracy-first construction: 4.00+ remains a target, not a reason to add
# weaker legs. A lower-odds ticket is allowed when it materially preserves
# whole-ticket model probability.
TARGET_COMBINED_ODDS=4.0
MIN_ACCURACY_FIRST_ODDS=2.0
ACCURACY_PRESERVATION_RATIO=0.90
MIN_COMBINED_ODDS=MIN_ACCURACY_FIRST_ODDS
VIRTUAL_MIN_PROB=0.65
TICKET_SPOILER_MIN_SAMPLE=50
TICKET_SPOILER_MIN_ACCURACY=0.90
PARTICIPANT_HISTORY_MIN_N=3
PARTICIPANT_HISTORY_MAX_BONUS=0.035
MAX_BATCHES=6
# Keep Builder candidates close to kickoff so participant evidence and market prices can be refreshed.
MAX_BUILDER_HORIZON_MINUTES=180
MAX_BATCH_KICKOFF_SPAN_MINUTES=60


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):
        return default


def kickoff_age_minutes(x, now):
    try:
        raw=x.get("start_time")
        if not raw:return None
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(timezone.utc)
        return (dt-now).total_seconds()/60.0
    except (TypeError,ValueError):
        return None


def within_builder_horizon(x, now):
    minutes=kickoff_age_minutes(x,now)
    return minutes is not None and 0.0 < minutes <= MAX_BUILDER_HORIZON_MINUTES


def upcoming(x, now):
    try:
        raw=x.get("start_time")
        if not raw:return False
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        return dt.astimezone(timezone.utc)>now
    except (TypeError,ValueError):
        return False


def fair_odds(p):
    return round(1.0/float(p),3) if float(p)>0 else 0.0

