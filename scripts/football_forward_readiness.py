"""Build the football forward-planning readiness artifact.

This is a planning-state layer, not a model-qualification layer.
A competition may be CALCULATING when it has usable prior evidence and an
upcoming fixture window, even while its stricter model validation remains
research/validation-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import runpy

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "football_forward_readiness.json"
PLANNING_DAYS = 21

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

CORE_LEAGUES = {
    "EPL": "eng.1",
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Serie A": "ita.1",
    "Ligue 1": "fra.1",
    "Champions League": "uefa.champions",
    "MLS": "usa.1",
    "Primeira Liga": "por.1",
}

AUXILIARY_ESPN_LEAGUES = {
    "Eredivisie": "ned.1",
}

GENERIC_ERROR = "provider lookup unavailable; status derived from published artifacts"


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def upcoming_count(rows, now):
    count = 0
    for row in rows:
        dt = parse_time(row.get("start_time"))
        if dt and dt >= now and not row.get("settled"):
            count += 1
    return count


PREDICT_NS = runpy.run_path(str(ROOT / "scripts" / "predict_today.py"))
FETCH_SCOREBOARD = PREDICT_NS["fetch_scoreboard"]


def espn_upcoming_count(league_code, now):
    """Count real scheduled ESPN fixtures using the production ESPN client."""
    today = now.date()
    total = 0
    seen = set()
    errors = []

    for offset in range(PLANNING_DAYS + 1):
        day = today + timedelta(days=offset)
        try:
            body = FETCH_SCOREBOARD("soccer", league_code, day.strftime("%Y%m%d"))
            for event in body.get("events", []):
                event_id = str(event.get("id") or "")
                if event_id and event_id in seen:
                    continue
                if event_id:
                    seen.add(event_id)

                status = (event.get("status") or {}).get("type") or {}
                if status.get("completed"):
                    continue

                start = parse_time(event.get("date"))
                if start is None or start >= now:
                    total += 1
        except Exception as exc:
            errors.append(str(exc))

    return total, errors


def artifact_count(rows, league, sport="football"):
    return sum(
        1
        for row in rows
        if row.get("sport") == sport and row.get("league") == league
    )


def historical_count(history, performance, league):
    by_perf = performance.get("by_league") or {} if isinstance(performance, dict) else {}
    perf = by_perf.get(league) or {}
    settled = int(perf.get("settled") or 0)
    if settled:
        return settled
    return sum(
        1
        for row in history
        if row.get("sport") == "football"
        and row.get("league") == league
        and row.get("settled")
    )


def main():
    now = datetime.now(timezone.utc)
    predictions = load("predictions.json", [])
    history = load("prediction_history.json", [])
    performance = load("football_performance.json", {})
    pdl_status = load("pdl_status.json", {})
    pdl_predictions = load("pdl_predictions.json", [])
    expansion_status = load("expansion_status.json", {})
    saudi_status = load("saudi_pro_league_status.json", {})

    expansion_comps = (
        expansion_status.get("competitions")
        or expansion_status.get("leagues")
        or {}
    ) if isinstance(expansion_status, dict) else {}

    records = []

    for league in LEAGUES:
        rows = [
            row for row in predictions
            if row.get("sport") == "football" and row.get("league") == league
        ]
        published = len(rows)
        published_upcoming = upcoming_count(rows, now)
        historical = 0
        upcoming = published_upcoming
        errors = []
        source = "published prediction artifact"

        if league in CORE_LEAGUES:
            historical = historical_count(history, performance, league)
            if upcoming == 0:
                provider_upcoming, provider_errors = espn_upcoming_count(
                    CORE_LEAGUES[league], now
                )
                upcoming = provider_upcoming
                errors.extend(provider_errors)
                source = (
                    "ESPN day-by-day forward fixture scan"
                    if provider_upcoming
                    else GENERIC_ERROR
                )

        elif league == "Eredivisie":
            meta = expansion_comps.get(league) if isinstance(expansion_comps, dict) else None
            if isinstance(meta, dict):
                historical = int(
                    meta.get("historical_events")
                    or meta.get("historical_rows")
                    or 0
                )
                upstream = int(meta.get("current_fixtures") or 0)
                if upcoming == 0 and upstream > 0:
                    upcoming = upstream
                    source = "expansion-status current fixture feed"

            if historical == 0:
                ere_history = load("ere_divisie_history.json", [])
                historical = len(ere_history) if isinstance(ere_history, list) else 0

            # Expansion status can legitimately be zero while a real future
            # round is already scheduled upstream. Verify it independently.
            if upcoming == 0:
                provider_upcoming, provider_errors = espn_upcoming_count(
                    AUXILIARY_ESPN_LEAGUES[league], now
                )
                upcoming = provider_upcoming
                errors.extend(provider_errors)
                source = (
                    "ESPN day-by-day forward fixture scan"
                    if provider_upcoming
                    else source
                )

        elif league == "Saudi Pro League":
            status_source = saudi_status if isinstance(saudi_status, dict) else {}
            historical = sum(
                1
                for row in history
                if row.get("sport") == "football"
                and row.get("league") == league
                and row.get("settled")
            )
            upstream = int(status_source.get("current_fixtures") or 0)
            if upcoming == 0 and upstream > 0:
                upcoming = upstream
                source = "Saudi Pro League status feed"

        else:
            pdl_current = len(pdl_predictions) if isinstance(pdl_predictions, list) else 0
            pdl_upcoming = int(pdl_status.get("current_upcoming") or pdl_current or 0)
            historical = int(pdl_status.get("historical_rows") or 0)
            upcoming = max(pdl_upcoming, published_upcoming)
            source = "PDL dedicated fixture/model feed"

            if upcoming > 0 and historical >= 5:
                status = (
                    "CALCULATING"
                    if pdl_current > 0
                    else "CALCULATING_PENDING_PUBLICATION"
                )
            elif upcoming > 0:
                status = "SCHEDULED_ONLY"
            else:
                status = "MONITORING"

            records.append({
                "league": league,
                "status": status,
                "published_predictions": pdl_current,
                "upcoming_fixtures": upcoming,
                "historical_observations": historical,
                "model_qualified": False,
                "paper_only": True,
                "source": source,
                "provider_errors": errors[:3],
                "reason": (
                    "Dedicated PDL engine; planning readiness is separate "
                    "from walk-forward qualification."
                ),
            })
            continue

        if upcoming > 0 and historical >= 5:
            status = "CALCULATING"
        elif upcoming > 0 and historical > 0:
            status = "PROVISIONAL"
        elif upcoming > 0:
            status = "SCHEDULED_ONLY"
        else:
            status = "MONITORING"

        records.append({
            "league": league,
            "status": status,
            "published_predictions": published,
            "upcoming_fixtures": upcoming,
            "historical_observations": historical,
            "model_qualified": False,
            "paper_only": True,
            "source": source,
            "provider_errors": errors[:3],
            "reason": "Forward planning readiness is independent of strict model qualification.",
        })

    payload = {
        "generated_at": iso_now(),
        "mode": "PAPER_RESEARCH_ONLY",
        "planning_window_days": PLANNING_DAYS,
        "qualification_is_separate": True,
        "provider_policy": (
            "Use published rows when present; otherwise verify forward "
            "fixtures directly from the dedicated upstream feed."
        ),
        "statuses": records,
    }

    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
