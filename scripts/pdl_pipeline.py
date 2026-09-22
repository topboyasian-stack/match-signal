"""England U21 Professional Development League prediction pipeline.

Historical results: BetStudy current-season results page.
Upcoming fixtures: Match Signal's SportyBet NG proxy, filtered to the exact
PDL tournament name. Model fitting is independent of bookmaker prices.
"""
from __future__ import annotations
import json, math, re, io
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
SPORTY="https://match-signal.pages.dev/api/sportybet"
LEAGUE="England Amateur - U21 Professional Development League"
RESULTS_URL="https://www.betstudy.com/soccer-stats/c/england/u21-professional-development-league-2/d/results/"
S=requests.Session()
S.headers.update({"User-Agent":"MatchSignal/PDL/1.1","Accept":"text/html,application/json"})

def parse_date(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).replace(tzinfo=timezone.utc) if "+" not in str(v) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:
        for f in ("%d.%m.%Y","%Y-%m-%d"):
            try:return datetime.strptime(str(v).strip(),f).replace(tzinfo=timezone.utc)
            except Exception:pass
    return None

def history():
    html=S.get(RESULTS_URL,timeout=30).text
    tables=pd.read_html(io.StringIO(html))
    rows=[]
    for df in tables:
        cols={str(c).strip().lower() for c in df.columns}
        if not {"date","home","score","away"}.issubset(cols):continue
        df.columns=[str(c).strip().lower() for c in df.columns]
        for _,r in df.iterrows():
            d=parse_date(r.get("date"))
            m=re.search(r"(\d+)\s*-\s*(\d+)",str(r.get("score","")))
            h=str(r.get("home","")).strip();a=str(r.get("away","")).strip()
            if d and m and h and a:
                rows.append({"event_id":f"betstudy|{d.date()}|{h}|{a}","start_time":d.isoformat(),"home":h,"away":a,"home_score":float(m.group(1)),"away_score":float(m.group(2))})
    if not rows:raise RuntimeError("BetStudy PDL results table was not parsed")
    return sorted({x["event_id"]:x for x in rows}.values(),key=lambda x:x["start_time"])

def upcoming():
    params={"sportId":"sr:sport:1","marketId":"1,18,10,14,16,29,45,47","pageSize":"100","pageNum":"1","timeline":"168"}
    r=S.get(SPORTY,params=params,timeout=30);r.raise_for_status();body=r.json()
    events=[]
    for t in (body.get("data") or {}).get("tournaments") or []:
        if str(t.get("name") or "").strip()!=LEAGUE:continue
        for e in t.get("events") or []:
            try:start=datetime.fromtimestamp(float(e.get("estimateStartTime"))/1000,tz=timezone.utc)
            except Exception:continue
            h=str(e.get("homeTeamName") or "").strip();a=str(e.get("awayTeamName") or "").strip()
            if not h or not a:continue
            events.append({"event_id":str(e.get("eventId")),"start_time":start.isoformat(),"home":h,"away":a,"home_score":None,"away_score":None})
    return sorted({x["event_id"]:x for x in events if x["event_id"]}.values(),key=lambda x:x["start_time"])

def pois(lam,k):return math.exp(-lam)*lam**k/math.factorial(k)

def outcome(lh,la):
    hp=[pois(lh,k) for k in range(13)];ap=[pois(la,k) for k in range(13)];h=d=a=0.0
    for i,x in enumerate(hp):
        for j,y in enumerate(ap):
            if i>j:h+=x*y
            elif i==j:d+=x*y
            else:a+=x*y
    s=h+d+a;return h/s,d/s,a/s

def over(total,line):return 1-sum(pois(total,k) for k in range(math.floor(line)+1))

