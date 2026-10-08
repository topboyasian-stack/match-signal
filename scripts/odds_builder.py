"""Match Signal V6 market-calibrated value engine.

# 2026-10-02: force post-gate Builder regeneration for production verification.
# 2026-10-04: force a fresh market snapshot after booking-code volatility verification.

Research/paper-trading only. A candidate is eligible only when:
- calibrated model probability clears the minimum threshold,
- a fresh SportyBet price is actually present,
- bookmaker margin is removed where a complete market is available,
- model edge clears the V6 threshold,
- data/price freshness and uncertainty gates pass,
- correlated selections are not duplicated in the same accumulator.

No wager is placed and no leg count is forced; the adaptive construction range is 2–4 legs.
"""
from __future__ import annotations
import json, math, urllib.parse, urllib.request
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
MIN_LEGS,MAX_LEGS=2,4
# Active accuracy-first policy: 2.70x is the current floor; 2.80x is preferred until earned.
# Leg count remains adaptive from 2–4, but no weak leg is added just to reach the odds target.
TARGET_COMBINED_ODDS=2.80
STRETCH_COMBINED_ODDS=4.0
MIN_ACCURACY_FIRST_ODDS=2.70
ACCURACY_PRESERVATION_RATIO=0.90
BATCH_MIN_LEGS=2
# Adaptive 2–4 leg construction safety tiers.
# 90%+ per-leg model probability is preferred; 80% is the safety floor for every
# included leg regardless of whether the ticket has 2, 3, or 4 legs.
LEG_COUNT_MIN_MODEL_PROBABILITY={2:0.80,3:0.80,4:0.80}
MIN_SAFE_LEG_MODEL_PROBABILITY=0.80
PREFERRED_LEG_MODEL_PROBABILITY=0.90
HIGH_ODDS_TARGET=2.80
HIGH_ODDS_HARD_GATE_WIN_RECORDS=10
# Results-first Builder: 2.70 minimum combined odds is the active eligibility floor.
# The 2.80 target remains preferred until the 2–4-leg family earns 10 settled wins.
RESULTS_FIRST_ENABLED=True
RESULTS_FIRST_MAX_LEGS=4
RESULTS_FIRST_MIN_OBS=50
RESULTS_FIRST_MIN_ACCURACY=0.90
RESULTS_FIRST_MIN_COMBINED_ODDS=2.70
# Existing Results-first expected-ROI floor used by construction diagnostics and QA.
RESULTS_FIRST_MIN_EXPECTED_ROI=0.02
# Construction-specific ticket diagnostics cover the active 2–4-leg family.
# A shape still needs its own settled evidence when the Results-first lane is promoted.
RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS=(2,3,4)
RESULTS_FIRST_CONSTRUCTION_LEG_COUNT=2
RESULTS_FIRST_MIN_CONSTRUCTION_TICKETS=10
RESULTS_FIRST_MAX_CONSTRUCTION_LOSS_RATE=0.50
MIN_COMBINED_ODDS=2.70
VIRTUAL_MIN_PROB=0.65
# eFootball exact-line/side spoiler guard: older wins must not mask a fresh collapse.
# These are construction-eligibility safeguards, not model-probability overrides.
EFOOTBALL_RECENT_SPOILER_MIN_OBS=12
EFOOTBALL_RECENT_SPOILER_LAST10_MIN_HIT=0.50
EFOOTBALL_RECENT_SPOILER_LAST20_MIN_OBS=20
EFOOTBALL_RECENT_SPOILER_LAST20_MIN_HIT=0.55
EFOOTBALL_RECENT_SPOILER_MAX_CONSECUTIVE_LOSSES=4
TICKET_SPOILER_MIN_SAMPLE=50
TICKET_SPOILER_MIN_ACCURACY=0.90
PARTICIPANT_HISTORY_MIN_N=3
PARTICIPANT_HISTORY_MAX_BONUS=0.035
MAX_BATCHES=6
# Keep Builder candidates close to kickoff so participant evidence and market prices can be refreshed.
MAX_BUILDER_HORIZON_MINUTES=720
MAX_BATCH_KICKOFF_SPAN_MINUTES=60
MODEL_FIRST_MAX_KICKOFF_SPAN_MINUTES=270
# Controlled research-only fallback: allow strong exact-value legs just below
# the 70% average frontier while retaining positive single-leg EV, live-price,
# freshness, correlation, and whole-ticket ROI gates.
MODEL_FIRST_MIN_AVG_PROBABILITY=0.68
# eFootball exact-line evidence is currently validated at a 65% directional
# threshold. Keep that lane evidence-based instead of requiring the unrelated
# 68% frontier used by the generic secondary value lane.
EFOOTBALL_VALUE_MIN_AVG_PROBABILITY=0.65
EFOOTBALL_VALUE_MIN_LEG_PROBABILITY=0.65
# Mixed research lane: preserve a small VFootball component only when its own
# exact-line/value gates pass, then combine it with one or two qualified
# eFootball value legs. This does not promote the batch to Results-first.
MIXED_RESEARCH_MAX_LEGS=4
MIXED_RESEARCH_MIN_AVG_PROBABILITY=0.80
MIXED_RESEARCH_MIN_VFOOTBALL_LEGS=1
MIXED_RESEARCH_MIN_EFOOTBALL_LEGS=1
MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES=360

# Phase 2 isolated cyclical-loop research lane.
# This is deliberately separate from the baseline football/tennis/Poisson paths.
# It can only construct 2–3-leg Virtual/eFootball paper batches from legs that
# already pass the Builder's normal eligibility/evidence gates.
PHASE2_CYCLICAL_LOOP_ENABLED=True
PHASE2_CYCLICAL_MIN_CONFIDENCE=0.78
PHASE2_CYCLICAL_MAX_LEGS=3
PHASE2_CYCLICAL_MIN_LEGS=2
PHASE2_CYCLICAL_MIN_STREAK_LENGTH=2
PHASE2_CYCLICAL_MIN_BREAK_OBSERVATIONS=8
PHASE2_CYCLICAL_HIGH_VARIANCE_ODDS=4.0
# Bound the experimental combination search so Phase 2 cannot dominate Builder runtime.
PHASE2_CYCLICAL_POOL_CAP=40
_COMBINED_ODDS_GATE_CACHE=None

def combined_odds_gate_state():
    """Return the currently earned accuracy-first combined-odds floor for this Builder run."""
    global _COMBINED_ODDS_GATE_CACHE
    if _COMBINED_ODDS_GATE_CACHE is not None:
        return _COMBINED_ODDS_GATE_CACHE
    wins=0
    try:
        tracker_path=DATA/"odds_ticket_tracker.json"
        tracker=json.loads(tracker_path.read_text(encoding="utf-8"))
        tickets=tracker.get("tickets") if isinstance(tracker,dict) else []
        for ticket in tickets if isinstance(tickets,list) else []:
            if str(ticket.get("status") or "").upper() != "WON":
                continue
            try:
                leg_count=int(ticket.get("leg_count") or len(ticket.get("legs") or []))
                odds=float(ticket.get("combined_odds") or 0.0)
            except (TypeError,ValueError):
                continue
            if leg_count in RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS and odds >= TARGET_COMBINED_ODDS:
                wins+=1
    except Exception:
        wins=0
    hard_gate_active=wins >= HIGH_ODDS_HARD_GATE_WIN_RECORDS
    _COMBINED_ODDS_GATE_CACHE={
        "floor":TARGET_COMBINED_ODDS if hard_gate_active else MIN_ACCURACY_FIRST_ODDS,
        "preferred_target":HIGH_ODDS_TARGET,
        "stretch_target":STRETCH_COMBINED_ODDS,
        "hard_gate_active":hard_gate_active,
        "gate_mode":"earned_preferred_target",
        "settled_2_80_plus_wins":wins,
        "wins_required_for_2_80_hard_gate":HIGH_ODDS_HARD_GATE_WIN_RECORDS
    }
    return _COMBINED_ODDS_GATE_CACHE

def active_min_combined_odds():
    return float(combined_odds_gate_state()["floor"])


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):
        return default


def kickoff_age_minutes(x, now):
    try:
        raw=x.get("start_time")
        if not raw:return None
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(timezone.utc)
        return (dt-now).total_seconds()/60.0
    except (TypeError,ValueError):
        return None


def within_builder_horizon(x, now):
    minutes=kickoff_age_minutes(x,now)
    return minutes is not None and 0.0 < minutes <= MAX_BUILDER_HORIZON_MINUTES


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


def min_model_probability_for_leg_count(leg_count):
    try:
        count=int(leg_count)
    except (TypeError,ValueError):
        count=BATCH_MIN_LEGS
    return float(LEG_COUNT_MIN_MODEL_PROBABILITY.get(count,MIN_SAFE_LEG_MODEL_PROBABILITY))


def legs_meet_safe_model_threshold(legs):
    if not isinstance(legs,list) or len(legs)<BATCH_MIN_LEGS:
        return False
    required=min_model_probability_for_leg_count(len(legs))
    return all(float(x.get("model_probability") or 0.0)>=required for x in legs)


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
        stamp=x.get("odds_timestamp") or x.get("market_odds_timestamp")
        if not stamp:return None
        return max(0.0,(datetime.now(timezone.utc)-datetime.fromisoformat(str(stamp).replace("Z","+00:00"))).total_seconds())
    except (TypeError,ValueError):
        return None


def football_candidates(now):
    # Builder applies its own fresh market/value gates; candidate artifacts may be stale.
    raw=load(PREDICTIONS,[])
    out=[]
    if not isinstance(raw,list):return out
    for x in raw:
        if not isinstance(x,dict) or x.get("sport")!="football" or not within_builder_horizon(x,now):continue
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
        if not isinstance(x,dict) or x.get("sport")!="tennis" or not within_builder_horizon(x,now):continue
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


def _norm_fixture(v):
    import re
    s=str(v or "").lower().replace("vs"," ")
    return re.sub(r"[^a-z0-9]+"," ",s).strip()


def _live_participant_identity(value):
    import re
    s=str(value or "").strip()
    m=re.search(r"\\(([^()]*)\\)\\s*$",s)
    if m and m.group(1).strip(): s=m.group(1).strip()
    return re.sub(r"[^a-z0-9]+"," ",s.lower()).strip()


def _participant_pair_key(row):
    product=str(row.get("product") or "")
    vals=[]
    for key in ("participant_1","participant_2","player_1","player_2","team_1","team_2"):
        v=row.get(key)
        if v:
            ident=_live_participant_identity(v)
            if ident and ident not in vals: vals.append(ident)
    if len(vals)<2:
        return ""
    return product+"|"+"|".join(sorted(vals[:2]))

def _virtual_selection_side(row):
    """Resolve the exact O/U side from the normalized Builder candidate."""
    import re
    side=str(row.get("builder_pick") or "").strip().lower()
    if side in {"over","under"}:
        return side
    text=str(row.get("pick") or "").strip().lower()
    match=re.search(r"\b(over|under)\b",text)
    return match.group(1) if match else ""

def refresh_virtual_quotes(rows):
    """Join unified fixtures to the current read-only SportyBet snapshot.

    Event ID is preferred. When IDs differ between pipeline snapshots, fall
    back to exact normalized participant identity. Never join by market ID
    alone, because one event can expose several O/U ladders.
    """
    if not isinstance(rows,list) or not rows:
        return rows,{"live_events":0,"live_match_keys":0,"matched_by_id":0,"matched_by_match":0,"unmatched":0,"samples":[]}
    live_by_id={}
    live_by_match={}
    live_by_pair={}
    live_samples=[]
    fetched_at=datetime.now(timezone.utc).isoformat()
    # Use the same bounded collector as the Virtual Lab live pipeline so the
    # Builder refreshes the SportyBet catalogue immediately before qualification.
    # The collector covers multiple pages/sources and stamps every compacted row
    # with the current observation time. This prevents the Builder from trusting
    # an otherwise healthy but old Unified Upcoming artifact.
    try:
        from virtual_lab_sync import collect_proxy, collect_direct, compact
        try:
            raw_events, live_source = collect_proxy()
        except Exception as proxy_error:
            raw_events, live_source = collect_direct()
            live_source = live_source + "_fallback"
        for raw in raw_events if isinstance(raw_events,list) else []:
            event = compact(raw)
            if not isinstance(event,dict) or not event.get("event_id"):
                continue
            product = str(event.get("product") or "")
            if product not in {"efootball_gt","efootball_adriatic","vfootball","zoom","other"}:
                continue
            event["price_snapshot_source"]="fresh_live_sportybet_collector"
            event["market_odds_timestamp"]=event.get("timestamp") or fetched_at
            live_by_id[str(event["event_id"])]=event
            key=_norm_fixture(event.get("match") or event.get("name") or f"{event.get('participant_1') or event.get('team_1') or ''} vs {event.get('participant_2') or event.get('team_2') or ''}")
            if key: live_by_match[key]=event
            pair_key=_participant_pair_key(event)
            if pair_key: live_by_pair.setdefault(pair_key,[]).append(event)
            if len(live_samples)<3:
                live_samples.append({"event_id":event.get("event_id"),"match":event.get("match"),"participant_1":event.get("participant_1"),"participant_2":event.get("participant_2"),"source":live_source})
    except Exception as exc:
        # Keep the failure diagnosable. We intentionally do not reuse old prices
        # here; an unavailable refresh must fail closed rather than make a stale
        # quote look fresh.
        live_samples.append({"refresh_error":str(exc)[:240]})
    if not live_by_id and not live_by_match:
        # Fail closed: never carry an old Unified Upcoming price forward when the
        # immediate SportyBet refresh is unavailable.
        cleaned=[]
        stale_keys=("sportybet_over_odds","sportybet_under_odds","bookmaker_odds","sportybet_odds","bookmaker_available","bookmaker_source","sportybet_event_id","sportybet_match","market_odds_timestamp","sportybet_identity_match","price_snapshot_source")
        for original in rows:
            if not isinstance(original,dict):
                continue
            x=dict(original)
            for key in stale_keys:
                x.pop(key,None)
            cleaned.append(x)
        return cleaned,{"live_events":0,"live_match_keys":0,"live_pair_keys":0,"matched_by_id":0,"matched_by_match":0,"matched_by_participant_time":0,"unmatched":len(rows),"samples":live_samples,"source":"live_refresh_unavailable","market_samples":[]}
    out=[]
    join_diag={"live_events":len(live_by_id),"live_match_keys":len(live_by_match),"live_pair_keys":len(live_by_pair),"matched_by_id":0,"matched_by_match":0,"matched_by_participant_time":0,"unmatched":0,"samples":live_samples}
    for x in rows:
        y=dict(x)
        # Never carry a price from unified_upcoming into the Builder. A virtual
        # leg is priced only when this exact current SportyBet event AND exact
        # requested O/U line are found in the fresh proxy snapshot.
        for stale_key in ("sportybet_over_odds","sportybet_under_odds","bookmaker_available","bookmaker_source","sportybet_event_id","sportybet_match","market_odds_timestamp","sportybet_identity_match"):
            y.pop(stale_key,None)
        y["bookmaker_available"]=False
        key=_norm_fixture(x.get("match") or f"{x.get('player_1') or x.get('participant_1') or x.get('team_1') or ''} vs {x.get('player_2') or x.get('participant_2') or x.get('team_2') or ''}")
        e=live_by_id.get(str(x.get("event_id")))
        if isinstance(e,dict): join_diag["matched_by_id"]+=1
        else:
            e=live_by_match.get(key)
            if isinstance(e,dict): join_diag["matched_by_match"]+=1
            else:
                pair_key=_participant_pair_key(x)
                options=live_by_pair.get(pair_key,[])
                if options:
                    try:
                        target_dt=datetime.fromisoformat(str(x.get("start_time") or "").replace("Z","+00:00"))
                        target_ts=target_dt.timestamp()
                        ranked=[]
                        for opt in options:
                            raw_ms=opt.get("start_time_ms")
                            if raw_ms is None: continue
                            diff=abs(float(raw_ms)/1000.0-target_ts)
                            if diff<=1800: ranked.append((diff,opt))
                        if ranked:
                            ranked.sort(key=lambda z:z[0]); e=ranked[0][1]
                            join_diag["matched_by_participant_time"]+=1
                        else: e=None
                    except (TypeError,ValueError):
                        e=None
                if not isinstance(e,dict): join_diag["unmatched"]+=1
        if isinstance(e,dict):
            line=x.get("line")
            over=under=None
            for m in e.get("markets") or []:
                if not isinstance(m,dict): continue
                ml=m.get("line")
                try:
                    same_line=line is not None and ml is not None and abs(float(ml)-float(line))<1e-9
                except (TypeError,ValueError):
                    same_line=False
                if not same_line:
                    continue
                for o in m.get("outcomes") or []:
                    if not isinstance(o,dict): continue
                    name=str(o.get("name") or "").lower()
                    try: odds=float(o.get("odds"))
                    except (TypeError,ValueError): continue
                    if odds<=1: continue
                    if name.startswith("over"): over=odds
                    elif name.startswith("under"): under=odds
                if over is not None or under is not None:
                    break
            if over is not None: y["sportybet_over_odds"]=over
            if under is not None: y["sportybet_under_odds"]=under
            if over is not None or under is not None:
                y["bookmaker_available"]=bool(over and under)
                y["bookmaker_source"]="SportyBet NG"
                y["sportybet_event_id"]=str(e.get("event_id"))
                y["sportybet_match"]=e.get("match") or e.get("name")
                y["market_odds_timestamp"]=fetched_at
                y["sportybet_identity_match"]=str(e.get("event_id"))==str(x.get("event_id")) or _norm_fixture(e.get("match") or e.get("name"))==key
                # Preserve the exact current SportyBet O/U market and BOTH side-specific
                # outcome IDs. The same numeric IDs are reused on every line, but the
                # side is semantic: Over=12, Under=13 in the normalized live feed.
                requested_side=_virtual_selection_side(x)
                y.pop("sportybet_market_id",None)
                y.pop("sportybet_specifier",None)
                y.pop("sportybet_outcome_id",None)
                y.pop("sportybet_outcome_name",None)
                y.pop("sportybet_over_outcome_id",None)
                y.pop("sportybet_over_outcome_name",None)
                y.pop("sportybet_under_outcome_id",None)
                y.pop("sportybet_under_outcome_name",None)
                y["sportybet_selection_side"]=requested_side or None
                for m in e.get("markets") or []:
                    if not isinstance(m,dict):
                        continue
                    try:
                        same_line=line is not None and m.get("line") is not None and abs(float(m.get("line"))-float(line))<1e-9
                    except (TypeError,ValueError):
                        same_line=False
                    if not same_line:
                        continue
                    y["sportybet_market_id"]=str(m.get("id") or "")
                    y["sportybet_specifier"]=m.get("specifier")
                    for o in m.get("outcomes") or []:
                        if not isinstance(o,dict):
                            continue
                        name=str(o.get("name") or o.get("desc") or "").strip()
                        lower=name.lower()
                        if lower.startswith("over"):
                            y["sportybet_over_outcome_id"]=str(o.get("id") or "")
                            y["sportybet_over_outcome_name"]=name
                        elif lower.startswith("under"):
                            y["sportybet_under_outcome_id"]=str(o.get("id") or "")
                            y["sportybet_under_outcome_name"]=name
                    if requested_side=="over" and y.get("sportybet_over_outcome_id"):
                        y["sportybet_outcome_id"]=y["sportybet_over_outcome_id"]
                        y["sportybet_outcome_name"]=y.get("sportybet_over_outcome_name")
                    elif requested_side=="under" and y.get("sportybet_under_outcome_id"):
                        y["sportybet_outcome_id"]=y["sportybet_under_outcome_id"]
                        y["sportybet_outcome_name"]=y.get("sportybet_under_outcome_name")
                    break
            out.append(y)
    return out,join_diag

_TICKET_SPOILER_CACHE=None

