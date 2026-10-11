#!/usr/bin/env python3
"""Isolated pre-match eFootball winner/BTTS quote research; never creates production picks."""
from __future__ import annotations
import argparse, hashlib, json, math, os, re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
LIVE=DATA/"virtual_lab_live.json"
ARCHIVE=DATA/"efootball_market_research.json"
BASE=os.getenv("MATCH_SIGNAL_PUBLIC_BASE","https://match-signal.pages.dev").rstrip("/")
PRODUCTS={"efootball_gt","efootball_adriatic"}
WINDOW=15

def now_utc(): return datetime.now(timezone.utc)
def dt(v):
    if v is None or v=="": return None
    try:
        if isinstance(v,(int,float)) or str(v).strip().isdigit():
            n=float(v); return datetime.fromtimestamp(n/(1000 if n>10_000_000_000 else 1),timezone.utc)
        d=datetime.fromisoformat(str(v).strip().replace("Z","+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError): return None
def norm(v): return re.sub(r"[^a-z0-9]+"," ",str(v or "").lower()).strip()
def canon(kind,label,p1="",p2=""):
    n=norm(label); compact=n.replace(" ","")
    if kind=="btts":
        if compact in {"yes","gg","bttsyes","bothteamsyes","true"} or n=="both teams to score yes": return "yes"
        if compact in {"no","ng","ngg","bttsno","bothteamsno","false"} or n=="both teams to score no": return "no"
        if re.search(r"\b(yes|gg)\b",n): return "yes"
        if re.search(r"\b(no|ngg|ng)\b",n): return "no"
        return None
    if compact in {"1","home","homewin","team1","player1","p1"}: return "home"
    if compact in {"x","draw","tie","drawn"}: return "draw"
    if compact in {"2","away","awaywin","team2","player2","p2"}: return "away"
    a,b=norm(p1),norm(p2)
    if a and (n==a or n.startswith(a+" ")): return "home"
    if b and (n==b or n.startswith(b+" ")): return "away"
    return None
def classify(m):
    name=norm(m.get("name") or m.get("desc") or m.get("title")); compact=name.replace(" ","")
    if any(x in name for x in ("1st half","first half","2nd half","second half","half time","halftime","extra time","corners","handicap","to qualify")): return None
    outs={norm(o.get("name") or o.get("desc") or o.get("title")).replace(" ","") for o in m.get("outcomes",[]) if isinstance(o,dict)}
    if ("btts" in compact or "bothteamstoscore" in compact or "gg/ngg" in str(m.get("name","")).lower()
        or "gg/ng" in str(m.get("name","")).lower()
        or ({"yes","no"}<=outs and any(x in name for x in ("score","goal","both")))):
        return "btts"
    if any(x in compact for x in ("1x2","matchresult","fulltimeresult","matchwinner","winner")):
        return "match_winner"
    if str(m.get("id") or "")=="1" and bool(outs & {"1","home"}) and bool(outs & {"2","away"}):
        return "match_winner"
    return None
def no_vig(odds):
    inv={k:1.0/v for k,v in odds.items() if math.isfinite(v) and v>1}
    total=sum(inv.values())
    return {k:v/total for k,v in inv.items()} if total else {}
def sample_id(event,kind,m):
    raw="|".join(map(str,[event.get("product"),event.get("event_id"),kind,m.get("id"),m.get("specifier"),m.get("line")]))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
def make_sample(e,m,kind,now):
    p1=str(e.get("participant_1") or e.get("team_1") or ""); p2=str(e.get("participant_2") or e.get("team_2") or "")
    odds={}; raw=[]
    for o in m.get("outcomes",[]) if isinstance(m.get("outcomes"),list) else []:
        if not isinstance(o,dict) or o.get("active") is False: continue
        try: price=float(o.get("odds"))
        except (TypeError,ValueError): continue
        if not math.isfinite(price) or price<=1: continue
        label=str(o.get("name") or o.get("desc") or o.get("title") or "")
        key=canon(kind,label,p1,p2)
        raw.append({"id":str(o.get("id") or ""),"name":label,"odds":price,"canonical":key})
        if key: odds[key]=price
    required={"yes","no"} if kind=="btts" else {"home","away"}
    if not required.issubset(odds): return None
    probs=no_vig(odds)
    if not required.issubset(probs): return None
    start=dt(e.get("start_time") or e.get("start_time_ms"))
    if not start: return None
    fave=max(probs,key=probs.get)
    return {"sample_id":sample_id(e,kind,m),"event_id":str(e.get("event_id") or ""),
      "product":str(e.get("product") or ""),"competition":str(e.get("competition") or e.get("tournament") or ""),
      "category_id":str(e.get("category_id") or e.get("categoryId") or ""),
      "tournament_id":str(e.get("tournament_id") or e.get("tournamentId") or ""),
      "participant_1":p1,"participant_2":p2,"start_time":start.isoformat(),"market_type":kind,
      "market_id":str(m.get("id") or ""),"market_name":str(m.get("name") or m.get("desc") or m.get("title") or ""),
      "specifier":m.get("specifier"),"line":m.get("line"),"raw_outcomes":raw,"odds":odds,
      "market_probabilities_no_vig":probs,"market_favourite":fave,"favourite_odds":odds[fave],
      "captured_at":now.isoformat(),"provider_quote_changed_at":m.get("odds_changed_at",m.get("lastOddsChangeTime")),
      "quote_rule":"Observed SportyBet price frozen by Match Signal before kickoff; captured_at is retrieval time.",
      "settlement_status":"PENDING","final_score":None,"actual_outcome":None,
      "favourite_correct":None,"favourite_net_units":None,"settled_at":None}
def capture(live,archive,now):
    rows=archive.setdefault("observations",[]); seen={str(r.get("sample_id")) for r in rows if isinstance(r,dict)}; added=0
    for e in live.get("events",[]) if isinstance(live.get("events"),list) else []:
        if not isinstance(e,dict) or e.get("product") not in PRODUCTS or not e.get("event_id"): continue
        start=dt(e.get("start_time") or e.get("start_time_ms"))
        if not start: continue
        mins=(start-now).total_seconds()/60
        if not 0<mins<=WINDOW: continue
        for m in e.get("markets",[]) if isinstance(e.get("markets"),list) else []:
            if not isinstance(m,dict): continue
            kind=classify(m)
            if kind not in {"match_winner","btts"}: continue
            row=make_sample(e,m,kind,now)
            if row and row["sample_id"] not in seen:
                rows.append(row); seen.add(row["sample_id"]); added+=1
    return added
def score(v):
    if isinstance(v,(int,float)):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v,str):
        try: n=float(v.strip()); return n if math.isfinite(n) else None
        except ValueError: return None
    if isinstance(v,dict):
        for k in ("display","value","score","current","points","goals"):
            if k in v:
                n=score(v[k])
                if n is not None: return n
    return None
def side_score(event,side):
    candidates=[event.get(side+"Score"),event.get(side+"_score"),event.get(side+"TeamScore"),
      event.get(side,{}).get("score") if isinstance(event.get(side),dict) else None,
      event.get("score",{}).get(side) if isinstance(event.get("score"),dict) else None,
      event.get("scores",{}).get(side) if isinstance(event.get("scores"),dict) else None]
    for v in candidates:
        n=score(v)
        if n is not None:return n
    target=side+"score"
    def walk(x,depth=0):
        if depth>4 or not isinstance(x,dict):return None
        for k,v in x.items():
            key=re.sub(r"[^a-z0-9]","",str(k).lower())
            if target in key or (side=="home" and key=="hscore") or (side=="away" and key=="ascore"):
                n=score(v)
                if n is not None:return n
        for v in x.values():
            if isinstance(v,dict):
                n=walk(v,depth+1)
                if n is not None:return n
        return None
    return walk(event)
def outcome(kind,hs,ass,allowed):
    if kind=="btts":return "yes" if hs>0 and ass>0 else "no"
    if hs>ass:return "home"
    if ass>hs:return "away"
    return "draw" if "draw" in allowed else None
def settlement_events(payload):
    if isinstance(payload,dict):
        if isinstance(payload.get("events"),list):return [e for e in payload["events"] if isinstance(e,dict)]
        d=payload.get("data")
        if isinstance(d,dict) and isinstance(d.get("events"),list):return [e for e in d["events"] if isinstance(e,dict)]
    return []
def settle(archive,events,at):
    by_id={str(e.get("eventId") or e.get("event_id") or ""):e for e in events if e.get("eventId") or e.get("event_id")}
    n=0
    for s in archive.get("observations",[]):
        if not isinstance(s,dict) or s.get("settlement_status")!="PENDING":continue
        e=by_id.get(str(s.get("event_id") or ""))
        if not e:continue
        hs,ass=side_score(e,"home"),side_score(e,"away")
        if hs is None or ass is None:continue
        result=outcome(s.get("market_type",""),hs,ass,set((s.get("odds") or {}).keys()))
        if result is None:
            s["settlement_status"]="UNSETTLED_DRAW_SCOPE"
            s["settlement_note"]="Draw in a two-way winner market; exclude until provider settlement semantics are confirmed."
            continue
        probs=s.get("market_probabilities_no_vig") or {}; fave=s.get("market_favourite")
        s.update(final_score=[hs,ass],actual_outcome=result,favourite_correct=(fave==result),
          favourite_net_units=round(float(s.get("favourite_odds") or 0)-1,6) if fave==result else -1.0,
          settlement_status="SETTLED",settled_at=at.isoformat(),
          market_brier=round(sum((float(probs.get(k,0))-(1.0 if k==result else 0.0))**2 for k in probs),8),
          market_log_loss=round(-math.log(max(1e-15,float(probs.get(result,0)))),8))
        n+=1
    return n
def summary(archive,at):
    groups=defaultdict(list)
    for s in archive.get("observations",[]):
        if isinstance(s,dict):groups[(str(s.get("product") or "unknown"),str(s.get("market_type") or "unknown"))].append(s)
    sums={}
    for (product,kind),rows in sorted(groups.items()):
        settled=[x for x in rows if x.get("settlement_status")=="SETTLED"]
        fave=[x for x in settled if isinstance(x.get("favourite_correct"),bool)]
        net=sum(float(x.get("favourite_net_units") or 0) for x in fave)
        sums[product+"|"+kind]={"captured":len(rows),"settled":len(settled),
          "pending":sum(x.get("settlement_status")=="PENDING" for x in rows),
          "favourite_hit_rate":round(sum(x["favourite_correct"] for x in fave)/len(fave),6) if fave else None,
          "favourite_flat_stake_roi":round(net/len(fave),6) if fave else None,
          "mean_market_brier":round(sum(float(x["market_brier"]) for x in settled)/len(settled),8) if settled else None,
          "mean_market_log_loss":round(sum(float(x["market_log_loss"]) for x in settled)/len(settled),8) if settled else None,
          "interpretation":"Descriptive market baseline only; not independent model evidence."}
    return {"schema_version":1,"updated_at":at.isoformat(),"mode":"PAPER_RESEARCH_ONLY",
      "live_trading_approved":False,"production_qualification_enabled":False,"odds_builder_eligible":False,
      "observations_count":len(archive.get("observations",[])),"summary_by_product_market":sums,
      "promotion_policy":{"preliminary_review_after":100,"preferred_review":"200-300+ settled samples per product/market plus independent chronological holdout",
       "requirements":["positive post-margin returns","calibration against no-vig market baseline","chronological holdout","stable exact-market settlement","no participant identity leakage"],"automatic_promotion":False}}
def fetch_results(pending,now):
    scopes=defaultdict(list)
    for s in pending:
        cat,tour=str(s.get("category_id") or ""),str(s.get("tournament_id") or "")
        if cat and tour:scopes[(cat,tour)].append(s)
    if not scopes:return [],(["pending samples lack provider category/tournament IDs"] if pending else [])
    events=[];errors=[]
    ordered=sorted(scopes.items(),key=lambda x:min(dt(s.get("start_time")) or now for s in x[1]))
    for (cat,tour),samples in ordered[:12]:
        dates=[dt(s.get("start_time")) for s in samples];dates=[d for d in dates if d]
        params={"source":"efootball","categoryId":cat,"tournamentId":tour,"pageSize":100,"pageNum":1,
          "startTime":int((min(dates)-timedelta(days=1)).timestamp()*1000) if dates else "",
          "endTime":int((now+timedelta(minutes=2)).timestamp()*1000)}
        try:
            r=requests.get(BASE+"/api/sportybet-virtual-results",params=params,timeout=35);r.raise_for_status()
            events.extend(settlement_events(r.json()))
        except Exception as exc:errors.append(f"{cat}/{tour}: {exc}")
    return events,errors
def read_archive(path):
    try:
        v=json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v,dict) else {"observations":[]}
    except (OSError,json.JSONDecodeError):return {"observations":[]}
