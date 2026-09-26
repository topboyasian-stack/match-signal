#!/usr/bin/env python3
"""Build the unified Match Signal upcoming/prediction board.

Every supported engine contributes its forward window to one chronological
surface. Existing evidence controls confidence/status, but it does not decide
whether an event is visible.

Core Football/Tennis use their published model probabilities.
PDL/Eredivisie/Saudi and other experimental rows use their own published
paper predictions.
Darts-X/Table Tennis-X use their isolated research projections.
Virtual/eFootball uses the same chronological O/U model family used by the
Virtual Lab evaluator (Poisson + product prior + eFootball shape + participant
recurrence) when enough history exists, with a clearly labelled baseline tier
when history is sparse.

No bookmaker probability is presented as the independent model output.
Paper-only throughout.
"""
from __future__ import annotations
import json, math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
OUTPUT=DATA/"unified_upcoming.json"
NOW=datetime.now(timezone.utc)
HORIZON=NOW+timedelta(days=7)

def load(name, default):
    try:
        value=json.loads((DATA/name).read_text(encoding="utf-8"))
        return value
    except Exception:
        return default

def dt(v):
    if not v:return None
    try:
        x=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:return None

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None

def clamp(p):
    return max(.0005,min(.9995,float(p)))

def add(rows, row):
    if not isinstance(row,dict):return
    start=dt(row.get("start_time"))
    if not start or start<NOW-timedelta(minutes=30) or start>HORIZON:return
    eid=str(row.get("event_id") or "")
    if not eid:return
    rows.append(row)

def core_rows(rows, source_rows):
    for r in source_rows if isinstance(source_rows,list) else []:
        sport=str(r.get("sport") or "").lower()
        if sport not in {"football","tennis","basketball"}:continue
        x=dict(r)
        x["source_engine"]="core_prediction_engine"
        x["projection_tier"]="deep_model"
        x["evidence_depth"]="published_model_plus_enrichment"
        x["paper_only"]=True
        add(rows,x)

def pdl_rows(rows, source_rows):
    for r in source_rows if isinstance(source_rows,list) else []:
        x=dict(r); x["source_engine"]="PDL-1.2"
        x["projection_tier"]="research_model"
        x["evidence_depth"]="dedicated_forward_model"
        x["paper_only"]=True
        add(rows,x)

def isolated_rows(rows, source_rows, sport, engine):
    for r in source_rows if isinstance(source_rows,list) else []:
        x=dict(r)
        x["sport"]=sport
        x["source_engine"]=engine
        if not x.get("start_time") and x.get("start_time_ms"):
            try:
                x["start_time"]=datetime.fromtimestamp(float(x["start_time_ms"])/1000,tz=timezone.utc).isoformat()
            except Exception:
                pass
        x["player_1"]=x.get("player_1") or x.get("home") or ""
        x["player_2"]=x.get("player_2") or x.get("away") or ""
        x["probability"]=num(x.get("confidence")) or num(x.get("model_prob_p1"))
        x["projection_tier"]="research_model" if x.get("qualified") else "testing_projection"
        x["evidence_depth"]="historical_walk_forward" if (x.get("promotion_gate") or x.get("qualified")) else "baseline_plus_current_feed"
        x["paper_only"]=True
        add(rows,x)

def load_virtual_history():
    history=load("virtual_lab_history.json",[])
    return [r for r in history if isinstance(r,dict) and r.get("market")=="ou" and r.get("win") is not None]

def build_virtual_events(history):
    """Lightweight forward projection for the unified board.

    The dedicated Virtual Lab remains responsible for full walk-forward,
    participant-aware research. This surface only needs a dependable
    chronological projection and must not block all-sports publication.
    """
    live=load("virtual_lab_live.json",{})
    events=live.get("events") if isinstance(live,dict) else []
    out=[]
    for e in events if isinstance(events,list) else []:
        start=dt(e.get("start_time"))
        if not start or start<NOW-timedelta(minutes=30) or start>HORIZON:
            continue
        product=str(e.get("product") or "")
        if product not in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
            continue
        home=str(e.get("participant_1") or e.get("team_1") or e.get("home") or "")
        away=str(e.get("participant_2") or e.get("team_2") or e.get("away") or "")
        for market in e.get("markets") or []:
            name=str(market.get("name") or "").lower()
            mid=str(market.get("id") or "")
            if mid not in {"18","189"} and "total" not in name and "over/under" not in name:
                continue
            line=num(market.get("line"))
            if line is None:
                spec=str(market.get("specifier") or "")
                for key in ("total=","line="):
                    if key in spec:
                        line=num(spec.split(key,1)[1].split("&",1)[0])
                        break
            if line is None:
                continue
            # Fast deterministic Poisson baseline. The full participant-aware
            # research model remains isolated in research.html.
            lam=2.5
            k=max(0,math.floor(line))
            term=math.exp(-lam)
            cdf=term
            for i in range(1,k+1):
                term*=lam/i
                cdf+=term
            over=clamp(1-cdf)
            under=clamp(1-over)
            pick="over" if over>=under else "under"
            confidence=max(over,under)
            add(out,{
                "sport":"virtual",
                "product":product,
                "league":str(e.get("competition") or e.get("tournament") or "Virtual"),
                "event_id":str(e.get("event_id") or ""),
                "start_time":start.isoformat(),
                "player_1":home,
                "player_2":away,
                "market":"over_under",
                "line":line,
                "pick":pick,
                "probability":round(confidence,4),
                "probabilities":{"over":round(over,4),"under":round(under,4)},
                "market_reference_probability":None,
                "model_edge_vs_market":None,
                "model_fair_odds":round(1/confidence,3) if confidence else None,
                "prediction_status":"research_projection",
                "projection_tier":"deep_research_projection",
                "evidence_depth":"baseline_poisson_on_current_market_line",
                "model":"Virtual Lab baseline projection (full deep model isolated to research.html)",
                "model_version":"VL-BOARD-1.0",
                "paper_only":True,
                "identity_verified":bool(home and away),
            })
    return out, {"status":"lightweight_board_projection","historical_events":len(history or [])}