def _load_ticket_performance_index():
    """Index settled Builder-ticket outcomes by exact product/line/side.

    This is a construction-only safeguard. It never substitutes for the
    Virtual Lab evidence gate and only activates after a meaningful sample.
    """
    global _TICKET_SPOILER_CACHE
    if _TICKET_SPOILER_CACHE is not None:
        return _TICKET_SPOILER_CACHE
    raw=load(DATA/"odds_ticket_tracker.json",{})
    index={}
    tickets=raw.get("tickets") if isinstance(raw,dict) else []
    for ticket in tickets if isinstance(tickets,list) else []:
        if str(ticket.get("status") or "") not in {"WON","LOST"}:
            continue
        for leg in ticket.get("legs") or []:
            if not isinstance(leg,dict) or str(leg.get("status") or "") not in {"WON","LOST"}:
                continue
            product=str(leg.get("product") or "")
            pick_text=str(leg.get("pick") or "")
            lower=pick_text.lower()
            side="under" if "under" in lower else "over" if "over" in lower else None
            if not product or not side:
                continue
            line=leg.get("line")
            if line is None:
                import re
                match=re.search(r"(?:over|under)\s+(\d+(?:\.\d+)?)\s*$",lower)
                if match:
                    line=match.group(1)
            try:
                line_key=f"{float(line):g}"
            except (TypeError,ValueError):
                continue
            key=(product,line_key,side)
            row=index.setdefault(key,{"n":0,"wins":0,"losses":0})
            row["n"]+=1
            if leg.get("status")=="WON":
                row["wins"]+=1
            else:
                row["losses"]+=1
    _TICKET_SPOILER_CACHE=index
    return index

def ticket_performance_gate(product,line,pick):
    try:
        key=(str(product or ""),f"{float(line):g}",str(pick or "").lower())
    except (TypeError,ValueError):
        return True,{"available":False,"reason":"invalid_key"}
    row=_load_ticket_performance_index().get(key)
    if not row or row.get("n",0)<TICKET_SPOILER_MIN_SAMPLE:
        return True,{"available":False,"n":row.get("n",0) if row else 0,"min_n":TICKET_SPOILER_MIN_SAMPLE}
    n=int(row["n"])
    wins=int(row["wins"])
    accuracy=wins/n if n else 0.0
    details={
        "available":True,
        "n":n,
        "wins":wins,
        "losses":int(row["losses"]),
        "accuracy":round(accuracy,4),
        "min_accuracy":TICKET_SPOILER_MIN_ACCURACY,
        "source":"data/odds_ticket_tracker.json",
        "role":"construction_only",
    }
    return accuracy>=TICKET_SPOILER_MIN_ACCURACY,details

_RESULTS_FIRST_CACHE=None

def _load_results_first_index():
    """Index actual settled ticket/leg results for results-first qualification."""
    global _RESULTS_FIRST_CACHE
    if _RESULTS_FIRST_CACHE is not None:
        return _RESULTS_FIRST_CACHE
    raw=load(DATA/"odds_ticket_tracker.json",{})
    exact={}
    product_tickets={}
    construction_tickets={}
    tickets=raw.get("tickets") if isinstance(raw,dict) else []
    import re
    for ticket in tickets if isinstance(tickets,list) else []:
        tstatus=str(ticket.get("status") or "")
        if tstatus not in {"WON","LOST"}:
            continue

        legs=ticket.get("legs") or []
        try:
            structure_legs=int(ticket.get("leg_count") or len(legs))
        except (TypeError,ValueError):
            structure_legs=len(legs)

        # Count each product once per settled ticket. These broad product stats
        # remain useful diagnostics, but they do not decide the current 2-leg lane.
        product_names={str(product or "") for product in (ticket.get("products") or []) if product}
        product_names.update(
            str(leg.get("product") or leg.get("sport") or "")
            for leg in legs if isinstance(leg,dict) and (leg.get("product") or leg.get("sport"))
        )
        for product in product_names:
            row=product_tickets.setdefault(product,{"tickets":0,"wins":0,"losses":0})
            row["tickets"]+=1
            row["wins"]+=1 if tstatus=="WON" else 0
            row["losses"]+=1 if tstatus=="LOST" else 0

            ckey=(product,structure_legs)
            crow=construction_tickets.setdefault(
                ckey,{"tickets":0,"wins":0,"losses":0,"odds_sum":0.0,"odds_count":0}
            )
            crow["tickets"]+=1
            crow["wins"]+=1 if tstatus=="WON" else 0
            crow["losses"]+=1 if tstatus=="LOST" else 0
            try:
                combined_odds=float(ticket.get("combined_odds"))
                if combined_odds>1.0:
                    crow["odds_sum"]+=combined_odds
                    crow["odds_count"]+=1
            except (TypeError,ValueError):
                pass

        for leg in legs:
            if not isinstance(leg,dict) or str(leg.get("status") or "") not in {"WON","LOST"}:
                continue
            product=str(leg.get("product") or leg.get("sport") or "")
            pick_text=str(leg.get("pick") or "").lower()
            side="under" if "under" in pick_text else "over" if "over" in pick_text else None
            if not product or not side:
                continue
            line=leg.get("line")
            if line is None:
                m=re.search(r"\b(?:over|under)\s+(\d+(?:\.\d+)?)\b",pick_text)
                if m:
                    line=m.group(1)
            try:
                line_key=f"{float(line):g}"
            except (TypeError,ValueError):
                continue
            key=(product,line_key,side)
            row=exact.setdefault(key,{"n":0,"wins":0,"losses":0})
            row["n"]+=1
            row["wins"]+=1 if str(leg.get("status"))=="WON" else 0
            row["losses"]+=1 if str(leg.get("status"))=="LOST" else 0
    _RESULTS_FIRST_CACHE={
        "exact":exact,
        "product_tickets":product_tickets,
        "construction_tickets":construction_tickets,
    }
    return _RESULTS_FIRST_CACHE

def construction_shape_diagnostics(product, idx=None):
    """Evaluate 2–4-leg ticket shapes independently from settled tickets."""
    if idx is None:
        idx=_load_results_first_index()
    product=str(product or "")
    rows=[]
    for leg_count in RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS:
        row=idx["construction_tickets"].get(
            (product,leg_count),
            {"tickets":0,"wins":0,"losses":0,"odds_sum":0.0,"odds_count":0}
        )
        n=int(row.get("tickets") or 0)
        wins=int(row.get("wins") or 0)
        losses=int(row.get("losses") or 0)
        accuracy=(wins/n) if n else None
        loss_rate=(losses/n) if n else None
        odds_count=int(row.get("odds_count") or 0)
        avg_odds=(float(row.get("odds_sum") or 0.0)/odds_count) if odds_count else None
        expected_roi=(accuracy*avg_odds-1.0) if accuracy is not None and avg_odds else None
        qualifies=(
            n >= RESULTS_FIRST_MIN_CONSTRUCTION_TICKETS
            and loss_rate is not None
            and loss_rate <= RESULTS_FIRST_MAX_CONSTRUCTION_LOSS_RATE
            and avg_odds is not None
            and avg_odds >= active_min_combined_odds()
            and expected_roi is not None
            and expected_roi >= RESULTS_FIRST_MIN_EXPECTED_ROI
        )
        rows.append({
            "leg_count":leg_count,
            "ticket_n":n,
            "ticket_wins":wins,
            "ticket_losses":losses,
            "ticket_accuracy":round(accuracy,4) if accuracy is not None else None,
            "loss_rate":round(loss_rate,4) if loss_rate is not None else None,
            "avg_combined_odds":round(avg_odds,4) if avg_odds is not None else None,
            "break_even_accuracy":round(1.0/avg_odds,4) if avg_odds else None,
            "empirical_expected_roi":round(expected_roi,6) if expected_roi is not None else None,
            "min_ticket_n":RESULTS_FIRST_MIN_CONSTRUCTION_TICKETS,
            "min_combined_odds":active_min_combined_odds(),
            "min_expected_roi":RESULTS_FIRST_MIN_EXPECTED_ROI,
            "qualifies":bool(qualifies),
        })
    return rows

def results_first_gate(product,line,pick):
    """Require demonstrated settled results and an independently proven 2–4-leg shape."""
    idx=_load_results_first_index()
    product=str(product or "")
    side=str(pick or "").lower()
    try:
        line_key=f"{float(line):g}"
    except (TypeError,ValueError):
        return False,{"eligible":False,"reason":"invalid_line"}

    exact=idx["exact"].get((product,line_key,side))
    ticket_row=idx["product_tickets"].get(product,{"tickets":0,"wins":0,"losses":0})
    ticket_n=int(ticket_row.get("tickets") or 0)
    ticket_w=int(ticket_row.get("wins") or 0)
    ticket_rate=(ticket_w/ticket_n) if ticket_n else None

    shape_rows=construction_shape_diagnostics(product,idx)
    viable_shapes=[row for row in shape_rows if row.get("qualifies")]
    # The frozen 2026-10-03 benchmark demonstrated a strong untouched VFootball
    # event-level holdout (82.12% participant model / 81.73% Poisson across 3,295
    # O/U rows) while the historical ticket ledger is only 43 tickets and mixes
    # older construction rules. Do not let that small, heterogeneous ticket
    # ledger permanently suppress a stronger event-evidence lane. Construction
    # still has to pass the live whole-ticket calibrated probability/odds gates.
    if not viable_shapes and product=="vfootball":
        return True,{
            "eligible":True,
            "reason":"vfootball_event_holdout_lane",
            "product":product,
            "construction_shapes":shape_rows,
            "construction_leg_count":None,
            "all_product_ticket_n":ticket_n,
            "all_product_ticket_accuracy":round(ticket_rate or 0.0,4) if ticket_rate is not None else None,
            "event_holdout_reference":{"rows":3295,"poisson_accuracy":0.8173,"participant_accuracy":0.8212},
            "ticket_ledger_role":"diagnostic_only_until_2_to_4_leg_family_has_adequate_sample",
            "source":"MATCH_SIGNAL_BENCHMARK.md",
            "qualification_lane":"vfootball_event_holdout_value"
        }
    if not viable_shapes:
        return False,{
            "eligible":False,
            "reason":"no_profitable_construction_shape",
            "product":product,
            "construction_shapes":shape_rows,
            "construction_leg_count":None,
            "all_product_ticket_n":ticket_n,
            "all_product_ticket_accuracy":round(ticket_rate or 0.0,4) if ticket_rate is not None else None,
        }

    selected_shape=max(
        viable_shapes,
        key=lambda row:(
            float(row.get("empirical_expected_roi") or -999.0),
            float(row.get("ticket_accuracy") or -999.0),
            int(row.get("ticket_n") or 0),
            -int(row.get("leg_count") or 99),
        )
    )
    construction_n=int(selected_shape.get("ticket_n") or 0)
    construction_w=int(selected_shape.get("ticket_wins") or 0)
    avg_construction_odds=selected_shape.get("avg_combined_odds")
    empirical_roi=selected_shape.get("empirical_expected_roi")

    if product!="vfootball":
        return False,{"eligible":False,"reason":"no_results_first_lane","product":product,"construction_shapes":shape_rows}

    if not exact:
        return False,{"eligible":False,"reason":"no_settled_exact_line_side_results",
                       "key":[product,line_key,side],"construction_shapes":shape_rows,
                       "construction_leg_count":selected_shape["leg_count"]}

    n=int(exact.get("n") or 0)
    wins=int(exact.get("wins") or 0)
    accuracy=wins/n if n else 0.0
    if n < RESULTS_FIRST_MIN_OBS:
        return False,{"eligible":False,"reason":"insufficient_settled_exact_line_side_results",
                       "n":n,"wins":wins,"min_n":RESULTS_FIRST_MIN_OBS,"key":[product,line_key,side],
                       "construction_shapes":shape_rows,"construction_leg_count":selected_shape["leg_count"]}
    if accuracy < RESULTS_FIRST_MIN_ACCURACY:
        return False,{"eligible":False,"reason":"settled_exact_line_side_accuracy_below_results_floor",
                       "n":n,"wins":wins,"losses":int(exact.get("losses") or 0),
                       "accuracy":round(accuracy,4),"min_accuracy":RESULTS_FIRST_MIN_ACCURACY,
                       "key":[product,line_key,side],"construction_shapes":shape_rows,
                       "construction_leg_count":selected_shape["leg_count"]}

    posterior=(wins+2.0)/(n+4.0)
    return True,{
        "eligible":True,"n":n,"wins":wins,"losses":int(exact.get("losses") or 0),
        "accuracy":round(accuracy,4),"posterior_probability":round(posterior,6),
        "min_n":RESULTS_FIRST_MIN_OBS,"min_accuracy":RESULTS_FIRST_MIN_ACCURACY,
        "product_ticket_n":ticket_n,"product_ticket_wins":ticket_w,
        "product_ticket_losses":int(ticket_row.get("losses") or 0),
        "product_ticket_accuracy":round(ticket_rate,4) if ticket_rate is not None else None,
        "construction_leg_count":int(selected_shape["leg_count"]),
        "construction_ticket_n":construction_n,
        "construction_ticket_wins":construction_w,
        "construction_ticket_losses":int(selected_shape.get("ticket_losses") or 0),
        "construction_ticket_accuracy":selected_shape.get("ticket_accuracy"),
        "construction_loss_rate":selected_shape.get("loss_rate"),
        "construction_avg_combined_odds":avg_construction_odds,
        "construction_empirical_expected_roi":empirical_roi,
        "construction_shapes":shape_rows,
        "min_construction_combined_odds":active_min_combined_odds(),
        "min_construction_expected_roi":RESULTS_FIRST_MIN_EXPECTED_ROI,
        "source":"data/odds_ticket_tracker.json","role":"primary_results_gate_construction_specific"
    }

_VIRTUAL_RECENT_GATE_CACHE=None


def _load_recent_virtual_evidence():
    global _VIRTUAL_RECENT_GATE_CACHE
    if _VIRTUAL_RECENT_GATE_CACHE is not None:
        return _VIRTUAL_RECENT_GATE_CACHE
    files=sorted((DATA/"virtual_lab_archive"/"settlements").glob("*.jsonl"))
    rows=[]
    for path in files[-5:]:
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                row=json.loads(raw)
                if row.get("market")!="ou" or row.get("product") not in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
                    continue
                if row.get("line") is None or row.get("win") is None:
                    continue
                rows.append(row)
        except Exception:
            continue
    rows.sort(key=lambda r:str(r.get("settled_at") or r.get("timestamp") or ""),reverse=True)
    rows=rows[:2500]
    index={}
    for row in rows:
        try:
            line=float(row.get("line"))
        except (TypeError,ValueError):
            continue
        side="over" if str(row.get("selection") or "").upper().startswith("O") else "under" if str(row.get("selection") or "").upper().startswith("U") else None
        if side is None:
            continue
        key=(str(row.get("product") or ""),f"{line:g}",side)
        index.setdefault(key,[]).append(row)
    _VIRTUAL_RECENT_GATE_CACHE=index
    return index


def _efootball_recent_spoiler_guard(product,exact):
    """Fail closed when an eFootball exact line/side deteriorates recently.

    exact is ordered newest-first by _load_recent_virtual_evidence.
    The base 65% exact-side gate remains unchanged; this guard only stops
    stale older wins from masking a fresh collapse. It is intentionally scoped
    to eFootball products so the existing VFootball lane is not altered.
    """
    product=str(product or "")
    if not product.startswith("efootball_"):
        return True,{"enabled":False}
    n=len(exact) if isinstance(exact,list) else 0
    details={
        "enabled":True,
        "n":n,
        "min_n":EFOOTBALL_RECENT_SPOILER_MIN_OBS,
        "last10_min_hit_rate":EFOOTBALL_RECENT_SPOILER_LAST10_MIN_HIT,
        "last20_min_observations":EFOOTBALL_RECENT_SPOILER_LAST20_MIN_OBS,
        "last20_min_hit_rate":EFOOTBALL_RECENT_SPOILER_LAST20_MIN_HIT,
        "max_consecutive_losses":EFOOTBALL_RECENT_SPOILER_MAX_CONSECUTIVE_LOSSES,
    }
    if n < EFOOTBALL_RECENT_SPOILER_MIN_OBS:
        details["status"]="not_triggered_insufficient_recent_sample"
        return True,details

    last10=exact[:10]
    last20=exact[:20]
    last10_wins=sum(1 for row in last10 if row.get("win") is True)
    last20_wins=sum(1 for row in last20 if row.get("win") is True)
    last10_hit=last10_wins/len(last10) if last10 else 0.0
    last20_hit=last20_wins/len(last20) if last20 else 0.0
    loss_streak=0
    for row in exact:
        if row.get("win") is True:
            break
        loss_streak+=1

    details.update({
        "last10_n":len(last10),
        "last10_wins":last10_wins,
        "last10_hit_rate":round(last10_hit,4),
        "last20_n":len(last20),
        "last20_wins":last20_wins,
        "last20_hit_rate":round(last20_hit,4),
        "consecutive_losses":loss_streak,
    })

    if loss_streak >= EFOOTBALL_RECENT_SPOILER_MAX_CONSECUTIVE_LOSSES:
        details["status"]="blocked_recent_loss_streak"
        details["reason"]="efootball_recent_loss_streak"
        return False,details
    if len(last10) >= 10 and last10_hit < EFOOTBALL_RECENT_SPOILER_LAST10_MIN_HIT:
        details["status"]="blocked_last10_hit_rate"
        details["reason"]="efootball_recent_last10_below_threshold"
        return False,details
    if len(last20) >= EFOOTBALL_RECENT_SPOILER_LAST20_MIN_OBS and last20_hit < EFOOTBALL_RECENT_SPOILER_LAST20_MIN_HIT:
        details["status"]="blocked_last20_hit_rate"
        details["reason"]="efootball_recent_last20_below_threshold"
        return False,details

    details["status"]="passed"
    return True,details


def virtual_recent_gate(product,line,pick):
    """Exact product + line + selected-side recent evidence gate.

    The settlement files are loaded once per Builder run and indexed by
    product/line/side, preserving the existing threshold while avoiding
    repeated disk parsing for every live candidate.
    """
    index=_load_recent_virtual_evidence()
    try:
        key=(str(product or ""),f"{float(line):g}",str(pick or "").lower())
    except (TypeError,ValueError):
        return False,{"reason":"invalid_line"}
    exact=index.get(key,[])
    min_n=8
    if len(exact)<min_n:
        return False,{"n":len(exact),"reason":"insufficient_recent_side_evidence","min_n":min_n}
    wins=sum(1 for r in exact if r.get("win") is True)
    hit=wins/len(exact)
    threshold=0.65 if product=="efootball_gt" else 0.75
    details={
        "n":len(exact),
        "wins":wins,
        "hit_rate":round(hit,4),
        "threshold":threshold,
        "side":str(pick or "").lower(),
    }
    if hit < threshold:
        details["reason"]="recent_evidence_below_threshold"
        return False,details
    guard_pass,guard_details=_efootball_recent_spoiler_guard(product,exact)
    details["efootball_recent_spoiler_guard"]=guard_details
    if not guard_pass:
        details["reason"]=guard_details.get("reason") or "efootball_recent_spoiler_guard"
        return False,details
    return True,details

def virtual_directional_evidence(recent):
    """Score exact product/line/side settlement evidence for eFootball ranking.

    Bayesian shrinkage keeps small samples from dominating larger histories.
    This is ranking-only; the existing evidence threshold remains the gate.
    """
    if not isinstance(recent,dict):
        return {"score":0.0,"posterior_rate":0.0,"sample_confidence":0.0,"n":0,"wins":0}
    try:
        n=int(recent.get("n") or 0)
        wins=int(recent.get("wins") or 0)
    except (TypeError,ValueError):
        return {"score":0.0,"posterior_rate":0.0,"sample_confidence":0.0,"n":0,"wins":0}
    if n<8:
        return {"score":0.0,"posterior_rate":0.0,"sample_confidence":0.0,"n":n,"wins":wins}
    posterior=(wins+2.0)/(n+4.0)
    sample_confidence=min(1.0,math.sqrt(n/30.0))
    score=posterior*(0.75+0.25*sample_confidence)
    return {
        "score":round(score,6),
        "posterior_rate":round(posterior,6),
        "sample_confidence":round(sample_confidence,6),
        "n":n,
        "wins":wins
    }

