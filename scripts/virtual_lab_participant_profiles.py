"""Build time-safe participant performance profiles for the standalone Virtual Lab.

Profiles use automatic settled O/U history only. Stable eFootball participant
identity is the parenthetical participant token; team/club labels are contextual.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"virtual_lab_history.json"
OUTPUT=DATA/"virtual_lab_participant_profiles.json"
LINES=(1.5,3.5,4.5)
MIN_PROFILE_N=3
SUPPORTED_PRODUCTS={"efootball_gt","efootball_adriatic","vfootball","zoom"}

def participant_identity(product: str, value: str) -> str:
    s=" ".join(str(value or "").split()).strip()
    if not s:
        return ""
    product=str(product or "")
    if product.startswith("efootball"):
        m=re.search(r"\(([^()]+)\)\s*$",s)
        return m.group(1).strip() if m and m.group(1).strip() else ""
    if product in {"vfootball","zoom"}:
        return s
    return ""

def timestamp(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
    except Exception:
        return float("inf")

def event_total(row):
    parts=str(row.get("score") or "").replace(" ","").split(":")
    if len(parts)!=2:
        return None
    try:
        return float(parts[0])+float(parts[1])
    except Exception:
        return None

def main():
    history=json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    events={}
    for row in history:
        if not isinstance(row,dict) or row.get("market")!="ou" or row.get("win") is None:
            continue
        product=str(row.get("product") or "")
        if product not in SUPPORTED_PRODUCTS:
            continue
        event_id=str(row.get("event_id") or "")
        stamp=str(row.get("timestamp") or "")
        total=event_total(row)
        if not event_id or not stamp or total is None:
            continue
        key=f"{event_id}|{stamp}"
        g=events.setdefault(key,{
            "product":product,
            "timestamp":stamp,
            "competition":str(row.get("competition") or "Unknown"),
            "home":str(row.get("participant_1") or ""),
            "away":str(row.get("participant_2") or ""),
            "total":total
        })
        if g["total"] is None:
            g["total"]=total

    ordered=sorted(events.values(),key=lambda e:timestamp(e["timestamp"]))
    groups=defaultdict(list)
    for event in ordered:
        for raw in (event["home"],event["away"]):
            identity=participant_identity(event["product"],raw)
            if identity:
                groups[(event["product"],identity.casefold())].append(event)

    profiles=[]
    for (product,_),event_rows in groups.items():
        identity=next(
            participant_identity(product,raw)
            for event in event_rows
            for raw in (event["home"],event["away"])
            if participant_identity(product,raw)
        )
        total_n=len(event_rows)
        avg_total=sum(e["total"] for e in event_rows)/total_n
        last5=event_rows[-5:]
        last5_avg=sum(e["total"] for e in last5)/len(last5)
        line_stats={}
        for line in LINES:
            decisive=[e for e in event_rows if e["total"]!=line]
            over=sum(e["total"]>line for e in decisive)
            recent=[e for e in last5 if e["total"]!=line]
            recent_over=sum(e["total"]>line for e in recent)
            line_stats[str(line)]={
                "n":len(decisive),
                "over_rate":over/len(decisive) if decisive else None,
                "recent_n":len(recent),
                "recent_over_rate":recent_over/len(recent) if recent else None
            }

        hot=None
        best=None
        for line,stats in line_stats.items():
            if stats["n"]<MIN_PROFILE_N:
                continue
            rate=stats["over_rate"]
            recent_rate=stats["recent_over_rate"]
            if rate is None or recent_rate is None:
                continue
            direction="OVER" if rate>=0.67 else "UNDER" if rate<=0.33 else None
            if direction is None:
                continue
            recent_ok=recent_rate>=0.60 if direction=="OVER" else recent_rate<=0.40
            if not recent_ok:
                continue
            strength=abs(rate-0.5)*0.65+abs(recent_rate-0.5)*0.35
            candidate=(strength,stats["n"],float(line),direction)
            if best is None or candidate>best:
                best=candidate
        if best:
            hot={"line":best[2],"direction":best[3],"strength":best[0],"basis_n":best[1]}

        profiles.append({
            "participant_key":f"{product}|{identity.casefold()}",
            "product":product,
            "participant":identity,
            "total_n":total_n,
            "avg_total":avg_total,
            "last5_n":len(last5),
            "last5_avg_total":last5_avg,
            "lines":line_stats,
            "hot":hot
        })

    profiles.sort(key=lambda x:(x["product"],0 if x["hot"] else 1,-(x["hot"]["strength"] if x["hot"] else 0),-x["total_n"],x["participant"].casefold()))
    hot=[p for p in profiles if p["hot"]]
    OUTPUT.write_text(json.dumps({
        "schema_version":1,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "source_contract":"automatic SportyBet result history only; user-reported tickets excluded",
        "product_scope":sorted(SUPPORTED_PRODUCTS),
        "participant_count":len(profiles),
        "hot_count":len(hot),
        "minimum_profile_history":MIN_PROFILE_N,
        "profiles":profiles,
        "hot_participants":hot
    },indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"participant_count":len(profiles),"hot_count":len(hot)},indent=2))

if __name__=="__main__":
    main()
