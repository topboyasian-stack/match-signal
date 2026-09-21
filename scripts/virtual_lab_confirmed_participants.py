"""Build official-result tracking for the confirmed participant watchlist.
The user's original ticket outcomes are never added to training labels.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
WATCH=DATA/"virtual_lab_confirmed_participants.json"
HISTORY=DATA/"virtual_lab_history.json"
OUT=DATA/"virtual_lab_confirmed_participant_results.json"
def main():
    watch=json.loads(WATCH.read_text()) if WATCH.exists() else {"participants":[]}
    hist=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    profiles=[]
    for w in watch.get("participants",[]):
        name=str(w.get("participant","")).strip()
        product=str(w.get("product","")).strip()
        rows=[r for r in hist if isinstance(r,dict) and r.get("market")=="ou" and str(r.get("product",""))==product and name in {str(r.get("participant_1","")).strip(),str(r.get("participant_2","")).strip()} and r.get("win") is not None]
        profiles.append({"participant":name,"product":product,"official_settled_rows":len(rows),
                         "wins":sum(bool(r.get("win")) for r in rows),
                         "losses":sum(not bool(r.get("win")) for r in rows),
                         "rate":(sum(bool(r.get("win")) for r in rows)/len(rows)) if rows else None})
    OUT.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),
      "source_contract":"automatic SportyBet history only; user-reported ticket outcomes excluded",
      "profiles":profiles},indent=2)+"\n")
    print(json.dumps({"tracked":len(profiles),"matched":sum(p["official_settled_rows"]>0 for p in profiles),
      "rows":sum(p["official_settled_rows"] for p in profiles)},indent=2))
if __name__=="__main__": main()
