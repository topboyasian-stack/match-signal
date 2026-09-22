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
from bs4 import BeautifulSoup

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

def betstudy_history():
    response=S.get(RESULTS_URL,timeout=30)
    response.raise_for_status()

    # BetStudy's current results page is card/list markup, not an HTML table.
    # Parse the visible result sequence directly: date -> home -> score -> away.
    soup=BeautifulSoup(response.text,"html.parser")
    strings=list(soup.stripped_strings)
    stop=next(
        (i for i,value in enumerate(strings)
         if "quick stats" in value.lower()),
        len(strings),
    )
    strings=strings[:stop]

    date_re=re.compile(r"^(\d{2}\.\d{2}\.\d{4})(?:\s+.*)?$")
    score_re=re.compile(r"^(\d+)\s*-\s*(\d+)$")
    rows=[]
    current_date=None

    for i,value in enumerate(strings):
        dm=date_re.match(value)
        if dm:
            current_date=dm.group(1)
            continue

        sm=score_re.match(value)
        if not sm or not current_date:
            continue

        # The visible result card sequence places the home team immediately
        # before the score and the away team immediately after it.
        before=strings[i-1].strip() if i else ""
        after=strings[i+1].strip() if i+1<len(strings) else ""
        if not before or not after:
            continue

        # Skip UI/control text that can occur around the result list.
        blocked={"HOME","AWAY","ODDS","PREDICTIONS","RESULTS","SHOW MORE"}
        if before.upper() in blocked or after.upper() in blocked:
            continue

        d=parse_date(current_date)
        if not d:
            continue

        rows.append({
            "event_id":f"betstudy|{d.date()}|{before}|{after}",
            "start_time":d.isoformat(),
            "home":before,
            "away":after,
            "home_score":float(sm.group(1)),
            "away_score":float(sm.group(2)),
            "source":"BetStudy current-season PDL results",
        })

    rows=[x for x in rows if x["home"] and x["away"]]
    if not rows:
        raise RuntimeError("BetStudy PDL result cards were not parsed")
    return sorted(
        {x["event_id"]:x for x in rows}.values(),
        key=lambda x:x["start_time"]
    )




def sofascore_history():
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
    return sorted(
        {x["event_id"]:x for x in rows}.values(),
        key=lambda x:x["start_time"]
    )


def history():
    try:
        return betstudy_history(), "BetStudy"
    except Exception as primary_error:
        hist=sofascore_history()
        return hist, "SofaScore fallback"




def sportybet_upcoming():
    params={"sportId":"sr:sport:1","marketId":"1,18,10,14,16,29,45,47","pageSize":"100","pageNum":"1","timeline":"168"}
    r=S.get(SPORTY,params=params,timeout=30)
    r.raise_for_status()
    body=r.json()
    events=[]
    for t in (body.get("data") or {}).get("tournaments") or []:
        if str(t.get("name") or "").strip()!=LEAGUE:
            continue
        for e in t.get("events") or []:
            try:
                start=datetime.fromtimestamp(float(e.get("estimateStartTime"))/1000,tz=timezone.utc)
            except Exception:
                continue
            h=str(e.get("homeTeamName") or "").strip()
            a=str(e.get("awayTeamName") or "").strip()
            if not h or not a:
                continue
            events.append({
                "event_id":str(e.get("eventId") or ""),
                "start_time":start.isoformat(),
                "home":h,
                "away":a,
                "home_score":None,
                "away_score":None,
                "source":"SportyBet NG via Match Signal Cloudflare proxy",
            })
    return sorted(
        {x["event_id"]:x for x in events if x["event_id"]}.values(),
        key=lambda x:x["start_time"]
    )


def betstudy_upcoming():
    response=S.get(RESULTS_URL,timeout=30)
    response.raise_for_status()
    soup=BeautifulSoup(response.text,"html.parser")
    strings=list(soup.stripped_strings)
    start_idx=next(
        (i for i,value in enumerate(strings)
         if "computer prediction" in value.lower()),
        0,
    )
    stop=next(
        (i for i in range(start_idx+1,len(strings))
         if "u21 professional development league 2 predictions" in strings[i].lower()),
        len(strings),
    )
    date_re=re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})$")
    rows=[]
    for i in range(start_idx+1,stop):
        dm=date_re.match(strings[i])
        if not dm or i==0:
            continue
        match_name=strings[i-1].strip()
        parts=[x.strip() for x in match_name.split(" - ",1)]
        if len(parts)!=2:
            continue
        try:
            dt=datetime.strptime(strings[i],"%d %B %Y %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        rows.append({
            "event_id":f"betstudy-upcoming|{dt.date()}|{parts[0]}|{parts[1]}",
            "start_time":dt.isoformat(),
            "home":parts[0],
            "away":parts[1],
            "home_score":None,
            "away_score":None,
            "source":"BetStudy PDL computer-prediction fixture feed",
        })
    return sorted(
        {x["event_id"]:x for x in rows}.values(),
        key=lambda x:x["start_time"]
    )


def upcoming():
    try:
        events=sportybet_upcoming()
        if events:
            return events, "SportyBet"
    except Exception:
        pass
    events=betstudy_upcoming()
    if events:
        return events, "BetStudy"
    return [], "none"



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
    hist,history_source=history();future,fixture_source=upcoming();pred=build(hist,future);now=datetime.now(timezone.utc).isoformat()
    status={"updated_at":now,"competition":LEAGUE,"historical_rows":len(hist),"current_upcoming":len(pred),"historical_source":history_source,"fixture_source":fixture_source,"model":"PDL-1.2-2026.09.22","paper_only":True,"gates":{"model_live_trading_approved":False,"requires_walk_forward_validation":True,"requires_market_benchmark":True}}
    (DATA/"pdl_predictions.json").write_text(json.dumps(pred,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(DATA/"pdl_status.json").write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");print(json.dumps(status,indent=2))
if __name__=="__main__":main()