# Phase 2 cyclical-loop history is a research signal only. It never changes
# the baseline Builder eligibility gates.
_PHASE2_CYCLE_HISTORY_CACHE=None

def _load_phase2_cycle_history():
    """Load chronological Virtual/eFootball O/U outcomes for cycle analysis."""
    global _PHASE2_CYCLE_HISTORY_CACHE
    if _PHASE2_CYCLE_HISTORY_CACHE is not None:
        return _PHASE2_CYCLE_HISTORY_CACHE
    files=sorted((DATA/"virtual_lab_archive"/"settlements").glob("*.jsonl"))
    index={}
    rows=[]
    for path in files[-5:]:
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                row=json.loads(raw)
                if row.get("market")!="ou" or row.get("product") not in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
                    continue
                if row.get("line") is None or row.get("win") is None:
                    continue
                selection=str(row.get("selection") or "").upper()
                if selection.startswith("O"):
                    selected_side="over"
                elif selection.startswith("U"):
                    selected_side="under"
                else:
                    continue
                actual_side=selected_side if row.get("win") is True else ("under" if selected_side=="over" else "over")
                try:
                    line_key=f"{float(row.get('line')):g}"
                except (TypeError,ValueError):
                    continue
                stamp=str(row.get("settled_at") or row.get("timestamp") or "")
                rows.append((stamp,str(row.get("product") or ""),line_key,actual_side))
        except Exception:
            continue
    rows.sort(key=lambda item:item[0])
    for stamp,product,line_key,actual_side in rows:
        index.setdefault((product,line_key),[]).append({
            "settled_at":stamp,
            "actual_side":actual_side
        })
    _PHASE2_CYCLE_HISTORY_CACHE=index
    return index

def _phase2_cyclical_loop_signal(x):
    """Score a candidate as a potential high-probability streak break.

    A streak break is only flagged when:
    - the candidate is Virtual/eFootball and already Builder-eligible,
    - the latest exact product+line sequence has at least a 2-result streak,
    - the candidate side is the opposite side of that current streak,
    - the historical sequence contains enough prior break opportunities, and
    - a blended model/evidence/cycle confidence reaches 78%.
    
    This is a research hypothesis, not a gambler's-fallacy override. The baseline
    Builder never consumes this score unless the separate Phase 2 constructor wins.
    """
    result={
        "enabled":PHASE2_CYCLICAL_LOOP_ENABLED,
        "flagged":False,
        "confidence":0.0,
        "model_probability":0.0,
        "evidence_posterior":None,
        "cycle_break_posterior":None,
        "current_streak_side":None,
        "current_streak_length":0,
        "historical_break_observations":0,
        "historical_breaks":0,
        "reason":"not_virtual_efootball"
    }
    product=str(x.get("product") or "")
    if not PHASE2_CYCLICAL_LOOP_ENABLED or not (product.startswith("efootball_") or product=="vfootball"):
        return result
    try:
        model_p=float(x.get("builder_probability") or 0.0)
    except (TypeError,ValueError):
        model_p=0.0
    result["model_probability"]=round(model_p,6)
    if model_p < PHASE2_CYCLICAL_MIN_CONFIDENCE:
        result["reason"]="model_probability_below_78_percent"
        return result

    line=x.get("line")
    side=str(x.get("builder_pick") or x.get("pick") or "").lower()
    if side not in {"over","under"} or line is None:
        result["reason"]="invalid_virtual_side_or_line"
        return result
    try:
        line_key=f"{float(line):g}"
    except (TypeError,ValueError):
        result["reason"]="invalid_line"
        return result

    history=_load_phase2_cycle_history().get((product,line_key),[])
    result["historical_break_observations"]=0
    result["historical_breaks"]=0
    if len(history)<(PHASE2_CYCLICAL_MIN_BREAK_OBSERVATIONS+2):
        result["reason"]="insufficient_cycle_history"
        return result

    seq=[str(row.get("actual_side") or "") for row in history if row.get("actual_side") in {"over","under"}]
    if len(seq)<(PHASE2_CYCLICAL_MIN_BREAK_OBSERVATIONS+2):
        result["reason"]="insufficient_cycle_sequence"
        return result

    current_side=seq[-1]
    current_len=1
    for idx in range(len(seq)-2,-1,-1):
        if seq[idx]==current_side:
            current_len+=1
        else:
            break
    result["current_streak_side"]=current_side
    result["current_streak_length"]=current_len

    if current_len < PHASE2_CYCLICAL_MIN_STREAK_LENGTH or side==current_side:
        result["reason"]="no_current_opposite_side_streak_break"
        return result

    # Historical break rate: after at least a 2-result run of the opposite side,
    # how often did the next observation switch to the candidate side?
    opportunities=0
    breaks=0
    run_len=1
    for idx in range(1,len(seq)-1):
        if seq[idx]==seq[idx-1]:
            run_len+=1
        else:
            run_len=1
        if run_len>=PHASE2_CYCLICAL_MIN_STREAK_LENGTH and seq[idx+1] in {"over","under"}:
            opportunities+=1
            if seq[idx+1]==side:
                breaks+=1
    if opportunities < PHASE2_CYCLICAL_MIN_BREAK_OBSERVATIONS:
        result["reason"]="insufficient_historical_break_opportunities"
        result["historical_break_observations"]=opportunities
        return result

    cycle_p=(breaks+2.0)/(opportunities+4.0)
    recent=x.get("recent_evidence") or {}
    try:
        n=int(recent.get("n") or 0)
        wins=int(recent.get("wins") or 0)
        evidence_p=(wins+2.0)/(n+4.0) if n>=8 else None
    except (TypeError,ValueError):
        evidence_p=None

    # Model probability is primary, exact-line evidence is secondary, and the
    # cycle reversal statistic is a deliberately modest third component.
    confidence=(0.60*model_p)+(0.25*(evidence_p if evidence_p is not None else model_p))+(0.15*cycle_p)
    flagged=(
        model_p>=PHASE2_CYCLICAL_MIN_CONFIDENCE and
        evidence_p is not None and
        opportunities>=PHASE2_CYCLICAL_MIN_BREAK_OBSERVATIONS and
        confidence>=PHASE2_CYCLICAL_MIN_CONFIDENCE
    )
    result.update({
        "flagged":bool(flagged),
        "confidence":round(confidence,6),
        "evidence_posterior":round(evidence_p,6) if evidence_p is not None else None,
        "cycle_break_posterior":round(cycle_p,6),
        "historical_break_observations":opportunities,
        "historical_breaks":breaks,
        "reason":"high_probability_streak_break" if flagged else "cycle_confidence_below_78_percent"
    })
    return result

def _phase2_kelly_diagnostic(probability,combined_odds):
    """Paper-only Kelly diagnostic; never controls or executes staking."""
    try:
        p=float(probability)
        odds=float(combined_odds)
    except (TypeError,ValueError):
        return {"applicable":False,"reason":"invalid_inputs"}
    if odds<=PHASE2_CYCLICAL_HIGH_VARIANCE_ODDS or not 0.0<p<1.0:
        return {
            "applicable":False,
            "combined_odds":round(odds,3),
            "label":None,
            "paper_only":True,
            "reason":"high_variance_threshold_or_below"
        }
    b=odds-1.0
    k=((b*p)-(1.0-p))/b if b>0 else 0.0
    return {
        "applicable":True,
        "combined_odds":round(odds,3),
        "kelly_fraction":round(max(0.0,min(1.0,k)),6),
        "label":"High Variance - Fraction Stake Only",
        "paper_only":True,
        "execution":"none"
    }

def _construct_phase2_cyclical_loop_batches(pool,max_batches=4,min_odds=None):
    """Construct isolated 2–3-leg cyclical Virtual/eFootball research batches."""
    if min_odds is None:
        min_odds=active_min_combined_odds()
    eligible=[
        x for x in pool
        if str(x.get("sport") or "")=="virtual"
        and (str(x.get("product") or "")=="vfootball" or str(x.get("product") or "").startswith("efootball_"))
        and str((x.get("phase2_cyclical_loop") or {}).get("reason") or "")=="high_probability_streak_break"
        and bool((x.get("phase2_cyclical_loop") or {}).get("flagged"))
        and bool(x.get("builder_eligible"))
        and float(x.get("model_probability") or 0.0)>=PHASE2_CYCLICAL_MIN_CONFIDENCE
    ]
    import itertools
    eligible=sorted(
        eligible,
        key=lambda x:(
            -float((x.get("phase2_cyclical_loop") or {}).get("confidence") or 0.0),
            -float(x.get("model_probability") or 0.0),
            -float(x.get("evidence_score") or 0.0),
            -float(x.get("model_edge") or 0.0),
            -float(x.get("bookmaker_odds") or 1.0),
            _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")
        )
    )[:PHASE2_CYCLICAL_POOL_CAP]
    import itertools
    options=[]
    for shape in range(PHASE2_CYCLICAL_MIN_LEGS,PHASE2_CYCLICAL_MAX_LEGS+1):
        for combo in itertools.combinations(eligible,shape):
            event_ids=[str(x.get("event_id") or "") for x in combo if x.get("event_id")]
            if len(event_ids)!=len(set(event_ids)):
                continue
            participants=[p for row in combo for p in _participants(row)]
            if len(participants)!=len(set(participants)):
                continue
            if _batch_kickoff_span_minutes(combo)>MAX_BATCH_KICKOFF_SPAN_MINUTES:
                continue
            odds=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in combo)
            if odds<min_odds:
                continue
            if any(float((x.get("phase2_cyclical_loop") or {}).get("confidence") or 0.0)<PHASE2_CYCLICAL_MIN_CONFIDENCE for x in combo):
                continue
            metrics=_batch_metrics(list(combo))
            roi=(float(metrics.get("combined_model_probability") or 0.0)*odds)-1.0
            if roi<RESULTS_FIRST_MIN_EXPECTED_ROI:
                continue
            min_conf=min(float((x.get("phase2_cyclical_loop") or {}).get("confidence") or 0.0) for x in combo)
            avg_prob=float(metrics.get("avg_model_probability") or 0.0)
            options.append({
                "rows":list(combo),
                "metrics":metrics,
                "odds":odds,
                "span":_batch_kickoff_span_minutes(combo),
                "roi":roi,
                "min_confidence":min_conf,
                "score":(
                    min_conf,
                    float(metrics.get("combined_model_probability") or 0.0),
                    avg_prob,
                    roi,
                    odds,
                )
            })
    options.sort(key=lambda row:row["score"],reverse=True)
    selected=[]
    used_events=set()
    used_participants=set()
    for option in options:
        if len(selected)>=max_batches:
            break
        rows=option["rows"]
        events={str(x.get("event_id") or "") for x in rows if x.get("event_id")}
        participants={p for row in rows for p in _participants(row)}
        if events & used_events or participants & used_participants:
            continue
        risk=_phase2_kelly_diagnostic(option["metrics"].get("combined_model_probability"),option["odds"])
        option["kelly_risk"]=risk
        selected.append(option)
        used_events.update(events)
        used_participants.update(participants)
    return selected,{
        "enabled":PHASE2_CYCLICAL_LOOP_ENABLED,
        "eligible_legs":len(eligible),
        "candidate_combinations":len(options),
        "batches_selected":len(selected),
        "min_confidence":PHASE2_CYCLICAL_MIN_CONFIDENCE,
        "min_legs":PHASE2_CYCLICAL_MIN_LEGS,
        "max_legs":PHASE2_CYCLICAL_MAX_LEGS,
        "pool_cap":PHASE2_CYCLICAL_POOL_CAP,
        "min_combined_odds":min_odds,
        "high_variance_odds_threshold":PHASE2_CYCLICAL_HIGH_VARIANCE_ODDS,
        "execution_track":"PHASE2_CYCLICAL_LOOP",
        "mixed_with_baseline":False,
        "reason":None if selected else "no_isolated_streak_break_combination_reached_all_gates"
    }

