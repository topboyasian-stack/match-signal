"""England U21 Professional Development League prediction pipeline."""
from __future__ import annotations
import json, math, re
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
BASE="https://www.sofascore.com/api/v1"
TOURNAMENT_ID=13946
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"MatchSignal/PDL/1.0","Accept":"application/json"})

def get(path):
    r=SESSION.get(BASE+path,timeout=25)
    r.raise_for_status()
    return r.json()

def dt(v):
    try:return datetime.fromtimestamp(float(v),tz=timezone.utc)
    except Exception:return None

def score(e):
    h=e.get("homeScore") or {}; a=e.get("awayScore") or {}
    try:return float(h.get("normaltime",h.get("current"))),float(a.get("normaltime",a.get("current")))
    except Exception:return None

def name(t):return str((t or {}).get("name") or (t or {}).get("shortName") or "").strip()

def seasons():
    return get(f"/unique-tournament/{TOURNAMENT_ID}/seasons").get("seasons") or []

def choose():
    ss=seasons()
    def year(s):
        m=re.search(r"20\d{2}",str(s.get("name") or s.get("year") or ""))
        return int(m.group()) if m else 0
    ss=sorted(ss,key=year,reverse=True)
    return (ss[0] if ss else None),(ss[1] if len(ss)>1 else None)

def events(season_id):
    out={}
    for endpoint in ("last","next"):
        for page in range(10):
            try:batch=get(f"/unique-tournament/{TOURNAMENT_ID}/season/{season_id}/events/{endpoint}/{page}").get("events") or []
            except Exception:break
            if not batch:break
            for e in batch:
                if e.get("id"):out[str(e["id"])]=e
            if len(batch)<20:break
    return list(out.values())

def norm(rows):
    out=[]
    for e in rows:
        d=dt(e.get("startTimestamp")); h=name(e.get("homeTeam")); a=name(e.get("awayTeam"))
        if not d or not h or not a:continue
        sc=score(e)
        out.append({"event_id":str(e["id"]),"start_time":d.isoformat(),"home":h,"away":a,"home_score":sc[0] if sc else None,"away_score":sc[1] if sc else None})
    return sorted(out,key=lambda x:(x["start_time"],x["event_id"]))

def pois(lam,k):
    return math.exp(-lam)*lam**k/math.factorial(k)

def outcome(lh,la):
    hp=[pois(lh,k) for k in range(13)];ap=[pois(la,k) for k in range(13)]
    h=d=a=0.0
    for i,x in enumerate(hp):
        for j,y in enumerate(ap):
            if i>j:h+=x*y
            elif i==j:d+=x*y
            else:a+=x*y
    s=h+d+a
    return h/s,d/s,a/s

def over(total,line):
    return 1-sum(pois(total,k) for k in range(math.floor(line)+1))

def build(history):
    done=[x for x in history if x["home_score"] is not None and x["away_score"] is not None]
    future=[x for x in history if x["home_score"] is None or x["away_score"] is None]
    lh=sum(x["home_score"] for x in done)/len(done) if done else 1.55
    la=sum(x["away_score"] for x in done)/len(done) if done else 1.30
    stats={}
    now=datetime.now(timezone.utc)
    for x in done:
        age=max(0,(now-datetime.fromisoformat(x["start_time"])).total_seconds()/86400)
        w=math.exp(-math.log(2)*age/120)
        for t,gf,ga in ((x["home"],x["home_score"],x["away_score"]),(x["away"],x["away_score"],x["home_score"])):
            s=stats.setdefault(t,{"gf":0,"ga":0,"w":0,"n":0});s["gf"]+=w*gf;s["ga"]+=w*ga;s["w"]+=w;s["n"]+=1
    out=[]
    for x in future:
        h=stats.get(x["home"],{});a=stats.get(x["away"],{})
        hw=min(1,h.get("w",0)/(h.get("w",0)+4));aw=min(1,a.get("w",0)/(a.get("w",0)+4))
        ha=(h.get("gf",0)/max(h.get("w",1),1e-9));hd=(h.get("ga",0)/max(h.get("w",1),1e-9))
        aa=(a.get("gf",0)/max(a.get("w",1),1e-9));ad=(a.get("ga",0)/max(a.get("w",1),1e-9))
        hatk=hw*(ha/max(lh,.5))+(1-hw);hdef=hw*(hd/max(la,.4))+(1-hw)
        aatk=aw*(aa/max(la,.4))+(1-aw);adef=aw*(ad/max(lh,.5))+(1-aw)
        ex_h=max(.2,lh*hatk*adef);ex_a=max(.15,la*aatk*hdef);total=ex_h+ex_a
        hp,dp,ap=outcome(ex_h,ex_a);probs={"p1":round(hp,4),"draw":round(dp,4),"p2":round(ap,4)}
        pick=max((("p1",hp),("draw",dp),("p2",ap)),key=lambda z:z[1])[0]
        ladder={}
        for line in (1.5,2.5,3.5,4.5):
            o=over(total,line);ladder[str(line)]={"line":line,"over":round(o,4),"under":round(1-o,4),"pick":"over" if o>=.5 else "under","fair_over":round(1/max(o,1e-9),2),"fair_under":round(1/max(1-o,1e-9),2)}
        btts=(1-math.exp(-ex_h))*(1-math.exp(-ex_a))
        out.append({"sport":"football","league":"England Amateur - U21 Professional Development League","event_id":x["event_id"],"start_time":x["start_time"],"player_1":x["home"],"player_2":x["away"],"venue":None,"probabilities":probs,"pick":pick,"confidence":round(max(hp,dp,ap),4),"expected_goals":{"p1":round(ex_h,2),"p2":round(ex_a,2),"total":round(total,2)},"markets":{"over_under":{"line":2.5,"over":ladder["2.5"]["over"],"under":ladder["2.5"]["under"],"pick":ladder["2.5"]["pick"],"source":"PDL time-safe recency-weighted team model","ladder":ladder},"btts":{"yes":round(btts,4),"no":round(1-btts,4)}},"fair_odds":{"p1":round(1/max(hp,1e-9),2),"draw":round(1/max(dp,1e-9),2),"p2":round(1/max(ap,1e-9),2)},"model":"PDL time-safe recency-weighted attack/defence + Poisson","model_version":"PDL-1.0-2026.09.22","prediction_status":"research_only","paper_only":True})
    return out,len(done)

def main():
    cur,prev=choose()
    if not cur:raise RuntimeError("PDL season feed unavailable")
    ce=norm(events(cur["id"]));pe=norm(events(prev["id"])) if prev else []
    pred,done=build(pe+ce)
    current_ids={e["event_id"] for e in ce if e["home_score"] is None or e["away_score"] is None}
    pred=[p for p in pred if p["event_id"] in current_ids]
    now=datetime.now(timezone.utc).isoformat()
    status={"updated_at":now,"competition":"England Amateur - U21 Professional Development League","tournament_id":TOURNAMENT_ID,"season":{"id":cur.get("id"),"name":cur.get("name")},"previous_season_id":prev.get("id") if prev else None,"completed_history_rows":done,"current_upcoming":len(pred),"source":"SofaScore public competition feed","model":"PDL-1.0-2026.09.22","paper_only":True,"market_source":"SportyBet NG synchronization is separate from model fitting","gates":{"model_live_trading_approved":False,"requires_walk_forward_validation":True,"requires_market_benchmark":True}}
    (DATA/"pdl_predictions.json").write_text(json.dumps(pred,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    (DATA/"pdl_status.json").write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(status,indent=2))
if __name__=="__main__":main()
