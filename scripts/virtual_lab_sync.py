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
HEADERS={"Accept":"application/json","User-Agent":"MatchSignal-VirtualLab/2.0"}
MARKETS="1,18,10,29,11,26,36,14,60100,186,189,202,204,210"

def request(url, params, headers=HEADERS):
    r=requests.get(url,params=params,headers=headers,timeout=20)
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

def compact(raw, fallback_product=None):
    t=str(raw.get("tournament") or raw.get("competition") or "")
    c=str(raw.get("category") or "")
    h=str(raw.get("participant_1") or raw.get("homeTeamName") or "")
    a=str(raw.get("participant_2") or raw.get("awayTeamName") or "")
    product=raw.get("product") or product_for(t,c,h,a) or fallback_product
    if not product: return None
    markets=[]
    for m in raw.get("markets") or []:
        outs=[]
        for o in m.get("outcomes") or []:
            try: odds=float(o.get("odds"))
            except (TypeError,ValueError): continue
            if odds<=0: continue
            outs.append({"id":str(o.get("id") or ""),"name":str(o.get("name") or o.get("desc") or ""),"odds":odds,"active":o.get("active",o.get("isActive",True)) is not False})
        if outs:
            spec=m.get("specifier")
            mm=re.search(r"(?:total|line)=([0-9]+(?:\.[0-9]+)?)",str(spec or ""),re.I)
            markets.append({"id":str(m.get("id") or ""),"name":str(m.get("name") or m.get("desc") or m.get("title") or ""),"specifier":spec,"line":float(mm.group(1)) if mm else m.get("line"),"status":m.get("status"),"outcomes":outs,"odds_changed_at":m.get("odds_changed_at",m.get("lastOddsChangeTime"))})
    start=raw.get("start_time")
    if not start and raw.get("start_time_ms") is not None:
        try: start=datetime.fromtimestamp(float(raw["start_time_ms"])/1000,tz=timezone.utc).isoformat().replace("+00:00","Z")
        except (TypeError,ValueError): start=None
    return {"product":product,"provider":"SportyBet NG","event_id":str(raw.get("event_id") or raw.get("eventId") or ""),"timestamp":datetime.now(tz=timezone.utc).isoformat(),"competition":t,"category":c,"participant_1":h,"participant_2":a,"start_time":start,"match_status":raw.get("match_status",raw.get("matchStatus")),"markets":markets,"source":"SportyBet NG via Match Signal live virtual proxy"}

def main():
    now=datetime.now(tz=timezone.utc).isoformat()
    events={}
    errors=[]
    for page in range(1,6):
        params={"pageSize":100,"pageNum":page,"timeline":168,"_t":int(datetime.now(tz=timezone.utc).timestamp()*1000)}
        try:
            body=request(PROXY,{**params,"sources":"efootball,srl,vfootball"})
            batch=0
            for raw in body.get("events") or []:
                row=compact(raw)
                if row and row["event_id"]:
                    events[row["event_id"]]=row; batch+=1
            print(f"proxy page={page} events={batch}")
            if not batch: break
        except Exception as exc:
            errors.append(f"proxy page {page}: {exc}")
            break
    rows=sorted(events.values(),key=lambda x:(x.get("start_time") or "",x.get("product") or "",x.get("event_id") or ""))
    counts={}
    for x in rows: counts[x["product"]]=counts.get(x["product"],0)+1
    payload={"updated_at":now,"status":"LIVE" if rows else "UPSTREAM_EMPTY","source":[PROXY],"endpoint":PROXY,"events_count":len(rows),"product_counts":counts,"events":rows,"errors":errors,"refresh_seconds":30}
    out=DATA/"virtual_lab_live.json"
    out.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"events_count":len(rows),"product_counts":counts,"errors":errors},indent=2))
    if not rows: raise SystemExit("ABORT: no live virtual/eFootball/SRL events collected")

if __name__=="__main__": main()