def virtual_candidates(now):
    """Build Virtual candidates from the freshest exact SportyBet O/U snapshot.

    The Unified Upcoming Board is itself generated from the live SportyBet feed and
    preserves the exact observed O/U ladder. A bounded direct refresh can update a
    matching event/line, but it must not replace a fresh validated half-line with
    a different representation from another endpoint.
    """
    board=load(DATA/"unified_upcoming.json",{})
    model_rows=board.get("events") if isinstance(board,dict) else []
    # Unified Upcoming is generated directly from the live SportyBet snapshot.
    # Use that fresh exact-line snapshot as the price authority here; a second
    # network call can expose a different virtual ladder and can also stall the
    # Builder without adding evidence.
    refreshed_rows, quote_diag = refresh_virtual_quotes(model_rows if isinstance(model_rows,list) else [])

    def row_key(row):
        try:
            return (
                str(row.get("product") or ""),
                str(row.get("event_id") or ""),
                f"{float(row.get('line')):g}" if row.get("line") is not None else "",
            )
        except (TypeError,ValueError):
            return (str(row.get("product") or ""),str(row.get("event_id") or ""),"")
    
    original_map={}
    for row in model_rows if isinstance(model_rows,list) else []:
        if not isinstance(row,dict):
            continue
        original_map[row_key(row)]=row

    merged=[]
    for row in refreshed_rows if isinstance(refreshed_rows,list) else []:
        x=dict(row)
        original=original_map.get(row_key(row))
        if isinstance(original,dict):
            # The direct endpoint may expose a different line ladder for the same
            # recurring fixture. Preserve a fresh exact SportyBet quote from the
            # Unified Board when the direct refresh does not contain that exact line.
            if not x.get("sportybet_over_odds") or not x.get("sportybet_under_odds"):
                age=odds_age(original)
                if (
                    age is not None and age<=MAX_ODDS_AGE_SECONDS
                    and str(original.get("bookmaker_source") or "")=="SportyBet NG"
                    and original.get("sportybet_over_odds") is not None
                    and original.get("sportybet_under_odds") is not None
                ):
                    for key in (
                        "bookmaker_available","bookmaker_source","sportybet_over_odds",
                        "sportybet_under_odds","bookmaker_odds","sportybet_odds",
                        "market_odds_timestamp","sportybet_event_id","sportybet_match"
                    ):
                        if key in original:
                            x[key]=original.get(key)
                    x["price_snapshot_source"]="fresh_unified_sportybet_snapshot"
            else:
                x["price_snapshot_source"]="fresh_direct_sportybet_match"
        merged.append(x)

    # The refreshed list can be smaller than the board when its endpoint uses a
    # narrower current ladder. Add fresh board rows that have exact SportyBet
    # quotes and were not returned by the direct refresh.
    seen={row_key(x) for x in merged}
    for original in model_rows if isinstance(model_rows,list) else []:
        if not isinstance(original,dict):
            continue
        key=row_key(original)
        if key in seen:
            continue
        age=odds_age(original)
        if (
            age is not None and age<=MAX_ODDS_AGE_SECONDS
            and str(original.get("bookmaker_source") or "")=="SportyBet NG"
            and original.get("sportybet_over_odds") is not None
            and original.get("sportybet_under_odds") is not None
        ):
            x=dict(original)
            x["price_snapshot_source"]="fresh_unified_sportybet_snapshot"
            merged.append(x)
            seen.add(key)

    def template_key(product,line,pick):
        return (str(product or ""),f"{float(line):g}",str(pick or "").lower())

    # Discovery universe: every current SportyBet eFootball event and every
    # observed O/U line is inspected independently of the legacy model board.
    # Qualification still requires exact settled evidence and all existing gates.
    recent_index=_load_recent_virtual_evidence()
    templates={}
    discovery_events=set()
    discovery_lines=set()
    discovery_modelable=set()
    discovery_no_evidence=set()
    for row in merged:
        if not isinstance(row,dict) or row.get("sport")!="virtual":
            continue
        product=str(row.get("product") or "")
        if not product.startswith("efootball_"):
            continue
        line=row.get("line")
        if line is None:
            continue
        try:
            line_key=f"{float(line):g}"
        except (TypeError,ValueError):
            continue
        discovery_events.add(str(row.get("event_id") or ""))
        discovery_lines.add((product,line_key))
        for side in ("over","under"):
            exact=recent_index.get((product,line_key,side),[])
            n=len(exact)
            if n<8:
                discovery_no_evidence.add((product,line_key,side))
                continue
            wins=sum(1 for item in exact if item.get("win") is True)
            prob=(wins+2.0)/(n+4.0)
            key=template_key(product,line,side)
            candidate={**row,
                       "probabilities":{"over":prob if side=="over" else 1.0-prob,
                                        "under":prob if side=="under" else 1.0-prob},
                       "probability":prob,
                       "pick":side,
                       "model":"Virtual Lab exact-line empirical fallback"}
            prev=templates.get(key)
            if prev is None or prob>float(prev.get("probability") or 0):
                templates[key]=candidate
            discovery_modelable.add((product,line_key,side))

    out=[]
    diagnostics={
        "seen":0,"qualified":0,"evidence_pass":0,"rejected_evidence":0,"rejected_ticket_performance":0,"rejected_results_first":0,
        "current_feed_events":0,"model_templates":len(templates),
        "current_market_candidates":0,"evidence_value_candidates":0,"reasons":{}
    }
    diagnostics["current_feed_events"]=len({str(x.get("event_id") or "") for x in merged if isinstance(x,dict) and x.get("event_id")})
    diagnostics["model_template_keys"]=[list(k) for k in sorted(templates.keys())]
    diagnostics["discovery_universe"]={
        "scope":"all current SportyBet eFootball events and every observed O/U line inside the Builder horizon",
        "events_scanned":len([x for x in discovery_events if x]),
        "product_line_pairs_scanned":len(discovery_lines),
        "modelable_product_line_side_pairs":len(discovery_modelable),
        "product_line_side_pairs_without_8_settled_observations":len(discovery_no_evidence),
        "note":"No-evidence lines remain discovery-only and cannot qualify; no gate is weakened."
    }
    diagnostics["current_product_counts"]={}
    diagnostics["current_market_line_counts"]={}
    diagnostics["price_snapshot_sources"]={}
    diagnostics["live_quote_refresh"]={
        "source":quote_diag.get("source") if isinstance(quote_diag,dict) else None,
        "live_events":quote_diag.get("live_events",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_id":quote_diag.get("matched_by_id",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_match":quote_diag.get("matched_by_match",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_participant_time":quote_diag.get("matched_by_participant_time",0) if isinstance(quote_diag,dict) else 0,
        "unmatched":quote_diag.get("unmatched",0) if isinstance(quote_diag,dict) else 0
    }

    for event in merged:
        if not isinstance(event,dict):
            continue
        if event.get("sport")!="virtual" or event.get("product") not in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
            continue
        if not within_builder_horizon(event,now):
            continue
        product=str(event.get("product") or "")
        line=event.get("line")
        pick=str(event.get("pick") or "").lower()
        if line is None:
            continue
        if not product.startswith("efootball_") and pick not in {"over","under"}:
            continue
        try:
            line=float(line)
        except (TypeError,ValueError):
            continue
        over=event.get("sportybet_over_odds")
        under=event.get("sportybet_under_odds")
        try:
            over=float(over) if over is not None else None
            under=float(under) if under is not None else None
        except (TypeError,ValueError):
            over=under=None
        if over is None or under is None:
            continue

        diagnostics["seen"]+=1
        diagnostics["qualified"]+=1
        diagnostics["current_market_candidates"]+=2
        diagnostics["current_product_counts"][product]=diagnostics["current_product_counts"].get(product,0)+1
        lk=f"{product}|{float(line):g}"
        diagnostics["current_market_line_counts"][lk]=diagnostics["current_market_line_counts"].get(lk,0)+1
        source=str(event.get("price_snapshot_source") or "fresh_unified_sportybet_snapshot")
        diagnostics["price_snapshot_sources"][source]=diagnostics["price_snapshot_sources"].get(source,0)+1

        # Direction-neutral for eFootball; vFootball uses live board probability.
        is_efootball=product.startswith("efootball_")
        sides=["over","under"] if is_efootball else ([pick] if pick in {"over","under"} else [])

        for side in sides:
            template=templates.get(template_key(product,line,side)) if is_efootball else event
            if not template:
                diagnostics["reasons"]["no_exact_line_model"]=diagnostics["reasons"].get("no_exact_line_model",0)+1
                continue
            probabilities=template.get("probabilities") or {}
            try:
                prob=probabilities.get(side)
                if prob is None:
                    if side==str(template.get("pick") or "").lower():
                        prob=template.get("probability")
                    else:
                        preferred=probabilities.get(str(template.get("pick") or "").lower())
                        if preferred is not None:
                            prob=1.0-float(preferred)
                prob=float(prob)
            except (TypeError,ValueError):
                continue
            if not 0.0<prob<1.0:
                continue

            y={**template}
            y.update({
                "sport":"virtual","product":product,
                "league":event.get("league") or template.get("league"),
                "event_id":str(event.get("event_id") or ""),
                "start_time":event.get("start_time"),
                "participant_1":event.get("participant_1") or event.get("player_1") or event.get("team_1"),
                "participant_2":event.get("participant_2") or event.get("player_2") or event.get("team_2"),
                "player_1":event.get("player_1") or event.get("participant_1") or event.get("team_1"),
                "player_2":event.get("player_2") or event.get("participant_2") or event.get("team_2"),
                "match":event.get("match") or f"{event.get('player_1') or event.get('participant_1') or ''} vs {event.get('player_2') or event.get('participant_2') or ''}",
                "line":line,"pick":side,
                "probability":prob,"builder_probability":prob,
                "bookmaker_available":True,
                "sportybet_over_odds":over,"sportybet_under_odds":under,
                "bookmaker_odds":over if side=="over" else under,
                "sportybet_odds":over if side=="over" else under,
                "bookmaker_source":"SportyBet NG",
                "sportybet_event_id":str(event.get("sportybet_event_id") or event.get("event_id") or ""),
                "sportybet_match":event.get("sportybet_match") or event.get("match"),
                "market_odds_timestamp":event.get("market_odds_timestamp"),
                "sportybet_identity_match":True,
                "sportybet_market_id":event.get("sportybet_market_id"),
                "sportybet_specifier":event.get("sportybet_specifier"),
                "sportybet_over_outcome_id":event.get("sportybet_over_outcome_id"),
                "sportybet_over_outcome_name":event.get("sportybet_over_outcome_name"),
                "sportybet_under_outcome_id":event.get("sportybet_under_outcome_id"),
                "sportybet_under_outcome_name":event.get("sportybet_under_outcome_name"),
                "sportybet_selection_side":side,
                "sportybet_outcome_id":(
                    event.get("sportybet_over_outcome_id") if side=="over" else event.get("sportybet_under_outcome_id")
                ),
                "sportybet_outcome_name":(
                    event.get("sportybet_over_outcome_name") if side=="over" else event.get("sportybet_under_outcome_name")
                ),
                "builder_pick":side,"builder_market":"virtual_total",
                "price_snapshot_source":source,
                "directional_candidate_derived":bool(side!=pick),
                "source_model_pick":pick,
            })

            passed,recent=virtual_recent_gate(product,line,side)
            if not passed:
                diagnostics["rejected_evidence"]+=1
                reason=str(recent.get("reason") or "recent_evidence_below_threshold")
                diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1
                continue

            ticket_pass,ticket_perf=ticket_performance_gate(product,line,side)
            if not ticket_pass:
                diagnostics["rejected_ticket_performance"]+=1
                reason="ticket_performance_below_threshold"
                diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1
                continue

            results_pass,results_perf=results_first_gate(product,line,side) if RESULTS_FIRST_ENABLED else (True,{"eligible":False,"role":"disabled"})
            evidence=virtual_directional_evidence(recent)
            if not results_pass:
                reason=str(results_perf.get("reason") or "results_first_rejected")
                # eFootball has exact-line/side settlement evidence but does not
                # have a promoted vFootball construction shape. Preserve those
                # evidence-backed candidates for the model-first 4.00+ fallback
                # instead of dropping them as if they lacked evidence.
                if product.startswith("efootball_"):
                    diagnostics["evidence_value_candidates"]+=1
                    diagnostics["reasons"]["efootball_evidence_value_lane"]=diagnostics["reasons"].get("efootball_evidence_value_lane",0)+1
                    calibrated_probability=float(evidence.get("posterior_rate") or prob)
                    y["probability"]=calibrated_probability
                    y["builder_probability"]=calibrated_probability
                    y["model"]="Exact-line evidence calibration · eFootball value lane"
                    y["recent_evidence"]=recent
                    y["directional_evidence"]=evidence
                    y["evidence_score"]=evidence["score"]
                    y["ticket_performance"]=ticket_perf
                    y["results_first"]=results_perf
                    y["qualification_lane"]="efootball_exact_evidence_value"
                    out.append(y)
                    continue

                # VFootball may participate in the controlled mixed research lane
                # when its own exact-line evidence and ticket-spoiler gates pass,
                # even though the whole VFootball 2–4-leg construction family
                # has not yet earned Results-first promotion. We do NOT reuse it
                # in the pure fallback lane and we do NOT relax the 75% evidence
                # threshold, live-price, edge, freshness, quality or uncertainty
                # checks above.
                if (
                    product=="vfootball"
                    and reason=="no_profitable_construction_shape"
                ):
                    diagnostics["evidence_value_candidates"]+=1
                    diagnostics["reasons"]["vfootball_mixed_evidence_value_lane"]=diagnostics["reasons"].get("vfootball_mixed_evidence_value_lane",0)+1
                    calibrated_probability=float(evidence.get("posterior_rate") or prob)
                    y["probability"]=calibrated_probability
                    y["builder_probability"]=calibrated_probability
                    y["model"]="Exact-line evidence calibration · VFootball mixed research lane"
                    y["recent_evidence"]=recent
                    y["directional_evidence"]=evidence
                    y["evidence_score"]=evidence["score"]
                    y["ticket_performance"]=ticket_perf
                    y["results_first"]=results_perf
                    y["qualification_lane"]="vfootball_exact_evidence_value"
                    out.append(y)
                    continue

                diagnostics["rejected_results_first"]+=1
                diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1
                continue

            diagnostics["evidence_pass"]+=1
            if (
                product=="vfootball"
                and str(results_perf.get("reason") or "")=="vfootball_event_holdout_lane"
            ):
                # The frozen event holdout earns the VFootball construction lane,
                # but the leg probability should still come from the exact
                # product+line+side evidence that already passed virtual_recent_gate.
                # This keeps the 80% per-leg safety floor intact while preventing
                # the older raw model probability from suppressing evidence-backed
                # VFootball legs.
                evidence_probability=float(evidence.get("posterior_rate") or prob)
                calibrated_probability=max(float(prob),evidence_probability)
                y["model"]="Exact-line evidence calibration · VFootball event-holdout lane"
            else:
                calibrated_probability=float(results_perf.get("posterior_probability") or prob)
                y["model"]="Results-first settled-leg calibration"
            y["probability"]=calibrated_probability
            y["builder_probability"]=calibrated_probability
            y["recent_evidence"]=recent
            y["directional_evidence"]=evidence
            y["evidence_score"]=evidence["score"]
            y["ticket_performance"]=ticket_perf
            y["results_first"]=results_perf
            y["qualification_lane"]=str(results_perf.get("qualification_lane") or "")
            out.append(y)

    diagnostics["quote_join"]=quote_diag
    diagnostics["stale_unified_prices_used"]=False
    diagnostics["current_feed_is_price_authority"]=True
    diagnostics["price_authority"]="fresh SportyBet snapshot collected in-process immediately before Builder qualification"
    return out,diagnostics

def market_rows(x):
    market=x.get("builder_market")
    if market=="virtual_total":
        return [
            {"side":"over","odds":x.get("sportybet_over_odds")},
            {"side":"under","odds":x.get("sportybet_under_odds")}
        ]
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


def _participant_identity(value):
    """Extract the stable virtual participant identity from a feed label.

    Virtual fixtures commonly arrive as Team (participant). The parenthetical
    identity is the durable entity; plain labels are normalized as-is.
    """
    import re
    s=str(value or "").strip()
    m=re.search(r"\(([^()]*)\)\s*$",s)
    if m and m.group(1).strip():
        s=m.group(1).strip()
    s=re.sub(r"[^a-z0-9]+"," ",s.lower()).strip()
    return s


_PARTICIPANT_PROFILES_CACHE=None
_PARTICIPANT_PROFILE_INDEX_CACHE=None


def participant_history_profiles():
    """Load participant O/U profiles once per Builder run.

    The profiles are generated only from settled SportyBet history and are used
    strictly as a ranking feature after all eligibility gates. Caching avoids
    repeatedly parsing the same artifact for every candidate leg.
    """
    global _PARTICIPANT_PROFILES_CACHE
    if _PARTICIPANT_PROFILES_CACHE is None:
        profile_path=DATA/"virtual_lab_participant_profiles.json"
        raw=load(profile_path,{})
        profiles=raw.get("profiles") if isinstance(raw,dict) else []
        _PARTICIPANT_PROFILES_CACHE=profiles if isinstance(profiles,list) else []
    return _PARTICIPANT_PROFILES_CACHE


def participant_history_signal(x):
    """Return conservative exact-line O/U history for both participants.

    A Bayesian prior keeps tiny samples near 50%. Recent exact-line history is
    blended with the full exact-line record when available. This feature can
    rank already-qualified legs but cannot make a rejected leg eligible.
    """
    if x.get("sport")!="virtual":
        return {"available":False,"score":0.5,"participants":[]}
    product=str(x.get("product") or "")
    line=x.get("line")
    pick=str(x.get("builder_pick") or "").lower()
    try:line_key=f"{float(line):g}"
    except (TypeError,ValueError):
        return {"available":False,"score":0.5,"participants":[]}
    names=[x.get("participant_1") or x.get("player_1") or x.get("team_1"),
           x.get("participant_2") or x.get("player_2") or x.get("team_2")]
    global _PARTICIPANT_PROFILE_INDEX_CACHE
    profiles=participant_history_profiles()
    if _PARTICIPANT_PROFILE_INDEX_CACHE is None:
        _PARTICIPANT_PROFILE_INDEX_CACHE={str(p.get("participant_key")):p for p in profiles if isinstance(p,dict)}
    by_key=_PARTICIPANT_PROFILE_INDEX_CACHE
    details=[]
    for raw_name in names:
        identity=_participant_identity(raw_name)
        key=f"{product}|{identity}" if identity else ""
        profile=by_key.get(key)
        line_data=(profile or {}).get("lines",{}).get(line_key) if profile else None
        if not isinstance(line_data,dict):
            details.append({"participant":identity,"n":0,"recent_n":0,"score":0.5,"available":False})
            continue
        try:n=int(line_data.get("n") or 0)
        except (TypeError,ValueError):n=0
        try:over=int(line_data.get("over") or 0)
        except (TypeError,ValueError):over=0
        try:rn=int(line_data.get("recent_n") or 0)
        except (TypeError,ValueError):rn=0
        try:ro=float(line_data.get("recent_over_rate")) if rn else None
        except (TypeError,ValueError):ro=None
        full_wins=over if pick=="over" else max(0,n-over)
        full=(full_wins+2.0)/(n+4.0) if n else 0.5
        recent_wins=(ro*rn) if pick=="over" and ro is not None else ((1.0-ro)*rn if ro is not None else 0.0)
        recent=(recent_wins+2.0)/(rn+4.0) if rn else full
        if rn>=PARTICIPANT_HISTORY_MIN_N and n>=PARTICIPANT_HISTORY_MIN_N:
            score=0.65*recent+0.35*full
        elif n>=PARTICIPANT_HISTORY_MIN_N:
            score=full
        else:
            score=0.5
        details.append({"participant":identity,"n":n,"recent_n":rn,"full_score":round(full,4),"recent_score":round(recent,4),"score":round(score,4),"available":n>=PARTICIPANT_HISTORY_MIN_N})
    available=[d for d in details if d["available"]]
    score=sum(d["score"] for d in available)/len(available) if available else 0.5
    return {"available":bool(available),"score":round(score,4),"participants":details,"line":line_key,"side":pick}


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
    elif x.get("sport")=="virtual":
        market=f"O/U {x.get('builder_pick')} {x.get('line')}"
        match=f"{x.get('player_1')} vs {x.get('player_2')}"
        pick=f"{match} — {market}"
    else:
        match=f"{x.get('home_team')} vs {x.get('away_team')}"
        pick=x.get("builder_pick")
    # Participant history is a ranking feature only. It never bypasses
    # eligibility, evidence, freshness, edge, uncertainty or ticket gates.
    participant_history={"available":False,"score":0.5,"participants":[]}
    history_bonus=0.0
    evidence_score=None
    if str(x.get("product") or "").startswith("efootball_"):
        try:
            value=float(x.get("evidence_score"))
            evidence_score=value if math.isfinite(value) else None
        except (TypeError,ValueError):
            evidence_score=None
        participant_history=participant_history_signal(x)
        if participant_history.get("available"):
            history_bonus=max(-PARTICIPANT_HISTORY_MAX_BONUS,
                              min(PARTICIPANT_HISTORY_MAX_BONUS,
                                  (float(participant_history.get("score") or 0.5)-0.5)*2.0))
    if evidence_score is not None:
        # Exact-line settled evidence remains primary; participant history is a
        # small secondary ranking signal so recurring high-performing identities
        # can surface without changing qualification thresholds.
        selection_score=(0.90*evidence_score)+(0.10*max(0.0,float(edge or 0.0)))+history_bonus
    else:
        selection_score=(edge if edge is not None else -1.0)+history_bonus
    phase2_cycle=_phase2_cyclical_loop_signal(x) if str(x.get("sport") or "")=="virtual" else {
        "enabled":PHASE2_CYCLICAL_LOOP_ENABLED,
        "flagged":False,
        "confidence":0.0,
        "reason":"not_virtual"
    }
    return {
        "sport":x.get("sport"),"competition":x.get("league"),"event_id":x.get("event_id"),
        "start_time":x.get("start_time"),"match":match,"market":x.get("builder_market"),
        "pick":pick,"model_probability":round(p,6),"model_fair_odds":fair_odds(p),
        "bookmaker_odds":round(bookmaker,3) if bookmaker is not None else None,
        "market_implied_probability":round(implied,6) if implied is not None else None,
        "de_vig_probability":round(devig,6) if devig is not None else None,
        "model_edge":round(edge,6) if edge is not None else None,
        "expected_value":round(ev,6) if ev is not None else None,
        "participant_history":participant_history,
        "participant_history_bonus":round(history_bonus,6),
        "evidence_score":round(evidence_score,6) if evidence_score is not None else None,
        "selection_score":round(selection_score,6),
        "product":x.get("product"),
        "edge_percent":round(edge*100,2) if edge is not None else None,
        "odds_fresh":bool(age is not None and age<=MAX_ODDS_AGE_SECONDS),
        "market_odds_age_seconds":round(age,1) if age is not None else None,
        "data_quality":round(quality,3),"uncertainty":round(uncert,3),
        "market_complete":complete,"builder_eligible":eligible,"real_money_eligible":False,"paper_only":True,
        "status":"LIVE_VALUE" if eligible else ("STALE" if age is not None and age>MAX_ODDS_AGE_SECONDS else "REJECTED"),
        "source":x.get("model"),"market_source":x.get("market_source") or x.get("bookmaker_source"),
        "recent_evidence":x.get("recent_evidence"),
        "results_first":x.get("results_first"),
        "qualification_lane":x.get("qualification_lane"),
        "phase2_cyclical_loop":phase2_cycle,
        "market_odds_timestamp":x.get("odds_timestamp") or x.get("market_odds_timestamp"),
        "sportybet_event_id":x.get("sportybet_event_id") or x.get("event_id"),
        "sportybet_market_id":x.get("sportybet_market_id"),
        "sportybet_specifier":x.get("sportybet_specifier"),
        "sportybet_outcome_id":x.get("sportybet_outcome_id"),
        "sportybet_outcome_name":x.get("sportybet_outcome_name")
    }


def _participants(leg):
    """Return normalized participant identities for correlation control."""
    import re
    vals=[]
    for key in ("participant_1","participant_2","player_1","player_2","team_1","team_2"):
        v=leg.get(key)
        if v: vals.append(v)
    if not vals:
        match=str(leg.get("match") or "")
        vals=[p.strip() for p in re.split(r"\s+vs\s+",match,flags=re.I) if p.strip()]
    out=[]
    for v in vals:
        s=re.sub(r"[^a-z0-9]+"," ",str(v).lower()).strip()
        if s and s not in out: out.append(s)
    return out

_TICKET_CALIBRATION_CACHE=None

def _ticket_calibration_gamma():
    """Estimate a time-safe ticket-probability shrinkage exponent.

    Individual VFootball probabilities are strong, but the old ticket layer
    multiplied them into systematically overconfident joint probabilities.
    This estimator learns a conservative exponent only from earlier settled
    2–7-leg tickets, using a rolling Brier-minimization procedure. It never
    uses pending/current tickets as training rows.
    """
    global _TICKET_CALIBRATION_CACHE
    if _TICKET_CALIBRATION_CACHE is not None:
        return _TICKET_CALIBRATION_CACHE
    raw=load(DATA/"odds_ticket_tracker.json",{})
    tickets=raw.get("tickets") if isinstance(raw,dict) else []
    rows=[]
    for ticket in tickets if isinstance(tickets,list) else []:
        if str(ticket.get("status") or "").upper() not in {"WON","LOST"}:
            continue
        try:
            leg_count=int(ticket.get("leg_count") or len(ticket.get("legs") or []))
            raw_p=float(ticket.get("combined_model_probability"))
        except (TypeError,ValueError):
            continue
        if not 2<=leg_count<=7 or not 0<raw_p<1:
            continue
        stamp=ticket.get("last_settled_at") or ticket.get("settled_at") or ticket.get("updated_at")
        if not stamp:
            continue
        rows.append((str(stamp),raw_p,1.0 if str(ticket.get("status") or "").upper()=="WON" else 0.0))
    rows.sort(key=lambda x:x[0])
    warmup=8
    gammas=[0.5+i*0.1 for i in range(46)]
    chosen=[]
    for i in range(warmup,len(rows)):
        prior=rows[:i]
        best=min(gammas,key=lambda g:sum((y-max(.0005,min(.9995,p**g)))**2 for _,p,y in prior)/len(prior))
        chosen.append(best)
    if len(chosen)<3:
        result={"gamma":1.0,"sample":len(rows),"warmup":warmup,"trained":False,"source":"insufficient_settled_2_to_7_ticket_history"}
    else:
        gamma=max(1.0,min(4.0,sum(chosen)/len(chosen)))
        result={"gamma":round(gamma,4),"sample":len(rows),"warmup":warmup,"trained":True,
                "source":"chronological_2_to_7_ticket_brier_calibration","gamma_observations":len(chosen)}
    _TICKET_CALIBRATION_CACHE=result
    return result

def _calibrated_ticket_probability(raw_probability):
    try:
        p=max(.0005,min(.9995,float(raw_probability)))
    except (TypeError,ValueError):
        return 0.0
    gamma=float(_ticket_calibration_gamma().get("gamma") or 1.0)
    return max(.0005,min(.9995,p**gamma))

def _vfootball_holdout_lower_bound(leg,confidence=0.95):
    """Conservative per-leg probability from the exact-line holdout sample.

    This is deliberately separate from the historical settled-ticket calibration:
    the holdout lane has large exact-line samples but does not yet have enough
    settled 2–7-leg ticket outcomes to justify reusing the historical ticket shrinkage.
    """
    try:
        evidence=leg.get("recent_evidence") or {}
        n=int(evidence.get("n") or 0)
        wins=int(evidence.get("wins") or 0)
        if n<=0 or wins<0 or wins>n:
            return None
        phat=wins/n
        from statistics import NormalDist
        z=NormalDist().inv_cdf(0.5+confidence/2.0)
        z2=z*z
        denom=1.0+(z2/n)
        centre=phat+(z2/(2.0*n))
        spread=z*math.sqrt((phat*(1.0-phat)/n)+(z2/(4.0*n*n)))
        lower=(centre-spread)/denom
        return max(0.0005,min(0.9995,lower))
    except (TypeError,ValueError,AttributeError):
        return None

def _batch_metrics(legs):
    probs=[max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0))) for x in legs if float(x.get("model_probability") or 0.0)>0]
    edges=[float(x.get("model_edge") or 0.0) for x in legs]
    if not probs:
        return {
            "model_rating":0.0,
            "raw_model_rating":0.0,
            "combined_model_probability":0.0,
            "raw_combined_model_probability":0.0,
            "ticket_calibration_gamma":float(_ticket_calibration_gamma().get("gamma") or 1.0),
            "leg_strength_rating":0.0,
            "avg_model_probability":0.0,
            "avg_model_edge_percent":0.0
        }
    raw_combined=math.prod(probs)
    all_vfootball_holdout=all(
        str(x.get("qualification_lane") or "")=="vfootball_event_holdout_value"
        and str(x.get("product") or "")=="vfootball"
        for x in legs
    )
    ticket_calibration_mode="historical_settled_ticket_gamma"
    ticket_gamma=float(_ticket_calibration_gamma().get("gamma") or 1.0)
    all_efootball_evidence=all(
        str(x.get("qualification_lane") or "")=="efootball_exact_evidence_value"
        and str(x.get("product") or "").startswith("efootball_")
        for x in legs
    )
    if all_efootball_evidence:
        # Do not apply the historical VFootball ticket gamma to eFootball.
        # eFootball has no adequate settled-ticket calibration sample yet;
        # each leg already uses exact-line/side evidence calibration.
        calibrated=raw_combined
        ticket_calibration_mode="efootball_exact_evidence_independence_proxy"
        ticket_gamma=1.0
    elif all_vfootball_holdout:
        lower_bounds=[_vfootball_holdout_lower_bound(x,confidence=0.95) for x in legs]
        if all(v is not None for v in lower_bounds):
            # Preserve a common-model-error cushion while avoiding the unrelated
            # historical ticket gamma for this distinct event-holdout evidence regime.
            calibrated=max(
                0.0005,
                min(raw_combined,
                    math.prod(lower_bounds)*ACCURACY_PRESERVATION_RATIO)
            )
            ticket_calibration_mode="vfootball_event_holdout_wilson_lower_bound"
            ticket_gamma=1.0
        else:
            calibrated=_calibrated_ticket_probability(raw_combined)
    else:
        calibrated=_calibrated_ticket_probability(raw_combined)
    geometric=math.exp(sum(math.log(p) for p in probs)/len(probs))
    return {
        "model_rating":round(calibrated*100.0,2),
        "raw_model_rating":round(raw_combined*100.0,2),
        "combined_model_probability":round(calibrated,6),
        "raw_combined_model_probability":round(raw_combined,6),
        "ticket_calibration_gamma":round(ticket_gamma,4),
        "ticket_calibration_mode":ticket_calibration_mode,
        "leg_strength_rating":round(geometric*100.0,2),
        "avg_model_probability":round(sum(probs)/len(probs)*100.0,2),
        "avg_model_edge_percent":round(sum(edges)/len(edges)*100.0,2) if edges else 0.0,
    }


