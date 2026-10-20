"""Time-safe ticket probability calibration experiment.

Diagnostic only. Reads settled Odds Builder tickets and evaluates:
1) current naive product probability,
2) bookmaker-implied probability,
3) a prior-only linear blend of model and market probabilities,
4) a prior-only logit blend.

No production selection rule is changed by this script.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from ticket_history import event_disjoint_tickets, merge_ticket_history, settled_ticket_history

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
TRACKER=DATA/"odds_ticket_tracker.json"
OUTPUT=DATA/"ticket_calibration_experiment.json"

GRID=[i/20 for i in range(21)]
WARMUP=8

def load(p, default):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return default

def prob(t,key):
    try:return min(.9995,max(.0005,float(t.get(key))))
    except (TypeError,ValueError):return None

def market(t):
    try:
        o=float(t.get("combined_odds") or 0)
        return min(.9995,max(.0005,1/o)) if o>0 else None
    except (TypeError,ValueError):return None

def outcome(t):
    return 1.0 if str(t.get("status") or "").upper()=="WON" else 0.0

def brier(rows, fn):
    vals=[fn(t) for t in rows]
    vals=[v for v in vals if v is not None]
    if not vals:return None
    return sum((outcome(t)-v)**2 for t,v in zip(rows,vals) if v is not None)/len(vals)

def logloss(rows,fn):
    s=n=0
    for t in rows:
        p=fn(t)
        if p is None:continue
        y=outcome(t); p=min(.9995,max(.0005,p))
        s += -(y*math.log(p)+(1-y)*math.log(1-p)); n+=1
    return s/n if n else None

def metrics(rows,fn):
    vals=[(t,fn(t)) for t in rows]
    vals=[(t,p) for t,p in vals if p is not None]
    if not vals:return {"n":0}
    return {
        "n":len(vals),
        "hit_rate":sum(outcome(t) for t,_ in vals)/len(vals),
        "avg_probability":sum(p for _,p in vals)/len(vals),
        "brier":sum((outcome(t)-p)**2 for t,p in vals)/len(vals),
        "log_loss":sum(-(outcome(t)*math.log(min(.9995,max(.0005,p)))+(1-outcome(t))*math.log(1-min(.9995,max(.0005,p)))) for t,p in vals)/len(vals)
    }

def blend(m,q,a): return a*m+(1-a)*q

def logit(p): return math.log(p/(1-p))
def invlogit(z): return 1/(1+math.exp(-max(-30,min(30,z))))

def calibrate(rows, model_key="raw_combined_model_probability"):
    rows=sorted(rows,key=lambda t:str(t.get("_calibration_stamp") or t.get("last_settled_at") or t.get("settled_at") or t.get("updated_at") or ""))
    usable=[t for t in rows if prob(t,model_key) is not None and market(t) is not None]
    predictions=[]
    for i,t in enumerate(usable):
        prior=usable[:i]
        if len(prior)<WARMUP:continue
        def score_linear(a):
            return brier(prior,lambda x:blend(prob(x,model_key),market(x),a))
        def score_logit(a):
            return brier(prior,lambda x:invlogit(a*logit(prob(x,model_key))+(1-a)*logit(market(x))))
        best_a=min(GRID,key=score_linear)
        best_l=min(GRID,key=score_logit)
        m=prob(t,model_key); q=market(t)
        predictions.append({
            "ticket_id":t.get("ticket_id"),
            "settled_at":t.get("_calibration_stamp") or t.get("last_settled_at") or t.get("settled_at") or t.get("updated_at"),
            "leg_count":int(t.get("leg_count") or len(t.get("legs") or [])),
            "status":t.get("status"),
            "model_probability":m,
            "market_probability":q,
            "linear_alpha":best_a,
            "linear_probability":blend(m,q,best_a),
            "logit_alpha":best_l,
            "logit_probability":invlogit(best_l*logit(m)+(1-best_l)*logit(q)),
        })
    def pred(fn): return metrics(predictions,fn)
    return predictions,{
        "n":len(predictions),
        "naive":pred(lambda x:x["model_probability"]),
        "market":pred(lambda x:x["market_probability"]),
        "linear_blend":pred(lambda x:x["linear_probability"]),
        "logit_blend":pred(lambda x:x["logit_probability"]),
        "mean_linear_alpha":sum(x["linear_alpha"] for x in predictions)/len(predictions) if predictions else None,
        "mean_logit_alpha":sum(x["logit_alpha"] for x in predictions)/len(predictions) if predictions else None,
    }

def main():
    raw=load(TRACKER,{})
    unique_tickets,history_diagnostics=merge_ticket_history(raw)
    observed_settled=settled_ticket_history(raw,min_legs=2,max_legs=7)
    settled,global_overlap_diagnostics=event_disjoint_tickets(observed_settled)
    modern=[t for t in settled if 2<=int(t.get("leg_count") or len(t.get("legs") or []))<=4]
    all_raw=[t for t in settled if prob(t,"raw_combined_model_probability") is not None and market(t) is not None]
    modern_raw=[t for t in modern if prob(t,"raw_combined_model_probability") is not None and market(t) is not None]
    all_pred,all_metrics=calibrate(all_raw)
    modern_pred,modern_metrics=calibrate(modern_raw)

    # Keep calibration diagnostics segmented by the original Builder lane. An
    # aggregate can hide large differences between exact-evidence eFootball,
    # high-confidence research, and older mixed construction lanes. Only rows
    # with the uncalibrated joint product are scored; legacy probability fields
    # are too ambiguous to train a second correction from.
    by_primary_lane={}
    lane_names=sorted({str(t.get("primary_lane") or "unknown") for t in observed_settled})
    for lane in lane_names:
        lane_observed=[t for t in observed_settled if str(t.get("primary_lane") or "unknown")==lane]
        lane_tickets,lane_overlap_diagnostics=event_disjoint_tickets(lane_observed)
        lane_raw=[t for t in lane_tickets if prob(t,"raw_combined_model_probability") is not None and market(t) is not None]
        if len(lane_raw)<WARMUP+2:
            continue
        _,lane_metrics=calibrate(lane_raw)
        by_primary_lane[lane]={
            "observed_settled_sample":len(lane_observed),
            "dependent_overlap_ticket_count":lane_overlap_diagnostics.get("dependent_overlap_ticket_count",0),
            "settled_sample":len(lane_tickets),
            "raw_joint_probability_sample":len(lane_raw),
            "scored_holdout_sample":lane_metrics.get("n",0),
            **lane_metrics,
        }

    out={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "mode":"PAPER_ONLY_DIAGNOSTIC",
        "production_selection_changed":False,
        "method":"strict chronological ticket-level walk-forward on the stored raw joint product; each calibration weight uses only earlier settled tickets",
        "history_scope":"Deduplicated union of tickets and archived_tickets; current ticket rows take precedence when ticket IDs overlap. Calibration observations are filtered chronologically to event-disjoint tickets.",
        "history_diagnostics":{
            **history_diagnostics,
            "unique_ticket_rows":len(unique_tickets),
            "settled_calibration_rows":len(settled),
            "observed_settled_calibration_rows":len(observed_settled),
            "dependent_overlap_tickets_excluded":global_overlap_diagnostics.get("dependent_overlap_ticket_count",0),
            "independent_event_count":global_overlap_diagnostics.get("unique_event_count",0),
        },
        "warmup_tickets":WARMUP,
        "grid":GRID,
        "samples":{
            "active_rows":history_diagnostics.get("current_rows",0),
            "archived_rows":history_diagnostics.get("archived_rows",0),
            "unique_rows":history_diagnostics.get("unique_rows",0),
            "duplicate_rows_collapsed":history_diagnostics.get("duplicate_rows_collapsed",0),
            "all_settled":len(settled),
            "all_settled_observed":len(observed_settled),
            "event_overlap_tickets_excluded":global_overlap_diagnostics.get("dependent_overlap_ticket_count",0),
            "modern_2_to_4":len(modern),
            "raw_joint_probability_rows":len(all_raw),
            "modern_2_to_4_raw_joint_probability_rows":len(modern_raw),
        },
        "probability_source":"raw_combined_model_probability (uncalibrated joint probability); legacy rows without this field are excluded from probability scoring.",
        "calibration_status":"INSUFFICIENT_COMPATIBLE_RAW_JOINT_HISTORY" if len(modern_raw)<WARMUP+3 else "PAPER_DIAGNOSTIC_READY_FOR_REVIEW",
        "all_settled":all_metrics,
        "modern_2_to_4":modern_metrics,
        "by_primary_lane":by_primary_lane,
        "decision":{
            "promotion_allowed":False,
            "reason":"Calibration experiment must be independently reviewed before production use.",
            "note":"A lower Brier/log-loss on held-forward rows is evidence for calibration, not evidence of future profitability. Do not use this report to lower production gates automatically."
        },
        "modern_predictions":modern_pred,
    }
    OUTPUT.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "modern_2_to_4":modern_metrics,
        "all_settled":all_metrics,
        "output":str(OUTPUT)
    },indent=2))

if __name__=="__main__":main()