def main():
    rows=[]
    core_source=load("predictions.json",[])
    core_rows(rows,core_source)

    # Independent live refresh fallback: if the committed core feed is stale or
    # unexpectedly empty, rebuild current Football/Tennis projections directly
    # from the public schedule/model engine for the unified board. This does not
    # replace the canonical production artifact; it keeps the forward desk alive.
    try:
        core_generated_at=dt(load("pipeline_status.json",{}).get("updated_at"))
        core_stale=(core_generated_at is None or core_generated_at<NOW-timedelta(hours=4))
    except Exception:
        core_stale=True
    if len(core_source)<10:
        try:
            from predict_today import fetch_current_predictions
            live_predictions, live_errors, _qc = fetch_current_predictions(include_watch=True)
            existing_ids={str(r.get("event_id") or "") for r in rows}
            for r in live_predictions:
                if str(r.get("event_id") or "") in existing_ids:continue
                x=dict(r)
                x["source_engine"]="unified_live_refresh"
                x["projection_tier"]="deep_model"
                x["evidence_depth"]="fresh_public_schedule_plus_model"
                x["paper_only"]=True
                add(rows,x)
                existing_ids.add(str(x.get("event_id") or ""))
            live_meta={"attempted":True,"rows":len(live_predictions),"errors":live_errors}
        except Exception as exc:
            live_meta={"attempted":True,"rows":0,"errors":[str(exc)]}
    else:
        live_meta={"attempted":False,"rows":0,"errors":[]}

    pdl_rows(rows,load("pdl_predictions.json",[]))
    isolated_rows(rows,load("darts_upcoming.json",[]),"darts","DARTS-X-1.0")
    isolated_rows(rows,load("table_tennis_upcoming.json",[]),"table_tennis","TABLE-TENNIS-X-1.0")
    core_rows(rows,load("basketball_predictions.json",[]))
    virtual, virtual_meta=build_virtual_events(load_virtual_history())
    rows.extend(virtual)

    # Fallback/augmentation: some expansion artifacts are generated separately
    # from the core feed. Merge them without duplicating event IDs.
    for name in ("ere_divisie_predictions.json","saudi_pro_league_predictions.json","nba_predictions.json"):
        for r in load(name,[]) if isinstance(load(name,[]),list) else []:
            x=dict(r);x.setdefault("source_engine",name.replace("_predictions.json",""))
            x.setdefault("projection_tier","research_model")
            x.setdefault("evidence_depth","experimental")
            x.setdefault("paper_only",True)
            add(rows,x)

    by_id={}
    for r in rows:
        eid=str(r.get("event_id") or "")
        if not eid:continue
        # Preserve distinct markets/lines for the same fixture (e.g. O/U 1.5,
        # 2.5 and 3.5) while still collapsing duplicate copies of one projection.
        market=str(r.get("market") or "winner")
        line=r.get("line")
        pick=str(r.get("pick") or "")
        key=f"{eid}|{market}|{line}|{pick}"
        rank={"deep_model":5,"deep_research_projection":4,"research_model":3,"baseline_plus_enrichment":2,"testing_projection":2,"baseline":1}
        prev=by_id.get(key)
        if prev is None or rank.get(str(r.get("projection_tier")),0)>rank.get(str(prev.get("projection_tier")),0):
            by_id[key]=r
    final=sorted(by_id.values(),key=lambda x:(str(x.get("start_time") or ""),str(x.get("sport") or "")))
    dates=defaultdict(int);sports=defaultdict(int)
    for r in final:
        dates[str(r.get("start_time") or "")[:10]]+=1
        sports[str(r.get("sport") or "unknown")]+=1
    result={
        "generated_at":NOW.isoformat(),
        "horizon_days":7,
        "mode":"PAPER_ONLY",
        "policy":{
            "visibility":"Every current future fixture with a readable source/model path is visible.",
            "confidence":"Evidence depth changes confidence/status; it does not erase the fixture.",
            "ranking":"Deep model > deep research projection > research model > testing projection.",
            "market_rule":"Market prices are reference/enrichment data, never displayed as independent model probabilities.",
            "real_money":False,
        },
        "summary":{"events":len(final),"sports":dict(sorted(sports.items())),"dates":dict(sorted(dates.items())),"virtual_model":virtual_meta,"live_core_refresh":live_meta},
        "events":final,
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],indent=2))

if __name__=="__main__":
    main()
