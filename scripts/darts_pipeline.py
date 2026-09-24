"""Isolated Darts-X research engine.

Scope is deliberately independent from Football, Tennis, Basketball and the
Virtual Lab. SportyBet supplies current prices/fixtures; TheSportsDB supplies
public historical results. No private feeds, RNG manipulation or cross-sport
model state is used.
"""
from __future__ import annotations
import json, math, time, hashlib
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"darts_history.json"
UPCOMING=DATA/"darts_upcoming.json"
MODEL=DATA/"darts_model.json"
CANDIDATES=DATA/"darts_candidates.json"
STATUS=DATA/"darts_status.json"

SPORTYBET_PROXY="https://match-signal.pages.dev/api/sportybet-darts"
SPORTYBET="https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents"
SPORTYBET_HEADERS={"Accept":"application/json, text/plain, */*","Content-Type":"application/json","Current-Country":"NG","Origin":"https://www.sportybet.com","Referer":"https://www.sportybet.com/ng/","User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"}
TSDB="https://www.thesportsdb.com/api/v1/json/123/eventsday.php"
BENCHMARK=0.80325064
HISTORY_DAYS=21
K=28.0
RECENT=8
MIN_GATE_N=30

def load(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return default
def save(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def norm(s):
    return " ".join("".join(c for c in str(s or "").lower().strip() if c not in "[]").replace("-"," ").split())
def ts(v):
    try:
        x=str(v or "").replace("Z","+00:00")
        d=datetime.fromisoformat(x)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:return 0.0
def iso(v):
    t=ts(v)
    return datetime.fromtimestamp(t,tz=timezone.utc).isoformat() if t else ""
def clamp(p):return max(0.01,min(0.99,float(p)))
def elo_prob(a,b):return 1/(1+10**((b-a)/400))
def wilson_lower(w,n,z=1.645):
    if n<=0:return 0.0
    p=w/n; den=1+z*z/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/den

def fetch_sportybet():
    errors=[]
    urls=[SPORTYBET_PROXY]
    # Direct SportyBet access from hosted CI can be protected or return non-JSON.
    # The isolated Cloudflare provider boundary is therefore authoritative.
    for url in urls:
        try:
            params={"pageSize":100,"pageNum":1,"timeline":168,"_t":int(time.time()*1000)}
            if "sportybet-" in url:
                params={}
            r=requests.get(url,params=params,headers={"Accept":"application/json","User-Agent":"MatchSignal-Darts-X/1.0"},timeout=25)
            r.raise_for_status()
            body=r.json()
            rows=[]
            for e in (body.get("events") or []):
                p1=str(e.get("participant_1") or "").strip()
                p2=str(e.get("participant_2") or "").strip()
                if not p1 or not p2 or not e.get("event_id"):continue
                markets=[]
                for m in (e.get("markets") or []):
                    outs=[]
                    for o in (m.get("outcomes") or []):
                        try:od=float(o.get("odds"))
                        except (TypeError,ValueError):continue
                        if od>1:outs.append({"id":str(o.get("id") or ""),"name":str(o.get("name") or o.get("desc") or "").strip(),"odds":od})
                    if outs:markets.append({"id":str(m.get("id") or ""),"name":str(m.get("name") or m.get("desc") or "").strip(),"outcomes":outs})
                rows.append({"event_id":str(e["event_id"]),"competition":str(e.get("competition") or ""),"category":str(e.get("category") or ""),"start_time_ms":e.get("start_time_ms"),"player_1":p1,"player_2":p2,"markets":markets})
            return rows,errors
        except Exception as exc:
            errors.append(f"SportyBet provider boundary: {exc}")
    return [],errors

def winner_market(row):
    ms=[m for m in row.get("markets",[]) if len(m.get("outcomes",[]))>=2]
    for m in ms:
        if m["id"] in {"1","186"} or any(x in m["name"].lower() for x in ("winner","match result","1x2")):return m
    return ms[0] if ms else None

def fetch_results(days=HISTORY_DAYS):
    out=[]; errors=[]
    now=datetime.now(timezone.utc).date()
    session=requests.Session(); session.headers.update({"User-Agent":"MatchSignal-Darts-X/1.0","Accept":"application/json"})
    for i in range(days,0,-1):
        day=now-timedelta(days=i)
        try:
            r=session.get(TSDB,params={"d":day.isoformat(),"s":"Darts"},timeout=20)
            r.raise_for_status(); payload=r.json()
            for e in payload.get("events") or []:
                a=str(e.get("strHomeTeam") or e.get("strPlayer1") or "").strip()
                b=str(e.get("strAwayTeam") or e.get("strPlayer2") or "").strip()
                if not a or not b:continue
                ha=e.get("intHomeScore"); hb=e.get("intAwayScore")
                try:ha=int(float(ha)); hb=int(float(hb))
                except (TypeError,ValueError):continue
                stamp=e.get("strTimestamp") or e.get("dateEvent") or ""
                if not stamp:stamp=day.isoformat()+"T00:00:00Z"
                eid=str(e.get("idEvent") or hashlib.sha1(f"darts|{day}|{a}|{b}|{ha}|{hb}".encode()).hexdigest()[:16])
                out.append({"event_id":eid,"source":"TheSportsDB","timestamp":iso(stamp) or day.isoformat()+"T00:00:00+00:00","competition":str(e.get("strLeague") or ""),"player_1":a,"player_2":b,"score_1":ha,"score_2":hb})
        except Exception as exc:errors.append(f"{day.isoformat()}: {exc}")
        time.sleep(0.20)
    dedup={x["event_id"]:x for x in out}
    return sorted(dedup.values(),key=lambda x:ts(x["timestamp"])),errors

def build_variant(records,variant):
    ratings={}; forms=defaultdict(lambda:deque(maxlen=RECENT)); margins=defaultdict(lambda:deque(maxlen=RECENT)); h2h=defaultdict(lambda:[0,0])
    scored=[]
    for row in sorted(records,key=lambda x:ts(x["timestamp"])):
        a,b=norm(row["player_1"]),norm(row["player_2"])
        ra,rb=ratings.get(a,1500.0),ratings.get(b,1500.0)
        p=elo_prob(ra,rb)
        if variant in {"elo_form","elo_form_h2h","elo_form_margin"}:
            fa=(sum(forms[a])+1)/(len(forms[a])+2); fb=(sum(forms[b])+1)/(len(forms[b])+2)
            p=.75*p+.25*(fa/(fa+fb))
        if variant=="elo_form_h2h":
            key=tuple(sorted((a,b))); w,l=h2h[key]
            if w+l>=5:p=.85*p+.15*((w+1)/(w+l+2))
        if variant=="elo_form_margin":
            ma=sum(margins[a])/len(margins[a]) if margins[a] else 0
            mb=sum(margins[b])/len(margins[b]) if margins[b] else 0
            p=clamp(.85*p+.15*(1/(1+math.exp(-(ma-mb)/3))))
        p=clamp(p)
        actual=1.0 if row["score_1"]>row["score_2"] else 0.0
        scored.append((row,p,actual))
        change=K*(actual-p)
        ratings[a]=ra+change;ratings[b]=rb-change
        forms[a].append(1 if actual else 0);forms[b].append(0 if actual else 1)
        margins[a].append(row["score_1"]-row["score_2"]);margins[b].append(row["score_2"]-row["score_1"])
        if actual:h2h[tuple(sorted((a,b)))][0]+=1
        else:h2h[tuple(sorted((a,b)))][1]+=1
    return scored

def metrics(items):
    if not items:return {"n":0,"accuracy":None,"brier":None,"log_loss":None,"wilson_lower_90":None}
    correct=sum((p>=.5)==bool(y) for _,p,y in items); n=len(items)
    b=sum((p-y)**2 for _,p,y in items)/n
    ll=sum(-(y*math.log(max(p,1e-6))+(1-y)*math.log(max(1-p,1e-6))) for _,p,y in items)/n
    return {"n":n,"accuracy":correct/n,"brier":b,"log_loss":ll,"wilson_lower_90":wilson_lower(correct,n)}

def precision_bands(items):
    rows=[]
    for threshold in (0.65,0.70,0.75,0.80):
        sel=[x for x in items if max(x[1],1-x[1])>=threshold]
        m=metrics(sel);rows.append({"threshold":threshold,**m})
    return rows

def main():
    history=load(HISTORY,[])
    if not isinstance(history,list):history=[]
    fresh,source_errors=fetch_results()
    merged={str(x.get("event_id")):x for x in history if isinstance(x,dict) and x.get("event_id")}
    for x in fresh:merged[str(x["event_id"])]=x
    history=sorted(merged.values(),key=lambda x:ts(x.get("timestamp")))
    save(HISTORY,history)
    variants={}
    for v in ("elo","elo_form","elo_form_h2h","elo_form_margin"):
        scored=build_variant(history,v)
        split=max(1,int(len(scored)*0.70))
        train,test=scored[:split],scored[split:]
        variants[v]={"all":metrics(scored),"train":metrics(train),"holdout":metrics(test),"bands":precision_bands(test)}
    selected=max(variants,key=lambda v:((variants[v]["holdout"]["accuracy"] or 0),-(variants[v]["holdout"]["brier"] or 1)))
    chosen=variants[selected]
    qualifying=[b for b in chosen["bands"] if b["n"]>=MIN_GATE_N and b["accuracy"] is not None]
    gate_row=max(qualifying,key=lambda b:(b["accuracy"],b["wilson_lower_90"] or 0)) if qualifying else {"threshold":0.75,"n":0,"accuracy":None,"wilson_lower_90":None}
    promoted=bool(gate_row["accuracy"] is not None and gate_row["n"]>=MIN_GATE_N and gate_row["accuracy"]>BENCHMARK and (gate_row.get("wilson_lower_90") or 0)>=0.75)
    model={"version":"DARTS-X-1.0","generated_at":datetime.now(timezone.utc).isoformat(),"scope":"Darts pre-match winner only","history_events":len(history),"source_results":"TheSportsDB public event results","source_odds":"SportyBet NG current odds","frozen_vfootball_benchmark":BENCHMARK,"variants":variants,"selected_variant":selected,"precision_gate":{"minimum_n":MIN_GATE_N,"selected":gate_row,"beats_vfootball":bool(gate_row.get("accuracy") is not None and gate_row["accuracy"]>BENCHMARK),"promoted":promoted},"mode":"PAPER_ONLY"}
    save(MODEL,model)
    upcoming,odds_errors=fetch_sportybet()
    ratings={}
    for row,p,actual in build_variant(history,selected):
        a,b=norm(row["player_1"]),norm(row["player_2"])
        ra,rb=ratings.get(a,1500.0),ratings.get(b,1500.0)
        ch=K*(actual-p); ratings[a]=ra+ch; ratings[b]=rb-ch
    candidates=[]; enriched=[]
    threshold=float(gate_row.get("threshold") or .75)
    for e in upcoming:
        a,b=norm(e["player_1"]),norm(e["player_2"]); pa=elo_prob(ratings.get(a,1500),ratings.get(b,1500))
        wm=winner_market(e); odds={}
        if wm:
            for o in wm["outcomes"]:
                no=norm(o["name"])
                if no==a or a in no or no.endswith(" "+a):odds["p1"]=o["odds"]
                if no==b or b in no or no.endswith(" "+b):odds["p2"]=o["odds"]
            if "p1" not in odds and len(wm["outcomes"])>=2:odds["p1"]=wm["outcomes"][0]["odds"];odds["p2"]=wm["outcomes"][1]["odds"]
        pick="p1" if pa>=.5 else "p2"; prob=max(pa,1-pa); book=odds.get(pick); edge=(prob-1/book) if book else None
        row={**e,"model_variant":selected,"model_prob_p1":round(pa,6),"pick":pick,"confidence":round(prob,6),"book_odds":book,"fair_odds":round(1/prob,3),"edge":round(edge,6) if edge is not None else None,"promotion_gate":promoted,"qualified":bool(promoted and prob>=threshold and edge is not None and edge>=0.015)}
        enriched.append(row)
        if row["qualified"]:candidates.append(row)
    save(UPCOMING,enriched)
    save(CANDIDATES,{"generated_at":datetime.now(timezone.utc).isoformat(),"sport":"darts","mode":"PAPER_ONLY","candidates":candidates,"gate":model["precision_gate"]})
    save(STATUS,{"updated_at":datetime.now(timezone.utc).isoformat(),"sport":"darts","sport_id":"sr:sport:22","history_events":len(history),"upcoming_events":len(enriched),"candidate_count":len(candidates),"model_status":"PROMOTED" if promoted else ("TESTING" if history else "COLLECTING"),"source_results":"TheSportsDB public event results","source_odds":"SportyBet NG","source_errors":source_errors+odds_errors})
    print(json.dumps({"sport":"darts","history":len(history),"upcoming":len(enriched),"selected_variant":selected,"holdout":chosen["holdout"],"precision_gate":model["precision_gate"],"candidates":len(candidates)},indent=2))

if __name__=="__main__":main()
