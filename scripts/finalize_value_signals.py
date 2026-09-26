#!/usr/bin/env python3
"""Finalize current model-vs-SportyBet value signals after all model layers run.

This step never changes model probabilities. It converts the already attached
current SportyBet odds into de-vig reference probabilities and records explicit
edge/EV/fair-odds signals for the selection and risk gates.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"

def load(name, default):
    try:return json.loads((DATA/name).read_text(encoding="utf-8"))
    except Exception:return default

def number(v):
    try:
        x=float(v)
        return x if x>0 else None
    except (TypeError,ValueError):return None

def devig(odds):
    vals=[number(x) for x in odds]
    if any(x is None for x in vals):return None
    implied=[1/x for x in vals]
    total=sum(implied)
    if total<=0:return None
    return [x/total for x in implied]

def two_way(odds):
    vals=[number(x) for x in odds]
    if any(x is None for x in vals):return None
    implied=[1/x for x in vals]
    total=sum(implied)
    if total<=0:return None
    return [x/total for x in implied]

def ev(prob, odds):
    d=number(odds)
    p=number(prob)
    if d is None or p is None:return None
    return p*d-1.0

def finalize(row):
    probs=row.get("probabilities") or {}
    winner=row.get("sportybet_winner_odds") or {}
    snapshot=row.get("sportybet_market_snapshot") or {}
    out=row.get("market_insights") or {}
    out["snapshot_at"]=snapshot.get("fetched_at") or row.get("odds_timestamp")
    out["source"]="SportyBet NG"
    model_pick=str(row.get("pick") or "")
    if model_pick in {"p1","p2","draw"} and winner:
        odds_map={"p1":winner.get("p1"),"draw":winner.get("draw"),"p2":winner.get("p2")}
        ordered=[odds_map.get("p1"),odds_map.get("draw"),odds_map.get("p2")] if row.get("sport")=="football" else [odds_map.get("p1"),odds_map.get("p2")]
        market_probs=devig(ordered)
        if market_probs:
            model_probs=[number(probs.get("p1")),number(probs.get("draw")),number(probs.get("p2"))] if row.get("sport")=="football" else [number(probs.get("p1")),number(probs.get("p2"))]
            if all(x is not None for x in model_probs):
                idx={"p1":0,"draw":1,"p2":2}[model_pick] if row.get("sport")=="football" else {"p1":0,"p2":1}[model_pick]
                mp=market_probs[idx]
                bp=ordered[idx]
                fair=1/model_probs[idx] if model_probs[idx]>0 else None
                out.update({
                    "winner_model_probability":round(model_probs[idx],6),
                    "winner_market_probability":round(mp,6),
                    "winner_model_edge_vs_market":round(model_probs[idx]-mp,6),
                    "winner_expected_value":round(ev(model_probs[idx],bp),6) if ev(model_probs[idx],bp) is not None else None,
                    "winner_book_odds":bp,
                    "winner_fair_odds":round(fair,4) if fair else None,
                    "winner_value_signal":bool(model_probs[idx]-mp>=0.035 and ev(model_probs[idx],bp) is not None and ev(model_probs[idx],bp)>=0.05),
                })

    totals=row.get("sportybet_total_games_odds") or []
    total_model=((row.get("analytics") or {}).get("total_games") or {})
    model_line=number(total_model.get("line"))
    model_over=number(total_model.get("over"))
    if model_line is not None and model_over is not None and totals:
        exact=None
        for t in totals:
            line=number(t.get("line"))
            if line is not None and abs(line-model_line)<=0.01:
                exact=t
                break
        if exact:
            sides=[]
            for side in ("over","under"):
                odds=number(exact.get("odds")) if str(exact.get("side"))==side else None
                if odds is not None:sides.append((side,odds))
            # The provider returns one row per side; pair them by line.
            pair={}
            for t in totals:
                line=number(t.get("line"))
                if line is None or abs(line-model_line)>0.01:continue
                side=str(t.get("side") or "")
                odds=number(t.get("odds"))
                if side in {"over","under"} and odds is not None:pair[side]=odds
            if "over" in pair and "under" in pair:
                mp=two_way([pair["over"],pair["under"]])
                if mp:
                    pick="over" if model_over>=0.5 else "under"
                    idx=0 if pick=="over" else 1
                    model_prob=model_over if pick=="over" else 1-model_over
                    book=pair[pick]
                    out["total"]={
                        "line":model_line,
                        "pick":pick,
                        "model_probability":round(model_prob,6),
                        "market_probability":round(mp[idx],6),
                        "model_edge_vs_market":round(model_prob-mp[idx],6),
                        "expected_value":round(ev(model_prob,book),6),
                        "book_odds":book,
                        "fair_odds":round(1/model_prob,4) if model_prob>0 else None,
                        "value_signal":bool(model_prob-mp[idx]>=0.035 and ev(model_prob,book) is not None and ev(model_prob,book)>=0.05),
                    }
    row["market_insights"]=out
    return row

predictions=load("predictions.json",[])
updated=0
winner_value=0
total_value=0
for row in predictions:
    finalize(row)
    updated+=1
    mi=row.get("market_insights") or {}
    if mi.get("winner_value_signal"):winner_value+=1
    if (mi.get("total") or {}).get("value_signal"):total_value+=1
(DATA/"predictions.json").write_text(json.dumps(predictions,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
(DATA/"value_signal_status.json").write_text(json.dumps({
    "updated_at":datetime.now(timezone.utc).isoformat(),
    "predictions_processed":updated,
    "winner_value_signals":winner_value,
    "total_value_signals":total_value,
    "paper_only":True,
    "thresholds":{"edge":0.035,"expected_value":0.05},
    "policy":"Value layer consumes current SportyBet prices as benchmark/reference only; it never changes model probabilities."
},indent=2)+"\n",encoding="utf-8")
print(json.dumps({"predictions_processed":updated,"winner_value_signals":winner_value,"total_value_signals":total_value},indent=2))
