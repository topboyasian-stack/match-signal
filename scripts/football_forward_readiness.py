"""Build the football forward-planning readiness artifact.

This is a planning-state layer, not a model-qualification layer.
A competition may be CALCULATING when it has usable prior evidence and an
upcoming fixture window, even while its stricter model validation remains
RESEARCH/VALIDATING.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "football_forward_readiness.json"

LEAGUES = [
    "EPL",
    "La Liga",
    "Bundesliga",
    "Serie A",
    "Ligue 1",
    "Champions League",
    "MLS",
    "Primeira Liga",
    "Eredivisie",
    "Saudi Pro League",
    "England Amateur - U21 Professional Development League",
]


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def upcoming_count(rows, now):
    count = 0
    for row in rows:
        try:
            value = str(row.get("start_time") or "").replace("Z", "+00:00")
            if datetime.fromisoformat(value) >= now and not row.get("settled"):
                count += 1
        except Exception:
            continue
    return count


def main():
    now = datetime.now(timezone.utc)
    predictions = load("predictions.json", [])
    history = load("prediction_history.json", [])
    performance = load("football_performance.json", {})
    pdl_status = load("pdl_status.json", {})
    pdl_predictions = load("pdl_predictions.json", [])

    by_perf = (performance.get("by_league") or {}) if isinstance(performance, dict) else {}
    records = []

    for league in LEAGUES:
        rows = [x for x in predictions if x.get("sport") == "football" and x.get("league") == league]
        historical = [x for x in history if x.get("sport") == "football" and x.get("league") == league and x.get("settled")]
        perf = by_perf.get(league) or {}
        settled = int(perf.get("settled") or len(historical) or 0)

        if league == "England Amateur - U21 Professional Development League":
            pdl_current = len(pdl_predictions) if isinstance(pdl_predictions, list) else 0
            pdl_upcoming = int(pdl_status.get("current_upcoming") or pdl_current or 0)
            if pdl_upcoming > 0 and (int(pdl_status.get("historical_rows") or 0) >= 5 or pdl_current > 0):
                status = "CALCULATING" if pdl_current > 0 else "CALCULATING_PENDING_PUBLICATION"
            elif pdl_upcoming > 0:
                status = "SCHEDULED_ONLY"
            else:
                status = "MONITORING"
            records.append({
                "league": league,
                "status": status,
                "published_predictions": pdl_current,
                "upcoming_fixtures": pdl_upcoming,
                "historical_observations": int(pdl_status.get("historical_rows") or 0),
                "model_qualified": False,
                "paper_only": True,
                "reason": "Dedicated PDL engine; planning readiness is separate from walk-forward qualification.",
            })
            continue

        upcoming = upcoming_count(rows, now)
        # Core/experimental leagues with prior settled evidence and an actual
        # forward fixture can be calculated. This is intentionally lower than
        # the stricter research qualification threshold.
        if upcoming > 0 and settled >= 5:
            status = "CALCULATING"
        elif upcoming > 0 and settled > 0:
            status = "PROVISIONAL"
        elif upcoming > 0:
            status = "SCHEDULED_ONLY"
        else:
            status = "MONITORING"

        records.append({
            "league": league,
            "status": status,
            "published_predictions": len(rows),
            "upcoming_fixtures": upcoming,
            "historical_observations": settled,
            "model_qualified": False,
            "paper_only": True,
            "reason": "Forward planning readiness is independent of strict model qualification.",
        })

    payload = {
        "generated_at": iso_now(),
        "mode": "PAPER_RESEARCH_ONLY",
        "planning_window_days": 7,
        "qualification_is_separate": True,
        "statuses": records,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