def build(hist,future):
    now=datetime.now(timezone.utc)
    lh=sum(x["home_score"] for x in hist)/len(hist);la=sum(x["away_score"] for x in hist)/len(hist)
    stats={}
    for x in hist:
        d=parse_date(x["start_time"]);age=max(0,(now-d).total_seconds()/86400) if d else 0;w=math.exp(-math.log(2)*age/120)
        for t,gf,ga in ((x["home"],x["home_score"],x["away_score"]),(x["away"],x["away_score"],x["home_score"])):
            q=stats.setdefault(t,{"gf":0,"ga":0,"w":0});q["gf"]+=w*gf;q["ga"]+=w*ga;q["w"]+=w
    out=[]
    for x in future:
        h=stats.get(x["home"],{});a=stats.get(x["away"],{});hw=min(1,h.get("w",0)/(h.get("w",0)+4));aw=min(1,a.get("w",0)/(a.get("w",0)+4))
        ha=h.get("gf",0)/max(h.get("w",1),1e-9);hd=h.get("ga",0)/max(h.get("w",1),1e-9);aa=a.get("gf",0)/max(a.get("w",1),1e-9);ad=a.get("ga",0)/max(a.get("w",1),1e-9)
        hatk=hw*(ha/max(lh,.5))+(1-hw);hdef=hw*(hd/max(la,.4))+(1-hw);aatk=aw*(aa/max(la,.4))+(1-aw);adef=aw*(ad/max(lh,.5))+(1-aw)
        ex_h=max(.2,lh*hatk*adef);ex_a=max(.15,la*aatk*hdef);total=ex_h+ex_a;hp,dp,ap=outcome(ex_h,ex_a);probs={"p1":round(hp,4),"draw":round(dp,4),"p2":round(ap,4)}
        pick=max((("p1",hp),("draw",dp),("p2",ap)),key=lambda z:z[1])[0];ladder={}
        for line in (1.5,2.5,3.5,4.5):
            o=over(total,line);ladder[str(line)]={"line":line,"over":round(o,4),"under":round(1-o,4),"pick":"over" if o>=.5 else "under","fair_over":round(1/max(o,1e-9),2),"fair_under":round(1/max(1-o,1e-9),2)}
        btts=(1-math.exp(-ex_h))*(1-math.exp(-ex_a))
        out.append({"sport":"football","league":LEAGUE,"event_id":x["event_id"],"start_time":x["start_time"],"player_1":x["home"],"player_2":x["away"],"probabilities":probs,"pick":pick,"confidence":round(max(hp,dp,ap),4),"expected_goals":{"p1":round(ex_h,2),"p2":round(ex_a,2),"total":round(total,2)},"markets":{"over_under":{"line":2.5,"over":ladder["2.5"]["over"],"under":ladder["2.5"]["under"],"pick":ladder["2.5"]["pick"],"source":"PDL time-safe recency-weighted attack/defence + Poisson","ladder":ladder},"btts":{"yes":round(btts,4),"no":round(1-btts,4)}},"fair_odds":{"p1":round(1/max(hp,1e-9),2),"draw":round(1/max(dp,1e-9),2),"p2":round(1/max(ap,1e-9),2)},"model":"PDL time-safe recency-weighted attack/defence + Poisson","model_version":"PDL-1.1-2026.09.22","prediction_status":"research_only","paper_only":True})
    return out

def main():
    hist=history();future=upcoming();pred=build(hist,future);now=datetime.now(timezone.utc).isoformat()
    status={"updated_at":now,"competition":LEAGUE,"historical_rows":len(hist),"current_upcoming":len(pred),"historical_source":RESULTS_URL,"fixture_source":"SportyBet NG via Match Signal Cloudflare proxy","model":"PDL-1.1-2026.09.22","paper_only":True,"gates":{"model_live_trading_approved":False,"requires_walk_forward_validation":True,"requires_market_benchmark":True}}
    (DATA/"pdl_predictions.json").write_text(json.dumps(pred,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(DATA/"pdl_status.json").write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");print(json.dumps(status,indent=2))
if __name__=="__main__":main()
