"""Basketball collector using SportScore's free public API.

SofaScore is intentionally not used here. SportScore is a keyless public JSON API
for basketball and requires a visible attribution link on pages that render its data.
The dashboard therefore records the provider and the frontend can show the attribution.
"""
import json, math, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import requests

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"
BASE="https://sportscore.com"
BBL_TEAMS=["giessen","chemnitz","gottingen","mitteldeutscher","hamburg","rostock-seawolves","kirchheim-knights","ludwigsburg","skyliners-frankfurt","jena","heidelberg","oldenburg"]
CLUBS=[
 "san-lorenzo","instituto-cordoba","kumamoto","taiwanbeer-leopards","lucentum-alicante","cb-granada",
 "baskonia","alba-berlin","partizan-mozzart-bet","fuenlabrada","real-madrid","tenerife",
 "olympiakos","crvena-zvezda","torun","trefl-sopot","split","kk-dubrovnik","manresa","barcelona",
]
TARGET_BBL={"giessen","chemnitz","gottingen","mitteldeutscher","hamburg","rostock","kirchheim","ludwigsburg","skyliners","jena","heidelberg","oldenburg"}


def load(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def save(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")

def get(path,params):
    r=requests.get(BASE+path,params=params,timeout=20,headers={"User-Agent":"MatchSignal/1.0"}); r.raise_for_status(); return r.json()

def rows(payload):
    if isinstance(payload,dict):
        for k in ("matches","data","fixtures","events"):
            if isinstance(payload.get(k),list): return payload[k]
    return []

def slug_name(s):
    s=re.sub(r"[^a-z0-9]+","-",str(s).lower()).strip("-")
    return s

def name(x):
    return x.get("name") if isinstance(x,dict) else x

def teams(r):
    h=name(r.get("home_team") or r.get("homeTeam") or r.get("home")); a=name(r.get("away_team") or r.get("awayTeam") or r.get("away"))
    return h,a

def timestamp(r):
    t=r.get("time") or r.get("start_time") or r.get("startTime") or r.get("kickoff")
    if isinstance(t,(int,float)): return float(t)
    if isinstance(t,str):
        try:return datetime.fromisoformat(t.replace("Z","+00:00")).timestamp()
        except Exception:return 0
    return 0

def score(r):
    h=r.get("home_score") or r.get("homeScore") or {}; a=r.get("away_score") or r.get("awayScore") or {}
    try:
        hv=h.get("current",h) if isinstance(h,dict) else h; av=a.get("current",a) if isinstance(a,dict) else a
        return float(hv),float(av)
    except Exception:return None

def finished(r):
    return str(r.get("status","")).lower() in {"finished","final","ended"} or str(r.get("status_type","")).lower() in {"finished","final"}

def odds_from_detail(obj):
    found=[]
    def walk(x):
        if isinstance(x,dict):
            m=str(x.get("market") or x.get("market_name") or x.get("name") or "").lower()
            if any(k in m for k in ("total","over/under","money line","moneyline","spread","handicap")): found.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(obj)
    total=None
    for x in found:
        m=str(x.get("market") or x.get("market_name") or x.get("name") or "").lower()
        if "total" not in m and "over/under" not in m: continue
        line=x.get("line") or x.get("handicap")
        if isinstance(line,(int,float)) and 100<=float(line)<=260: total=float(line); break
        s=str(line or "")
        q=re.search(r"(\d{3}(?:\.5)?)",s)
        if q and 100<=float(q.group(1))<=260: total=float(q.group(1)); break
    return total

def collect_team(slug):
    try:return rows(get("/api/widget/team/",{"sport":"basketball","slug":slug,"limit":30}))
    except Exception:return []

def collect_match_detail(r):
    slug=r.get("slug") or r.get("match_slug")
    if not slug:
        h,a=teams(r); slug=f"{slug_name(h)}-vs-{slug_name(a)}"
    try:return get("/api/widget/match/",{"sport":"basketball","slug":slug})
    except Exception:return {}

def predict(event,recent):
    h,a=teams(event)
    if not h or not a:return None
    ts=timestamp(event); now=datetime.now(timezone.utc).timestamp()
    if ts and ts < now-3600:return None
    vals=[]
    for r in recent:
        s=score(r)
        if finished(r) and s: vals.append(sum(s))
    vals=vals[-10:]
    expected=round(sum(vals)/len(vals),1) if vals else None
    detail=collect_match_detail(event)
    market_line=odds_from_detail(detail)
    line=market_line if market_line is not None else (round(expected*2)/2 if expected is not None else None)
    if market_line is not None and expected is not None:
        over=1/(1+math.exp(-(expected-line)/7)); pick="over" if over>.5 else "under"; source="SportScore public match detail"
    else:
        over=under=.5; pick=None; source="Model-estimated total; no published public O/U line found"
    return {
      "sport":"basketball","league":str(event.get("competition") or event.get("tournament") or "International Club Friendly"),
      "source":"SportScore public API","event_id":str(event.get("id") or event.get("match_id") or event.get("slug") or f"{h}-{a}"),
      "start_time":datetime.fromtimestamp(ts,timezone.utc).isoformat() if ts else datetime.now(timezone.utc).isoformat(),
      "player_1":h,"player_2":a,"probabilities":{"p1":.5,"p2":.5},"pick":None,"confidence":round(.5+(abs(over-.5)*.35),4),
      "markets":{"moneyline":None,"total_ou":{"line":line,"over":round(over,4),"under":round(under,4),"pick":pick,"expected_total":expected,"source":source,"settlement":"Official final score including overtime"},"spread":None},
      "form":{"recent_total_samples":len(vals)},
      "signal_quality":{"components":sum(bool(x) for x in [expected is not None,market_line is not None]),"max_components":2,"market_total_available":market_line is not None,"recent_total_form_available":expected is not None},
      "model":"SportScore public match data + recent scoring form",
      "rules_note":"Basketball total settlement uses the official final score, including overtime.",
    }

def main():
    candidates=[]; sources=[]; seen=set(); cutoff=datetime.now(timezone.utc).timestamp()+7*86400
    for slug in BBL_TEAMS+CLUBS:
        for r in collect_team(slug):
            h,a=teams(r); comp=str(r.get("competition") or r.get("tournament") or "")
            if not h or not a:continue
            low=(comp+" "+str(h)+" "+str(a)).lower()
            target=("bbl" in low or "pokal" in low or slug in BBL_TEAMS) if slug in BBL_TEAMS else ("friendly" in low or "club" in low)
            if not target:continue
            ts=timestamp(r)
            if ts and ts>cutoff:continue
            eid=str(r.get("id") or r.get("match_id") or r.get("slug") or f"{h}-{a}")
            if eid in seen:continue
            seen.add(eid); candidates.append((r,collect_team(slug)))
    predictions=[]
    for r,recent in candidates:
        p=predict(r,recent)
        if p:predictions.append(p)
    history=load(DATA/"basketball_history.json",[]); known={(str(x.get("event_id")),x.get("league")) for x in history}
    for p in predictions:
        if (p["event_id"],p["league"]) not in known:history.append(p)
    save(DATA/"basketball_predictions.json",sorted(predictions,key=lambda x:x["start_time"]))
    save(DATA/"basketball_history.json",history)
    settled=[x for x in history if x.get("settled")]; totals=[x for x in settled if x.get("total_correct") is not None]
    save(DATA/"basketball_accuracy.json",{"updated_at":datetime.now(timezone.utc).isoformat(),"settled":len(settled),"correct":sum(bool(x.get("correct")) for x in settled),"accuracy":sum(bool(x.get("correct")) for x in settled)/len(settled) if settled else None,"total_ou_settled":len(totals),"total_ou_correct":sum(bool(x.get("total_correct")) for x in totals),"total_ou_accuracy":sum(bool(x.get("total_correct")) for x in totals)/len(totals) if totals else None})
    status=load(DATA/"pipeline_status.json",{}); status.update({"basketball_count":len(predictions),"basketball_settled":len(settled),"basketball_sources":[{"source":"https://sportscore.com/api/widget/team/","events":len(predictions),"status":"ok"}],"basketball_source_status":"SportScore public API; SofaScore disabled","basketball_updated_at":datetime.now(timezone.utc).isoformat(),"basketball_rules":"Totals settle on official final score including overtime"}); save(DATA/"pipeline_status.json",status)
    print(f"SportScore basketball: {len(predictions)} predictions; settled={len(settled)}")

if __name__=="__main__":main()