def _create_sportybet_booking_code(legs):
    """Request a fresh non-staking SportyBet share code for the exact live batch."""
    selections=[]
    missing=[]
    for leg in legs:
        event_id=str(leg.get("sportybet_event_id") or "")
        market_id=str(leg.get("sportybet_market_id") or "")
        outcome_id=str(leg.get("sportybet_outcome_id") or "")
        if not event_id or not market_id or not outcome_id:
            missing.append(leg.get("match") or leg.get("pick"))
            continue
        item={"eventId":event_id,"marketId":market_id,"outcomeId":outcome_id}
        if leg.get("sportybet_specifier") not in (None,""):
            item["specifier"]=leg.get("sportybet_specifier")
        selections.append(item)
    if missing:
        return {"status":"UNAVAILABLE","reason":"live_selection_mapping_incomplete","missing_legs":missing}
    payload=json.dumps({"selections":selections}).encode("utf-8")
    req=urllib.request.Request("https://www.sportybet.com/api/ng/orders/share",data=payload,method="POST",
        headers={"Accept":"application/json","Content-Type":"application/json","Current-Country":"NG","User-Agent":"Match-Signal/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:
            body=json.loads(response.read().decode("utf-8","replace"))
        data=body.get("data") or {}
        code=data.get("shareCode") or body.get("shareCode")
        if not code:
            return {"status":"UNAVAILABLE","reason":"sportybet_share_endpoint_returned_no_code","unavailable_outcomes":data.get("unavailableOutcomes") or []}
        return {"status":"AVAILABLE","booking_code":str(code),"share_url":data.get("shareURL"),
                "expires_at":data.get("deadline"),"selection_count":len(selections),
                "unavailable_outcomes":data.get("unavailableOutcomes") or []}
    except Exception as exc:
        return {"status":"UNAVAILABLE","reason":"sportybet_share_request_failed","error":str(exc)[:240]}

def _batch_capacity_diagnostic(eligible_pool):
    """Measure the best 7-leg odds capacity without weakening any gate."""
    pool=[x for x in eligible_pool if x.get("builder_eligible")]
    ranked=sorted(pool,key=lambda x:float(x.get("bookmaker_odds") or 1.0),reverse=True)
    chosen=[];events=set();participants=set();strict_product=1.0
    for leg in ranked:
        eid=str(leg.get("event_id") or "")
        if eid and eid in events: continue
        pids=set(_participants(leg))
        if pids & participants: continue
        chosen.append(leg); events.add(eid) if eid else None; participants.update(pids)
        strict_product*=float(leg.get("bookmaker_odds") or 1.0)
        if len(chosen)>=MAX_LEGS: break
    relaxed=sorted(pool,key=lambda x:float(x.get("bookmaker_odds") or 1.0),reverse=True)[:MAX_LEGS]
    relaxed_product=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in relaxed) if relaxed else 1.0
    return {
        "eligible_legs":len(pool),
        "strict_capacity_odds":round(strict_product,3),
        "strict_capacity_legs":len(chosen),
        "event_only_capacity_odds":round(relaxed_product,3),
        "event_only_capacity_legs":len(relaxed),
        "active_floor_reachable_with_current_gates":relaxed_product>=active_min_combined_odds(),
        "preferred_2_80_target_reachable":relaxed_product>=TARGET_COMBINED_ODDS,
        "target_reachable_with_current_gates":relaxed_product>=active_min_combined_odds(),
    }

def _construct_model_first_batch(
    pool,
    max_legs=MAX_LEGS,
    min_odds=MIN_COMBINED_ODDS,
    min_leg_probability=MIN_SAFE_LEG_MODEL_PROBABILITY,
):
    """Construct the strongest whole-ticket model-probability batch that can reach 4.00+.

    This is a constrained construction heuristic, not a qualification change:
    every input leg is already Builder-eligible. The selection objective is
    whole-ticket model probability; SportyBet odds are used only as the hard
    reachability constraint. Participant and event correlation rules remain
    active.
    """
    if not pool:
        return []

    def sort_model(rows):
        return sorted(rows, key=lambda x: (
            -float(x.get("model_probability") or 0.0),
            -float(x.get("evidence_score") or 0.0),
            -float(x.get("model_edge") or 0.0),
            -float(x.get("bookmaker_odds") or 1.0)
        ))

    def conflict(a, selected_events, selected_participants):
        eid=str(a.get("event_id") or "")
        if eid and eid in selected_events:
            return True
        return bool(set(_participants(a)) & selected_participants)

    def greedy(seed=None, tradeoff=0.0):
        selected=[]
        selected_events=set()
        selected_participants=set()
        remaining=list(pool)
        combined=1.0
        if seed is not None:
            selected=[seed]
            eid=str(seed.get("event_id") or "")
            if eid: selected_events.add(eid)
            selected_participants.update(_participants(seed))
            combined=float(seed.get("bookmaker_odds") or 1.0)
            remaining=[x for x in remaining if not conflict(x,selected_events,selected_participants)]
        while remaining and len(selected)<max_legs and combined<min_odds:
            feasible=[]
            slots=max_legs-len(selected)-1
            # Optimistic odds upper bound: pre-sort once per construction step
            # instead of sorting the remaining pool once per candidate.
            odds_ranked=sorted(
                [(x,float(x.get("bookmaker_odds") or 1.0)) for x in remaining
                 if float(x.get("bookmaker_odds") or 1.0)>1.0],
                key=lambda z:z[1], reverse=True
            )
            top_count=min(slots,len(odds_ranked))
            top_product=math.prod(v for _,v in odds_ranked[:top_count]) if top_count else 1.0
            next_odds=odds_ranked[top_count][1] if top_count<len(odds_ranked) else 1.0
            top_ids={id(x):v for x,v in odds_ranked[:top_count]}
            for leg in remaining:
                if conflict(leg,selected_events,selected_participants):
                    continue
                odds=float(leg.get("bookmaker_odds") or 1.0)
                if odds<=1.0:
                    continue
                new_product=combined*odds
                if slots:
                    if id(leg) in top_ids:
                        rest=(top_product/odds)*next_odds
                    else:
                        rest=top_product
                else:
                    rest=1.0
                if new_product*rest >= min_odds:
                    feasible.append(leg)
            if feasible:
                def trade_key(x):
                    p=max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0)))
                    odds=max(1.0001,float(x.get("bookmaker_odds") or 1.0))
                    # Lagrangian search explores the model/price frontier without
                    # ever changing qualification. The final winner is still
                    # selected by actual whole-ticket model probability.
                    objective=(-math.log(p))-(tradeoff*math.log(odds))
                    return (objective,-p,-float(x.get("evidence_score") or 0.0),
                            -float(x.get("model_edge") or 0.0),-odds)
                leg=min(feasible,key=trade_key)
            else:
                # No model-first addition can still reach the active odds floor within the leg cap.
                # Use the strongest model leg among remaining; do not switch to
                # price-first construction.
                compatible=[x for x in remaining if not conflict(x,selected_events,selected_participants)]
                if not compatible:
                    break
                leg=max(compatible,key=lambda x:(
                    float(x.get("model_probability") or 0.0),
                    float(x.get("evidence_score") or 0.0),
                    float(x.get("model_edge") or 0.0),
                    float(x.get("bookmaker_odds") or 1.0)
                ))
            selected.append(leg)
            eid=str(leg.get("event_id") or "")
            if eid: selected_events.add(eid)
            selected_participants.update(_participants(leg))
            combined*=float(leg.get("bookmaker_odds") or 1.0)
            remaining=[x for x in remaining if x is not leg and not conflict(x,selected_events,selected_participants)]
        return selected if combined>=min_odds else []

    ranked=sort_model(pool)
    price_ranked=sorted(pool,key=lambda x:float(x.get("bookmaker_odds") or 1.0),reverse=True)
    tradeoffs=(0.0,0.1,0.2,0.3,0.4,0.5,0.75,1.0)
    candidates=[]
    for tradeoff in tradeoffs:
        candidates.append(greedy(None,tradeoff))
        seed_rows=[]
        for row in ranked[:8]:
            if row not in seed_rows: seed_rows.append(row)
        for row in price_ranked[:4]:
            if row not in seed_rows: seed_rows.append(row)
        for row in seed_rows:
            candidates.append(greedy(row,tradeoff))
    candidates=[x for x in candidates if x and math.prod(float(y.get("bookmaker_odds") or 1.0) for y in x)>=min_odds]
    if not candidates:
        return []
    # Bounded frontier search repairs the greedy failure mode: it retains
    # both model-heavy and price-feasible paths, then chooses the highest
    # whole-ticket model probability that actually reaches the active odds floor.
    frontier=list({id(x):x for x in (ranked[:100]+price_ranked[:60])}.values())
    states=[([],set(),set(),0.0,0.0)]
    for _ in range(max_legs):
        expanded=[]
        for selected,events,participants,logp,logo in states:
            start=0
            if selected:
                try:start=frontier.index(selected[-1])+1
                except ValueError:start=0
            for idx in range(start,len(frontier)):
                leg=frontier[idx]
                if conflict(leg,events,participants): continue
                p=max(0.0005,min(0.9995,float(leg.get("model_probability") or 0.0)))
                odds=max(1.0001,float(leg.get("bookmaker_odds") or 1.0))
                ne=set(events); eid=str(leg.get("event_id") or "")
                if eid: ne.add(eid)
                np=set(participants)|set(_participants(leg))
                expanded.append((selected+[leg],ne,np,logp+math.log(p),logo+math.log(odds)))
        if not expanded: break
        by_model=sorted(expanded,key=lambda s:(s[3],s[4]),reverse=True)[:900]
        by_trade=sorted(expanded,key=lambda s:(s[3]+0.55*s[4],s[3],s[4]),reverse=True)[:900]
        merged={tuple(id(x) for x in s[0]):s for s in by_model+by_trade}
        states=list(merged.values())[:1800]
        candidates.extend([s[0] for s in states if s[4]>=math.log(min_odds)])
    # The public Builder contract is a 2–4-leg accumulator. A single high-odds leg
    # can satisfy the numeric odds floor by itself (for example a 4.00x+ single leg), but that
    # must never outrank a valid 2-leg construction and then be discarded later by
    # build_value_batches. Enforce the minimum leg count at the construction stage.
    valid=[]
    for rows in candidates:
        if not rows or not (BATCH_MIN_LEGS<=len(rows)<=min(RESULTS_FIRST_MAX_LEGS,max_legs)):
            continue
        if any(
            float(x.get("model_probability") or 0.0) < float(min_leg_probability)
            for x in rows
        ):
            continue
        odds=math.prod(float(y.get("bookmaker_odds") or 1.0) for y in rows)
        if odds<min_odds:
            continue
        raw=math.prod(max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0))) for x in rows)
        all_efootball_evidence=all(
            str(x.get("qualification_lane") or "")=="efootball_exact_evidence_value"
            and str(x.get("product") or "").startswith("efootball_")
            for x in rows
        )
        calibrated=raw if all_efootball_evidence else _calibrated_ticket_probability(raw)
        if (calibrated*odds)-1.0 < RESULTS_FIRST_MIN_EXPECTED_ROI:
            continue
        valid.append((rows,calibrated,odds))
    if valid:
        return max(valid,key=lambda item:(
            item[1],
            -len(item[0]),
            sum(float(x.get("model_edge") or 0.0) for x in item[0])/len(item[0]),
            item[2]
        ))[0]
    return []


def _kickoff_timestamp(leg):
    try:
        raw=leg.get("start_time")
        if not raw:return None
        return datetime.fromisoformat(str(raw).replace("Z","+00:00")).astimezone(timezone.utc).timestamp()
    except (TypeError,ValueError):
        return None


def _batch_kickoff_span_minutes(legs):
    stamps=[_kickoff_timestamp(x) for x in legs]
    stamps=[x for x in stamps if x is not None]
    if len(stamps)<2:return 0.0
    return (max(stamps)-min(stamps))/60.0


def _near_kickoff_window(pool, anchor):
    anchor_ts=_kickoff_timestamp(anchor)
    if anchor_ts is None:return []
    out=[]
    for x in pool:
        ts=_kickoff_timestamp(x)
        if ts is not None and 0.0 <= (ts-anchor_ts)/60.0 <= MAX_BATCH_KICKOFF_SPAN_MINUTES:
            out.append(x)
    return out


def _construct_results_first_batch(pool, max_legs=RESULTS_FIRST_MAX_LEGS):
    """Choose the strongest proven legs; odds are only a tie-breaker."""
    if not pool:
        return []
    ranked=sorted(pool,key=lambda x:(
        -float(x.get("model_probability") or 0.0),
        -float((x.get("results_first") or {}).get("accuracy") or 0.0),
        -int((x.get("results_first") or {}).get("n") or 0),
        -float(x.get("bookmaker_odds") or 1.0)
    ))
    selected=[]
    events=set()
    participants=set()
    for leg in ranked:
        eid=str(leg.get("event_id") or "")
        if eid and eid in events:
            continue
        pids=set(_participants(leg))
        if pids & participants:
            continue
        selected.append(leg)
        if eid:
            events.add(eid)
        participants.update(pids)
        if len(selected)>=max_legs:
            break
    return selected

def _construct_mixed_virtual_efootball_batches(pool, max_batches=4, max_legs=MIXED_RESEARCH_MAX_LEGS, min_odds=None):
    """Build several disjoint 1x VFootball + 1-3x eFootball research batches.

    Every leg has already passed its individual Builder gates. This function
    only performs controlled composition and keeps batches disjoint by event and
    participant identity so the Builder offers multiple independent choices from
    the same fresh market scan.
    """
    if min_odds is None:
        min_odds=active_min_combined_odds()

    vpool=[
        x for x in pool
        if str(x.get("product") or "")=="vfootball"
        and str(x.get("qualification_lane") or "") in {"vfootball_exact_evidence_value","vfootball_event_holdout_value"}
        and float(x.get("model_probability") or 0.0)>=VIRTUAL_MIN_PROB
        and float(x.get("expected_value") or 0.0)>=0.0
    ]
    epool=[
        x for x in pool
        if str(x.get("product") or "").startswith("efootball_")
        and str(x.get("qualification_lane") or "")=="efootball_exact_evidence_value"
        and float(x.get("model_probability") or 0.0)>=VIRTUAL_MIN_PROB
        and float(x.get("expected_value") or 0.0)>=0.0
    ]

    vpool=sorted(vpool,key=lambda x:(
        -float(x.get("model_probability") or 0.0),
        -float(x.get("evidence_score") or 0.0),
        -float(x.get("model_edge") or 0.0),
        -float(x.get("bookmaker_odds") or 1.0),
        _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"),
    ))[:50]
    epool=sorted(epool,key=lambda x:(
        -float(x.get("model_probability") or 0.0),
        -float(x.get("evidence_score") or 0.0),
        -float(x.get("model_edge") or 0.0),
        -float(x.get("bookmaker_odds") or 1.0),
        _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"),
    ))[:14]

    vpool=vpool[:30]

    # Adaptive 2–7 leg construction. A longer ticket is considered only when
    # every leg clears the stronger safety tier for that final leg count.
    import itertools
    options=[]
    considered=0

    for e_count in range(1,max_legs):
        shape=1+e_count
        required_leg_prob=min_model_probability_for_leg_count(shape)
        for vleg in vpool:
            if float(vleg.get("model_probability") or 0.0)<required_leg_prob:
                continue
            for es in itertools.combinations(epool,e_count):
                rows=[vleg,*es]
                if any(float(x.get("model_probability") or 0.0)<required_leg_prob for x in rows):
                    continue
                event_ids=[str(x.get("event_id") or "") for x in rows if x.get("event_id")]
                if len(event_ids)!=len(set(event_ids)):
                    continue
                participants=[]
                for row in rows:
                    participants.extend(_participants(row))
                if len(participants)!=len(set(participants)):
                    continue
                span=_batch_kickoff_span_minutes(rows)
                if span>MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES:
                    continue
                odds=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in rows)
                if odds<min_odds:
                    continue
                metrics=_batch_metrics(rows)
                avg_prob=float(metrics.get("avg_model_probability") or 0.0)
                roi=(float(metrics.get("combined_model_probability") or 0.0)*odds)-1.0
                if avg_prob<MIXED_RESEARCH_MIN_AVG_PROBABILITY or roi<RESULTS_FIRST_MIN_EXPECTED_ROI:
                    continue
                if not legs_meet_safe_model_threshold(rows):
                    continue
                considered+=1
                preferred_share=sum(
                    1 for x in rows
                    if float(x.get("model_probability") or 0.0)>=PREFERRED_LEG_MODEL_PROBABILITY
                )/len(rows)
                options.append({
                    "rows":rows,
                    "metrics":metrics,
                    "odds":odds,
                    "span":span,
                    "roi":roi,
                    "score":(
                        shape,
                        min(float(x.get("model_probability") or 0.0) for x in rows),
                        avg_prob,
                        preferred_share,
                        float(metrics.get("combined_model_probability") or 0.0),
                        float(metrics.get("avg_model_edge_percent") or 0.0),
                        roi,
                        odds,
                    )
                })

    # The first sort key is leg count, so larger options surface when all legs
    # are strong enough. No weak leg is ever added just to reach an odds target.
    options.sort(key=lambda o:o["score"],reverse=True)
    selected_batches=[]
    used_events=set()
    used_participants=set()

    for option in options:
        if len(selected_batches)>=max_batches:
            break
        rows=option["rows"]
        event_ids={str(x.get("event_id") or "") for x in rows if x.get("event_id")}
        participants={p for row in rows for p in _participants(row)}
        if event_ids & used_events or participants & used_participants:
            continue
        selected_batches.append(option)
        used_events.update(event_ids)
        used_participants.update(participants)

    return selected_batches,{
        "vfootball_pool":len(vpool),
        "efootball_pool":len(epool),
        "candidate_combinations":considered,
        "batches_selected":len(selected_batches),
        "max_batches":max_batches,
        "min_combined_odds":min_odds,
        "disjoint":True,
        "batch_leg_counts":[len(x["rows"]) for x in selected_batches],
        "combined_odds":[round(float(x["odds"]),3) for x in selected_batches],
        "expected_rois":[round(float(x["roi"]),6) for x in selected_batches],
        "kickoff_spans":[round(float(x["span"]),1) for x in selected_batches],
        "composition":[
            ["vfootball"]+[str(row.get("product") or "") for row in option["rows"] if str(row.get("product") or "")!="vfootball"]
            for option in selected_batches
        ],
        "reason":None if selected_batches else "no_mixed_combination_reached_all_gates"
    }

