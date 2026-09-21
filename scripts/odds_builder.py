"""Match Signal V6 market-calibrated value engine.

Research/paper-trading only. A candidate is eligible only when:
- calibrated model probability clears the minimum threshold,
- a fresh SportyBet price is actually present,
- bookmaker margin is removed where a complete market is available,
- model edge clears the V6 threshold,
- data/price freshness and uncertainty gates pass,
- correlated selections are not duplicated in the same accumulator.

No wager is placed and no 3-4 leg target is forced.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
CANDIDATES=DATA/"selection_candidates.json"
PREDICTIONS=DATA/"predictions.json"
OUTPUT=DATA/"odds_builder.json"
HISTORY=DATA/"prediction_history.json"
SELECTION_GATE=DATA/"selection_gate.json"
RISK_GATE=DATA/"risk_gate.json"

MIN_PROB=0.60
MIN_EDGE=0.025
MAX_ODDS_AGE_SECONDS=900
MAX_UNCERTAINTY=0.22
MIN_DATA_QUALITY=0.70
MIN_LEGS,MAX_LEGS=3,4


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):
        return default


def upcoming(x, now):
    try:
        raw=x.get("start_time")
        if not raw:return False
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        return dt.astimezone(timezone.utc)>now
    except (TypeError,ValueError):
        return False


def fair_odds(p):
    return round(1.0/float(p),3) if float(p)>0 else 0.0


def prob_value(x, *keys):
    for key in keys:
        try:
            value=x.get(key)
            if value is not None:return float(value)
        except (TypeError,ValueError):
            pass
    return 0.0


def data_quality(x):
    q=x.get("data_quality")
    if q is not None:
        try:return max(0.0,min(1.0,float(q)))
        except (TypeError,ValueError):pass
    qobj=x.get("signal_quality") or {}
    try:
        components=float(qobj.get("components",0))
        return min(1.0,components/5.0) if components else 0.75
    except (TypeError,ValueError):
        return 0.75


def uncertainty(x,p):
    explicit=x.get("uncertainty")
    if explicit is not None:
        try:return max(0.0,min(1.0,float(explicit)))
        except (TypeError,ValueError):pass
    # Conservative proxy when the model does not expose a dedicated uncertainty field.
    return max(0.0,min(1.0,abs(0.5-float(p))*0.35))


def odds_age(x):
    try:
        stamp=x.get("odds_timestamp")
        if not stamp:return None
        return max(0.0,(datetime.now(timezone.utc)-datetime.fromisoformat(str(stamp).replace("Z","+00:00"))).total_seconds())
    except (TypeError,ValueError):
        return None


def football_candidates(now):
    raw=load(CANDIDATES,[])
    out=[]
    if not isinstance(raw,list):return out
    for x in raw:
        if not isinstance(x,dict) or x.get("candidate_status")!="SELECTED" or x.get("sport")!="football" or not upcoming(x,now):continue
        probs=x.get("calibrated_probabilities") or x.get("probabilities") or {}
        pick=x.get("pick")
        try:p=float(probs.get(pick,x.get("calibrated_confidence",x.get("confidence",0))) or 0)
        except (TypeError,ValueError):continue
        if p>=MIN_PROB and pick in {"p1","draw","p2"}:
            out.append({**x,"builder_market":"1X2","builder_probability":p,"builder_pick":pick})
    return out


def tennis_candidates(now):
    raw=load(PREDICTIONS,[])
    out=[]
    if not isinstance(raw,list):return out
    for x in raw:
        if not isinstance(x,dict) or x.get("sport")!="tennis" or not upcoming(x,now):continue
        probs=x.get("calibrated_probabilities") or x.get("probabilities") or {}
        pick=x.get("pick")
        try:wp=float(probs.get(pick,x.get("calibrated_confidence",0)) or 0) if pick else 0.0
        except (TypeError,ValueError):wp=0.0
        total=(x.get("analytics") or {}).get("total_games") or {}
        ou_pick=total.get("pick")
        try:op=float(total.get("calibrated_"+ou_pick,total.get(ou_pick,0)) or 0) if ou_pick else 0.0
        except (TypeError,ValueError):op=0.0
        if wp>=MIN_PROB and pick in {"p1","p2"}:
            out.append({**x,"builder_market":"winner","builder_probability":wp,"builder_pick":pick})
        if ou_pick in {"over","under"} and op>=MIN_PROB and total.get("line") is not None:
            out.append({**x,"builder_market":"total_games","builder_probability":op,"builder_pick":ou_pick})
    return out


def market_rows(x):
    market=x.get("builder_market")
    if market=="total_games":
        total=(x.get("analytics") or {}).get("total_games") or {}
        line=float(total.get("line")) if total.get("line") is not None else None
        rows=x.get("sportybet_total_games_odds") or []
        return [r for r in rows if isinstance(r,dict) and line is not None and r.get("line") is not None and abs(float(r.get("line"))-line)<1e-9]
    snap=x.get("sportybet_winner_odds") or {}
    if isinstance(snap,dict):
        return [{"side":k,"odds":v} for k,v in snap.items() if k in {"p1","p2","draw"} and v is not None]
    return []


def selected_price_and_devig(x):
    rows=market_rows(x)
    pick=x.get("builder_pick")
    selected=None
    inv=[]
    for row in rows:
        try:
            odds=float(row.get("odds"))
            if odds<=1:continue
            inv.append((row.get("side"),1.0/odds))
            if row.get("side")==pick:selected=odds
        except (TypeError,ValueError):
            continue
    if selected is None:return None,None,None,False
    total=sum(v for _,v in inv)
    if total<=0:return selected,1.0/selected,None,False
    devig=next((v/total for side,v in inv if side==pick),None)
    complete=(len(inv)>=2 if x.get("builder_market")=="total_games" else len(inv)>=2)
    return selected,1.0/selected,devig,complete


def make_leg(x):
    p=float(x["builder_probability"])
    bookmaker,implied,devig,complete=selected_price_and_devig(x)
    age=odds_age(x)
    quality=data_quality(x)
    uncert=uncertainty(x,p)
    market_prob=devig if complete and devig is not None else implied
    edge=(p-market_prob) if market_prob is not None else None
    ev=((p*bookmaker)-1.0) if bookmaker is not None else None
    eligible=(
        bookmaker is not None and
        edge is not None and edge>=MIN_EDGE and
        age is not None and age<=MAX_ODDS_AGE_SECONDS and
        quality>=MIN_DATA_QUALITY and uncert<=MAX_UNCERTAINTY
    )
    if x.get("sport")=="tennis":
        if x.get("builder_market")=="total_games":
            total=(x.get("analytics") or {}).get("total_games") or {}
            market=f"Total Games {x.get('builder_pick')} {total.get('line')}"
        else:
            market=f"Winner {x.get('builder_pick')}"
        match=f"{x.get('player_1')} vs {x.get('player_2')}"
        pick=f"{match} — {market}"
    else:
        match=f"{x.get('home_team')} vs {x.get('away_team')}"
        pick=x.get("builder_pick")
    return {
        "sport":x.get("sport"),"competition":x.get("league"),"event_id":x.get("event_id"),
        "start_time":x.get("start_time"),"match":match,"market":x.get("builder_market"),
        "pick":pick,"model_probability":round(p,6),"model_fair_odds":fair_odds(p),
        "bookmaker_odds":round(bookmaker,3) if bookmaker is not None else None,
        "market_implied_probability":round(implied,6) if implied is not None else None,
        "de_vig_probability":round(devig,6) if devig is not None else None,
        "model_edge":round(edge,6) if edge is not None else None,
        "expected_value":round(ev,6) if ev is not None else None,
        "edge_percent":round(edge*100,2) if edge is not None else None,
        "odds_fresh":bool(age is not None and age<=MAX_ODDS_AGE_SECONDS),
        "market_odds_age_seconds":round(age,1) if age is not None else None,
        "data_quality":round(quality,3),"uncertainty":round(uncert,3),
        "market_complete":complete,"real_money_eligible":eligible,
        "status":"LIVE_VALUE" if eligible else ("STALE" if age is not None and age>MAX_ODDS_AGE_SECONDS else "REJECTED"),
        "source":x.get("model"),"market_source":x.get("market_source"),
        "market_odds_timestamp":x.get("odds_timestamp")
    }


def select_value(candidates):
    built=[make_leg(x) for x in candidates]
    eligible=[x for x in built if x["real_money_eligible"]]
    eligible.sort(key=lambda x:(x.get("model_edge") or -1,x.get("model_probability") or 0),reverse=True)
    selected=[];events=set()
    for leg in eligible:
        eid=str(leg.get("event_id") or "")
        if eid and eid in events:continue
        selected.append(leg)
        if eid:events.add(eid)
        if len(selected)>=MAX_LEGS:break
    return selected,built


def recent_settled(history,now,known):
    if not isinstance(history,list):return []
    today=now.date().isoformat();out=[]
    for x in history:
        if not isinstance(x,dict) or not x.get("settled") or str(x.get("event_id") or "") not in known or str(x.get("start_time",""))[:10]!=today or x.get("sport")!="tennis":continue
        total=(x.get("analytics") or {}).get("total_games") or {}; pick=total.get("pick")
        if pick not in {"over","under"} or total.get("line") is None:continue
        try:p=float(total.get("calibrated_"+pick,total.get(pick,0)) or 0)
        except (TypeError,ValueError):continue
        if p<MIN_PROB:continue
        actual=x.get("actual_markets") or {}; correct=actual.get("total_games_correct")
        if correct is None:
            result=actual.get("total_games_result");correct=(result==pick) if result in {"over","under"} else x.get("correct")
        if not isinstance(correct,bool):continue
        out.append({"sport":"tennis","competition":x.get("league"),"event_id":x.get("event_id"),
                    "start_time":x.get("start_time"),"match":f"{x.get('player_1')} vs {x.get('player_2')}",
                    "market":"total_games","pick":f"{x.get('player_1')} vs {x.get('player_2')} — Total Games {pick} {total.get('line')}",
                    "model_probability":round(p,6),"model_fair_odds":fair_odds(p),
                    "settlement":{"finished":True,"correct":bool(correct)},"final_score":x.get("final_score"),
                    "actual_markets":actual,"settled_at":x.get("settled_at")})
    out.sort(key=lambda x:str(x.get("settled_at") or ""),reverse=True)
    return out[:4]


def main():
    now=datetime.now(timezone.utc)
    gate=load(SELECTION_GATE,{})
    risk=load(RISK_GATE,{})
    gate_status=str(gate.get("status") or "")
    selected_predictions=int(gate.get("selected_predictions") or 0)
    tennis_risk=(risk.get("gate") or {}).get("tennis") or {}
    tennis_live_eligible=bool(tennis_risk.get("live_eligible") is True)
    # The accumulator must never bypass the upstream research/risk gate.
    # This prevents the builder from turning a losing public prediction feed
    # into an apparent betting recommendation.
    upstream_blocked = gate_status not in {"ok","PASS"} or selected_predictions <= 0 or not tennis_live_eligible
    football=football_candidates(now)
    tennis=tennis_candidates(now)
    selected,built=select_value([] if upstream_blocked else (football+tennis))
    previous=load(OUTPUT,{})
    previous_ids={str(x) for x in (previous.get("builder_event_ids",[]) if isinstance(previous,dict) else []) if x}
    previous_ids.update(str(x.get("event_id")) for x in (previous.get("qualified_legs",[]) if isinstance(previous,dict) else []) if isinstance(x,dict) and x.get("event_id"))
    known=previous_ids|{"183724","183769"}
    settled_ids={str(x.get("event_id")) for x in load(HISTORY,[]) if isinstance(x,dict) and x.get("settled") and x.get("event_id")}
    selected=[x for x in selected if str(x.get("event_id")) not in settled_ids]
    sports=sorted({x["sport"] for x in selected})
    status="LIVE_VALUE_SET" if len(selected)>=MIN_LEGS else ("SINGLE_LIVE_VALUE" if selected else "NO_BET")
    rejection_counts={}
    for leg in built:
        leg_status=str(leg.get("status") or "REJECTED")
        rejection_counts[leg_status]=rejection_counts.get(leg_status,0)+1
    result={
        "generated_at":now.isoformat(),"engine_version":"V6.1-RESEARCH-GATED",
        "mode":"PAPER_ONLY","target_legs":"3-4","sports_supported":["football","tennis"],
        "research_gate":{
            "selection_gate_status":gate_status,
            "selected_predictions":selected_predictions,
            "tennis_live_eligible":tennis_live_eligible,
            "upstream_blocked":upstream_blocked,
            "risk_reasons":tennis_risk.get("reasons",[]),
            "selection_reasons":gate.get("rejection_reasons",{})
        },
        "candidate_diagnostics":{
            "football_candidates":len(football),
            "tennis_candidates":len(tennis),
            "evaluated":len(built),
            "rejections":rejection_counts
        },
        "selection_policy":{"min_calibrated_probability":MIN_PROB,"min_model_edge":MIN_EDGE,
            "max_odds_age_seconds":MAX_ODDS_AGE_SECONDS,"max_uncertainty":MAX_UNCERTAINTY,
            "min_data_quality":MIN_DATA_QUALITY,"requires_live_sportybet_price":True,
            "requires_complete_market_for_devig":True,"avoid_same_event_correlation":True,
            "never_force_accumulator":True,"real_money_execution":False},
        "bookmaker_odds":{"status":"LIVE_SPORTYBET_SNAPSHOT","sportybet_direct_feed":"VIA_CLOUDFLARE_PROXY",
            "stake_direct_feed":"NOT_CONNECTED","instruction":"Verify the displayed SportyBet price immediately before any manual wager."},
        "candidates_considered":{"football":len(football),"tennis":len(tennis),"all_built":len(built)},
        "qualified_legs":selected,
        "rejected_candidates":[x for x in built if not x["real_money_eligible"]][:20],
        "settled_legs":recent_settled(load(HISTORY,[]),now,known),
        "builder_event_ids":sorted(known),"leg_count":len(selected),"sports_selected":sports,
        "status":("UPSTREAM_RESEARCH_GATE_BLOCKED" if upstream_blocked else ("LIVE_VALUE_SET" if len(selected)>=MIN_LEGS else ("SINGLE_LIVE_VALUE" if selected else "NO_BET"))),
        "reference_combined_odds":round(math.prod(x["model_fair_odds"] for x in selected),3) if selected else None,
        "reference_odds_type":"MODEL_FAIR_ODDS_NOT_BOOKMAKER_PRICE",
        "market_price_combined_odds":round(math.prod(x["bookmaker_odds"] for x in selected),3) if selected and all(x.get("bookmaker_odds") is not None for x in selected) else None,
        "theme":{"name":"Midnight Graphite / Electric Cyan / Signal Green","accent":"#28D7E8","positive":"#35D07F","background":"#080D14"},
        "notes":["V6 qualifies on market edge, not probability alone.","Missing or stale SportyBet prices produce NO_BET/REJECTED.","Model fair odds never overwrite bookmaker odds.","Accumulator size is allowed to fall below four and is never padded with weak selections.","Paper-only until V6 demonstrates stable calibration, edge and closing-line value over a meaningful sample."]
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