def merge(remote,candidate):
    out=dict(remote); rows={}
    for source in (remote.get("observations",[]),candidate.get("observations",[])):
        for s in source if isinstance(source,list) else []:
            if not isinstance(s,dict) or not s.get("sample_id"):continue
            key=str(s["sample_id"]);old=rows.get(key)
            if old is None:rows[key]=s;continue
            old_s=old.get("settlement_status")=="SETTLED"; new_s=s.get("settlement_status")=="SETTLED"
            if new_s and not old_s:rows[key]=s
            elif new_s and old_s and (dt(s.get("settled_at")) or datetime.min.replace(tzinfo=timezone.utc))>(dt(old.get("settled_at")) or datetime.min.replace(tzinfo=timezone.utc)):rows[key]=s
    out["observations"]=sorted(rows.values(),key=lambda s:(str(s.get("start_time") or ""),str(s.get("product") or ""),str(s.get("market_type") or ""),str(s.get("sample_id") or "")))
    old_run=remote.get("last_run") or {}; new_run=candidate.get("last_run") or {}
    if (dt(new_run.get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= (dt(old_run.get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc)):out["last_run"]=new_run
    out.update(schema_version=1,mode="PAPER_RESEARCH_ONLY",live_trading_approved=False,production_qualification_enabled=False,odds_builder_eligible=False)
    return out
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--merge-candidate");args=parser.parse_args()
    DATA.mkdir(exist_ok=True);now=now_utc()
    if args.merge_candidate:
        a=merge(read_archive(ARCHIVE),read_archive(Path(args.merge_candidate)));a["updated_at"]=now.isoformat();a["summary"]=summary(a,now)
        ARCHIVE.write_text(json.dumps(a,ensure_ascii=False,indent=2)+"\n");print(json.dumps({"status":"MERGED","observations":len(a.get("observations",[])),"research_only":True}));return
    try:live=json.loads(LIVE.read_text(encoding="utf-8"))
    except Exception as exc:raise SystemExit(f"cannot read current virtual feed: {exc}")
    a=read_archive(ARCHIVE);a.setdefault("observations",[])
    added=capture(live,a,now)
    pending=[s for s in a["observations"] if isinstance(s,dict) and s.get("settlement_status")=="PENDING" and (dt(s.get("start_time")) or now)<now]
    settled=0;errors=[]
    if now.minute%30<=2 or os.getenv("EFOOTBALL_RESEARCH_FORCE_SETTLE")=="1":
        try:
            events,errs=fetch_results(pending,now);settled=settle(a,events,now);errors.extend(errs)
        except Exception as exc:errors.append("result source unavailable: "+str(exc))
    a.update(schema_version=1,mode="PAPER_RESEARCH_ONLY",live_trading_approved=False,production_qualification_enabled=False,odds_builder_eligible=False,updated_at=now.isoformat())
    a["last_run"]={"captured_at":now.isoformat(),"captured_new":added,"settled_new":settled,"settlement_errors":errors}
    a["summary"]=summary(a,now);ARCHIVE.write_text(json.dumps(a,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","captured_new":added,"settled_new":settled,"observations":len(a["observations"]),"settlement_errors":errors,"research_only":True},indent=2))
if __name__=="__main__":main()