def _construct_high_confidence_value_batches(pool,max_batches=4,max_legs=MIXED_RESEARCH_MAX_LEGS,min_odds=None):
    """Build several disjoint 2–7 leg research batches from >=80% exact-evidence legs.

    Uses a bounded beam/frontier rather than exhaustive combinations, so a large
    live candidate pool cannot make the Builder refresh unresponsive.
    """
    if min_odds is None:
        min_odds=active_min_combined_odds()
    eligible=[
        x for x in pool
        if str(x.get("qualification_lane") or "") in {
            "vfootball_exact_evidence_value","vfootball_event_holdout_value","efootball_exact_evidence_value"
        }
        and float(x.get("model_probability") or 0.0)>=MIN_SAFE_LEG_MODEL_PROBABILITY
        and float(x.get("expected_value") or 0.0)>=0.0
    ]
    # Keep enough diversity for four disjoint batches while bounding the search.
    model_rank=sorted(eligible,key=lambda x:(
        -float(x.get("model_probability") or 0.0),
        -float(x.get("evidence_score") or 0.0),
        -float(x.get("model_edge") or 0.0),
        _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"),
    ))
    odds_rank=sorted(eligible,key=lambda x:(
        -float(x.get("bookmaker_odds") or 1.0),
        -float(x.get("model_probability") or 0.0),
        -float(x.get("model_edge") or 0.0),
    ))
    early_rank=sorted(eligible,key=lambda x:(
        _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"),
        -float(x.get("model_probability") or 0.0),
        -float(x.get("bookmaker_odds") or 1.0),
    ))
    pool_cap=22
    bounded=[]
    for row in model_rank[:20]+odds_rank[:12]+early_rank[:12]:
        if row not in bounded:
            bounded.append(row)
        if len(bounded)>=pool_cap:
            break
    eligible=bounded

    import itertools
    states=[]
    for shape in range(BATCH_MIN_LEGS,max_legs+1):
        required=min_model_probability_for_leg_count(shape)
        expanded=[]
        for combo in itertools.combinations(eligible,shape):
            if any(float(x.get("model_probability") or 0.0)<required for x in combo):
                continue
            event_ids=[str(x.get("event_id") or "") for x in combo if x.get("event_id")]
            if len(event_ids)!=len(set(event_ids)):
                continue
            participants=[p for row in combo for p in _participants(row)]
            if len(participants)!=len(set(participants)):
                continue
            span=_batch_kickoff_span_minutes(combo)
            if span>MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES:
                continue
            odds=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in combo)
            if odds<min_odds:
                continue
            metrics=_batch_metrics(list(combo))
            avg_prob=float(metrics.get("avg_model_probability") or 0.0)
            roi=(float(metrics.get("combined_model_probability") or 0.0)*odds)-1.0
            if avg_prob<MIN_SAFE_LEG_MODEL_PROBABILITY or roi<RESULTS_FIRST_MIN_EXPECTED_ROI:
                continue
            strong_count=sum(1 for x in combo if float(x.get("model_probability") or 0.0)>=PREFERRED_LEG_MODEL_PROBABILITY)
            expanded.append({
                "rows":list(combo),"metrics":metrics,"odds":odds,"span":span,"roi":roi,
                "score":(
                    shape,
                    min(float(x.get("model_probability") or 0.0) for x in combo),
                    strong_count,
                    avg_prob,
                    float(metrics.get("combined_model_probability") or 0.0),
                    float(metrics.get("avg_model_edge_percent") or 0.0),
                    roi,
                    odds,
                )
            })
        expanded.sort(key=lambda o:o["score"],reverse=True)
        states.extend(expanded[:400])
    options=sorted(states,key=lambda o:o["score"],reverse=True)
    # Evaluate all adaptive shapes together, then prefer the largest shape only
    # when it actually clears the same calibrated whole-ticket ROI gate. A weak
    # 4-leg frontier must never suppress a viable 2- or 3-leg construction.

    selected=[]
    used_events=set()
    used_participants=set()
    for option in options:
        if len(selected)>=max_batches:
            break
        rows=option["rows"]
        events={str(x.get("event_id") or "") for x in rows if x.get("event_id")}
        participants={p for row in rows for p in _participants(row)}
        if events & used_events or participants & used_participants:
            continue
        selected.append(option)
        used_events.update(events)
        used_participants.update(participants)

    return selected,{
        "eligible_legs":len(eligible),
        "candidate_combinations":len(options),
        "batches_selected":len(selected),
        "max_batches":max_batches,
        "min_combined_odds":min_odds,
        "min_per_leg_model_probability":MIN_SAFE_LEG_MODEL_PROBABILITY,
        "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
        "batch_leg_counts":[len(x["rows"]) for x in selected],
        "combined_odds":[round(float(x["odds"]),3) for x in selected],
        "expected_rois":[round(float(x["roi"]),6) for x in selected],
        "kickoff_spans":[round(float(x["span"]),1) for x in selected],
        "products":[sorted({str(row.get("product") or "") for row in x["rows"]}) for x in selected],
        "reason":None if selected else "no_high_confidence_combination_reached_all_gates"
    }

def _construct_vfootball_holdout_batches(pool,max_batches=4,max_legs=MIXED_RESEARCH_MAX_LEGS,min_odds=None):
    """Build disjoint VFootball holdout batches without the cross-sport frontier cap.

    Inputs are already Builder-eligible exact-line event-holdout legs. The lane
    keeps the same 80% per-leg floor, fresh-price/positive-EV filters, event and
    participant correlation rules, 2.70+ combined-odds floor and +2% calibrated
    whole-ticket ROI gate. It evaluates the active 2–4-leg range directly
    so a large low-price virtual pool cannot hide a viable high-price construction.
    """
    if min_odds is None:
        min_odds=active_min_combined_odds()
    eligible=[
        x for x in pool
        if str(x.get("qualification_lane") or "")=="vfootball_event_holdout_value"
        and str(x.get("product") or "")=="vfootball"
        and float(x.get("model_probability") or 0.0)>=MIN_SAFE_LEG_MODEL_PROBABILITY
        and float(x.get("expected_value") or 0.0)>=0.0
    ]
    # Price-first ordering keeps the accumulator target reachable while all
    # candidates remain subject to the same model/ROI/correlation gates below.
    eligible=sorted(
        eligible,
        key=lambda x:(
            -float(x.get("bookmaker_odds") or 1.0),
            -float(x.get("model_probability") or 0.0),
            -float(x.get("model_edge") or 0.0),
            _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")
        )
    )[:18]

    import itertools
    options=[]
    rejection_counts={"probability":0,"event":0,"participant":0,"span":0,"odds":0,"average_probability":0,"roi":0,"safety":0}
    first_failure_samples=[]
    for shape in range(BATCH_MIN_LEGS,max_legs+1):
        required=min_model_probability_for_leg_count(shape)
        for combo in itertools.combinations(eligible,shape):
            reason=None
            if any(float(x.get("model_probability") or 0.0)<required for x in combo):
                rejection_counts["probability"]+=1; reason="probability"
            if reason is None:
                event_ids=[str(x.get("event_id") or "") for x in combo if x.get("event_id")]
                if len(event_ids)!=len(set(event_ids)):
                    rejection_counts["event"]+=1; reason="event"
            if reason is None:
                participants=[p for row in combo for p in _participants(row)]
                if len(participants)!=len(set(participants)):
                    rejection_counts["participant"]+=1; reason="participant"
            if reason is None:
                span=_batch_kickoff_span_minutes(combo)
                if span>MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES:
                    rejection_counts["span"]+=1; reason="span"
            if reason is None:
                odds=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in combo)
                if odds<min_odds:
                    rejection_counts["odds"]+=1; reason="odds"
            if reason is None:
                metrics=_batch_metrics(list(combo))
                raw_avg=sum(float(x.get("model_probability") or 0.0) for x in combo)/shape
                if raw_avg<required:
                    rejection_counts["average_probability"]+=1; reason="average_probability"
            if reason is None:
                calibrated=float(metrics.get("combined_model_probability") or 0.0)
                roi=(calibrated*odds)-1.0
                if roi<RESULTS_FIRST_MIN_EXPECTED_ROI:
                    rejection_counts["roi"]+=1; reason="roi"
            if reason is None:
                if not legs_meet_safe_model_threshold(list(combo)):
                    rejection_counts["safety"]+=1; reason="safety"
            if reason is not None:
                if len(first_failure_samples)<8 and shape==2:
                    sample={
                        "reason":reason,
                        "legs":[str(x.get("match") or "") for x in combo],
                        "odds":round(math.prod(float(x.get("bookmaker_odds") or 1.0) for x in combo),3),
                        "probabilities":[round(float(x.get("model_probability") or 0.0),6) for x in combo],
                    }
                    if reason=="roi":
                        sample["raw_combined_probability"]=round(math.prod(float(x.get("model_probability") or 0.0) for x in combo),6)
                        sample["calibrated_probability"]=round(float(metrics.get("combined_model_probability") or 0.0),6)
                        sample["ticket_calibration_gamma"]=round(float(_ticket_calibration_gamma().get("gamma") or 1.0),6)
                        sample["roi"]=round(float(roi),6)
                    first_failure_samples.append(sample)
                continue
            options.append({
                "rows":list(combo),
                "metrics":metrics,
                "odds":odds,
                "span":span,
                "roi":roi,
                "score":(
                    calibrated,
                    min(float(x.get("model_probability") or 0.0) for x in combo),
                    raw_avg,
                    sum(float(x.get("model_edge") or 0.0) for x in combo)/shape,
                    roi,
                    odds,
                    shape,
                )
            })

    options.sort(key=lambda x:x["score"],reverse=True)
    selected=[]
    used_events=set()
    used_participants=set()
    for option in options:
        if len(selected)>=max_batches:
            break
        rows=option["rows"]
        events={str(x.get("event_id") or "") for x in rows if x.get("event_id")}
        participants={p for row in rows for p in _participants(row)}
        if events & used_events or participants & used_participants:
            continue
        selected.append(option)
        used_events.update(events)
        used_participants.update(participants)

    return selected,{
        "eligible_legs":len(eligible),
        "candidate_combinations":len(options),
        "batches_selected":len(selected),
        "max_batches":max_batches,
        "min_combined_odds":min_odds,
        "min_per_leg_model_probability":MIN_SAFE_LEG_MODEL_PROBABILITY,
        "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
        "batch_leg_counts":[len(x["rows"]) for x in selected],
        "combined_odds":[round(float(x["odds"]),3) for x in selected],
        "expected_rois":[round(float(x["roi"]),6) for x in selected],
        "kickoff_spans":[round(float(x["span"]),1) for x in selected],
        "rejection_counts":rejection_counts,
        "first_failure_samples":first_failure_samples,
        "reason":None if selected else "no_vfootball_holdout_combination_reached_all_gates"
    }

