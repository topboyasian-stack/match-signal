"""Walk-forward Virtual Lab model evaluation.

Time-safe O/U evaluation only. No user-reported tickets are read.
Compares SportyBet de-vig baseline, line-ladder Poisson, product prior,
and the participant-aware model on untouched chronological holdouts.
"""
from __future__ import annotations
import json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"virtual_lab_history.json"
OUTPUT=DATA/"virtual_lab_model_eval.json"
LINES=(1.5,3.5,4.5)
HOLDOUT_FRACTION=.30
MIN_EVENT_HISTORY=8
MIN_PARTICIPANT_TOTAL_HISTORY=3
MIN_PARTICIPANT_HOLDOUT=20
MIN_HOLDOUT_ROWS=30
PRIOR_WEIGHT=.25
PAIR_WEIGHT=.25
MAX_PARTICIPANT_WEIGHT=.20
MAX_TOTAL_PARTICIPANT_WEIGHT=.15
EFOOTBALL_PRODUCTS={"efootball_gt","efootball_adriatic"}
EFOOTBALL_SHAPE_MIN_HISTORY=20
EFOOTBALL_SHAPE_FULL_HISTORY=60
EFOOTBALL_SHAPE_DECAY=60.0
EFOOTBALL_SHAPE_MAX_EVENTS=300

