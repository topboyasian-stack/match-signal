"""Build official-result tracking for the confirmed participant watchlist.
The user's original ticket outcomes are never added to training labels.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
WATCH=DATA/"virtual_lab_confirmed_participants.json"
HISTORY=DATA/"virtual_lab_history.json"
OUT=DATA/"virtual_lab_confirmed_participant_results.json"
SUPPORTED_PRODUCTS={"efootball_gt","efootball_adriatic","vfootball","zoom"}

def participant_identity(value: str) -> str:
    s=" ".join(str(value or "").split()).strip()
    m=re.search(r"\(([^()]+)\)\s*$",s)
    return m.group(1).strip() if m and m.group(1).strip() else s

def main():
    watch=json.loads(WATCH.read_text()) if WATCH.exists() else {"participants":[]}
    hist=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    profiles=[]
    participants=[w for w in watch.get("participants",[]) if str(w.get("product","")).strip() in SUPPORTED_PRODUCTS]
    for w in participants:
        name=participant_identity(w.get("participant",""))
        product=str(w.get("product","")).strip()
        rows=[]
        for r in hist:
            if not isinstance(r,dict) or r.get("market")!="ou" or str(r.get("product","")).strip()!=product or r.get("win") is None:
                continue
            identities={participant_identity(r.get("participant_1","")),participant_identity(r.get("participant_2",""))}
            if name in identities:
                rows.append(r)
        wins=sum(bool(r.get("win")) for r in rows)
        profiles.append({
            "participant":name,
            "product":product,
            "official_settled_rows":len(rows),
            "wins":wins,
            "losses":len(rows)-wins,
            "rate":wins/len(rows) if rows else None
        })
    OUT.write_text(json.dumps({
        "schema_version":1,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "source_contract":"automatic SportyBet history only; user-reported ticket outcomes excluded",
        "product_scope":sorted(SUPPORTED_PRODUCTS),
        "profiles":profiles
    },indent=2)+"\n")
    print(json.dumps({
        "tracked":len(profiles),
        "matched":sum(p["official_settled_rows"]>0 for p in profiles),
        "rows":sum(p["official_settled_rows"] for p in profiles)
    },indent=2))

if __name__=="__main__":
    main()