def build_value_batches(candidates):
    """Build one results-first paper ticket using the best proven 2–7-leg shape.

    A shape is promoted only when its own settled-ticket sample, realized odds,
    historical ROI, exact-line evidence, and current expected ROI all pass.
    No extra leg is added merely to reach a target.
    """
    built=[make_leg(x) for x in candidates]
    # Diagnostic-only snapshot of the settled 2–4-leg construction lane.
    # This does not alter eligibility or selection; it only exposes why a shape
    # cannot currently be promoted when the Builder returns NO_BET.
    construction_shapes=construction_shape_diagnostics("vfootball")
    eligible_all=[x for x in built if x.get("builder_eligible")]
    eligible_results=[
        x for x in eligible_all
        if RESULTS_FIRST_ENABLED
        and (x.get("results_first") or {}).get("eligible") is True
    ]
    vfootball_pool=[x for x in eligible_results if str(x.get("product") or "")=="vfootball"]
    ordered=sorted(vfootball_pool,key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")))

    promoted_shape=None
    if ordered:
        gate_info=(ordered[0].get("results_first") or {})
        promoted_shape=gate_info.get("construction_leg_count")
        try:
            promoted_shape=int(promoted_shape) if promoted_shape is not None else None
        except (TypeError,ValueError):
            promoted_shape=None

    window_candidates=[]
    allowed_shapes=tuple(sorted({
        int(shape) for shape in RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS
        if int(shape)>=BATCH_MIN_LEGS and int(shape)<=RESULTS_FIRST_MAX_LEGS
    }))
    for anchor in ordered:
        window=_near_kickoff_window(ordered,anchor)
        for shape in allowed_shapes:
            candidate=_construct_results_first_batch(window,max_legs=shape)
            if len(candidate)!=shape:
                continue
            if not legs_meet_safe_model_threshold(candidate):
                continue
            if _batch_kickoff_span_minutes(candidate)<=MAX_BATCH_KICKOFF_SPAN_MINUTES:
                window_candidates.append(candidate)

    batches=[]
    used_events=set()
    results_first_rejection=None
    if window_candidates:
        batch=max(window_candidates,key=lambda rows:(
            len(rows),
            min(float(x.get("model_probability") or 0.0) for x in rows),
            sum(float(x.get("model_probability") or 0.0) for x in rows)/len(rows),
            math.prod(max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0))) for x in rows),
            min(_kickoff_timestamp(x) for x in rows if _kickoff_timestamp(x) is not None)
        ))
        batch=sorted(batch,key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")))
        metrics=_batch_metrics(batch)
        combined=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in batch)
        current_expected_roi=(float(metrics.get("combined_model_probability") or 0.0)*combined)-1.0
        if combined < active_min_combined_odds() or current_expected_roi < RESULTS_FIRST_MIN_EXPECTED_ROI:
            results_first_rejection={
                "reason":"combined_odds_or_expected_roi_below_results_first_gate",
                "candidate_combined_odds":round(combined,3),
                "candidate_expected_roi":round(current_expected_roi,6),
                "active_min_combined_odds":active_min_combined_odds(),
                "min_expected_roi":RESULTS_FIRST_MIN_EXPECTED_ROI,
            }
        else:
            batch_events={str(x.get("event_id") or "") for x in batch if x.get("event_id")}
            used_events.update(batch_events)
            batches.append({
                "batch_id":"BATCH-01",
                "label":f"BATCH-01 · Results-first Model Rating {metrics['model_rating']:.1f}/100",
                "rank_pending":False,
                "rank":1,
                "legs":batch,
                "leg_count":len(batch),
                "combined_odds":round(combined,3),
                "combined_model_rating":metrics["model_rating"],
                "combined_model_probability":metrics["combined_model_probability"],
                "leg_strength_rating":metrics["leg_strength_rating"],
                "avg_model_probability":metrics["avg_model_probability"],
                "avg_model_edge_percent":metrics["avg_model_edge_percent"],
                "products":sorted({str(x.get("product") or "") for x in batch if x.get("product")}),
                "primary_lane":"vfootball",
                "paper_only":True,
                "real_money_execution":False,
                "correlation_policy":"same-event and participant reuse prevented; only results-first qualified legs",
                "construction_objective":"maximize settled-results-backed whole-ticket probability; odds are secondary and never force weaker legs"
            })

    if not batches:
        # Controlled mixed research lane: when Results-first VFootball cannot
        # qualify, allow exactly 1 VFootball evidence-value leg plus 1-2
        # eFootball evidence-value legs. This is still research-only and does
        # not promote the batch to settled Results-first evidence.
        mixed_pool=[
            x for x in eligible_all
            if str(x.get("qualification_lane") or "") in {
                "vfootball_exact_evidence_value","vfootball_event_holdout_value","efootball_exact_evidence_value"
            }
        ]
        mixed_diag={
            "vfootball_pool":0,
            "efootball_pool":0,
            "candidate_combinations":0,
            "batches_selected":0,
            "max_batches":min(4,MAX_BATCHES),
            "min_combined_odds":active_min_combined_odds(),
            "disjoint":True,
            "batch_leg_counts":[],
            "combined_odds":[],
            "expected_rois":[],
            "kickoff_spans":[],
            "composition":[],
            "reason":"not_run"
        }
        mixed_pool=[
            x for x in eligible_all
            if str(x.get("qualification_lane") or "") in {
                "vfootball_exact_evidence_value","vfootball_event_holdout_value","efootball_exact_evidence_value"
            }
        ]
        mixed_options,mixed_diag=_construct_mixed_virtual_efootball_batches(
            mixed_pool,
            max_batches=min(4,MAX_BATCHES),
            max_legs=MIXED_RESEARCH_MAX_LEGS,
            min_odds=active_min_combined_odds()
        )
        if mixed_options:
            mixed_batches=[]
            mixed_options.sort(
                key=lambda option:min(
                    _kickoff_timestamp(x) for x in option["rows"]
                    if _kickoff_timestamp(x) is not None
                ) if any(_kickoff_timestamp(x) is not None for x in option["rows"]) else float("inf")
            )
            for idx,option in enumerate(mixed_options,1):
                mixed_batch=sorted(
                    option["rows"],
                    key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"))
                )
                mixed_metrics=option["metrics"]
                mixed_combined=float(option["odds"])
                mixed_batches.append({
                    "batch_id":f"BATCH-{idx:02d}",
                    "label":f"BATCH-{idx:02d} · Mixed Value Model Rating {mixed_metrics['model_rating']:.1f}/100",
                    "rank_pending":False,
                    "rank":idx,
                    "legs":mixed_batch,
                    "leg_count":len(mixed_batch),
                    "combined_odds":round(mixed_combined,3),
                    "combined_model_rating":mixed_metrics["model_rating"],
                    "combined_model_probability":mixed_metrics["combined_model_probability"],
                    "raw_combined_model_probability":mixed_metrics["raw_combined_model_probability"],
                    "ticket_calibration_gamma":mixed_metrics["ticket_calibration_gamma"],
                    "leg_strength_rating":mixed_metrics["leg_strength_rating"],
                    "avg_model_probability":mixed_metrics["avg_model_probability"],
                    "avg_model_edge_percent":mixed_metrics["avg_model_edge_percent"],
                    "products":sorted({str(x.get("product") or "") for x in mixed_batch if x.get("product")}),
                    "primary_lane":"mixed_vfootball_efootball_value",
                    "paper_only":True,
                    "real_money_execution":False,
                    "correlation_policy":"batches disjoint by event and participant; each batch contains 1 VFootball + 1-6 eFootball evidence-value legs and every leg meets the adaptive safety tier",
                    "construction_objective":"provide multiple independent paper choices from one fresh scan; prefer the largest safe 2–7-leg shape without forcing weak legs"
                })
            return mixed_batches,built,{
                "batch_count":len(mixed_batches),
                "max_batches":min(4,MAX_BATCHES),
                "disjoint":True,
                "min_combined_odds":active_min_combined_odds(),
                "target_combined_odds":TARGET_COMBINED_ODDS,
                "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
                "construction_priority":"mixed_vfootball_efootball_research",
                "priority_product":"mixed",
                "max_legs":MIXED_RESEARCH_MAX_LEGS,
                "adaptive_leg_counts":[2,3,4],
                "per_leg_min_model_probability":LEG_COUNT_MIN_MODEL_PROBABILITY,
                "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
                "construction_shapes_considered":[2,3,4,5,6,7],
                "promoted_construction_leg_count":None,
                "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
                "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
                "used_unique_events":len({str(x.get("event_id") or "") for b in mixed_batches for x in b["legs"] if x.get("event_id")}),
                "eligible_results_first_legs":len(eligible_results),
                "mixed_pool_eligible_legs":len(mixed_pool),
                "mixed_diagnostics":mixed_diag,
                "mixed_max_kickoff_span_minutes":MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES,
                "secondary_pool_eligible_legs":0,
                "capacity":_batch_capacity_diagnostic(mixed_pool),
                "construction_shape_diagnostics":construction_shapes,
                "ranking_metric":"whole-ticket model probability first, leg strength second, exact current edge third, odds as hard reachability constraint; batches disjoint"
            }

        # VFootball-only holdout fallback: the mixed lane intentionally requires
        # an eFootball partner, but a safe VFootball pair should never be suppressed
        # merely because the much larger eFootball pool fills the shared search cap.
        # This lane uses the exact same 80% per-leg, fresh-price, correlation, odds,
        # and calibrated whole-ticket ROI gates.
        vfootball_candidates=[
            x for x in eligible_all
            if str(x.get("qualification_lane") or "")=="vfootball_event_holdout_value"
            and str(x.get("product") or "")=="vfootball"
            and float(x.get("model_probability") or 0.0)>=MIN_SAFE_LEG_MODEL_PROBABILITY
            and float(x.get("expected_value") or 0.0)>=0.0
        ]
        # The generic constructor deliberately caps its search frontier at 36.
        # For this lane, sort the input by live bookmaker price first so that
        # high-price holdout legs are not crowded out by hundreds of near-1.0
        # probability / 1.0x-price candidates. Eligibility thresholds are
        # unchanged; this only changes which already-eligible rows are searched.
        vfootball_holdout_pool=sorted(
            vfootball_candidates,
            key=lambda x:(
                -float(x.get("bookmaker_odds") or 1.0),
                -float(x.get("model_probability") or 0.0),
                -float(x.get("model_edge") or 0.0),
                _kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")
            )
        )[:60]
        vfootball_options,vfootball_diag=_construct_vfootball_holdout_batches(
            vfootball_holdout_pool,
            max_batches=min(4,MAX_BATCHES),
            max_legs=RESULTS_FIRST_MAX_LEGS,
            min_odds=active_min_combined_odds()
        )
        if vfootball_options:
            vfootball_batches=[]
            vfootball_options.sort(
                key=lambda option:min(
                    _kickoff_timestamp(x) for x in option["rows"]
                    if _kickoff_timestamp(x) is not None
                ) if any(_kickoff_timestamp(x) is not None for x in option["rows"]) else float("inf")
            )
            for idx,option in enumerate(vfootball_options,1):
                rows=sorted(
                    option["rows"],
                    key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"))
                )
                metrics=option["metrics"]
                odds=float(option["odds"])
                vfootball_batches.append({
                    "batch_id":f"BATCH-{idx:02d}",
                    "label":f"BATCH-{idx:02d} · VFootball Holdout Model Rating {metrics['model_rating']:.1f}/100",
                    "rank_pending":False,
                    "rank":idx,
                    "legs":rows,
                    "leg_count":len(rows),
                    "combined_odds":round(odds,3),
                    "combined_model_rating":metrics["model_rating"],
                    "combined_model_probability":metrics["combined_model_probability"],
                    "raw_combined_model_probability":metrics["raw_combined_model_probability"],
                    "ticket_calibration_gamma":metrics["ticket_calibration_gamma"],
                    "leg_strength_rating":metrics["leg_strength_rating"],
                    "avg_model_probability":metrics["avg_model_probability"],
                    "avg_model_edge_percent":metrics["avg_model_edge_percent"],
                    "products":["vfootball"],
                    "primary_lane":"vfootball_event_holdout_value",
                    "paper_only":True,
                    "real_money_execution":False,
                    "correlation_policy":"batches disjoint by event and participant; exact-line VFootball holdout legs only",
                    "construction_objective":"maximize whole-ticket VFootball event-holdout probability subject to the active 2.70+ odds and calibrated ROI gates"
                })
            return vfootball_batches,built,{
                "batch_count":len(vfootball_batches),
                "max_batches":min(4,MAX_BATCHES),
                "disjoint":True,
                "min_combined_odds":active_min_combined_odds(),
                "target_combined_odds":TARGET_COMBINED_ODDS,
                "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
                "construction_priority":"vfootball_event_holdout_value",
                "priority_product":"vfootball",
                "max_legs":RESULTS_FIRST_MAX_LEGS,
                "adaptive_leg_counts":[2,3,4],
                "per_leg_min_model_probability":LEG_COUNT_MIN_MODEL_PROBABILITY,
                "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
                "construction_shapes_considered":[2,3,4,5,6,7],
                "promoted_construction_leg_count":None,
                "max_kickoff_span_minutes":MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES,
                "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
                "used_unique_events":len({str(x.get("event_id") or "") for b in vfootball_batches for x in b["legs"] if x.get("event_id")}),
                "eligible_results_first_legs":len(eligible_results),
                "mixed_pool_eligible_legs":len(mixed_pool),
                "mixed_diagnostics":mixed_diag,
                "pure_vfootball_diagnostics":vfootball_diag,
                "results_first_rejection":results_first_rejection,
                "secondary_pool_eligible_legs":0,
                "capacity":_batch_capacity_diagnostic(vfootball_options[0]["rows"])
            }

        # Isolated Phase 2 cyclical-loop lane. It is considered only after the
        # proven/results-first and existing mixed research lanes fail. Its batches
        # contain Virtual/eFootball legs only and are capped at 2–3 legs.
        phase2_options,phase2_diag=_construct_phase2_cyclical_loop_batches(
            eligible_all,
            max_batches=min(4,MAX_BATCHES),
            min_odds=active_min_combined_odds()
        )
        if phase2_options:
            phase2_batches=[]
            for idx,option in enumerate(phase2_options,1):
                rows=sorted(
                    option["rows"],
                    key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"))
                )
                metrics=option["metrics"]
                odds=float(option["odds"])
                risk=option.get("kelly_risk") or _phase2_kelly_diagnostic(metrics.get("combined_model_probability"),odds)
                phase2_batches.append({
                    "batch_id":f"BATCH-{idx:02d}",
                    "label":f"BATCH-{idx:02d} · Phase 2 Cyclical Loop {metrics['model_rating']:.1f}/100",
                    "rank_pending":False,
                    "rank":idx,
                    "legs":rows,
                    "leg_count":len(rows),
                    "combined_odds":round(odds,3),
                    "combined_model_rating":metrics["model_rating"],
                    "combined_model_probability":metrics["combined_model_probability"],
                    "raw_combined_model_probability":metrics["raw_combined_model_probability"],
                    "ticket_calibration_gamma":metrics["ticket_calibration_gamma"],
                    "leg_strength_rating":metrics["leg_strength_rating"],
                    "avg_model_probability":metrics["avg_model_probability"],
                    "avg_model_edge_percent":metrics["avg_model_edge_percent"],
                    "products":sorted({str(row.get("product") or "") for row in rows}),
                    "primary_lane":"phase2_cyclical_loop",
                    "execution_track":"PHASE2_CYCLICAL_LOOP",
                    "paper_only":True,
                    "real_money_execution":False,
                    "cyclical_loop_policy":{
                        "min_confidence":PHASE2_CYCLICAL_MIN_CONFIDENCE,
                        "max_legs":PHASE2_CYCLICAL_MAX_LEGS,
                        "min_legs":PHASE2_CYCLICAL_MIN_LEGS,
                        "strict_virtual_efootball_isolation":True,
                        "baseline_mixing":False
                    },
                    "risk_diagnostic":risk,
                    "correlation_policy":"batch is disjoint by event and participant; no baseline football/tennis/Poisson legs are mixed into this track",
                    "construction_objective":"maximize isolated streak-break confidence and calibrated whole-ticket probability while preserving the existing 2.70x and +2% ROI gates"
                })
            return phase2_batches,built,{
                "batch_count":len(phase2_batches),
                "max_batches":min(4,MAX_BATCHES),
                "disjoint":True,
                "min_combined_odds":active_min_combined_odds(),
                "target_combined_odds":TARGET_COMBINED_ODDS,
                "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
                "construction_priority":"phase2_cyclical_loop",
                "priority_product":"virtual_only",
                "max_legs":PHASE2_CYCLICAL_MAX_LEGS,
                "adaptive_leg_counts":[PHASE2_CYCLICAL_MIN_LEGS,PHASE2_CYCLICAL_MAX_LEGS],
                "per_leg_min_model_probability":PHASE2_CYCLICAL_MIN_CONFIDENCE,
                "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
                "construction_shapes_considered":[2,3],
                "promoted_construction_leg_count":None,
                "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
                "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
                "used_unique_events":len({str(x.get("event_id") or "") for b in phase2_batches for x in b["legs"] if x.get("event_id")}),
                "phase2_cyclical_loop":phase2_diag,
                "capacity":_batch_capacity_diagnostic([x for b in phase2_batches for x in b["legs"]]),
                "ranking_metric":"minimum streak-break confidence first; calibrated whole-ticket probability second; ROI/odds tie-breaker",
                "strict_isolation":True
            }

        # High-confidence adaptive lane: when the VFootball/eFootball mixed
        # composition cannot be formed, use any 2–7 legs that individually clear
        # the 80% safety floor. This avoids forcing a weak eFootball leg merely
        # to preserve a sport mix.
        high_options,high_diag=_construct_high_confidence_value_batches(
            mixed_pool,
            max_batches=min(4,MAX_BATCHES),
            max_legs=RESULTS_FIRST_MAX_LEGS,
            min_odds=active_min_combined_odds()
        )
        if high_options:
            high_batches=[]
            high_options.sort(
                key=lambda option:min(
                    _kickoff_timestamp(x) for x in option["rows"]
                    if _kickoff_timestamp(x) is not None
                ) if any(_kickoff_timestamp(x) is not None for x in option["rows"]) else float("inf")
            )
            for idx,option in enumerate(high_options,1):
                rows=sorted(
                    option["rows"],
                    key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"))
                )
                metrics=option["metrics"]
                odds=float(option["odds"])
                high_batches.append({
                    "batch_id":f"BATCH-{idx:02d}",
                    "label":f"BATCH-{idx:02d} · High-Confidence Model Rating {metrics['model_rating']:.1f}/100",
                    "rank_pending":False,
                    "rank":idx,
                    "legs":rows,
                    "leg_count":len(rows),
                    "combined_odds":round(odds,3),
                    "combined_model_rating":metrics["model_rating"],
                    "combined_model_probability":metrics["combined_model_probability"],
                    "raw_combined_model_probability":metrics["raw_combined_model_probability"],
                    "ticket_calibration_gamma":metrics["ticket_calibration_gamma"],
                    "leg_strength_rating":metrics["leg_strength_rating"],
                    "avg_model_probability":metrics["avg_model_probability"],
                    "avg_model_edge_percent":metrics["avg_model_edge_percent"],
                    "products":sorted({str(x.get("product") or "") for x in rows if x.get("product")}),
                    "primary_lane":"high_confidence_research",
                    "paper_only":True,
                    "real_money_execution":False,
                    "correlation_policy":"batches disjoint by event and participant; every leg clears the 80% safety floor and 90% is preferred",
                    "construction_objective":"prefer the largest safe 2–4-leg construction without adding a weak leg for odds"
                })
            return high_batches,built,{
                "batch_count":len(high_batches),
                "max_batches":min(4,MAX_BATCHES),
                "disjoint":True,
                "min_combined_odds":active_min_combined_odds(),
                "target_combined_odds":TARGET_COMBINED_ODDS,
                "construction_priority":"high_confidence_adaptive_research",
                "priority_product":"mixed",
                "max_legs":7,
                "adaptive_leg_counts":[2,3,4],
                "per_leg_min_model_probability":LEG_COUNT_MIN_MODEL_PROBABILITY,
                "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
                "mixed_diagnostics":mixed_diag,
                "high_confidence_diagnostics":high_diag,
                "used_unique_events":len({str(x.get("event_id") or "") for b in high_batches for x in b["legs"] if x.get("event_id")}),
                "eligible_results_first_legs":len(eligible_results),
                "mixed_pool_eligible_legs":len(mixed_pool),
                "capacity":_batch_capacity_diagnostic(mixed_pool),
                "construction_shape_diagnostics":construction_shapes,
                "ranking_metric":"largest safe leg count first; per-leg model probability and 90%+ strength next; odds satisfy the active floor"
            }

        # Secondary value lane: only runs after both proven vFootball and the
        # controlled mixed VFootball/eFootball research lane cannot produce a valid
        # ticket. Every input is still Builder-eligible with a fresh SportyBet price
        # and >=2.5% current model edge.
        secondary_pool=[
            x for x in eligible_all
            if str(x.get("product") or "")!="vfootball"
            and (
                str(x.get("sport") or "") in {"football","tennis"}
                or str(x.get("product") or "").startswith("efootball_")
            )
            # A leg may not be added merely to lift the accumulator over the fixed minimum.
            # Require non-negative single-leg raw EV in the paper value lane.
            and float(x.get("expected_value") or 0.0) >= 0.0
        ]
        secondary_batch=_construct_model_first_batch(
            secondary_pool,
            max_legs=RESULTS_FIRST_MAX_LEGS,
            min_odds=active_min_combined_odds(),
            min_leg_probability=(
                EFOOTBALL_VALUE_MIN_LEG_PROBABILITY
                if all(
                    str(x.get("product") or "").startswith("efootball_")
                    for x in secondary_pool
                )
                else MIN_SAFE_LEG_MODEL_PROBABILITY
            )
        )
        secondary_is_efootball=bool(secondary_pool) and all(
            str(x.get("product") or "").startswith("efootball_")
            for x in secondary_pool
        )
        secondary_avg_threshold=(
            EFOOTBALL_VALUE_MIN_AVG_PROBABILITY
            if secondary_is_efootball
            else MODEL_FIRST_MIN_AVG_PROBABILITY
        )
        if secondary_is_efootball:
            secondary_batch=[
                x for x in secondary_batch
                if float(x.get("model_probability") or 0.0)>=EFOOTBALL_VALUE_MIN_LEG_PROBABILITY
            ]
        if len(secondary_batch)>=BATCH_MIN_LEGS:
            secondary_batch=sorted(
                secondary_batch,
                key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf"))
            )
            secondary_metrics=_batch_metrics(secondary_batch)
            secondary_combined=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in secondary_batch)
            secondary_roi=(float(secondary_metrics.get("combined_model_probability") or 0.0)*secondary_combined)-1.0
            secondary_span=_batch_kickoff_span_minutes(secondary_batch)
            if (
                secondary_span<=MODEL_FIRST_MAX_KICKOFF_SPAN_MINUTES
                and float(secondary_metrics.get("avg_model_probability") or 0.0)>=secondary_avg_threshold
                and secondary_combined>=active_min_combined_odds()
                and secondary_roi>=RESULTS_FIRST_MIN_EXPECTED_ROI
            ):
                batches.append({
                    "batch_id":"BATCH-01",
                    "label":f"BATCH-01 · Value Model Rating {secondary_metrics['model_rating']:.1f}/100",
                    "rank_pending":False,
                    "rank":1,
                    "legs":secondary_batch,
                    "leg_count":len(secondary_batch),
                    "combined_odds":round(secondary_combined,3),
                    "combined_model_rating":secondary_metrics["model_rating"],
                    "combined_model_probability":secondary_metrics["combined_model_probability"],
                    "raw_combined_model_probability":secondary_metrics["raw_combined_model_probability"],
                    "ticket_calibration_gamma":secondary_metrics["ticket_calibration_gamma"],
                    "leg_strength_rating":secondary_metrics["leg_strength_rating"],
                    "avg_model_probability":secondary_metrics["avg_model_probability"],
                    "avg_model_edge_percent":secondary_metrics["avg_model_edge_percent"],
                    "products":sorted({str(x.get("product") or "") for x in secondary_batch if x.get("product")}),
                    "primary_lane":"model_first_value",
                    "paper_only":True,
                    "real_money_execution":False,
                    "correlation_policy":"same-event and participant reuse prevented; all legs independently Builder-eligible",
                    "construction_objective":"maximize whole-ticket model probability subject to the fixed 4.00+ odds floor; never add a leg after the model frontier cannot support the required ROI"
                })
                return batches,built,{
                    "batch_count":1,
                    "max_batches":1,
                    "disjoint":True,
                    "min_combined_odds":active_min_combined_odds(),
                    "target_combined_odds":TARGET_COMBINED_ODDS,
                    "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
                    "construction_priority":"model_first_value_fallback",
                    "priority_product":"mixed",
                    "max_legs":RESULTS_FIRST_MAX_LEGS,
                    "construction_shapes_considered":list(RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS),
                    "promoted_construction_leg_count":promoted_shape,
                    "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
                    "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
                    "used_unique_events":len({str(x.get("event_id") or "") for x in secondary_batch if x.get("event_id")}),
                    "eligible_results_first_legs":len(eligible_results),
                    "secondary_pool_eligible_legs":len(secondary_pool),
                    "secondary_expected_roi":round(secondary_roi,6),
                    "secondary_kickoff_span_minutes":round(secondary_span,1),
                    "secondary_max_kickoff_span_minutes":MODEL_FIRST_MAX_KICKOFF_SPAN_MINUTES,
                    "secondary_min_avg_model_probability":secondary_avg_threshold,
                    "secondary_efootball_value_lane":secondary_is_efootball,
                    "secondary_ticket_calibration_mode":(
                        "efootball_exact_evidence_independence_proxy"
                        if secondary_is_efootball
                        else "historical_settled_ticket_gamma"
                    ),
                    "capacity":_batch_capacity_diagnostic(secondary_pool),
                    "construction_shape_diagnostics":construction_shapes,
                    "ranking_metric":"whole-ticket model probability first, exact current edge second, odds as hard reachability constraint"
                }

    return batches,built,{
        "batch_count":len(batches),
        "max_batches":MAX_BATCHES,
        "disjoint":True,
        "min_combined_odds":active_min_combined_odds(),
        "target_combined_odds":TARGET_COMBINED_ODDS,
        "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
        "construction_priority":"settled_results_first",
        "priority_product":"vfootball",
        "max_legs":RESULTS_FIRST_MAX_LEGS,
        "construction_shapes_considered":list(RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS),
        "promoted_construction_leg_count":promoted_shape,
        "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
        "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
        "used_unique_events":len(used_events),
        "eligible_results_first_legs":len(eligible_results),
        "capacity":_batch_capacity_diagnostic(eligible_results),
        "ranking_metric":"settled exact-line/side hit rate first; calibrated probability second; odds only tie-breaker",
        "construction_shape_diagnostics":construction_shapes,
        "secondary_pool_eligible_legs":sum(1 for x in eligible_all if str(x.get("product") or "")!="vfootball" and (str(x.get("sport") or "") in {"football","tennis"} or str(x.get("product") or "").startswith("efootball_"))),
        "mixed_pool_eligible_legs":sum(1 for x in eligible_all if str(x.get("qualification_lane") or "") in {"vfootball_exact_evidence_value","vfootball_event_holdout_value","efootball_exact_evidence_value"}),
        "mixed_max_kickoff_span_minutes":MIXED_RESEARCH_MAX_KICKOFF_SPAN_MINUTES,
        "mixed_diagnostics":mixed_diag,
        "pure_vfootball_diagnostics":vfootball_diag,
        "pure_vfootball_input":{
            "eligible_legs":len(vfootball_holdout_pool),
            "sample":[
                {
                    "match":str(x.get("match") or ""),
                    "p":round(float(x.get("model_probability") or 0.0),6),
                    "odds":round(float(x.get("bookmaker_odds") or 0.0),3),
                    "ev":round(float(x.get("expected_value") or 0.0),6),
                    "participants":_participants(x)
                }
                for x in vfootball_holdout_pool[:12]
            ]
        }
    }


