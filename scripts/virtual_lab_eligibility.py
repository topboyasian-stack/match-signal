"""Build conservative Virtual Lab eligibility from raw O/U evidence plus strict model validation."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"
HISTORY=DATA/"virtual_lab_history.json"; MODEL=DATA/"virtual_lab_model_eval.json"; OUTPUT=DATA/"virtual_lab_eligibility.json"
MIN_COMP_N=12; MIN_COMP_OOS_N=4; MIN_LINE_N=12; MIN_LINE_OOS_N=4; DISCOVERY=.70
PRIORITY_OU_LINES=[1.5,3.5,4.5]

def settled(rows): return [r for r in rows if isinstance(r,dict) and r.get("win") is not None]
def stats(rows):
    n=len(rows); wins=sum(bool(r.get("win")) for r in rows)
    if not n:return {"n":0,"wins":0,"win_rate":None,"roi":None}
    roi=sum((float(r.get("odds") or 0)-1) if r.get("win") else -1 for r in rows)/n
    return {"n":n,"wins":wins,"win_rate":wins/n,"roi":roi}
def split(rows):
    ordered=sorted(rows,key=lambda r:str(r.get("timestamp") or "")); cut=int(len(ordered)*DISCOVERY)
    return ordered[:cut],ordered[cut:]
def eligible_comp(rows):
    _,test=split(rows); a,b=stats(rows),stats(test)
    return (a["n"]>=MIN_COMP_N and b["n"]>=MIN_COMP_OOS_N and a["win_rate"]>=.55 and b["win_rate"]>=.50 and b["roi"]>=-.05),a,b
def eligible_line(rows):
    _,test=split(rows); a,b=stats(rows),stats(test)
    return (a["n"]>=MIN_LINE_N and b["n"]>=MIN_LINE_OOS_N and a["win_rate"]>=.58 and b["win_rate"]>=.55 and b["roi"]>=-.02),a,b

def model_pass(x):
    """Validate the core O/U model without requiring participant enhancement."""
    if not x:return False
    market=x.get("market") or {}
    candidates=[]
    for name in ("efootball_shape","poisson_prior","poisson"):
        m=x.get(name) or {}
        if m.get("n",0)>=30 and all(k in m for k in ("brier","log_loss","ece")):
            if (not candidates or
                (m.get("brier",9),m.get("log_loss",9)) <
                (candidates[0][1].get("brier",9),candidates[0][1].get("log_loss",9))):
                candidates=[(name,m)]
    if not candidates or not market:return False
    _,best=candidates[0]
    return (
        best.get("brier",9)<market.get("brier",0) and
        best.get("log_loss",9)<market.get("log_loss",0) and
        best.get("ece",9)<=market.get("ece",9)+.02
    )

def main():
    history=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    rows=settled(history); comps={}; lines={}
    for r in rows:
        c=str(r.get("competition") or "Unknown"); comps.setdefault(c,[]).append(r)
        if r.get("market")=="ou" and r.get("line") is not None: lines.setdefault(str(float(r["line"])),[]).append(r)

    raw_comp=[]; blocked_comp=[]; comp_report={}
    for c,a in comps.items():
        ok,all_s,oos_s=eligible_comp(a); comp_report[c]={"raw_eligible":ok,"all":all_s,"oos":oos_s}
        (raw_comp if ok else blocked_comp).append(c)

    raw_lines=[]; blocked_lines=[]; line_report={}
    for line,a in lines.items():
        ok,all_s,oos_s=eligible_line(a); line_report[line]={"raw_eligible":ok,"all":all_s,"oos":oos_s}
        (raw_lines if ok else blocked_lines).append(float(line))

    model={}
    if MODEL.exists():
        try:model=json.loads(MODEL.read_text())
        except Exception:model={}
    by_line=model.get("by_line",{})
    by_comp=model.get("by_competition",{})
    model_lines=[float(k) for k,v in by_line.items() if model_pass(v.get("holdout",{}))]
    model_comps=[str(k) for k,v in by_comp.items() if model_pass(v)]
    eligible_lines=sorted(set(raw_lines)&set(model_lines))
    eligible_comps=sorted(set(raw_comp)&set(model_comps))

    # Product-scoped promotion is mandatory for the Virtual Lab. The legacy
    # top-level gates remain published for compatibility, but a vfootball
    # result must never qualify an eFootball competition/line (or vice versa).
    by_product_comp=model.get("by_product_competition",{})
    by_product_line=model.get("by_product_line",{})
    eligible_competitions_by_product={}
    model_qualified_competitions_by_product={}
    eligible_ou_lines_by_product={}
    model_qualified_ou_lines_by_product={}
    raw_eligible_competitions_by_product={}
    raw_eligible_ou_lines_by_product={}
    for product in sorted({str(r.get("product") or "other") for r in rows}):
        product_rows=[r for r in rows if str(r.get("product") or "other")==product]
        pcomps={}
        plines={}
        for r in product_rows:
            pcomps.setdefault(str(r.get("competition") or "Unknown"),[]).append(r)
            if r.get("market")=="ou" and r.get("line") is not None:
                plines.setdefault(str(float(r["line"])),[]).append(r)
        raw_pc=[]
        for comp,items in pcomps.items():
            ok,_,_=eligible_comp(items)
            if ok: raw_pc.append(comp)
        raw_pl=[]
        for line,items in plines.items():
            ok,_,_=eligible_line(items)
            if ok: raw_pl.append(float(line))
        pmodel_comps=[str(k) for k,v in (by_product_comp.get(product,{}) or {}).items() if model_pass(v)]
        pmodel_lines=[float(k) for k,v in (by_product_line.get(product,{}) or {}).items() if model_pass(v)]
        raw_eligible_competitions_by_product[product]=sorted(raw_pc)
        raw_eligible_ou_lines_by_product[product]=sorted(raw_pl)
        model_qualified_competitions_by_product[product]=sorted(pmodel_comps)
        model_qualified_ou_lines_by_product[product]=sorted(pmodel_lines)
        eligible_competitions_by_product[product]=sorted(set(raw_pc)&set(pmodel_comps))
        eligible_ou_lines_by_product[product]=sorted(set(raw_pl)&set(pmodel_lines))
    adaptive_policy={
        "base_gate":"best validated product-aware core model vs SportyBet market",
        "candidate_variants":["efootball_shape","poisson_prior","poisson"],
        "participant_feature_independent":True,
        "participant_feature_gate":model.get("participant_feature_gate",{}),
        "qualified_lines":sorted(model_lines),
        "qualified_competitions":sorted(model_comps)
    }
    out={
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "mode":"PAPER_RESEARCH_ONLY",
      "policy":{
        "minimum_competition_observations":MIN_COMP_N,"minimum_competition_oos":MIN_COMP_OOS_N,
        "minimum_line_observations":MIN_LINE_N,"minimum_line_oos":MIN_LINE_OOS_N,
        "discovery_fraction":DISCOVERY,"eligible_markets":["ou"],
        "blocked_markets":["winner","1x2","btts","handicap","other"],
        "model_gate":"Raw league/line evidence must also pass strict untouched walk-forward model validation before becoming active. Participant recurrence is never activated from user tickets."
      },
      "eligible_competitions":eligible_comps,
      "blocked_competitions":sorted(set(comps)-set(eligible_comps)),
      "raw_eligible_competitions":sorted(raw_comp),
      "model_qualified_competitions":sorted(model_comps),
      "eligible_competitions_by_product":eligible_competitions_by_product,
      "raw_eligible_competitions_by_product":raw_eligible_competitions_by_product,
      "model_qualified_competitions_by_product":model_qualified_competitions_by_product,
      "priority_ou_lines":PRIORITY_OU_LINES,
      "eligible_ou_lines":eligible_lines,
      "eligible_ou_lines_by_product":eligible_ou_lines_by_product,
      "raw_eligible_ou_lines_by_product":raw_eligible_ou_lines_by_product,
      "model_qualified_ou_lines_by_product":model_qualified_ou_lines_by_product,
      "raw_eligible_ou_lines":sorted(raw_lines),
      "model_qualified_ou_lines":sorted(model_lines),
      "blocked_ou_lines":sorted(set(blocked_lines)|set(raw_lines)-set(eligible_lines)),
      "competitions":comp_report,"ou_lines":line_report,
      "model_gate":model.get("participant_feature_gate",{"pass":False,"reason":"model artifact unavailable"}),
      "adaptive_model_policy":adaptive_policy,
      "paper_only":True
    }
    OUTPUT.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out,indent=2))
if __name__=="__main__":main()
