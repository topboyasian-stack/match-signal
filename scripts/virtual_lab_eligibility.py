"""Build a conservative, data-driven Virtual Lab eligibility gate.

Historical observations remain untouched. This gate only controls which leagues,
markets and O/U lines are eligible for the public research/selection UI.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HISTORY=DATA/"virtual_lab_history.json"
OUTPUT=DATA/"virtual_lab_eligibility.json"

MIN_COMP_N=12
MIN_COMP_OOS_N=4
MIN_LINE_N=12
MIN_LINE_OOS_N=4
DISCOVERY=.70
PRIORITY_OU_LINES=[1.5,3.5,4.5]

def settled(rows):
    return [r for r in rows if isinstance(r,dict) and r.get("win") is not None]

def stats(rows):
    n=len(rows)
    if not n:return {"n":0,"wins":0,"win_rate":None,"roi":None}
    wins=sum(bool(r.get("win")) for r in rows)
    roi=sum((float(r.get("odds") or 0)-1) if r.get("win") else -1 for r in rows)/n
    return {"n":n,"wins":wins,"win_rate":wins/n,"roi":roi}

def split(rows):
    ordered=sorted(rows,key=lambda r:str(r.get("timestamp") or ""))
    cut=int(len(ordered)*DISCOVERY)
    return ordered[:cut],ordered[cut:]

def eligible_comp(all_rows):
    train,test=split(all_rows)
    a,b=stats(all_rows),stats(test)
    ok=(a["n"]>=MIN_COMP_N and b["n"]>=MIN_COMP_OOS_N and
        a["win_rate"]>=.55 and b["win_rate"]>=.50 and b["roi"]>=-.05)
    return ok,a,b

def eligible_line(all_rows):
    train,test=split(all_rows)
    a,b=stats(all_rows),stats(test)
    ok=(a["n"]>=MIN_LINE_N and b["n"]>=MIN_LINE_OOS_N and
        a["win_rate"]>=.58 and b["win_rate"]>=.55 and b["roi"]>=-.02)
    return ok,a,b

def main():
    history=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    rows=settled(history)
    comps={}
    lines={}
    for r in rows:
        c=str(r.get("competition") or "Unknown")
        comps.setdefault(c,[]).append(r)
        if str(r.get("market"))=="ou" and r.get("line") is not None:
            lines.setdefault(str(float(r["line"])),[]).append(r)

    comp_report={}
    eligible_competitions=[]
    blocked_competitions=[]
    for c,a in comps.items():
        ok,all_s,oos_s=eligible_comp(a)
        comp_report[c]={"eligible":ok,"all":all_s,"oos":oos_s,
                       "reason":("passes league gate" if ok else
                                 "insufficient sample or weak all/OOS performance")}
        (eligible_competitions if ok else blocked_competitions).append(c)

    line_report={}
    eligible_lines=[]
    blocked_lines=[]
    for line,a in lines.items():
        ok,all_s,oos_s=eligible_line(a)
        line_report[line]={"eligible":ok,"all":all_s,"oos":oos_s,
                           "reason":("passes O/U line gate" if ok else
                                     "insufficient sample or weak all/OOS performance")}
        (eligible_lines if ok else blocked_lines).append(float(line))

    out={
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "mode":"PAPER_RESEARCH_ONLY",
      "policy":{
        "minimum_competition_observations":MIN_COMP_N,
        "minimum_competition_oos":MIN_COMP_OOS_N,
        "minimum_line_observations":MIN_LINE_N,
        "minimum_line_oos":MIN_LINE_OOS_N,
        "discovery_fraction":DISCOVERY,
        "eligible_markets":["ou"],
        "blocked_markets":["winner","1x2","btts","handicap","other"],
        "note":"Collection continues for blocked groups so the gate can be re-evaluated; blocked groups are excluded from research selections. Priority O/U lines are monitored continuously but do not bypass the evidence gate."
      },
      "eligible_competitions":sorted(eligible_competitions),
      "blocked_competitions":sorted(blocked_competitions),
      "priority_ou_lines":PRIORITY_OU_LINES,
      "eligible_ou_lines":sorted(eligible_lines),
      "blocked_ou_lines":sorted(blocked_lines),
      "competitions":comp_report,
      "ou_lines":line_report,
    }
    OUTPUT.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))

if __name__=="__main__":
    main()
