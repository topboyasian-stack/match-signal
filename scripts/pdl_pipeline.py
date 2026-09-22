"""England U21 Professional Development League prediction pipeline.

Historical results: BetStudy current-season results page.
Upcoming fixtures: Match Signal's SportyBet NG proxy, filtered to the exact
PDL tournament name. Model fitting is independent of bookmaker prices.
"""
from __future__ import annotations
import json, math, re
from datetime import datetime, timezone
from pathlib import Path
import requests

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

SOFASCORE="https://www.sofascore.com/api/v1"
TOURNAMENT_ID=13946

def sofascore_json(path):
    r=S.get(SOFASCORE+path,timeout=30,headers={"User-Agent":"MatchSignal/PDL/1.2"})
    r.raise_for_status()
    return r.json()

def current_season():
    body=sofascore_json(f"/unique-tournament/{TOURNAMENT_ID}/seasons")
    seasons=body.get("seasons") or []
    if not seasons:
        raise RuntimeError("SofaScore returned no PDL seasons")
    return int(seasons[0]["id"])

def history():
    season=current_season()
    rows=[]
    for page in range(0,10):
        body=sofascore_json(f"/unique-tournament/{TOURNAMENT_ID}/season/{season}/events/last/{page}")
        events=body.get("events") or []
        if not events:
            break
        for e in events:
            status=(e.get("status") or {})
            if status.get("type") not in {"finished","post"} and status.get("code") not in {100,120}:
                continue
            home=e.get("homeTeam") or {}
            away=e.get("awayTeam") or {}
            hs=(e.get("homeScore") or {}).get("current")
            as_=(e.get("awayScore") or {}).get("current")
            if hs is None:
                hs=(e.get("homeScore") or {}).get("normaltime")
            if as_ is None:
                as_=(e.get("awayScore") or {}).get("normaltime")
            ts=e.get("startTimestamp")
            if not ts or hs is None or as_ is None:
                continue
            rows.append({
                "event_id":f"sofascore|{e.get('id')}",
                "start_time":datetime.fromtimestamp(float(ts),tz=timezone.utc).isoformat(),
                "home":str(home.get("name") or "").strip(),
                "away":str(away.get("name") or "").strip(),
                "home_score":float(hs),
                "away_score":float(as_),
                "source":"SofaScore structured PDL season feed",
            })
        if len(events)<20:
            break
    rows=[x for x in rows if x["home"] and x["away"]]
    if not rows:
        raise RuntimeError("SofaScore PDL results returned no finished events")
    return sorted({x["event_id"]:x for x in rows}.values(),key=lambda x:x["start_time"])

def upcoming():
    events=[]
    for page in (1,2):
        params={"sportId":"sr:sport:1","marketId":"1,18,10,14,16,29,45,47","pageSize":"100","pageNum":str(page),"timeline":"168"}
        r=S.get(SPORTY,params=params,timeout=30);r.raise_for_status();body=r.json()

        # Support both known SportyBet proxy envelopes:
        # {events:[...]} and {data:{events:[...] / tournaments:[...]}}.
        scoped=[]
        top=body.get("events")
        if isinstance(top,list):
            scoped.extend((None,e) for e in top if isinstance(e,dict))
        data=body.get("data") if isinstance(body.get("data"),dict) else {}
        if isinstance(data.get("events"),list):
            scoped.extend((None,e) for e in data["events"] if isinstance(e,dict))
        if isinstance(data.get("tournaments"),list):
            for t in data["tournaments"]:
                if not isinstance(t,dict):
                    continue
                tournament_name=str(t.get("name") or t.get("tournamentName") or "").strip()
                if tournament_name and tournament_name!=LEAGUE:
                    continue
                for e in t.get("events") or []:
                    if isinstance(e,dict):
                        scoped.append((tournament_name,e))

        for tournament_name,e in scoped:
            event_tournament=str(
                e.get("tournamentName")
                or e.get("tournament_name")
                or e.get("competition")
                or ((e.get("tournament") or {}).get("name") if isinstance(e.get("tournament"),dict) else "")
                or tournament_name
                or ""
            ).strip()
            if event_tournament and event_tournament!=LEAGUE:
                continue
            try:
                raw_start=e.get("estimateStartTime")
                if raw_start is None:
                    raw_start=e.get("startTimeMs")
                start=datetime.fromtimestamp(float(raw_start)/1000,tz=timezone.utc)
            except Exception:
                continue
            event_id=str(e.get("eventId") or e.get("event_id") or "").strip()
            h=str(e.get("homeTeamName") or e.get("team_1") or e.get("homeTeam") or "").strip()
            a=str(e.get("awayTeamName") or e.get("team_2") or e.get("awayTeam") or "").strip()
            if not event_id or not h or not a:
                continue
            events.append({"event_id":event_id,"start_time":start.isoformat(),"home":h,"away":a,"home_score":None,"away_score":None})
        if len(top or [])<100 and not data.get("events") and not data.get("tournaments"):
            break
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
        out.append({"sport":"football","league":LEAGUE,"event_id":x["event_id"],"start_time":x["start_time"],"player_1":x["home"],"player_2":x["away"],"probabilities":probs,"pick":pick,"confidence":round(max(hp,dp,ap),4),"expected_goals":{"p1":round(ex_h,2),"p2":round(ex_a,2),"total":round(total,2)},"markets":{"over_under":{"line":2.5,"over":ladder["2.5"]["over"],"under":ladder["2.5"]["under"],"pick":ladder["2.5"]["pick"],"source":"PDL time-safe recency-weighted attack/defence + Poisson","ladder":ladder},"btts":{"yes":round(btts,4),"no":round(1-btts,4)}},"fair_odds":{"p1":round(1/max(hp,1e-9),2),"draw":round(1/max(dp,1e-9),2),"p2":round(1/max(ap,1e-9),2)},"model":"PDL time-safe recency-weighted attack/defence + Poisson","model_version":"PDL-1.2-2026.09.22","prediction_status":"research_only","paper_only":True})
    return out

def main():
    hist=history();future=upcoming();pred=build(hist,future);now=datetime.now(timezone.utc).isoformat()
    status={"updated_at":now,"competition":LEAGUE,"historical_rows":len(hist),"current_upcoming":len(pred),"historical_source":RESULTS_URL,"fixture_source":"SportyBet NG via Match Signal Cloudflare proxy","model":"PDL-1.2-2026.09.22","paper_only":True,"gates":{"model_live_trading_approved":False,"requires_walk_forward_validation":True,"requires_market_benchmark":True}}
    (DATA/"pdl_predictions.json").write_text(json.dumps(pred,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(DATA/"pdl_status.json").write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");print(json.dumps(status,indent=2))
if __name__=="__main__":main()
