"""Build time-safe participant performance profiles for the Virtual Lab.

Profiles use only automatic settled O/U history. They are research features,
not betting guarantees. A participant may face different opponents; recurrence
is keyed to the participant identity within the same virtual product.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"virtual_lab_history.json"
OUTPUT=DATA/"virtual_lab_participant_profiles.json"
LINES=(1.5,3.5,4.5)
MIN_PROFILE_N=3

def participant_identity(value: str) -> str:
    import re
    s=str(value or '').strip()
    m=re.search(r'\\(([^()]+)\\)\\s*

def t(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
    except Exception:return float("inf")

def main():
    history=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    events={}
    for r in history:
        if not isinstance(r,dict) or r.get("market")!="ou" or r.get("win") is None: continue
        if not r.get("event_id") or not r.get("timestamp"): continue
        key=f'{r["event_id"]}|{r["timestamp"]}'
        g=events.setdefault(key,{"product":r.get("product","other"),"timestamp":r.get("timestamp"),"competition":r.get("competition","Unknown"),"home":r.get("participant_1",""),"away":r.get("participant_2",""),"total":None})
        if g["total"] is None:
            parts=str(r.get("score") or "").replace(" ","").split(":")
            if len(parts)==2:
                try:g["total"]=float(parts[0])+float(parts[1])
                except Exception:pass
    ordered=sorted([e for e in events.values() if e["total"] is not None],key=lambda e:t(e["timestamp"]))
    groups=defaultdict(list)
    for e in ordered:
        for p in (e["home"],e["away"]):
            name=str(p or "").strip()
            if name: groups[(e["product"],name.casefold())].append(e)
    profiles=[]
    for (product,_), evs in groups.items():
        name=next((participant_identity(p) for e in evs for p in (e["home"],e["away"]) if participant_identity(p).casefold()==_),"")
        total_n=len(evs)
        avg=sum(e["total"] for e in evs)/total_n
        last5=evs[-5:]
        last5_avg=sum(e["total"] for e in last5)/len(last5)
        line_stats={}
        for line in LINES:
            decisive=[e for e in evs if e["total"]!=line]
            over=sum(e["total"]>line for e in decisive)
            recent=[e for e in last5 if e["total"]!=line]
            ro=sum(e["total"]>line for e in recent)
            line_stats[str(line)]={"n":len(decisive),"over_rate":over/len(decisive) if decisive else None,"recent_n":len(recent),"recent_over_rate":ro/len(recent) if recent else None}
        # Hotness is deliberately descriptive: enough history + strong recent/overall directional signal.
        hot=None
        best=None
        for line,s in line_stats.items():
            if s["n"]<MIN_PROFILE_N: continue
            rate=s["over_rate"]; recent=s["recent_over_rate"]
            if rate is None or recent is None: continue
            direction="OVER" if rate>=.67 else "UNDER" if rate<=.33 else None
            if not direction: continue
            recent_ok=recent>=.60 if direction=="OVER" else recent<=.40
            if not recent_ok: continue
            strength=abs(rate-.5)*.65+abs(recent-.5)*.35
            candidate=(strength,int(s["n"]),line,direction)
            if best is None or candidate>best: best=candidate
        if best:
            hot={"line":float(best[2]),"direction":best[3],"strength":best[0],"basis_n":best[1]}
        profiles.append({"product":product,"participant":name,"total_n":total_n,"avg_total":avg,"last5_n":len(last5),"last5_avg_total":last5_avg,"lines":line_stats,"hot":hot})
    profiles.sort(key=lambda x:(0 if x["hot"] else 1,-(x["hot"]["strength"] if x["hot"] else 0),-x["total_n"],x["participant"]))
    hot=[p for p in profiles if p["hot"]]
    OUTPUT.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"source_contract":"automatic SportyBet result history only; user-reported tickets excluded","participant_count":len(profiles),"hot_count":len(hot),"minimum_profile_history":MIN_PROFILE_N,"profiles":profiles,"hot_participants":hot},indent=2)+"\n")
    print(json.dumps({"participant_count":len(profiles),"hot_count":len(hot),"hot_participants":hot[:20]},indent=2))

if __name__=="__main__":main()
, s)
    return m.group(1).strip() if m and m.group(1).strip() else s


def t(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
    except Exception:return float("inf")

def main():
    history=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    events={}
    for r in history:
        if not isinstance(r,dict) or r.get("market")!="ou" or r.get("win") is None: continue
        if not r.get("event_id") or not r.get("timestamp"): continue
        key=f'{r["event_id"]}|{r["timestamp"]}'
        g=events.setdefault(key,{"product":r.get("product","other"),"timestamp":r.get("timestamp"),"competition":r.get("competition","Unknown"),"home":r.get("participant_1",""),"away":r.get("participant_2",""),"total":None})
        if g["total"] is None:
            parts=str(r.get("score") or "").replace(" ","").split(":")
            if len(parts)==2:
                try:g["total"]=float(parts[0])+float(parts[1])
                except Exception:pass
    ordered=sorted([e for e in events.values() if e["total"] is not None],key=lambda e:t(e["timestamp"]))
    groups=defaultdict(list)
    for e in ordered:
        for p in (e["home"],e["away"]):
            name=str(p or "").strip()
            if name: groups[(e["product"],name.casefold())].append(e)
    profiles=[]
    for (product,_), evs in groups.items():
        name=next((p for e in evs for p in (e["home"],e["away"]) if str(p).casefold()==_),"")
        total_n=len(evs)
        avg=sum(e["total"] for e in evs)/total_n
        last5=evs[-5:]
        last5_avg=sum(e["total"] for e in last5)/len(last5)
        line_stats={}
        for line in LINES:
            decisive=[e for e in evs if e["total"]!=line]
            over=sum(e["total"]>line for e in decisive)
            recent=[e for e in last5 if e["total"]!=line]
            ro=sum(e["total"]>line for e in recent)
            line_stats[str(line)]={"n":len(decisive),"over_rate":over/len(decisive) if decisive else None,"recent_n":len(recent),"recent_over_rate":ro/len(recent) if recent else None}
        # Hotness is deliberately descriptive: enough history + strong recent/overall directional signal.
        hot=None
        best=None
        for line,s in line_stats.items():
            if s["n"]<MIN_PROFILE_N: continue
            rate=s["over_rate"]; recent=s["recent_over_rate"]
            if rate is None or recent is None: continue
            direction="OVER" if rate>=.67 else "UNDER" if rate<=.33 else None
            if not direction: continue
            recent_ok=recent>=.60 if direction=="OVER" else recent<=.40
            if not recent_ok: continue
            strength=abs(rate-.5)*.65+abs(recent-.5)*.35
            candidate=(strength,int(s["n"]),line,direction)
            if best is None or candidate>best: best=candidate
        if best:
            hot={"line":float(best[2]),"direction":best[3],"strength":best[0],"basis_n":best[1]}
        profiles.append({"product":product,"participant":name,"total_n":total_n,"avg_total":avg,"last5_n":len(last5),"last5_avg_total":last5_avg,"lines":line_stats,"hot":hot})
    profiles.sort(key=lambda x:(0 if x["hot"] else 1,-(x["hot"]["strength"] if x["hot"] else 0),-x["total_n"],x["participant"]))
    hot=[p for p in profiles if p["hot"]]
    OUTPUT.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"source_contract":"automatic SportyBet result history only; user-reported tickets excluded","participant_count":len(profiles),"hot_count":len(hot),"minimum_profile_history":MIN_PROFILE_N,"profiles":profiles,"hot_participants":hot},indent=2)+"\n")
    print(json.dumps({"participant_count":len(profiles),"hot_count":len(hot),"hot_participants":hot[:20]},indent=2))

if __name__=="__main__":main()