def select_value(candidates):
    built=[make_leg(x) for x in candidates]
    eligible=[x for x in built if x["builder_eligible"]]
    eligible.sort(key=lambda x:(x.get("selection_score") or -1,x.get("model_edge") or -1,x.get("model_probability") or 0,x.get("bookmaker_odds") or 0),reverse=True)
    selected=[];events=set();participants=set();combined=1.0
    skipped_participant=0
    for leg in eligible:
        eid=str(leg.get("event_id") or "")
        if eid and eid in events:continue
        pids=_participants(leg)
        if any(pid in participants for pid in pids):
            skipped_participant+=1
            continue
        selected.append(leg)
        if eid:events.add(eid)
        participants.update(pids)
        combined*=float(leg.get("bookmaker_odds") or 1)
        if combined>=MIN_COMBINED_ODDS or len(selected)>=MAX_LEGS:break
    return selected,built,combined,{"participant_correlation_skips":skipped_participant,"unique_participants":len(participants)}


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

    # PAPER qualification is independent from live-money risk.
    # Refresh SportyBet before applying the Builder's own value gates.
    market_refresh={"status":"not_run","error":None}
    prediction_rows=load(PREDICTIONS,[])
    try:
        from predict_today import attach_sportybet_market_layer
        if isinstance(prediction_rows,list) and prediction_rows:
            market_stats = attach_sportybet_market_layer(prediction_rows)
            PREDICTIONS.write_text(json.dumps(prediction_rows,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            market_refresh={"status":"ok","stats":market_stats}
        else:
            market_refresh={"status":"empty_predictions","stats":{}}
    except Exception as exc:
        # Fail closed when the current SportyBet layer cannot be refreshed.
        market_refresh={"status":"failed","error":str(exc)[:240]}

    football=football_candidates(now) if market_refresh.get("status")=="ok" else []
    tennis=tennis_candidates(now) if market_refresh.get("status")=="ok" else []
    virtual,virtual_diag=virtual_candidates(now)
    # Live-money risk remains separate and is never a PAPER qualification blocker.
    core_pool=football+tennis
    upstream_blocked = market_refresh.get("status")!="ok"
    batches,built,batch_diag=build_value_batches(core_pool+virtual)
    # Evaluate the isolated Phase 2 track independently of the baseline batch path.
    phase2_options,phase2_diag=_construct_phase2_cyclical_loop_batches(
        built,
        max_batches=min(4,MAX_BATCHES),
        min_odds=active_min_combined_odds()
    )
    phase2_batches=[]
    for idx,option in enumerate(phase2_options,1):
        rows=sorted(option["rows"], key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")))
        metrics=option["metrics"]
        odds=float(option["odds"])
        risk=option.get("kelly_risk") or _phase2_kelly_diagnostic(metrics.get("combined_model_probability"),odds)
        phase2_batches.append({
            "batch_id":f"P2-BATCH-{idx:02d}",
            "label":f"P2-BATCH-{idx:02d} · Cyclical Loop {metrics['model_rating']:.1f}/100",
            "rank":idx,
            "legs":rows,
            "leg_count":len(rows),
            "combined_odds":round(odds,3),
            "combined_model_rating":metrics["model_rating"],
            "combined_model_probability":metrics["combined_model_probability"],
            "raw_combined_model_probability":metrics["raw_combined_model_probability"],
            "ticket_calibration_gamma":metrics["ticket_calibration_gamma"],
            "leg_strength_rating":metrics["leg_strength_rating"],
            "avg_model_probability":metrics["avg_model_probability"],
            "avg_model_edge_percent":metrics["avg_model_edge_percent"],
            "products":sorted({str(row.get("product") or "") for row in rows}),
            "primary_lane":"phase2_cyclical_loop",
            "execution_track":"PHASE2_CYCLICAL_LOOP",
            "paper_only":True,
            "real_money_execution":False,
            "risk_diagnostic":risk,
            "strict_isolation":True
        })
    primary=batches[0] if batches else None
    selected=list(primary.get("legs") or []) if primary else []
    combined=float(primary.get("combined_odds") or 1.0) if primary else 1.0
    booking_info=_create_sportybet_booking_code(selected) if selected else {"status":"UNAVAILABLE","reason":"no_selected_batch"}
    if primary is not None:
        primary["sportybet_booking"]=booking_info
    selection_diag={"participant_correlation_skips":0,"unique_participants":len({_p for leg in selected for _p in _participants(leg)}) if selected else 0}
    previous=load(OUTPUT,{})
    previous_ids={str(x) for x in (previous.get("builder_event_ids",[]) if isinstance(previous,dict) else []) if x}
    previous_ids.update(str(x.get("event_id")) for x in (previous.get("qualified_legs",[]) if isinstance(previous,dict) else []) if isinstance(x,dict) and x.get("event_id"))
    known=previous_ids|{"183724","183769"}
    settled_ids={str(x.get("event_id")) for x in load(HISTORY,[]) if isinstance(x,dict) and x.get("settled") and x.get("event_id")}
    selected=[x for x in selected if str(x.get("event_id")) not in settled_ids]
    sports=sorted({x["sport"] for x in selected})
    primary_lane=str(primary.get("primary_lane") or "") if primary else ""
    results_first_met=bool(selected) and len(selected)>=BATCH_MIN_LEGS and primary_lane=="vfootball"
    odds_gate=combined_odds_gate_state()
    value_floor_met=bool(selected) and len(selected)>=BATCH_MIN_LEGS and combined>=active_min_combined_odds()
    preferred_target_met=bool(selected) and combined>=TARGET_COMBINED_ODDS
    accuracy_floor_met=results_first_met
    status=("PHASE2_CYCLICAL_SET" if primary_lane=="phase2_cyclical_loop" and value_floor_met else
            ("LIVE_VALUE_SET" if results_first_met and value_floor_met else
             ("RESULTS_FIRST_SET" if results_first_met else
              ("VALUE_RESEARCH_SET" if value_floor_met else
               ("NO_BET" if not selected else "VALUE_RESEARCH_INSUFFICIENT")))))
    rejection_counts={}
    for leg in built:
        leg_status=str(leg.get("status") or "REJECTED")
        rejection_counts[leg_status]=rejection_counts.get(leg_status,0)+1
    result={
        "generated_at":now.isoformat(),"engine_version":"V6.1-RESEARCH-GATED",
        "mode":"PAPER_ONLY","target_legs":f"adaptive 2–4 legs; {odds_gate['floor']:.2f}x active minimum / {odds_gate['preferred_target']:.2f}x preferred combined odds","sports_supported":["football","tennis","virtual"],
        "research_gate":{
            "selection_gate_status":gate_status,
            "combined_odds_gate":odds_gate,
            "preferred_2_80_target_reached":preferred_target_met,
            "selected_predictions":selected_predictions,
            "tennis_live_eligible":tennis_live_eligible,
            "upstream_blocked":upstream_blocked,
            "paper_qualification_independent_of_live_risk":True,
            "current_market_refresh":market_refresh,
            "risk_reasons":tennis_risk.get("reasons",[]),
            "selection_reasons":gate.get("rejection_reasons",{})
        },
        "candidate_diagnostics":{
            "football_candidates":len(football),
            "tennis_candidates":len(tennis),
            "virtual_candidates":len(virtual),
            "virtual_gate_diagnostics":virtual_diag,
            "evaluated":len(built),
            "rejections":rejection_counts,"selection_diversity":selection_diag,
            "batch_diagnostics":batch_diag,
            "phase2_cyclical_loop":phase2_diag,
            "phase2_cyclical_loop_batches":phase2_batches,
            "participant_history_weighting":{
                "enabled":True,
                "min_n":PARTICIPANT_HISTORY_MIN_N,
                "max_bonus":PARTICIPANT_HISTORY_MAX_BONUS,
                "role":"ranking_only_after_all_existing_eligibility_gates",
                "source":"data/virtual_lab_participant_profiles.json"
            }
        },
        "selection_policy":{"min_calibrated_probability":MIN_PROB,"virtual_min_probability":VIRTUAL_MIN_PROB,"virtual_builder_lines":"all current O/U lines with exact-side evidence; no forced line list","minimum_combined_odds":active_min_combined_odds(),
            "accuracy_first_base_floor":RESULTS_FIRST_MIN_COMBINED_ODDS,
            "results_first":True,
            "results_first_min_observations":RESULTS_FIRST_MIN_OBS,
            "results_first_min_accuracy":RESULTS_FIRST_MIN_ACCURACY,
            "results_first_max_legs":RESULTS_FIRST_MAX_LEGS,
            "results_first_construction_leg_counts":list(RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS),
            "results_first_construction_leg_count":batch_diag.get("promoted_construction_leg_count"),
            "results_first_min_construction_tickets":RESULTS_FIRST_MIN_CONSTRUCTION_TICKETS,
            "results_first_max_construction_loss_rate":RESULTS_FIRST_MAX_CONSTRUCTION_LOSS_RATE,
            "results_first_min_expected_roi":RESULTS_FIRST_MIN_EXPECTED_ROI,
            "target_combined_odds":TARGET_COMBINED_ODDS,
            "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
            "construction_priority":"settled_results_first","min_model_edge":MIN_EDGE,
            "max_odds_age_seconds":MAX_ODDS_AGE_SECONDS,"max_uncertainty":MAX_UNCERTAINTY,
            "max_legs":MAX_LEGS,
            "active_construction_max_legs":RESULTS_FIRST_MAX_LEGS,
            "adaptive_leg_counts":[2,3,4],
            "per_leg_min_model_probability":LEG_COUNT_MIN_MODEL_PROBABILITY,
            "preferred_per_leg_model_probability":PREFERRED_LEG_MODEL_PROBABILITY,
            "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
            "max_batch_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
            "ticket_performance_filter":{"enabled":True,"min_settled_legs":TICKET_SPOILER_MIN_SAMPLE,"min_accuracy":TICKET_SPOILER_MIN_ACCURACY,"role":"construction_only; never substitutes for model evidence"},
            "min_data_quality":MIN_DATA_QUALITY,"requires_live_sportybet_price":True,
            "requires_complete_market_for_devig":True,"avoid_same_event_correlation":True,
            "participant_history_weighting":"qualified-leg ranking only; conservative exact-line settled O/U history; no eligibility bypass",
            "efootball_direction_neutral_ranking":{
                "enabled":True,
                "sides_compared":["over","under"],
                "primary_signal":"exact product + line + side settled evidence",
                "ranking_method":"Bayesian-shrunk hit rate with sample-confidence adjustment; model edge is a secondary tie-break",
                "eligibility_unchanged":True
            },
            "efootball_recent_spoiler_guard":{
                "enabled":True,
                "min_exact_side_observations":EFOOTBALL_RECENT_SPOILER_MIN_OBS,
                "last10_min_hit_rate":EFOOTBALL_RECENT_SPOILER_LAST10_MIN_HIT,
                "last20_min_observations":EFOOTBALL_RECENT_SPOILER_LAST20_MIN_OBS,
                "last20_min_hit_rate":EFOOTBALL_RECENT_SPOILER_LAST20_MIN_HIT,
                "max_consecutive_losses":EFOOTBALL_RECENT_SPOILER_MAX_CONSECUTIVE_LOSSES,
                "scope":"exact product + line + selected O/U side",
                "action":"reject_candidate_before_construction",
                "role":"construction eligibility safeguard; does not force Over or Under"
            },
            "never_force_accumulator":True,"real_money_execution":False,
            "phase2_cyclical_loop":{
                "enabled":PHASE2_CYCLICAL_LOOP_ENABLED,
                "min_confidence":PHASE2_CYCLICAL_MIN_CONFIDENCE,
                "min_legs":PHASE2_CYCLICAL_MIN_LEGS,
                "max_legs":PHASE2_CYCLICAL_MAX_LEGS,
                "virtual_efootball_only":True,
                "strict_baseline_isolation":True,
                "high_variance_odds_threshold":PHASE2_CYCLICAL_HIGH_VARIANCE_ODDS,
                "kelly_risk_diagnostic":"paper_only; no staking execution",
                "separate_execution_track":True,
                "phase2_batch_count":len(phase2_batches)
            }},
        "bookmaker_odds":{"status":"LIVE_SPORTYBET_SNAPSHOT","sportybet_direct_feed":"VIA_CLOUDFLARE_PROXY",
            "stake_direct_feed":"NOT_CONNECTED","instruction":"Verify the displayed SportyBet price immediately before any manual wager."},
        "candidates_considered":{"football":len(football),"tennis":len(tennis),"virtual":len(virtual),"all_built":len(built)},
        "qualified_legs":selected if value_floor_met else [],
        "best_available_legs":selected if selected else sorted([x for x in built if x.get("builder_eligible") and str(x.get("product") or "")=="vfootball"], key=lambda x:float(x.get("bookmaker_odds") or 1.0), reverse=True)[:MAX_LEGS],
        "combined_odds_selected":round(combined,3) if selected else None,
        "naive_independence_hit_proxy":round(math.prod(float(x.get("model_probability") or 0) for x in selected),6) if selected else None,
        "batch_count":len(batches),
        "batch_policy":{
            "min_combined_odds":active_min_combined_odds(),
            "results_first":True,
            "results_first_min_observations":RESULTS_FIRST_MIN_OBS,
            "results_first_min_accuracy":RESULTS_FIRST_MIN_ACCURACY,
            "results_first_max_legs":RESULTS_FIRST_MAX_LEGS,
            "target_combined_odds":TARGET_COMBINED_ODDS,
            "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
            "construction_priority":"settled_results_first",
            "max_batches":MAX_BATCHES,
            "max_legs":MAX_LEGS,
            "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
            "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
            "disjoint_batches":True,
            "ranking":"settled exact-line/side results first; calibrated probability second; odds only tie-breaker",
            "model_rating_definition":"100 × product of leg model probabilities (naive joint proxy)",
            "leg_strength_definition":"100 × geometric mean of leg model probabilities",
            "primary_lane":primary_lane or "none",
            "booking_code_policy":"fresh non-staking share code from exact live event/market/outcome IDs; never fabricate",
            "phase2_cyclical_loop":{
                "enabled":PHASE2_CYCLICAL_LOOP_ENABLED,
                "min_confidence":PHASE2_CYCLICAL_MIN_CONFIDENCE,
                "min_legs":PHASE2_CYCLICAL_MIN_LEGS,
                "max_legs":PHASE2_CYCLICAL_MAX_LEGS,
                "pool_cap":PHASE2_CYCLICAL_POOL_CAP,
                "virtual_efootball_only":True,
                "strict_baseline_isolation":True,
                "batch_count":len(phase2_batches),
                "diagnostics":phase2_diag
            }
        },
        "batches":batches,
        "phase2_cyclical_loop_batches":phase2_batches,
        "rejected_candidates":[x for x in built if not x["real_money_eligible"]][:20],
        "settled_legs":recent_settled(load(HISTORY,[]),now,known),
        "builder_event_ids":sorted(known),"leg_count":len(selected),"sports_selected":sports,
        "status":status,
        "reference_combined_odds":round(math.prod(x["model_fair_odds"] for x in selected),3) if selected else None,
        "reference_odds_type":"MODEL_FAIR_ODDS_NOT_BOOKMAKER_PRICE",
        "market_price_combined_odds":round(combined,3) if selected else None,
        "sportybet_booking":booking_info,
        "theme":{"name":"Midnight Graphite / Electric Cyan / Signal Green","accent":"#28D7E8","positive":"#35D07F","background":"#080D14"},
        "notes":["Results-first qualifies only from settled exact-line/side performance plus the existing live-price, freshness, data-quality and model-evidence gates.","Zero batches are now diagnosable: capacity reports whether the active 2.70x floor is reachable under the existing leg/correlation rules; no per-leg evidence gate is weakened.","best_available_legs is informational when no batch exists and is not a qualified accumulator.","Missing or stale SportyBet prices produce NO_BET/REJECTED.","Model fair odds never overwrite bookmaker odds.","The Builder evaluates 2–4-leg constructions adaptively. Every included leg must meet the 80% safety floor; 90%+ per-leg probability is preferred. The vFootball Results-first lane is promoted only when its own settled-ticket sample, loss rate, combined odds, empirical ROI, exact-line evidence, and current expected ROI pass.","When the proven Results-first lane cannot qualify, the controlled mixed research lane may use exactly 1 VFootball exact-evidence leg plus up to 3 exact-evidence eFootball legs; every included leg must remain independently Builder-eligible and have non-negative single-leg raw expected value. Only after that mixed lane fails does the broader football/tennis/eFootball value fallback run.","The active combined-odds floor is 2.70x. The 2.80x target remains preferred and becomes the active floor after 10 settled wins in the current 2–4-leg construction family. The fallback still requires current expected ROI >=2%, fresh SportyBet pricing, and the same correlation controls.","The ticket remains paper-only and the active construction lanes allow 2 through 4 legs; they are never pinned to a single leg count and never padded with a weak leg.","The proven Results-first lane keeps a 60-minute kickoff span. The model-first paper value lane may span up to 270 minutes only when its whole-ticket probability and expected ROI gates still pass; this is explicitly research-only, not promoted as settled Results-first evidence.","Near-term Builder horizon is 720 minutes; price freshness remains capped at 900 seconds so extending the scan window does not permit stale odds.","Builder refreshes every 15 minutes and after relevant upstream workflows, so candidate prices are repeatedly revalidated before kickoff.",
        "Phase 2 cyclical-loop research is isolated from the baseline model: only Virtual/eFootball legs with a model probability and blended streak-break confidence of at least 78% can enter its 2–3-leg constructor.",
        "The cyclical-loop signal is evidence-backed sequence analysis, not a gambler's-fallacy override: it requires a current opposite-side streak and historical break observations. It cannot weaken the existing evidence, price, correlation, 2.70x or +2% ROI gates; 4.00x is reserved for the separate Phase 2 variance diagnostic.",
        "When Phase 2 combined odds exceed 4.00x, the Builder records a paper-only Kelly variance diagnostic labeled 'High Variance - Fraction Stake Only'; no live stake is calculated or executed."]
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()

# Refresh marker: exact-side virtual evidence gate is active.
# Batch marker: vFootball-priority disjoint 2.70+ research batches with 2–4 adaptive legs.
# Final market freshness marker: 2026-10-05
# Trigger marker: regenerate Builder after QA policy alignment; no selection logic change.
# Trigger marker 2: rerun after restoring the missing Results-first ROI constant.