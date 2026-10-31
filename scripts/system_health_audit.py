#!/usr/bin/env python3
"""System-wide Match Signal health audit.

This is an operational guard, not a model gate. It detects stale engines,
missing forward fixtures, failed sources and publication regressions before a
user has to discover them manually.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from system_health_audit_lib import pdl_health_summary, virtual_live_health_summary, nba_live_observation_health_summary, virtual_participant_history_health_summary

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NOW = datetime.now(timezone.utc)


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def age_hours(value):
    if not value:
        return 999.0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (NOW - dt).total_seconds() / 3600)
    except Exception:
        return 999.0


def issue(code, severity, detail):
    return {"code": code, "severity": severity, "detail": detail}


pipeline = load("pipeline_status.json", {})
odds = load("odds_builder.json", {})
expansion = load("expansion_status.json", {})
virtual = load("virtual_lab_status.json", {})
virtual_live = load("virtual_lab_live.json", {})
nba_live_observations = load("nba_live_observations.json", {})
autopilot = load("autopilot_status.json", {})
darts = load("darts_status.json", {})
table = load("table_tennis_status.json", {})
pdl_status = load("pdl_status.json", {})
unified = load("unified_upcoming.json", {})
tennis_forward = load("tennis_forward_status.json", {})
desk_health = load("prediction_desk_health.json", {})
qa = load("qa/report.json", {})
selection = load("selection_gate.json", {})
predictions_file = DATA / "predictions.json"
accuracy_file = DATA / "accuracy.json"
prediction_rows = []
predictions_valid = False
accuracy_valid = False

try:
    raw = predictions_file.read_text(encoding="utf-8").strip()
    prediction_rows = json.loads(raw) if raw else []
    predictions_valid = isinstance(prediction_rows, list) and len(prediction_rows) > 0
except Exception:
    prediction_rows = []

try:
    raw = accuracy_file.read_text(encoding="utf-8").strip()
    accuracy_valid = bool(json.loads(raw)) if raw else False
except Exception:
    accuracy_valid = False

published_pdl_rows = sum(
    1 for row in prediction_rows
    if isinstance(row, dict)
    and str(row.get("league") or "") == "England Amateur - U21 Professional Development League"
)
pdl_lane, pdl_issues = pdl_health_summary(pdl_status, published_pdl_rows)

checks = []


def freshness(name, payload, field, threshold):
    age = age_hours(payload.get(field))
    status = "PASS" if age <= threshold else "STALE"
    checks.append({"engine": name, "status": status, "age_hours": round(age, 2), "threshold_hours": threshold})
    if status == "STALE":
        return issue("STALE_" + name.upper().replace("-", "_"), "critical", f"{field} age {age:.2f}h exceeds {threshold}h")
    return None


for args in [
    ("core_prediction_pipeline", pipeline, "updated_at", 4),
    ("odds_builder", odds, "generated_at", 8),
    ("expansion", expansion, "updated_at", 4),
    ("unified_upcoming", unified, "generated_at", 2),
]:
    x = freshness(*args)
    if x:
        checks.append(x)

desk_health_stamp = desk_health.get("generated_at")
desk_health_age = age_hours(desk_health_stamp)
desk_health_generated = str(desk_health.get("status") or "") == "GENERATED"
desk_health_fresh = bool(desk_health_stamp) and desk_health_generated and desk_health_age <= 2
checks.append({
    "engine": "prediction_desk_health",
    "status": "PASS" if desk_health_fresh else "STALE",
    "age_hours": round(desk_health_age, 2) if desk_health_stamp else None,
    "threshold_hours": 2,
})
if not desk_health_stamp or not desk_health_generated:
    checks.append(issue(
        "PREDICTION_DESK_HEALTH_NOT_GENERATED",
        "warning",
        "Prediction Desk health sidecar has not yet been replaced by a timestamped generated snapshot"
    ))
elif desk_health_age > 2:
    checks.append(issue(
        "PREDICTION_DESK_HEALTH_STALE",
        "warning",
        f"Prediction Desk health sidecar age {desk_health_age:.2f}h exceeds 2h"
    ))

# A freshly rebuilt board may still contain no certifiable eFootball/virtual
# picks if participant lifecycle, settlement and model inputs did not refresh.
virtual_status_age = age_hours(virtual.get("updated_at"))
virtual_participant_check, virtual_participant_issues = virtual_participant_history_health_summary(
    virtual_status_age, desk_health, max_age_minutes=30.0
)
checks.append(virtual_participant_check)
checks.extend(virtual_participant_issues)

# The separate 14-day tennis discovery task runs every six hours. A missing or
# old report means the system cannot distinguish "no fixtures" from "discovery
# did not refresh"; surface that as a distinct warning instead of guessing.
tennis_forward_age = age_hours(tennis_forward.get("updated_at"))
checks.append({
    "engine": "tennis_forward_discovery",
    "status": "PASS" if tennis_forward_age <= 8 else "STALE",
    "age_hours": round(tennis_forward_age, 2),
    "threshold_hours": 8,
})
if tennis_forward_age > 8:
    checks.append(issue(
        "TENNIS_FORWARD_DISCOVERY_STALE",
        "warning",
        f"tennis_forward_status age {tennis_forward_age:.2f}h exceeds the 8h threshold; the discovery result is too old to confirm current fixture coverage"
    ))

virtual_live_age = age_hours(virtual_live.get("updated_at"))
virtual_live_check, virtual_live_issues = virtual_live_health_summary(
    virtual_live, virtual_live_age, max_age_hours=0.5
)
checks.append(virtual_live_check)
checks.extend(virtual_live_issues)
nba_live_observation_age = age_hours(nba_live_observations.get("updated_at"))
nba_live_check, nba_live_issues = nba_live_observation_health_summary(
    nba_live_observations, nba_live_observation_age, max_age_hours=0.25
)
checks.append(nba_live_check)
checks.extend(nba_live_issues)

nba_competition = (expansion.get("competitions") or {}).get("NBA") or {}
retired = {
    "darts_x": {"status": "RETIRED", "artifact_at": darts.get("updated_at")},
    "table_tennis_x": {"status": "RETIRED", "artifact_at": table.get("updated_at")},
    # The legacy core basketball moneyline provider is retired, but the separate
    # ESPN/SportyBet NBA totals desk is still an experimental paper-only lane.
    "basketball_core_moneyline": {
        "status": "RETIRED",
        "provider": pipeline.get("basketball_market_provider_status") or "not_active",
    },
    "nba_totals_desk": {
        "status": nba_competition.get("status") or "UNKNOWN",
        "paper_only": not bool(expansion.get("live_trading_approved")),
        "historical_events": int(nba_competition.get("historical_events") or 0),
        "current_fixtures": int(nba_competition.get("current_fixtures") or 0),
    },
    # PDL stays paper-only and is explicitly visible even when external providers block refresh.
    "pdl_experimental_prediction_feed": pdl_lane,
}
checks.append({"engine": "engine_lifecycle", "status": "INFO", "lanes": retired})
checks.extend(pdl_issues)

prediction_count = int(pipeline.get("prediction_count") or 0)
football_count = int(pipeline.get("football_count") or 0)
tennis_count = int(pipeline.get("tennis_count") or 0)
autopilot_leagues = autopilot.get("league_counts") or {}
if prediction_count <= 0:
    checks.append(issue("CORE_PREDICTIONS_EMPTY", "critical", "data/pipeline_status.json reports zero current predictions"))
if football_count <= 0:
    checks.append(issue("FOOTBALL_FEED_EMPTY", "critical", "No current football predictions are published"))
def current_future_tennis_rows(rows):
    found = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("sport") or "").lower() != "tennis" or row.get("settled"):
            continue
        stamp = row.get("start_time") or row.get("date")
        if not stamp:
            continue
        try:
            start = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if start >= NOW:
            found.append(row)
    return found


if tennis_count <= 0:
    published_tennis = current_future_tennis_rows(prediction_rows)
    watch_tennis = [
        row for row in published_tennis
        if str(row.get("prediction_status") or "") == "watch_projection"
        or str(row.get("qualification_status") or "") == "TENNIS_FORWARD_WATCH_NOT_QUALIFIED"
    ]
    if published_tennis and len(watch_tennis) == len(published_tennis):
        checks.append(issue(
            "TENNIS_CORE_FEED_EMPTY",
            "warning",
            f"Canonical tennis pipeline has zero actionable predictions; {len(watch_tennis)} unqualified ATP forward-window watch projections are published for research only"
        ))
    elif published_tennis:
        checks.append(issue(
            "TENNIS_PIPELINE_COUNT_MISMATCH",
            "warning",
            f"Pipeline status reports zero tennis predictions, but {len(published_tennis)} future tennis rows are present in the published prediction feed"
        ))
    elif int(autopilot_leagues.get("ATP") or 0) > 0 or int(autopilot_leagues.get("WTA") or 0) > 0:
        checks.append(
            {
                "engine": "tennis_desk",
                "status": "INFO",
                "detail": "Canonical core pipeline has no actionable tennis predictions; separate forward/readiness diagnostics still report active tennis rows.",
                "autopilot_atp": int(autopilot_leagues.get("ATP") or 0),
                "autopilot_wta": int(autopilot_leagues.get("WTA") or 0),
            }
        )
    else:
        checks.append(issue("TENNIS_FEED_EMPTY", "warning", "No current tennis predictions or forward-window research rows are published"))

virtual_products = virtual_live.get("product_counts") or {}
for product in ("efootball_gt", "vfootball"):
    if int(virtual_products.get(product) or 0) <= 0:
        checks.append(issue("VIRTUAL_PRODUCT_EMPTY", "warning", f"{product} has no upcoming events in the latest live snapshot"))

sel = int(selection.get("selected_predictions") or 0)
if prediction_count > 0 and sel == 0:
    checks.append(issue("SELECTION_GATE_EMPTY", "info", "Current prediction feed exists but the selected-candidate layer returned zero qualified selections; no gate was weakened"))

if not predictions_valid:
    checks.append(issue("PREDICTION_FEED_EMPTY_OR_INVALID", "critical", f"data/predictions.json is empty/invalid ({len(prediction_rows)} rows)"))
if not accuracy_valid:
    checks.append(issue("ACCURACY_ARTIFACT_EMPTY_OR_INVALID", "critical", "data/accuracy.json is empty or invalid"))

pipeline_age_check = age_hours(pipeline.get("updated_at"))
if pipeline_age_check > 4:
    checks.append(issue("PIPELINE_STALE", "critical", f"pipeline_status age {pipeline_age_check:.2f}h exceeds 4h"))

unified_age_check = age_hours(unified.get("generated_at"))
if unified_age_check > 2:
    checks.append(issue("UNIFIED_BOARD_STALE", "warning", f"unified board age {unified_age_check:.2f}h exceeds 2h"))

qa_status = str(qa.get("status") or qa.get("overall") or "")
if qa_status and qa_status.upper() in {"FAIL", "FAILED"}:
    checks.append(issue("QA_FAIL", "critical", f"QA artifact reports {qa_status}"))

hard = [x for x in checks if x.get("severity") == "critical"]
status = "FAIL" if hard else ("DEGRADED" if any(x.get("status") == "STALE" or x.get("severity") == "warning" for x in checks) else "HEALTHY")
out = {
    "generated_at": NOW.isoformat(),
    "status": status,
    "critical_issues": len(hard),
    "warning_issues": sum(x.get("severity") == "warning" for x in checks),
    "info_issues": sum(x.get("severity") == "info" for x in checks),
    "checks": [x for x in checks if "engine" in x],
    "issues": [x for x in checks if "code" in x],
    "policy": "Proactive operational guard. Visibility is never reduced to zero just because an evidence gate is unmet.",
    "paper_only": True,
    "prediction_desk_filters": desk_health.get("publication_filters") or {},
}
(DATA / "system_health.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(out, indent=2))
if status == "FAIL":
    print("CRITICAL health state recorded; watchdog self-healing remains responsible for remediation.")
