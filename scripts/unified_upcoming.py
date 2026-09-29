#!/usr/bin/env python3
"""Build the unified Match Signal upcoming/prediction board.

Fresh Virtual snapshot synchronization is a publication dependency.

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
import re
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

def apply_bookmaker_fields(x):
    """Normalize current SportyBet quotes onto a unified prediction row."""
    winner=x.get("sportybet_winner_odds")
    totals=x.get("sportybet_total_games_odds") or []
    pick=str(x.get("pick") or "").lower()
    line=num(x.get("line"))
    quote=None
    if isinstance(winner,dict):
        side={"p1":"p1","p2":"p2","draw":"draw"}.get(pick)
        if side and num(winner.get(side)) is not None:
            quote=num(winner.get(side))
            x["sportybet_odds_market"]="winner"
    if quote is None and isinstance(totals,list):
        for item in totals:
            if not isinstance(item,dict): continue
            il=num(item.get("line"))
            side=str(item.get("side") or "").lower()
            if line is not None and il is not None and abs(il-line)<0.001 and side==pick and num(item.get("odds")) is not None:
                quote=num(item.get("odds"))
                x["sportybet_odds_market"]="total"
                x["sportybet_odds_line"]=il
                break
    if quote is not None:
        x["bookmaker_odds"]=quote
        x["sportybet_odds"]=quote
        x["bookmaker_available"]=True
        x["bookmaker_source"]="SportyBet NG"
        x["market_odds_timestamp"]=x.get("odds_timestamp")
    return x

def norm_name(v):
    return re.sub(r"[^a-z0-9]+"," ",str(v or "").lower()).strip()

def row_date(row):
    value=row.get("start_time") or row.get("timestamp") or row.get("date")
    d=dt(value)
    return d.date().isoformat() if d else ""

def match_key(row):
    sport=str(row.get("sport") or row.get("product") or "").lower()
    if sport=="virtual":
        sport=str(row.get("product") or sport).lower()
    p1=norm_name(row.get("player_1") or row.get("participant_1") or row.get("home") or row.get("team_1"))
    p2=norm_name(row.get("player_2") or row.get("participant_2") or row.get("away") or row.get("team_2"))
    day=row_date(row)
    if not p1 or not p2 or not day:
        return None
    pair="|".join(sorted((p1,p2)))
    return f"{sport}|{day}|{pair}"

def explicit_live(row):
    text=" ".join(str(row.get(k) or "") for k in ("match_status","matchStatus","status","state")).lower()
    return bool(row.get("live") or row.get("isLive") or re.search(r"(live|started|inprogress|playing|period|set)",text))

def explicit_terminal(row):
    if row.get("settled") is True or row.get("completed") is True or row.get("finished") is True or row.get("ended") is True:
        return True
    text=" ".join(str(row.get(k) or "") for k in ("match_status","matchStatus","status","state")).lower()
    return bool(re.search(r"(finished|ended|completed|settled|closed|full.?time)$",text))

def settlement_index():
    event_ids=set()
    keys=set()
    details={}

    def ingest(items, require_settled=True):
        for item in items if isinstance(items,list) else []:
            if not isinstance(item,dict):
                continue
            if require_settled and item.get("settled") is not True and item.get("win") is None:
                continue
            eid=str(item.get("event_id") or "").strip()
            if eid:
                event_ids.add(eid)
            key=match_key(item)
            if key:
                keys.add(key)

    ingest(load("prediction_history.json",[]),True)
    ingest(load("expansion_prediction_history.json",[]),True)
    ingest(load("virtual_lab_history.json",[]),True)
    # Darts/Table Tennis history rows are result-only ledgers, so every row is terminal.
    ingest(load("darts_history.json",[]),False)
    ingest(load("table_tennis_history.json",[]),False)
    return event_ids,keys,details

SETTLED_EVENT_IDS, SETTLED_MATCH_KEYS, SETTLED_DETAILS = settlement_index()

def settled_record(row):
    eid=str(row.get("event_id") or "")
    market=str(row.get("market") or "winner")
    line="" if row.get("line") is None else str(row.get("line"))
    pick=str(row.get("pick") or row.get("selection") or "")
    return SETTLED_DETAILS.get(f"{eid}|{market}|{line}|{pick}")

def add(rows, row):
    if not isinstance(row,dict):return
    start=dt(row.get("start_time"))
    if not start or start>HORIZON:return
    eid=str(row.get("event_id") or "")
    if not eid:return

    # Terminal result state wins over every other display rule. For Virtual/
    # eFootball, retain an exact settled prediction match for the recent
    # settlement window so Upcoming can show the original selection with its
    # result instead of silently deleting it.
    # Historical Virtual/eFootball event IDs can recur across sessions. Never hide a
    # genuinely future fixture merely because its ID appeared in an older settlement
    # ledger. Event-id/match-key settlement is only authoritative once kickoff has
    # passed; explicit terminal provider state still wins immediately.
    started_or_due = bool(start and start <= NOW)
    terminal=explicit_terminal(row) or (started_or_due and (eid in SETTLED_EVENT_IDS or match_key(row) in SETTLED_MATCH_KEYS))
    if terminal:
        sr=settled_record(row) if str(row.get("sport") or "")=="virtual" else None
        if sr and sr.get("settled_at"):
            try:
                age=(NOW-dt(sr.get("settled_at"))).total_seconds()
            except Exception:
                age=999999
            if age<=48*3600:
                row["event_state"]="SETTLED"
                row["settled"]=True
                row["settlement_result"]=sr.get("result") or sr.get("actual_result")
                row["final_score"]=sr.get("score") or sr.get("final_score")
                row["settled_at"]=sr.get("settled_at")
                row["prediction_trace_id"]=sr.get("trace_id") or sr.get("record_id")
            else:
                return
        else:
            return

    nowish=NOW-timedelta(minutes=30)
    if start < nowish and not explicit_live(row):
        # A kickoff already passed but settlement has not arrived yet. Keep it
        # only briefly as a pending-settlement/live queue item; once the
        # settlement ledger receives the result, it disappears automatically.
        age_hours=(NOW-start).total_seconds()/3600
        if age_hours>6:
            return
        row.setdefault("event_state","PENDING_SETTLEMENT")
    elif explicit_live(row):
        row.setdefault("event_state","LIVE")
    else:
        row.setdefault("event_state","UPCOMING")
    row["settlement_tracked"]=bool(eid in SETTLED_EVENT_IDS or match_key(row) in SETTLED_MATCH_KEYS)
    rows.append(row)

def core_rows(rows, source_rows, selection_map=None):
    selection_map=selection_map or {}
    for r in source_rows if isinstance(source_rows,list) else []:
        sport=str(r.get("sport") or "").lower()
        if sport not in {"football","tennis","basketball"}:continue
        x=dict(r)
        x["source_engine"]="core_prediction_engine"
        x["projection_tier"]="deep_model"
        x["evidence_depth"]="published_model_plus_enrichment"
        x["paper_only"]=True
        x=apply_bookmaker_fields(x)
        key=(str(x.get("event_id") or ""),str(x.get("pick") or ""))
        selected=selection_map.get(key) or selection_map.get((str(x.get("event_id") or ""), ""))
        if isinstance(selected,dict):
            x["candidate_status"]=selected.get("candidate_status","BETTING_QUALIFIED_PAPER")
            x["qualification_status"]="BETTING_QUALIFIED_PAPER"
            x["live_eligible"]=False
            x["qualification_basis"]=selected.get("qualification_basis")
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
        x=apply_bookmaker_fields(x)
        add(rows,x)

def load_virtual_history():
    history=load("virtual_lab_history.json",[])
    return [r for r in history if isinstance(r,dict) and r.get("market")=="ou" and r.get("win") is not None]

def build_virtual_events(history, lifecycle, eligibility):
    """Forward Virtual/eFootball projections using the same base qualification policy
    as the Virtual Lab, without waiting for participant enhancement to pass.
    """
    live=load("virtual_lab_live.json",{})
    events=live.get("events") if isinstance(live,dict) else []

    # The Virtual/eFootball desk is active around the clock. Do not make the
    # upcoming board wait for the separate 5-minute sync artifact when that
    # artifact is stale or has temporarily lost eFootball rows. Refresh the same
    # public SportyBet virtual connector in-process as a bounded fallback.
    live_refresh_meta={"attempted":False,"refreshed":False,"reason":"fresh_artifact"}
    try:
        live_updated=dt(live.get("updated_at")) if isinstance(live,dict) else None
        product_counts=live.get("product_counts") if isinstance(live,dict) else {}
        needs_refresh=(live_updated is None or live_updated < NOW-timedelta(minutes=7)
                       or int((product_counts or {}).get("efootball_gt") or 0)==0)
        if needs_refresh:
            from virtual_lab_sync import collect_proxy, collect_direct, compact
            live_refresh_meta={"attempted":True,"refreshed":False,"reason":"stale_or_missing_efootball"}
            try:
                raw,source=collect_proxy()
            except Exception:
                raw,source=collect_direct()
            refreshed=[]
            for item in raw:
                row=compact(item)
                if row and row.get("event_id") and row.get("product") in {"efootball_gt","efootball_adriatic","vfootball","zoom","other"}:
                    refreshed.append(row)
            if refreshed:
                refreshed.sort(key=lambda x:(x.get("start_time") or "",x.get("product") or "",x.get("event_id") or ""))
                events=refreshed
                counts={}
                for row in refreshed:
                    p=str(row.get("product") or "")
                    counts[p]=counts.get(p,0)+1
                live={"status":"LIVE","source":[source],"events_count":len(refreshed),"product_counts":counts,"events":refreshed,"updated_at":NOW.isoformat()}
                live_refresh_meta={"attempted":True,"refreshed":True,"reason":"stale_or_missing_efootball","events":len(refreshed),"product_counts":counts}
    except Exception as exc:
        live_refresh_meta={"attempted":True,"refreshed":False,"reason":"refresh_failed","error":str(exc)}
    eligibility=eligibility if isinstance(eligibility,dict) else {}
    lifecycle_profiles={}
    if isinstance(lifecycle,dict):
        for p in lifecycle.get("profiles") or []:
            if isinstance(p,dict) and p.get("participant_key"):
                lifecycle_profiles[str(p.get("participant_key"))]=p

    product_model_comp={
        str(k):{str(x).casefold() for x in (v or [])}
        for k,v in (eligibility.get("model_qualified_competitions_by_product") or {}).items()
    }
    product_model_line={
        str(k):{float(x) for x in (v or [])}
        for k,v in (eligibility.get("model_qualified_ou_lines_by_product") or {}).items()
    }
    product_active_comp={
        str(k):{str(x).casefold() for x in (v or [])}
        for k,v in (eligibility.get("eligible_competitions_by_product") or {}).items()
    }
    product_active_line={
        str(k):{float(x) for x in (v or [])}
        for k,v in (eligibility.get("eligible_ou_lines_by_product") or {}).items()
    }

    eval_art=load("virtual_lab_model_eval.json",{})
    h=eval_art.get("holdout_metrics") or {}
    market=h.get("market") or {}
    variants=["efootball_shape","poisson_prior","poisson"]
    viable=[h.get(name) for name in variants if isinstance(h.get(name),dict) and int(h.get(name,{}).get("n") or 0)>=30]
    best=min(viable,key=lambda m:(float(m.get("brier",9)),float(m.get("log_loss",9))) if m else (9,9)) if viable else None
    base_model_gate=bool(best and market and
        float(best.get("brier",9))<float(market.get("brier",0)) and
        float(best.get("log_loss",9))<float(market.get("log_loss",0)) and
        float(best.get("ece",9))<=float(market.get("ece",9))+.02)
    participant_gate=bool((eval_art.get("participant_feature_gate") or {}).get("pass"))

    # Validated product-bootstrap lane for new eFootball competition names.
    # This preserves the existing model/line/odds/edge gates while removing the
    # brittle requirement that every newly appearing competition already have
    # its own promoted-history record.
    product_bootstrap_gate={}
    for product,metrics in (eval_art.get("by_product") or {}).items():
        if not str(product).startswith("efootball_") or not isinstance(metrics,dict):
            continue
        market_m=metrics.get("market") or {}
        viable_m=[]
        for variant_name in ("poisson","poisson_prior","efootball_shape"):
            m=metrics.get(variant_name)
            if not isinstance(m,dict): continue
            if int(m.get("n") or 0)<300: continue
            if float(m.get("brier",9))>=float(market_m.get("brier",0)): continue
            if float(m.get("log_loss",9))>=float(market_m.get("log_loss",0)): continue
            if float(m.get("ece",9))>float(market_m.get("ece",9))+.02: continue
            viable_m.append(variant_name)
        product_bootstrap_gate[str(product)]=bool(viable_m)

    # Fit one stable lambda per product from the latest settled history.
    # Never recompute the grid separately for every fixture/market.
    product_points={}
    product_lambdas={}
    for r in history or []:
        if not isinstance(r,dict) or r.get("market")!="ou" or r.get("win") is None:
            continue
        product=str(r.get("product") or "")
        try:
            line_value=float(r.get("line"))
            prob_value=float(r.get("model_prob"))
        except (TypeError,ValueError):
            continue
        if not product:
            continue
        selected_prob=prob_value if str(r.get("selection") or "").upper().startswith("O") else 1-prob_value
        product_points.setdefault(product,[]).append((line_value,selected_prob))
    for product,points in product_points.items():
        if not points:
            continue
        best_lam=(2.5,float("inf"))
        for i in range(25,1201,5):
            candidate=i/100
            err=0.0
            for ln,prob in points:
                k=max(0,math.floor(float(ln)))
                pmf=math.exp(-candidate)
                cdf=pmf
                for j in range(1,k+1):
                    pmf*=candidate/j
                    cdf+=pmf
                pred=clamp(1-cdf)
                err+=(pred-float(prob))**2
            err/=len(points)
            if err<best_lam[1]:
                best_lam=(candidate,err)
        product_lambdas[product]=best_lam[0]

    out=[]
    for e in events if isinstance(events,list) else []:
        start=dt(e.get("start_time"))
        if not start or start<NOW-timedelta(minutes=30) or start>HORIZON:
            continue
        product=str(e.get("product") or "")
        if product not in {"efootball_gt","vfootball"}:
            # efootball_adriatic/zoom remain preserved in the research collector
            # but are retired from forward prediction generation until they earn
            # settled walk-forward evidence.
            continue
        competition=str(e.get("competition") or e.get("tournament") or "Virtual")
        home=str(e.get("participant_1") or e.get("team_1") or e.get("home") or "")
        away=str(e.get("participant_2") or e.get("team_2") or e.get("away") or "")
        p1_profile=lifecycle_profiles.get(f"{product}|{home.strip().casefold()}") if home else None
        p2_profile=lifecycle_profiles.get(f"{product}|{away.strip().casefold()}") if away else None
        participant_history=max(int((p1_profile or {}).get("settled_matches") or 0),int((p2_profile or {}).get("settled_matches") or 0))
        participant_hot=any((p or {}).get("monitor_grade")=="HOT_WATCH" for p in (p1_profile,p2_profile) if isinstance(p,dict))
        participant_status="PARTICIPANT_HOT_WATCH" if participant_hot else ("PARTICIPANT_TRACKED" if participant_history>=3 else "PARTICIPANT_NEW")
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
                        line=num(spec.split(key,1)[1].split("&",1)[0]); break
            if line is None:
                continue

            # De-vig current O/U probabilities from the actual SportyBet market.
            outcomes=market.get("outcomes") or []
            over_odds=next((num(o.get("odds")) for o in outcomes if str(o.get("name") or "").lower().startswith("over") and num(o.get("odds")) and num(o.get("odds"))>1),None)
            under_odds=next((num(o.get("odds")) for o in outcomes if str(o.get("name") or "").lower().startswith("under") and num(o.get("odds")) and num(o.get("odds"))>1),None)
            market_over=market_under=None
            if over_odds and under_odds:
                inv_over,inv_under=1/over_odds,1/under_odds
                total_inv=inv_over+inv_under
                market_over=inv_over/total_inv
                market_under=inv_under/total_inv

            # Same product-wide Poisson baseline used by the Virtual Lab evaluator.
            lam=float(product_lambdas.get(product,2.5))
            k=max(0,math.floor(line))
            pmf=math.exp(-lam); cdf=pmf
            for i in range(1,k+1):
                pmf*=lam/i; cdf+=pmf
            over=clamp(1-cdf)
            under=clamp(1-over)

            # Base model probability; participant enhancement is reported separately
            # and never required for the base qualification gate.
            model_prob=over
            if market_over is not None and market_under is not None:
                chosen_pick="over" if over>=under else "under"
                chosen_model=model_prob if chosen_pick=="over" else under
                chosen_market=market_over if chosen_pick=="over" else market_under
                edge=chosen_model-chosen_market
            else:
                chosen_pick="over" if over>=under else "under"
                chosen_model=model_prob if chosen_pick=="over" else under
                chosen_market=None
                edge=None

            comp_key=competition.casefold()
            active_comp=comp_key in product_active_comp.get(product,set())
            active_line=float(line) in product_active_line.get(product,set())
            model_comp=comp_key in product_model_comp.get(product,set())
            model_line=float(line) in product_model_line.get(product,set())

            if product.startswith("efootball"):
                if not base_model_gate:
                    qualification_status="BASE_MODEL_GATE_PENDING"
                elif not model_line:
                    qualification_status="MODEL_LINE_SCOPE_GATE_PENDING"
                elif edge is None:
                    qualification_status="MARKET_EDGE_PENDING"
                elif edge<0.02:
                    qualification_status="EDGE_BELOW_2PCT"
                elif chosen_model<0.65:
                    qualification_status="MODEL_PROBABILITY_BELOW_0_65"
                elif active_comp and model_comp:
                    qualification_status="BETTING_QUALIFIED_PAPER"
                elif product_bootstrap_gate.get(product,False):
                    qualification_status="BETTING_QUALIFIED_PAPER_BOOTSTRAP"
                elif not active_comp:
                    qualification_status="RAW_COMPETITION_GATE_PENDING"
                else:
                    qualification_status="MODEL_SCOPE_GATE_PENDING"
            else:
                qualification_status="RESEARCH_PROJECTION"

            qualified=qualification_status in {"BETTING_QUALIFIED_PAPER","BETTING_QUALIFIED_PAPER_BOOTSTRAP"}
            add(out,{
                "sport":"virtual",
                "product":product,
                "league":competition,
                "event_id":str(e.get("event_id") or ""),
                "start_time":start.isoformat(),
                "player_1":home,
                "player_2":away,
                "market":"over_under",
                "line":line,
                "pick":chosen_pick,
                "probability":round(chosen_model,4),
                "probabilities":{"over":round(over,4),"under":round(under,4)},
                "market_reference_probability":round(chosen_market,4) if chosen_market is not None else None,
                "model_edge_vs_market":round(edge,4) if edge is not None else None,
                "model_fair_odds":round(1/chosen_model,3) if chosen_model else None,
                "bookmaker_odds":(over_odds if chosen_pick=="over" else under_odds) if (over_odds or under_odds) else None,
                "sportybet_odds":(over_odds if chosen_pick=="over" else under_odds) if (over_odds or under_odds) else None,
                "sportybet_over_odds":over_odds,
                "sportybet_under_odds":under_odds,
                "bookmaker_available":bool(over_odds and under_odds),
                "bookmaker_source":"SportyBet NG" if (over_odds or under_odds) else None,
                "market_odds_timestamp":e.get("timestamp") or e.get("captured_at") or live.get("updated_at"),
                "prediction_status":"betting_qualified_paper" if qualified else "research_projection",
                "projection_tier":"deep_research_projection",
                "evidence_depth":"participant_lifecycle_plus_base_model" if participant_history>=3 else "feed_discovered_base_model",
                "participant_status":participant_status,
                "participant_history_rows":participant_history,
                "participant_hot_watch":participant_hot,
                "participant_enhancement_gate":participant_gate,
                "product_bootstrap_gate":product_bootstrap_gate.get(product,False),
                "base_model_gate":base_model_gate,
                "raw_competition_eligible":active_comp,
                "raw_line_eligible":active_line,
                "model_competition_qualified":model_comp,
                "model_line_qualified":model_line,
                "qualification_status":qualification_status,
                "betting_qualified":qualified,
                "qualified_for_builder":qualified,
                "qualification_engine":"Virtual Lab base walk-forward gate + qualified line + current SportyBet edge + competition evidence OR validated product-bootstrap evidence",
                "model":"Virtual Lab base O/U model",
                "model_version":"VL-BOARD-2.0",
                "paper_only":True,
                "identity_verified":bool(home and away),
            })
    return out, {"status":"base_model_policy_parity","historical_events":len(history or []),"base_model_gate":base_model_gate,"participant_enhancement_gate":participant_gate,"live_refresh":live_refresh_meta}

def main():
    rows=[]
    lifecycle=load("virtual_lab_participant_lifecycle.json",{})
    core_source=load("predictions.json",[])
    selected_rows=load("selection_candidates.json",[])
    selection_map={}
    for s in selected_rows if isinstance(selected_rows,list) else []:
        selection_map[(str(s.get("event_id") or ""),str(s.get("pick") or ""))]=s
        selection_map.setdefault((str(s.get("event_id") or "")),s)
    core_rows(rows,core_source,selection_map)

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
    # Darts-X and Table Tennis-X are retired from the active desk. Their
    # historical artifacts remain preserved, but no new rows enter Upcoming.
    core_rows(rows,load("basketball_predictions.json",[]),selection_map)
    virtual, virtual_meta=build_virtual_events(load_virtual_history(), lifecycle, load("virtual_lab_eligibility.json",{}))
    rows.extend(virtual)

    # Fallback/augmentation: some expansion artifacts are generated separately
    # from the core feed. Merge them without duplicating event IDs.
    for name in ("ere_divisie_predictions.json",):
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
    retired_sports={"darts","table_tennis","basketball"}
    retired_leagues={"EPL","MLS","Primeira Liga","Serie A","Saudi Pro League","WTA"}
    final=[r for r in by_id.values()
           if str(r.get("sport") or "").lower() not in retired_sports
           and str(r.get("league") or "") not in retired_leagues]
    final=sorted(final,key=lambda x:(str(x.get("start_time") or ""),str(x.get("sport") or "")))
    dates=defaultdict(int);sports=defaultdict(int)
    for r in final:
        dates[str(r.get("start_time") or "")[:10]]+=1
        sports[str(r.get("sport") or "unknown")]+=1
    pending_settlement=sum(1 for r in final if r.get("event_state")=="PENDING_SETTLEMENT")
    live_count=sum(1 for r in final if r.get("event_state")=="LIVE")
    result={
        "generated_at":NOW.isoformat(),
        "horizon_days":7,
        "mode":"PAPER_ONLY",
        "policy":{
            "visibility":"Every current future fixture with a readable source/model path is visible; terminal/settled fixtures are removed from this board.",
            "confidence":"Evidence depth changes confidence/status; it does not erase the fixture.",
            "settlement":"Completed events disappear from Upcoming through the settlement/result ledgers; their outcomes remain in permanent history and feed the next model/lifecycle cycle.",
            "ranking":"Deep model > deep research projection > research model > testing projection.",
            "market_rule":"Market prices are reference/enrichment data, never displayed as independent model probabilities.",
            "real_money":False,
        },
        "summary":{"events":len(final),"sports":dict(sorted(sports.items())),"dates":dict(sorted(dates.items())),"live":live_count,"pending_settlement":pending_settlement,"settled_hidden":len(SETTLED_EVENT_IDS),"virtual_model":virtual_meta,"live_core_refresh":live_meta},
        "events":final,
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],indent=2))

if __name__=="__main__":
    main()
