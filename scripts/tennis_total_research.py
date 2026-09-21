"""Research-only tennis total-games challenger.

Compares the current matchup-conditioned model with a simpler player-tempo
empirical distribution using strictly prior settled matches. Nothing here can
activate the public Odds Builder; the upstream risk gate remains authoritative.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path

from tennis_total_model import over_probability

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"prediction_history.json"
OUTPUT=DATA/"tennis_total_research.json"
MIN_PRIOR=30
HALF_LIFE=45.0


def dt(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(timezone.utc)
    except (TypeError,ValueError):
        return None


def eligible(row):
    if not isinstance(row,dict) or row.get("sport")!="tennis" or not row.get("settled"):
        return False
    score=row.get("final_score")
    if not isinstance(score,list) or len(score)!=2:
        return False
    try:
        total=float(score[0])+float(score[1])
    except (TypeError,ValueError):
        return False
    return 0 < total <= 65 and dt(row.get("start_time")) is not None


def names(row):
    return {str(row.get("player_1") or "").strip().lower(),
            str(row.get("player_2") or "").strip().lower()}


def weight(target,row,focus=False):
    a,b=dt(target.get("start_time")),dt(row.get("start_time"))
    if not a or not b or b>=a:return 0.0
    rec=0.5**(((a-b).total_seconds()/86400.0)/HALF_LIFE)
    if str(target.get("league") or "").upper()!=str(row.get("league") or "").upper():
        return 0.0
    return rec*(2.0 if names(target)&names(row) else (1.0 if not focus else 0.0))


def tempo_probability(target,history,line):
    prior=[r for r in history if eligible(r) and dt(r["start_time"])<dt(target["start_time"])]
    same=[r for r in prior if str(r.get("league") or "").upper()==str(target.get("league") or "").upper()]
    focused=[r for r in same if names(target)&names(r)]
    pool=focused if len(focused)>=MIN_PRIOR else same
    weighted=[]
    for r in pool:
        w=weight(target,r,focus=pool is focused)
        if w<=0:continue
        total=float(r["final_score"][0])+float(r["final_score"][1])
        weighted.append((total,w))
    if len(weighted)<MIN_PRIOR:return None
    # Player-tempo empirical CDF with a light prior centered on the tour's
    # observed distribution. This avoids pretending a sparse player history is
    # a complete match-duration model.
    mass={}
    for total,w in weighted:
        mass[total]=mass.get(total,0.0)+w
    alpha=0.20
    prior_mass={float(k):alpha for k in range(12,40 if str(target.get("league")).upper()=="WTA" else 66)}
    for k,v in mass.items():prior_mass[k]=prior_mass.get(k,alpha)+v
    z=sum(prior_mass.values())
    over=sum(v for k,v in prior_mass.items() if k>float(line))/z
    return {"over":over,"under":1-over,"n":len(weighted),"focused":pool is focused}


def score(rows,key):
    if not rows:return None
    b=l=acc=0.0
    for r in rows:
        p=max(.001,min(.999,float(r[key])))
        y=1.0 if r["actual_over"] else 0.0
        b+=(p-y)**2
        l-=y*math.log(p)+(1-y)*math.log(1-p)
        acc+=float((p>=.5)==bool(y))
    n=len(rows)
    return {"n":n,"accuracy":round(acc/n,4),"brier":round(b/n,4),"log_loss":round(l/n,4)}


def main():
    history=json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    rows=sorted([r for r in history if eligible(r)],key=lambda r:dt(r["start_time"]))
    scored=[]
    for i,target in enumerate(rows):
        prior=rows[:i]
        total=(target.get("analytics") or {}).get("total_games") or {}
        line=total.get("line")
        if line is None or len(prior)<MIN_PRIOR:continue
        line=float(line)
        actual=float(target["final_score"][0])+float(target["final_score"][1])>line
        current=over_probability(target,prior,line)
        tempo=tempo_probability(target,prior,line)
        if not current or not tempo:continue
        scored.append({"event_id":target.get("event_id"),"start_time":target.get("start_time"),
                       "tour":str(target.get("league") or "").upper(),"line":line,
                       "actual_over":actual,"current_over":float(current["over"]),
                       "tempo_over":float(tempo["over"]),"tempo_n":tempo["n"]})
    cut=int(len(scored)*.8)
    hold=scored[cut:]
    out={"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"PAPER_RESEARCH_ONLY",
         "rows":len(scored),"holdout_rows":len(hold),
         "all":{"current":score(scored,"current_over"),"tempo":score(scored,"tempo_over")},
         "holdout":{"current":score(hold,"current_over"),"tempo":score(hold,"tempo_over")},
         "by_tour":{}}
    for tour in sorted({r["tour"] for r in scored}):
        a=[r for r in scored if r["tour"]==tour]
        h=a[int(len(a)*.8):]
        out["by_tour"][tour]={"all":{"current":score(a,"current_over"),"tempo":score(a,"tempo_over")},
                              "holdout":{"current":score(h,"current_over"),"tempo":score(h,"tempo_over")}}
    out["activation_gate"]="HOLD — tempo challenger must beat current model and then the SportyBet benchmark on an untouched block before promotion."
    OUTPUT.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2))


if __name__=="__main__":
    main()
