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

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
NOW=datetime.now(timezone.utc)

def load(name,default):
    try:return json.loads((DATA/name).read_text(encoding="utf-8"))
    except Exception:return default

def age_hours(value):
    if not value:return 999.0
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return max(0.0,(NOW-dt).total_seconds()/3600)
    except Exception:return 999.0

def issue(code,severity,detail):
    return {"code":code,"severity":severity,"detail":detail}

pipeline=load("pipeline_status.json",{})
odds=load("odds_builder.json",{})
expansion=load("expansion_status.json",{})
virtual=load("virtual_lab_status.json",{})
darts=load("darts_status.json",{})
table=load("table_tennis_status.json",{})
unified=load("unified_upcoming.json",{})
qa=load("qa/report.json",{})
selection=load("selection_gate.json",{})
predictions_file=DATA/"predictions.json"
accuracy_file=DATA/"accuracy.json"
prediction_rows=[]
predictions_valid=False
accuracy_valid=False
try:
    raw=predictions_file.read_text(encoding="utf-8").strip()
    prediction_rows=json.loads(raw) if raw else []
    predictions_valid=isinstance(prediction_rows,list) and len(prediction_rows)>0
except Exception:
    prediction_rows=[]
try:
    raw=accuracy_file.read_text(encoding="utf-8").strip()
    accuracy_valid=bool(json.loads(raw)) if raw else False
except Exception:
    accuracy_valid=False


checks=[]
def freshness(name,payload,field,threshold):
    age=age_hours(payload.get(field))
    status="PASS" if age<=threshold else "STALE"
    checks.append({"engine":name,"status":status,"age_hours":round(age,2),"threshold_hours":threshold})
    if status=="STALE":
        return issue("STALE_"+name.upper().replace("-","_"),"critical",f"{field} age {age:.2f}h exceeds {threshold}h")
    return None

for args in [
    ("core_prediction_pipeline",pipeline,"updated_at",4),
    ("odds_builder",odds,"generated_at",8),
    ("expansion",expansion,"updated_at",4),
    ("virtual_lab",virtual,"updated_at",1),
    ("darts_x",darts,"updated_at",2),
    ("table_tennis_x",table,"updated_at",2),
    ("unified_upcoming",unified,"generated_at",2),
]:
    x=freshness(*args)
    if x:checks.append(x)

prediction_count=int(pipeline.get("prediction_count") or 0)
football_count=int(pipeline.get("football_count") or 0)
tennis_count=int(pipeline.get("tennis_count") or 0)
if prediction_count<=0:checks.append(issue("CORE_PREDICTIONS_EMPTY","critical","data/pipeline_status.json reports zero current predictions"))
if football_count<=0:checks.append(issue("FOOTBALL_FEED_EMPTY","critical","No current football predictions are published"))
if tennis_count<=0:checks.append(issue("TENNIS_FEED_EMPTY","warning","No current tennis predictions are published"))

if int(darts.get("upcoming_events") or 0)<=0:
    checks.append(issue("DARTS_NO_FORWARD_FIXTURES","warning","Darts-X has no forward fixtures"))
if int(table.get("upcoming_events") or 0)<=0:
    checks.append(issue("TABLE_TENNIS_NO_FORWARD_FIXTURES","warning","Table Tennis-X has no forward fixtures"))

virtual_products=virtual.get("upcoming_by_product") or {}
for product in ("efootball_gt","efootball_adriatic","vfootball"):
    if int(virtual_products.get(product) or 0)<=0:
        checks.append(issue("VIRTUAL_PRODUCT_EMPTY","warning",f"{product} has no upcoming events in the latest collector snapshot"))

sel=int(selection.get("selected_predictions") or 0)
if prediction_count>0 and sel==0:
    checks.append(issue("SELECTION_GATE_EMPTY","warning","Current prediction feed exists but the selected-candidate layer returned zero selections"))

if not predictions_valid:
    checks.append(issue("PREDICTION_FEED_EMPTY_OR_INVALID","critical",f"data/predictions.json is empty/invalid ({len(prediction_rows)} rows)"))
if not accuracy_valid:
    checks.append(issue("ACCURACY_ARTIFACT_EMPTY_OR_INVALID","critical","data/accuracy.json is empty or invalid"))
pipeline_age_check=age_hours(pipeline.get("updated_at"))
if pipeline_age_check>4:
    checks.append(issue("PIPELINE_STALE","critical",f"pipeline_status age {pipeline_age_check:.2f}h exceeds 4h"))
unified_age_check=age_hours(unified.get("generated_at"))
if unified_age_check>2:
    checks.append(issue("UNIFIED_BOARD_STALE","warning",f"unified board age {unified_age_check:.2f}h exceeds 2h"))

qa_status=str(qa.get("status") or qa.get("overall") or "")
if qa_status and qa_status.upper() in {"FAIL","FAILED"}:
    checks.append(issue("QA_FAIL","critical",f"QA artifact reports {qa_status}"))

hard=[x for x in checks if x.get("severity")=="critical"]
status="FAIL" if hard else ("DEGRADED" if any(x.get("status")=="STALE" or x.get("severity")=="warning" for x in checks) else "HEALTHY")
out={
    "generated_at":NOW.isoformat(),
    "status":status,
    "critical_issues":len(hard),
    "warning_issues":sum(x.get("severity")=="warning" for x in checks),
    "checks":[x for x in checks if "engine" in x],
    "issues":[x for x in checks if "code" in x],
    "policy":"Proactive operational guard. Visibility is never reduced to zero just because an evidence gate is unmet.",
    "paper_only":True,
}
(DATA/"system_health.json").write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps(out,indent=2))
if status=="FAIL":
    print("CRITICAL health state recorded; watchdog self-healing remains responsible for remediation.")
