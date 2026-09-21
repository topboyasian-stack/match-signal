#!/usr/bin/env python3
"""Collect live SportyBet NG virtual/eFootball/SRL events for Match Signal."""
from __future__ import annotations
import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
BASE=os.getenv("MATCH_SIGNAL_PUBLIC_BASE","https://match-signal.pages.dev").rstrip("/")
PROXY=f"{BASE}/api/sportybet-virtual"
DIRECT_PC="https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents"
DIRECT_VFL="https://www.sportybet.com/api/ng/factsCenter/wapConfigurableUpcomingEvents"
HEADERS={"Accept":"application/json, text/plain, */*","Content-Type":"application/json","Current-Country":"NG","Origin":"https://www.sportybet.com","Referer":"https://www.sportybet.com/ng/","User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"}
SPORTY_MARKETS="1,18,10,29,11,26,36,14,60100,186,189,202,204,210"

def request(url, params):
    r=requests.get(url,params=params,headers=HEADERS,timeout=25)
    r.raise_for_status()
    body=r.json()
    if not isinstance(body,dict): raise RuntimeError("upstream JSON was not an object")
    if body.get("bizCode") not in (None,10000): raise RuntimeError(f"bizCode={body.get('bizCode')}")
    return body

def product_for(t,c,h,a):
    blob=f"{t} {c} {h} {a}".lower()
    if "eadriatic" in blob: return "efootball_adriatic"
    if "gt sports league" in blob or "gt leagues" in blob or "efootball" in blob or "e soccer" in blob or "esoccer" in blob: return "efootball_gt"
    if "simulated reality" in blob or re.search(r"\bsrl\b",blob): return "srl"
    if "virtual football" in blob or "vfootball" in blob: return "vfootball"
    if "zoom" in blob or "turbo" in blob: return "zoom"
    if "virtual" in blob or "simulated" in blob: return "other"
    return None

def compact(raw,fallback_product=None):
    t=str(raw.get("tournament") or raw.get("competition") or "")
    c=str(raw.get("category") or "")
    h=str(raw.get("participant_1") or raw.get("homeTeamName") or "")
    a=str(raw.get("participant_2") or raw.get("awayTeamName") or "")
    product=raw.get("product") or product_for(t,c,h,a) or fallback_product
    if not product:return None
    markets=[]
    for m in raw.get("markets") or []:
        outs=[]
        for o in m.get("outcomes") or []:
            try:odds=float(o.get("odds"))
            except (TypeError,ValueError):continue
            if odds<=0:continue
            outs.append({"id":str(o.get("id") or ""),"name":str(o.get("name") or o.get("desc") or ""),"odds":odds,"active":o.get("active",o.get("isActive",True)) is not False})
        if outs:
            spec=m.get("specifier")
            mm=re.search(r"(?:total|line)=([0-9]+(?:\.[0-9]+)?)",str(spec or ""),re.I)
            markets.append({"id":str(m.get("id") or ""),"name":str(m.get("name") or m.get("desc") or m.get("title") or ""),"specifier":spec,"line":float(mm.group(1)) if mm else m.get("line"),"status":m.get("status"),"outcomes":outs,"odds_changed_at":m.get("odds_changed_at",m.get("lastOddsChangeTime"))})
    start=raw.get("start_time")
    if not start and raw.get("start_time_ms") is not None:
        try:start=datetime.fromtimestamp(float(raw["start_time_ms"])/1000,tz=timezone.utc).isoformat().replace("+00:00","Z")
        except (TypeError,ValueError):start=None
    return {"product":product,"provider":"SportyBet NG","event_id":str(raw.get("event_id") or raw.get("eventId") or ""),"timestamp":datetime.now(tz=timezone.utc).isoformat(),"competition":t,"category":c,"participant_1":h,"participant_2":a,"start_time":start,"match_status":raw.get("match_status",raw.get("matchStatus")),"markets":markets,"source":"SportyBet NG via Match Signal live virtual connector"}

def collect_proxy():
    events=[]
    for page in range(1,6):
        p={"pageSize":100,"pageNum":page,"timeline":168,"sources":"efootball,srl,vfootball","_t":int(datetime.now(tz=timezone.utc).timestamp()*1000)}
        body=request(PROXY,p)
        batch=body.get("events") or []
        events.extend(batch)
        if len(batch)<100:break
    return events,"cloudflare_proxy"

def collect_direct():
    events=[]
    for page in range(1,6):
        base={"pageSize":100,"pageNum":page,"timeline":168,"todayGames":"false","_t":int(datetime.now(tz=timezone.utc).timestamp()*1000)}
        for sport_id,product_hint,url in [
            ("sr:sport:1",None,DIRECT_PC),
            ("sr:sport:137","efootball_gt",DIRECT_PC),
            ("sr:sport:202120001","vfootball",DIRECT_VFL)
        ]:
            p=dict(base);p["sportId"]=sport_id
            if url==DIRECT_PC:p["marketId"]=SPORTY_MARKETS
            body=request(url,p)
            data=body.get("data") or {}
            for t in data.get("tournaments") or []:
                tn=str(t.get("name") or "");cat=str(t.get("categoryName") or "")
                for e in t.get("events") or []:
                    events.append({
                        "product":product_for(tn,cat,str(e.get("homeTeamName") or ""),str(e.get("awayTeamName") or "")) or product_hint,
                        "tournament":tn,"category":cat,"event_id":str(e.get("eventId") or ""),
                        "participant_1":str(e.get("homeTeamName") or ""),"participant_2":str(e.get("awayTeamName") or ""),
                        "start_time_ms":e.get("estimateStartTime"),"match_status":e.get("matchStatus"),"markets":e.get("markets") or []
                    })
        if not events: break
    return events,"sportybet_web_api_direct"

def main():
    now=datetime.now(tz=timezone.utc).isoformat()
    raw=[];source="";errors=[]
    try:
        raw,source=collect_proxy()
    except Exception as exc:
        errors.append("proxy: "+str(exc))
        try:
            raw,source=collect_direct()
        except Exception as direct_exc:
            errors.append("direct: "+str(direct_exc))
    rows={}
    for item in raw:
        row=compact(item)
        if row and row["event_id"] and row["product"] in {"efootball_gt","efootball_adriatic","srl","vfootball","zoom","other"}:
            rows[row["event_id"]]=row
    rows=sorted(rows.values(),key=lambda x:(x.get("start_time") or "",x.get("product") or "",x.get("event_id") or ""))
    counts={}
    for x in rows:counts[x["product"]]=counts.get(x["product"],0)+1
    status="LIVE" if rows else "UPSTREAM_EMPTY"
    out=DATA/"virtual_lab_live.json"
    previous={}
    if out.exists():
        try: previous=json.loads(out.read_text(encoding="utf-8"))
        except Exception: previous={}
    candidate={"status":status,"source":[source] if source else [],"endpoint":PROXY,"events_count":len(rows),"product_counts":counts,"events":rows}
    previous_cmp={k:previous.get(k) for k in candidate}
    if previous_cmp==candidate and previous:
        print("Virtual Lab snapshot unchanged; keeping published timestamp.")
        return
    payload={"updated_at":now,**candidate,"errors":errors,"refresh_seconds":30}
    out.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"events_count":len(rows),"product_counts":counts,"errors":errors},indent=2))
    if not rows:raise SystemExit("ABORT: no live virtual/eFootball/SRL events collected")

if __name__=="__main__":main()
