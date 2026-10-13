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

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
TRACKER=DATA/"odds_ticket_tracker.json"
OUTPUT=DATA/"ticket_calibration_experiment.json"

GRID=[i/20 for i in range(21)]
GAMMA_GRID=[0.5+i*0.1 for i in range(46)]
SHRINK_GRID=[i/20 for i in range(21)]
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

def calibrate(rows, model_key="combined_model_probability"):
    rows=sorted(rows,key=lambda t:str(t.get("last_settled_at") or t.get("settled_at") or t.get("updated_at") or ""))
    usable=[t for t in rows if prob(t,model_key) is not None and market(t) is not None]
    predictions=[]
    for i,t in enumerate(usable):
        prior=usable[:i]
        if len(prior)<WARMUP:continue
        def score_linear(a):
            return brier(prior,lambda x:blend(prob(x,model_key),market(x),a))
        def score_logit(a):
            return brier(prior,lambda x:invlogit(a*logit(prob(x,model_key))+(1-a)*logit(market(x))))
        def score_power(g):
            return brier(prior,lambda x:max(.0005,min(.9995,prob(x,model_key)**g)))
        def score_shrink(a):
            return brier(prior,lambda x:.5+a*(prob(x,model_key)-.5))
        best_a=min(GRID,key=score_linear)
        best_l=min(GRID,key=score_logit)
        best_g=min(GAMMA_GRID,key=score_power)
        best_s=min(SHRINK_GRID,key=score_shrink)
        m=prob(t,model_key); q=market(t)
        predictions.append({
            "ticket_id":t.get("ticket_id"),
            "settled_at":t.get("settled_at"),
            "leg_count":int(t.get("leg_count") or len(t.get("legs") or [])),
            "status":t.get("status"),
            "model_probability":m,
            "market_probability":q,
            "linear_alpha":best_a,
            "linear_probability":blend(m,q,best_a),
            "logit_alpha":best_l,
            "logit_probability":invlogit(best_l*logit(m)+(1-best_l)*logit(q)),
            "power_gamma":best_g,
            "power_probability":max(.0005,min(.9995,m**best_g)),
            "shrink_alpha":best_s,
            "shrink_probability":max(.0005,min(.9995,.5+best_s*(m-.5))),
        })
    def pred(fn): return metrics(predictions,fn)
    return predictions,{
        "n":len(predictions),
        "naive":pred(lambda x:x["model_probability"]),
        "market":pred(lambda x:x["market_probability"]),
        "linear_blend":pred(lambda x:x["linear_probability"]),
        "logit_blend":pred(lambda x:x["logit_probability"]),
        "power_calibration":pred(lambda x:x["power_probability"]),
        "shrink_to_half":pred(lambda x:x["shrink_probability"]),
        "mean_linear_alpha":sum(x["linear_alpha"] for x in predictions)/len(predictions) if predictions else None,
        "mean_logit_alpha":sum(x["logit_alpha"] for x in predictions)/len(predictions) if predictions else None,
        "mean_power_gamma":sum(x["power_gamma"] for x in predictions)/len(predictions) if predictions else None,
        "mean_shrink_alpha":sum(x["shrink_alpha"] for x in predictions)/len(predictions) if predictions else None,
    }

def main():
    raw=load(TRACKER,{})
    tickets=raw.get("tickets") if isinstance(raw,dict) else []
    settled=[t for t in tickets if str(t.get("status") or "").upper() in {"WON","LOST"}]
    modern=[t for t in settled if 2<=int(t.get("leg_count") or len(t.get("legs") or []))<=4]
    all_pred,all_metrics=calibrate(settled)
    modern_pred,modern_metrics=calibrate(modern)
    out={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "mode":"PAPER_ONLY_DIAGNOSTIC",
        "production_selection_changed":False,
        "method":"strict chronological ticket-level walk-forward; each calibration weight uses only earlier settled tickets",
        "warmup_tickets":WARMUP,
        "grid":GRID,
        "gamma_grid":GAMMA_GRID,
        "shrink_grid":SHRINK_GRID,
        "samples":{"all_settled":len(settled),"modern_2_to_4":len(modern)},
        "all_settled":all_metrics,
        "modern_2_to_4":modern_metrics,
        "decision":{
            "promotion_allowed":False,
            "reason":"Calibration experiment must be independently reviewed before production use.",
            "note":"A lower Brier/log-loss on the held-forward rows is evidence for calibration, not evidence of future profitability."
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