def ts(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
    except Exception:return float("inf")


def stable_participant_identity(product, value):
    import re
    s=" ".join(str(value or "").split()).strip()
    if not s:
        return ""
    product=str(product or "")
    if product.startswith("efootball"):
        m=re.search(r"\(([^()]+)\)\s*$",s)
        return m.group(1).strip() if m and m.group(1).strip() else ""
    if product in {"vfootball","zoom"}:
        return s
    return ""

def clamp(p):
    return max(.0005,min(.9995,float(p)))

def poisson_over(lam,line):
    lam=max(.05,min(30.,float(lam)))
    k=math.floor(float(line))
    pmf=math.exp(-lam); cdf=pmf
    for i in range(1,k+1):
        pmf*=lam/i; cdf+=pmf
    return clamp(1-cdf)

def fit_lambda(points):
    pts=[p for p in points if p[0] is not None and p[1] is not None]
    if not pts:return None
    best=(5.,float("inf"))
    for i in range(25,2001):
        lam=i/100
        loss=sum((poisson_over(lam,line)-prob)**2 for line,prob in pts)/len(pts)
        if loss<best[1]:best=(lam,loss)
    return best[0]

def build_events(rows):
    groups={}
    for r in rows:
        if r.get("market")!="ou" or r.get("win") is None or r.get("line") is None:continue
        eid=str(r.get("event_id") or "")
        stamp=str(r.get("timestamp") or "")
        if not eid or not stamp:continue
        key=eid+"|"+stamp
        g=groups.setdefault(key,{
            "key":key,"event_id":eid,"timestamp":stamp,
            "product":str(r.get("product") or "other"),
            "competition":str(r.get("competition") or "Unknown"),
            "home":str(r.get("participant_1") or ""),
            "away":str(r.get("participant_2") or ""),
            "rows":[],"total":None
        })
        g["rows"].append(r)
        if g["total"] is None:
            m=str(r.get("score") or "").replace(" ","").split(":")
            if len(m)==2:
                try:g["total"]=float(m[0])+float(m[1])
                except Exception:pass
    events=[]
    for g in groups.values():
        if g["total"] is None:continue
        pts=[]
        for r in g["rows"]:
            p=r.get("model_prob")
            if p is None:continue
            try:p=float(p)
            except Exception:continue
            sel=str(r.get("selection") or "").upper()
            over=p if sel.startswith("O") else 1-p
            pts.append((float(r["line"]),clamp(over)))
        lam=fit_lambda(pts)
        if lam is not None:
            g["lambda"]=lam; events.append(g)
    return sorted(events,key=lambda e:ts(e["timestamp"]))

def product_prior(events, product, line, cutoff):
    eligible=[e for e in events if e["product"]==product and ts(e["timestamp"])<cutoff]
    decisive=[e for e in eligible if e["total"]!=line]
    if not decisive:return None
    over=sum(e["total"]>line for e in decisive)
    return (over+2)/(len(decisive)+4)

def efootball_shape_prob(events,event,line,poisson_prob):
    """Product-specific full-distribution O/U estimate for eFootball.

    Uses the settled total-goal distribution across earlier same-product events,
    with bounded recency weighting and Beta(2,2) shrinkage, then blends it with
    the event's line-ladder Poisson probability. The feature is time-safe: the
    current event is never included.
    """
    product=str(event.get("product") or "")
    if product not in EFOOTBALL_PRODUCTS:
        return poisson_prob,0.0,0.0
    cutoff=ts(event.get("timestamp"))
    prior=[e for e in events
           if e.get("product")==product and e.get("total") is not None
           and ts(e.get("timestamp"))<cutoff]
    if len(prior)<EFOOTBALL_SHAPE_MIN_HISTORY:
        return poisson_prob,0.0,0.0
    prior=prior[-EFOOTBALL_SHAPE_MAX_EVENTS:]
    weighted_over=0.0
    weighted_under=0.0
    used=0
    for age,e in enumerate(reversed(prior)):
        total=e.get("total")
        if total is None or total==line:
            continue
        w=math.exp(-age/EFOOTBALL_SHAPE_DECAY)
        if total>line:
            weighted_over+=w
        else:
            weighted_under+=w
        used+=1
    decisive_weight=weighted_over+weighted_under
    if decisive_weight<=0:
        return poisson_prob,0.0,0.0
    empirical=(weighted_over+2)/(decisive_weight+4)
    confidence=max(0.0,min(1.0,
        (decisive_weight-EFOOTBALL_SHAPE_MIN_HISTORY) /
        (EFOOTBALL_SHAPE_FULL_HISTORY-EFOOTBALL_SHAPE_MIN_HISTORY)
    ))
    shape_weight=.15+.30*confidence
    shape_prob=clamp((1-shape_weight)*poisson_prob+shape_weight*empirical)
    return shape_prob,decisive_weight,shape_weight

def participant_prior(events,event,line):
    cutoff=ts(event["timestamp"]); product=event["product"]
    names={stable_participant_identity(product,event["home"]).casefold(),stable_participant_identity(product,event["away"]).casefold()}-{""}
    prior=[e for e in events if e["product"]==product and ts(e["timestamp"])<cutoff and e["total"] is not None]
    entity=[e for e in prior if names & {stable_participant_identity(product,e["home"]).casefold(),stable_participant_identity(product,e["away"]).casefold()}]
    # Participant recurrence is identity-based, not opponent-based. Use prior actual
    # totals across all O/U lines to estimate P(total > current line).
    total_decisive=[e for e in entity if e["total"]!=line]
    if len(total_decisive)<MIN_PARTICIPANT_TOTAL_HISTORY:return None,0,0
    total_prob=(sum(e["total"]>line for e in total_decisive)+2)/(len(total_decisive)+4)
    weight=min(MAX_TOTAL_PARTICIPANT_WEIGHT,max(.05,(len(total_decisive)-2)/35))
    # If exact-line evidence is mature, blend it in as a secondary refinement.
    exact=[e for e in total_decisive if any(abs(float(rr.get("line"))-line)<1e-9 for rr in e.get("rows",[]))]
    exact_prob=None
    if len(exact)>=MIN_EVENT_HISTORY:
        exact_prob=(sum(e["total"]>line for e in exact)+2)/(len(exact)+4)
        total_prob=.65*total_prob+.35*exact_prob
    pair=[]
    a,b=stable_participant_identity(product,event["home"]).casefold(),stable_participant_identity(product,event["away"]).casefold()
    for e in prior:
        eh,ea=stable_participant_identity(product,e["home"]).casefold(),stable_participant_identity(product,e["away"]).casefold()
        if ((eh==a and ea==b) or (eh==b and ea==a)) and e["total"]!=line:pair.append(e)
    if len(pair)>=6:
        pp=(sum(e["total"]>line for e in pair)+2)/(len(pair)+4)
        total_prob=(1-PAIR_WEIGHT)*total_prob+PAIR_WEIGHT*pp
    return total_prob,weight,len(total_decisive)

def probs(events,event,row):
    line=float(row["line"])
    market=clamp(float(row["model_prob"]))
    pois=poisson_over(event["lambda"],line)
    prior=product_prior(events,event["product"],line,ts(event["timestamp"]))
    base=pois if prior is None else clamp((1-PRIOR_WEIGHT)*pois+PRIOR_WEIGHT*prior)
    shape_prob,shape_n,shape_weight=efootball_shape_prob(events,event,line,pois)
    core=shape_prob if event["product"] in EFOOTBALL_PRODUCTS and shape_n>0 else base
    part,pw,pn=participant_prior(events,event,line)
    combined=core if part is None else clamp((1-pw)*core+pw*part)
    return market,pois,base,core,combined,pn,shape_prob,shape_n,shape_weight

def metrics(rows,key):
    if not rows:return None
    b=sum((r["y"]-r[key])**2 for r in rows)/len(rows)
    ll=sum(-(r["y"]*math.log(clamp(r[key]))+(1-r["y"])*math.log(1-clamp(r[key]))) for r in rows)/len(rows)
    hit=sum((r[key]>=.5)==bool(r["y"]) for r in rows)/len(rows)
    # Reliability: equal-width probability bins, weighted by observations.
    bins=[]
    ece=0.
    for lo in [i/10 for i in range(10)]:
        bucket=[r for r in rows if lo<=r[key]<(lo+.1 if lo<.9 else 1.0001)]
        if bucket:
            mean=sum(r[key] for r in bucket)/len(bucket); obs=sum(r["y"] for r in bucket)/len(bucket)
            ece+=len(bucket)/len(rows)*abs(mean-obs)
    return {"n":len(rows),"brier":b,"log_loss":ll,"hit_rate":hit,"ece":ece}

def evaluate(events):
    outputs=[]
    for i,event in enumerate(events):
        prior=events[:i]
        for row in event["rows"]:
            if row.get("win") is None or row.get("model_prob") is None:continue
            market,pois,base,core,combined,pn,shape_prob,shape_n,shape_weight=probs(prior,event,row)
            sel=str(row.get("selection") or "").upper()
            # Convert all observations to the probability of the selected side.
            inv=sel.startswith("U")
            y=1 if bool(row["win"]) else 0
            outputs.append({
                "event_key":event["key"],"timestamp":event["timestamp"],
                "product":event["product"],"competition":event["competition"],
                "selection":str(row.get("selection") or "").lower(),
                "line":float(row["line"]),"participant_active":pn>=MIN_EVENT_HISTORY,
                "y":y,
                "market":1-market if inv else market,
                "poisson":1-pois if inv else pois,
                "poisson_prior":1-base if inv else base,
                "efootball_shape":1-shape_prob if inv else shape_prob,
                "participant_model":1-combined if inv else combined,
                "participant_n":pn,
                "efootball_shape_n":shape_n,
                "efootball_shape_weight":shape_weight
            })
    return outputs

def grouped(rows, field):
    out={}
    for r in rows:out.setdefault(r[field],[]).append(r)
    return out

def main():
    history=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    rows=[r for r in history if isinstance(r,dict) and r.get("market")=="ou" and r.get("win") is not None]
    events=build_events(rows)
    cut=max(1,int(len(events)*(1-HOLDOUT_FRACTION)))
    hold_keys={e["key"] for e in events[cut:]}
    scored=evaluate(events)
    hold=[r for r in scored if r["event_key"] in hold_keys]
    participant_hold=[r for r in hold if r["participant_active"]]
    variants=["market","poisson","poisson_prior","efootball_shape","participant_model"]
    all_metrics={k:metrics(scored,k) for k in variants}
    hold_metrics={k:metrics(hold,k) for k in variants}
    part_metrics={k:metrics(participant_hold,k) for k in variants}
    def table(field, values):
        out={}
        for key,subset in grouped(hold,field).items():
            out[str(key)]={k:metrics(subset,k) for k in variants}
        return out

    def nested_table(primary_field, secondary_field, source_rows):
        """Diagnostic matrix used to isolate product-specific degradation without changing gates."""
        out={}
        for primary, subset in grouped(source_rows, primary_field).items():
            bucket={}
            for secondary, rows2 in grouped(subset, secondary_field).items():
                bucket[str(secondary)]={k:metrics(rows2,k) for k in variants}
            out[str(primary)]=bucket
        return out
    # Only promote a participant feature when it has a meaningful untouched holdout
    # and improves both probability losses without materially worsening calibration.
    ph=hold_metrics.get("participant_model"); mh=hold_metrics.get("market")
    participant_pass=bool(
        ph and mh and len(participant_hold)>=MIN_PARTICIPANT_HOLDOUT and len(hold)>=MIN_HOLDOUT_ROWS and
        ph["brier"]<mh["brier"] and ph["log_loss"]<mh["log_loss"] and ph["ece"]<=mh["ece"]+.02
    )
    line_reports={}
    for line in LINES:
        subset=[r for r in hold if r["line"]==line]
        line_reports[str(line)]={"holdout":{k:metrics(subset,k) for k in variants},
                                 "participant_holdout_n":sum(r["participant_active"] for r in subset)}
    out={
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "method":"strict chronological walk-forward; each scored event only sees earlier settled events",
      "source_contract":"automatic SportyBet result history only; user-reported tickets excluded",
      "history_rows":len(history),"ou_rows":len(rows),"events":len(events),
      "holdout":{"fraction":HOLDOUT_FRACTION,"events":len(events)-cut,"rows":len(hold),"participant_rows":len(participant_hold)},
      "variants":{
        "market":"SportyBet de-vig probability",
        "poisson":"O/U line-ladder Poisson fit",
        "poisson_prior":"Poisson + same-product historical prior with Beta(2,2) shrinkage",
        "participant_model":"Poisson + product prior + same-product participant recurrence with exact-pair evidence and shrinkage"
      },
      "all":all_metrics,"holdout_metrics":hold_metrics,
      "participant_holdout_metrics":part_metrics,
      "by_product":table("product",hold),
      "by_competition":table("competition",hold),
      "by_line":line_reports,
      "by_product_competition":nested_table("product","competition",hold),
      "by_product_line":nested_table("product","line",hold),
      "by_product_selection":nested_table("product","selection",hold),
      "efootball_gt_diagnostics":{
        "competition":nested_table("competition","line",[r for r in hold if r["product"]=="efootball_gt"]),
        "line":{str(line):{variant:metrics([r for r in hold if r["product"]=="efootball_gt" and r["line"]==line],variant) for variant in variants} for line in LINES},
        "selection":nested_table("selection","line",[r for r in hold if r["product"]=="efootball_gt"])
      },
      "participant_feature_gate":{
        "minimum_participant_total_history":MIN_PARTICIPANT_TOTAL_HISTORY,
        "minimum_exact_line_history":MIN_EVENT_HISTORY,
        "minimum_untouched_participant_rows":MIN_PARTICIPANT_HOLDOUT,
        "minimum_untouched_rows":MIN_HOLDOUT_ROWS,
        "pass":participant_pass,
        "reason":"passes both Brier and log loss with calibration tolerance" if participant_pass else "insufficient untouched participant evidence or no dual-loss improvement"
      },
      "paper_only":True
    }
    OUTPUT.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))

if __name__=="__main__":main()
