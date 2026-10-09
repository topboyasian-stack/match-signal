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
EFOOTBALL_PRODUCT_MIN_HIT_RATE=0.65
EFOOTBALL_DIRECTION_MIN_HOLDOUT_ROWS=30
EFOOTBALL_DIRECTION_MIN_RECENT_ROWS=30
EFOOTBALL_DIRECTION_MIN_HIT_RATE=0.65
EFOOTBALL_DIRECTION_RECENT_WINDOW=50
SETTLED_DESK_RETENTION_HOURS=2
EFOOTBALL_DESK_LEARNING_MIN_CALIBRATION_N=30
EFOOTBALL_DESK_EXACT_MIN_N=12
EFOOTBALL_DESK_LEARNING_PATH="efootball_desk_learning.json"
# A high Under line can look almost certain from the Poisson tail even when the
# exact line/direction has too little out-of-sample evidence. Keep it visible as
# research, but do not qualify VFootball Under 7.5+ without its own evidence.
VFOOTBALL_HIGH_UNDER_MIN_OOS_LINE=7.5
VFOOTBALL_HIGH_UNDER_MIN_OOS_N=30
VFOOTBALL_HIGH_UNDER_MIN_OOS_HIT_RATE=0.65
MAX_LIVE_AGE_HOURS={"football":4.0,"tennis":8.0,"virtual":2.0}
DESK_FILTER_STATS={
    "past_kickoff_rows_hidden":0,
    "stale_live_flags_hidden":0,
    "expired_settled_rows_hidden":0,
}

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

def calibrate_desk_probability(raw_probability, line, side, product_report):
    """Apply only a sufficiently supported correction for this product/line/side."""
    report=product_report if isinstance(product_report,dict) else {}
    exact_profiles=report.get("exact_selection") or {}
    exact_key=f"{float(line):g}|{side}"
    exact_profile=exact_profiles.get(exact_key,{})
    exact_n=int(exact_profile.get("n") or 0)
    if exact_n>=EFOOTBALL_DESK_EXACT_MIN_N:
        offset=num(exact_profile.get("calibration_offset"))
        weight=num(exact_profile.get("calibration_weight"))
        if offset is not None and weight is not None:
            return clamp(raw_probability + offset*weight), "EXACT_LINE_DIRECTION", exact_profile

    calibration=report.get("calibration") or {}
    bucket_key=str(min(0.95,max(0.50,(math.floor(float(raw_probability)/0.05)*0.05)))).rstrip("0").rstrip(".")
    bucket=(calibration.get("buckets") or {}).get(bucket_key,{})
    if bool(calibration.get("active")) and int(bucket.get("n") or 0)>=EFOOTBALL_DESK_LEARNING_MIN_CALIBRATION_N:
        offset=num(bucket.get("calibration_offset"))
        weight=num(bucket.get("calibration_weight"))
        if offset is not None and weight is not None:
            return clamp(raw_probability + offset*weight), "PROBABILITY_BUCKET", bucket
    return clamp(raw_probability), "NONE", exact_profile

def exact_line_direction_oos(eval_art, product, line, side):
    """Return the exact product/line/side chronological OOS result, without treating it as qualification."""
    side_key="o" if str(side).lower()=="over" else "u"
    try:
        line_key=f"{side_key}{float(line):g}"
    except (TypeError,ValueError):
        return {"n":0,"hit_rate":None,"brier":None,"variant":None}
    product_rows=((eval_art.get("by_product_selection") or {}).get(str(product)) or {})
    record=product_rows.get(line_key) if isinstance(product_rows,dict) else None
    if not isinstance(record,dict):
        return {"n":0,"hit_rate":None,"brier":None,"variant":None}
    for variant in ("participant_model","poisson_prior","poisson","efootball_shape"):
        stats=record.get(variant)
        if isinstance(stats,dict):
            try:
                return {
                    "n":int(stats.get("n") or 0),
                    "hit_rate":num(stats.get("hit_rate")),
                    "brier":num(stats.get("brier")),
                    "variant":variant,
                }
            except (TypeError,ValueError):
                pass
    return {"n":0,"hit_rate":None,"brier":None,"variant":None}

def live_age_limit_hours(row):
    sport=str((row or {}).get("sport") or "").lower()
    product=str((row or {}).get("product") or "").lower()
    if sport=="virtual" or product in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
        return MAX_LIVE_AGE_HOURS["virtual"]
    if sport=="tennis":
        return MAX_LIVE_AGE_HOURS["tennis"]
    return MAX_LIVE_AGE_HOURS["football"]

def stale_live_flag(row, now=None):
    """A stale LIVE flag cannot keep a match on Upcoming indefinitely."""
    now=now or NOW
    start=dt((row or {}).get("start_time") or (row or {}).get("timestamp") or (row or {}).get("date"))
    if start is None or start>now or not explicit_live(row):
        return False
    return (now-start)>timedelta(hours=live_age_limit_hours(row))

def high_vfootball_under_requires_research(product, line, side, exact_oos):
    """High VFootball Unders need a minimum exact-line chronological OOS sample."""
    if str(product or "").lower()!="vfootball" or str(side or "").lower()!="under":
        return False
    value=num(line)
    if value is None or value<VFOOTBALL_HIGH_UNDER_MIN_OOS_LINE:
        return False
    stats=exact_oos if isinstance(exact_oos,dict) else {}
    n=num(stats.get("n")) or 0
    hit=num(stats.get("hit_rate"))
    return n<VFOOTBALL_HIGH_UNDER_MIN_OOS_N or hit is None or hit<VFOOTBALL_HIGH_UNDER_MIN_OOS_HIT_RATE

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
            x["sportybet_odds_side"]=side
    if quote is None and isinstance(totals,list):
        for item in totals:
            if not isinstance(item,dict): continue
            il=num(item.get("line"))
            side=str(item.get("side") or "").lower()
            if line is not None and il is not None and abs(il-line)<0.001 and side==pick and num(item.get("odds")) is not None:
                quote=num(item.get("odds"))
                x["sportybet_odds_market"]="total"
                x["sportybet_odds_line"]=il
                x["sportybet_odds_side"]=side
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


def virtual_fixture_key(row):
    """Disambiguate recurring SportyBet session IDs using kickoff and stable handles."""
    import re
    product=str(row.get("product") or "").strip().lower()
    if not product:
        return None
    start=dt(row.get("start_time") or row.get("timestamp") or row.get("date"))
    if start is None:
        return None
    def identity(*keys):
        value=""
        for key in keys:
            if row.get(key):
                value=str(row.get(key)).strip()
                break
        embedded=re.search(r"\(([^()]*)\)\s*$",value)
        if embedded and embedded.group(1).strip():
            value=embedded.group(1).strip()
        return norm_name(value)
    p1=identity("participant_1","player_1","team_1","home")
    p2=identity("participant_2","player_2","team_2","away")
    if not p1 or not p2:
        return None
    minute=int(start.timestamp()//60)
    return f"{product}|{minute}|{'|'.join(sorted((p1,p2)))}"

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
            # Virtual/eFootball event IDs can recur across neighbouring matches.
            # Only the product + kickoff minute + stable participant identities
            # form an authoritative settled-fixture key.
            product=str(item.get("product") or "").lower()
            if product in {"efootball_gt","efootball_adriatic","vfootball","zoom"} and item.get("win") is not None:
                fixture_key=virtual_fixture_key(item)
                settled_at=dt(item.get("settled_at"))
                if fixture_key and settled_at:
                    previous=details.get(fixture_key)
                    if previous is None or settled_at > (dt(previous.get("settled_at")) or datetime.min.replace(tzinfo=timezone.utc)):
                        details[fixture_key]=dict(item)

    ingest(load("prediction_history.json",[]),True)
    ingest(load("expansion_prediction_history.json",[]),True)
    ingest(load("virtual_lab_history.json",[]),True)
    # Darts/Table Tennis history rows are result-only ledgers, so every row is terminal.
    ingest(load("darts_history.json",[]),False)
    ingest(load("table_tennis_history.json",[]),False)
    return event_ids,keys,details

SETTLED_EVENT_IDS, SETTLED_MATCH_KEYS, SETTLED_DETAILS = settlement_index()

def settled_record(row):
    return SETTLED_DETAILS.get(virtual_fixture_key(row))

def add(rows, row, now=None, horizon=None):
    if not isinstance(row,dict):return
    now=now or NOW
    horizon=horizon or (now+timedelta(days=7))
    start=dt(row.get("start_time"))
    if not start or start>horizon:return
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
    started_or_due = bool(start and start <= now)
    is_virtual=(
        str(row.get("sport") or "").lower()=="virtual"
        or str(row.get("product") or "").lower() in {"efootball_gt","efootball_adriatic","vfootball","zoom"}
    )
    sr=settled_record(row) if is_virtual else None
    history_terminal=(
        virtual_fixture_key(row) in SETTLED_DETAILS
        if is_virtual
        else (eid in SETTLED_EVENT_IDS or match_key(row) in SETTLED_MATCH_KEYS)
    )
    terminal=explicit_terminal(row) or (started_or_due and history_terminal)
    if not terminal and stale_live_flag(row,now):
        DESK_FILTER_STATS["stale_live_flags_hidden"]+=1
        return
    if terminal:
        if sr and sr.get("settled_at"):
            try:
                settled_stamp=dt(sr.get("settled_at"))
                age=(now-settled_stamp).total_seconds() if settled_stamp else float("inf")
            except Exception:
                age=float("inf")
            if 0 <= age <= SETTLED_DESK_RETENTION_HOURS*3600:
                row["event_state"]="SETTLED"
                row["settled"]=True
                row["settled_at"]=sr.get("settled_at")
                row["final_score"]=sr.get("score") or sr.get("final_score")
                row["prediction_trace_id"]=sr.get("trace_id") or sr.get("record_id")
                # Show the actual O/U result for this forecast line, not the
                # independent collector's favourite side at that line.
                line=num(row.get("line"))
                score=row.get("final_score")
                total=None
                if isinstance(score,(list,tuple)) and len(score)>=2:
                    try: total=float(score[0])+float(score[1])
                    except (TypeError,ValueError): total=None
                elif isinstance(score,str) and ":" in score:
                    try: total=sum(float(x) for x in score.replace(" ","").split(":")[:2])
                    except (TypeError,ValueError): total=None
                if str(row.get("market") or "")=="over_under" and line is not None and total is not None:
                    row["settlement_result"]="PUSH" if total==line else ("over" if total>line else "under")
                else:
                    row["settlement_result"]=sr.get("result") or sr.get("actual_result")
            else:
                # Hide from Upcoming after the short grace period. The result
                # remains in Virtual Lab history and the desk learning ledger.
                DESK_FILTER_STATS["expired_settled_rows_hidden"]+=1
                return
        else:
            return

    # Upcoming is not a stale-fixture queue. Once kickoff has passed, keep a
    # row only when the provider explicitly reports it live, or when the exact
    # settled fixture matched above is inside the short result-display grace.
    # Missing/late settlement data must never make an old match look upcoming.
    settled_visible = str(row.get("event_state") or "").upper() == "SETTLED"
    if start <= now and not explicit_live(row) and not settled_visible:
        DESK_FILTER_STATS["past_kickoff_rows_hidden"]+=1
        return
    if explicit_live(row):
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
            candidate_status=str(selected.get("candidate_status") or "")
            x["candidate_status"]=candidate_status or x.get("candidate_status")
            x["model_rating"]=selected.get("model_rating", x.get("model_rating"))
            x["candidate_group"]=selected.get("candidate_group", x.get("candidate_group"))
            # Candidate collection is model-first research data. Only an
            # explicit betting-qualified status may promote the core row.
            if candidate_status.startswith("BETTING_QUALIFIED"):
                x["qualification_status"]=candidate_status
                x["live_eligible"]=False
                x["qualification_basis"]=selected.get("qualification_basis")
            else:
                x["live_eligible"]=False
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

def build_efootball_directional_gate(eval_art, history):
    """Build exact product+line+side qualification evidence from untouched holdout + recent settled history.

    This is deliberately separate from the product-wide bootstrap gate. The base
    model must already pass its global walk-forward gate, then an exact O/U line
    and direction must have at least 30 untouched holdout rows at >=65% hit rate
    and at least 30 recent settled rows at >=65% hit rate. This does not lower
    the evidence threshold; it makes the validation granular enough to avoid
    blocking strong exact selections because another eFootball line/side is weak.
    """
    out={}
    by_key=defaultdict(list)
    for r in history if isinstance(history,list) else []:
        if not isinstance(r,dict) or r.get("product")!="efootball_gt" or r.get("market")!="ou" or r.get("win") is None:
            continue
        try:
            line=float(r.get("line"))
        except (TypeError,ValueError):
            continue
        selection=str(r.get("selection") or "").upper()
        side="over" if selection.startswith("O") else "under" if selection.startswith("U") else ""
        if not side:
            continue
        stamp=dt(r.get("settled_at") or r.get("timestamp"))
        by_key[(line,side)].append({
            "win":bool(r.get("win")),
            "timestamp":stamp
        })

    selection_eval=((eval_art.get("efootball_gt_diagnostics") or {}).get("selection") or {}) if isinstance(eval_art,dict) else {}
    for selection_key, line_map in selection_eval.items():
        key_text=str(selection_key).lower()
        side="over" if key_text.startswith("o") else "under" if key_text.startswith("u") else ""
        if not side:
            continue
        try:
            line=float(key_text[1:])
        except (TypeError,ValueError):
            continue
        report=(line_map or {}).get(str(line)) if isinstance(line_map,dict) else None
        # Prefer the participant-aware holdout variant when it exists; this
        # is the same time-safe model family used for the eFootball desk.
        poisson=(report or {}).get("participant_model") if isinstance(report,dict) else None
        if not isinstance(poisson,dict):
            poisson=(report or {}).get("efootball_shape") if isinstance(report,dict) else None
        if not isinstance(poisson,dict):
            poisson=(report or {}).get("poisson") if isinstance(report,dict) else None
        if not isinstance(poisson,dict):
            continue
        arr=sorted(by_key.get((line,side),[]), key=lambda x: x.get("timestamp") or datetime.min.replace(tzinfo=timezone.utc))
        recent=arr[-min(EFOOTBALL_DIRECTION_RECENT_WINDOW,len(arr)):] if arr else []
        holdout_n=int(poisson.get("n") or 0)
        holdout_hit=float(poisson.get("hit_rate") or 0)
        recent_n=len(recent)
        recent_hit=(sum(1 for x in recent if x.get("win"))/recent_n) if recent_n else 0.0
        passed=(
            holdout_n>=EFOOTBALL_DIRECTION_MIN_HOLDOUT_ROWS and
            holdout_hit>=EFOOTBALL_DIRECTION_MIN_HIT_RATE and
            recent_n>=EFOOTBALL_DIRECTION_MIN_RECENT_ROWS and
            recent_hit>=EFOOTBALL_DIRECTION_MIN_HIT_RATE
        )
        out[(line,side)]={
            "pass":passed,
            "holdout_n":holdout_n,
            "holdout_hit_rate":round(holdout_hit,4),
            "recent_n":recent_n,
            "recent_hit_rate":round(recent_hit,4),
            "threshold":EFOOTBALL_DIRECTION_MIN_HIT_RATE,
            "basis":"strict chronological holdout + latest settled exact-line direction history",
        }
    return out

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
        viable_details=[]
        for variant_name in ("poisson","poisson_prior","efootball_shape"):
            m=metrics.get(variant_name)
            if not isinstance(m,dict): continue
            if int(m.get("n") or 0)<300: continue
            if float(m.get("brier",9))>=float(market_m.get("brier",0)): continue
            if float(m.get("log_loss",9))>=float(market_m.get("log_loss",0)): continue
            if float(m.get("ece",9))>float(market_m.get("ece",9))+.02: continue
            viable_m.append(variant_name)
            viable_details.append({
                "variant":variant_name,
                "hit_rate":round(float(m.get("hit_rate",0)),4),
                "brier":round(float(m.get("brier",9)),4),
                "log_loss":round(float(m.get("log_loss",9)),4),
                "ece":round(float(m.get("ece",9)),4)
            })
        product_bootstrap_gate[str(product)]=bool(
            viable_m and max(float(metrics.get(v,{}).get("hit_rate",0)) for v in viable_m)>=EFOOTBALL_PRODUCT_MIN_HIT_RATE
        )

    directional_gate=build_efootball_directional_gate(eval_art, history)
    desk_learning=load(EFOOTBALL_DESK_LEARNING_PATH,{})
    desk_learning_by_product=(desk_learning.get("by_product") or {}) if isinstance(desk_learning,dict) else {}

    # Build the chronological Virtual Lab event history once per board refresh.
    # Reusing it for every current eFootball market keeps the five-minute desk
    # refresh bounded while preserving strict pre-event information flow.
    validated_history_events=[]
    validated_vl_probs=None
    validated_fit_lambda=None
    try:
        from virtual_lab_model_eval import build_events as _build_vl_events, fit_lambda as _fit_vl_lambda, probs as _vl_probs
        validated_history_events=_build_vl_events(history)
        validated_vl_probs=_vl_probs
        validated_fit_lambda=_fit_vl_lambda
    except Exception:
        validated_history_events=[]
        validated_vl_probs=None
        validated_fit_lambda=None

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

            # Use the same time-safe walk-forward eFootball model family as
            # scripts/virtual_lab_model_eval.py. The current SportyBet quote is
            # used only to fit the event-level line-ladder Poisson anchor; all
            # historical shape/participant learning is strictly pre-event.
            over=under=None
            validated_over=validated_under=None
            validated_meta={}
            try:
                if validated_vl_probs is None or validated_fit_lambda is None:
                    raise RuntimeError("validated walk-forward model helpers unavailable")
                prior_events=[h_event for h_event in validated_history_events if ts(h_event.get("timestamp")) < start.timestamp()]
                market_rows=[]
                if market_over is not None:
                    market_rows.append({"line":float(line),"model_prob":float(market_over),"selection":"over","win":None})
                if market_under is not None:
                    market_rows.append({"line":float(line),"model_prob":float(market_under),"selection":"under","win":None})
                current_lambda=validated_fit_lambda([
                    (float(line), float(market_over))
                ]) if market_over is not None else None
                if current_lambda is None:
                    current_lambda=float(product_lambdas.get(product,2.5))
                current_event={
                    "key":f"desk|{e.get('event_id')}|{line}",
                    "event_id":str(e.get("event_id") or ""),
                    "timestamp":start.isoformat(),
                    "product":product,
                    "competition":competition,
                    "home":home,
                    "away":away,
                    "rows":market_rows,
                    "total":None,
                    "lambda":current_lambda,
                }
                for side,mp in (("over",market_over),("under",market_under)):
                    if mp is None:
                        continue
                    row={"line":float(line),"model_prob":float(mp),"selection":side,"win":None}
                    result=validated_vl_probs(prior_events,current_event,row)
                    if side=="over":
                        validated_over=float(result[4])
                    else:
                        validated_under=float(result[4])
                    validated_meta[side]={
                        "market_probability":result[0],
                        "poisson_probability":result[1],
                        "product_prior_probability":result[2],
                        "efootball_shape_probability":result[6],
                        "participant_model_probability":result[4],
                        "participant_history_n":result[5],
                        "efootball_shape_n":result[7],
                        "efootball_shape_weight":result[8],
                    }
            except Exception as exc:
                validated_meta={"error":str(exc)[:240]}
            if validated_over is None or validated_under is None:
                lam=float(product_lambdas.get(product,2.5))
                k=max(0,math.floor(line))
                pmf=math.exp(-lam); cdf=pmf
                for i in range(1,k+1):
                    pmf*=lam/i; cdf+=pmf
                fallback_over=clamp(1-cdf)
                validated_over=validated_over if validated_over is not None else fallback_over
                validated_under=validated_under if validated_under is not None else clamp(1-fallback_over)
                validated_meta["fallback"]="product_lambda"
            raw_over=clamp(validated_over)
            raw_under=clamp(validated_under)
            # Desk learning is product-specific. Prefer a mature exact
            # product+line+direction calibration; fall back to a mature
            # probability bucket only when no exact profile is available.
            product_desk_learning=desk_learning_by_product.get(product,{}) if isinstance(desk_learning_by_product,dict) else {}
            if not product_desk_learning and product=="efootball_gt" and isinstance(desk_learning,dict):
                # Backward compatibility with reports written before by_product.
                product_desk_learning={
                    "calibration": desk_learning.get("calibration") or {},
                    "exact_selection": desk_learning.get("exact_selection") or {},
                    "settled_predictions": desk_learning.get("settled_predictions") or 0,
                }
            product_desk_calibration=product_desk_learning.get("calibration") or {}
            product_exact_profiles=product_desk_learning.get("exact_selection") or {}

            over, over_learning_source, over_learning_profile=calibrate_desk_probability(
                raw_over, line, "over", product_desk_learning
            )
            under, under_learning_source, under_learning_profile=calibrate_desk_probability(
                raw_under, line, "under", product_desk_learning
            )
            chosen_pick="over" if over>=under else "under"
            chosen_model=over if chosen_pick=="over" else under
            raw_chosen_model=raw_over if chosen_pick=="over" else raw_under
            chosen_market=market_over if chosen_pick=="over" else market_under
            chosen_learning_source=over_learning_source if chosen_pick=="over" else under_learning_source
            chosen_learning_profile=over_learning_profile if chosen_pick=="over" else under_learning_profile
            # Expose the exact line/direction sample even during calibration
            # warm-up so the desk can show users whether this line is learned.
            chosen_exact_profile=product_exact_profiles.get(f"{float(line):g}|{chosen_pick}",{})
            chosen_exact_n=int(chosen_exact_profile.get("n") or 0)
            chosen_exact_accuracy=num(chosen_exact_profile.get("accuracy"))
            bucket_key=str(min(0.95,max(0.50,(math.floor(raw_chosen_model/0.05)*0.05)))).rstrip("0").rstrip(".")
            edge=chosen_model-chosen_market if chosen_market is not None else None

            comp_key=competition.casefold()
            active_comp=comp_key in product_active_comp.get(product,set())
            active_line=float(line) in product_active_line.get(product,set())
            model_comp=comp_key in product_model_comp.get(product,set())
            model_line=float(line) in product_model_line.get(product,set())

            directional_key=(float(line),chosen_pick)
            directional=directional_gate.get(directional_key,{})
            exact_oos=exact_line_direction_oos(eval_art,product,line,chosen_pick)
            high_vfootball_under_pending=high_vfootball_under_requires_research(
                product,line,chosen_pick,exact_oos
            )
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
                elif directional.get("pass"):
                    qualification_status="BETTING_QUALIFIED_PAPER_DIRECTIONAL"
                else:
                    qualification_status="DIRECTIONAL_LINE_VALIDATION_GATE_PENDING"
            elif product=="vfootball":
                # A very high Under estimate is not enough on its own. Guard
                # U7.5/U8.5 and higher until the exact direction has >=30
                # chronological out-of-sample rows at the configured hit rate.
                if high_vfootball_under_pending:
                    qualification_status="HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING"
                elif not base_model_gate:
                    qualification_status="BASE_MODEL_GATE_PENDING"
                elif not active_line or not model_line:
                    qualification_status="MODEL_LINE_SCOPE_GATE_PENDING"
                elif edge is None:
                    qualification_status="MARKET_EDGE_PENDING"
                elif edge<0.02:
                    qualification_status="EDGE_BELOW_2PCT"
                elif chosen_model<0.65:
                    qualification_status="MODEL_PROBABILITY_BELOW_0_65"
                elif active_comp and model_comp:
                    qualification_status="BETTING_QUALIFIED_PAPER"
                else:
                    qualification_status="MODEL_SCOPE_GATE_PENDING"
            else:
                qualification_status="RESEARCH_PROJECTION"

            qualified=qualification_status in {"BETTING_QUALIFIED_PAPER","BETTING_QUALIFIED_PAPER_BOOTSTRAP","BETTING_QUALIFIED_PAPER_DIRECTIONAL"}
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
                "raw_model_probability":round(raw_chosen_model,4),
                "validated_model_family":"walk_forward_efootball_participant_model",
                "validated_model_over_probability":round(raw_over,4),
                "validated_model_under_probability":round(raw_under,4),
                "validated_model_components":validated_meta,
                "desk_learning_active":over_learning_source!="NONE" or under_learning_source!="NONE",
                "desk_learning_settled_n":int(product_desk_learning.get("settled_predictions") or 0),
                "desk_learning_bucket":bucket_key,
                "desk_learning_adjustment_source":(
                    chosen_learning_source if chosen_learning_source!="NONE"
                    else ("SIDE_COMPARISON_ONLY" if over_learning_source!="NONE" or under_learning_source!="NONE" else "NONE")
                ),
                "desk_learning_exact_n":chosen_exact_n,
                "desk_learning_exact_accuracy":round(chosen_exact_accuracy,4) if chosen_exact_accuracy is not None else None,
                "walkforward_exact_line_n":int(exact_oos.get("n") or 0),
                "walkforward_exact_line_hit_rate":exact_oos.get("hit_rate"),
                "walkforward_exact_line_brier":exact_oos.get("brier"),
                "walkforward_exact_line_model_variant":exact_oos.get("variant"),
                "walkforward_exact_line_status":(
                    "INSUFFICIENT_SAMPLE" if int(exact_oos.get("n") or 0)<VFOOTBALL_HIGH_UNDER_MIN_OOS_N
                    else "WALK_FORWARD_SAMPLE_AVAILABLE_NOT_QUALIFICATION"
                ),
                "desk_calibrated_probability":round(chosen_model,4),
                "market_reference_probability":round(chosen_market,4) if chosen_market is not None else None,
                "model_edge_vs_market":round(edge,4) if edge is not None else None,
                "model_fair_odds":round(1/chosen_model,3) if chosen_model else None,
                "bookmaker_odds":(over_odds if chosen_pick=="over" else under_odds) if (over_odds or under_odds) else None,
                "sportybet_odds":(over_odds if chosen_pick=="over" else under_odds) if (over_odds or under_odds) else None,
                "sportybet_odds_market":"total",
                "sportybet_odds_line":line,
                "sportybet_odds_side":chosen_pick,
                "sportybet_over_odds":over_odds,
                "sportybet_under_odds":under_odds,
                "bookmaker_available":bool(over_odds and under_odds),
                "bookmaker_source":"SportyBet NG" if (over_odds or under_odds) else None,
                "market_odds_timestamp":e.get("timestamp") or e.get("captured_at") or live.get("updated_at"),
                "prediction_status":"betting_qualified_paper" if qualified else "research_projection",
                "projection_tier":"deep_research_projection",
                "evidence_depth":(
                    "desk_calibrated_walk_forward_participant_model"
                    if (over_learning_source!="NONE" or under_learning_source!="NONE")
                    else ("walk_forward_participant_model_plus_exact_direction" if directional.get("pass") else
                          ("walk_forward_participant_model" if validated_meta else
                           ("participant_lifecycle_plus_base_model" if participant_history>=3 else "feed_discovered_base_model")))
                ),
                "participant_status":participant_status,
                "participant_history_rows":participant_history,
                "participant_hot_watch":participant_hot,
                "participant_enhancement_gate":participant_gate,
                "product_bootstrap_gate":product_bootstrap_gate.get(product,False),
                "directional_line_gate_pass":bool(directional.get("pass")),
                "directional_line_holdout_n":directional.get("holdout_n"),
                "directional_line_holdout_hit_rate":directional.get("holdout_hit_rate"),
                "directional_line_recent_n":directional.get("recent_n"),
                "directional_line_recent_hit_rate":directional.get("recent_hit_rate"),
                "directional_line_gate_basis":directional.get("basis"),
                "product_model_min_holdout_hit_rate":EFOOTBALL_PRODUCT_MIN_HIT_RATE if product.startswith("efootball") else None,
                "base_model_gate":base_model_gate,
                "raw_competition_eligible":active_comp,
                "raw_line_eligible":active_line,
                "model_competition_qualified":model_comp,
                "model_line_qualified":model_line,
                "qualification_status":qualification_status,
                "betting_qualified":qualified,
                "qualified_for_builder":qualified,
                "qualification_engine":"Virtual Lab base walk-forward gate + model-qualified line + current SportyBet edge + competition evidence OR validated product-bootstrap evidence OR exact line/direction holdout + recent evidence",
                "model":"Virtual Lab walk-forward eFootball participant model",
                "model_version":"VL-EFOOTBALL-WF-3.0",
                "paper_only":True,
                "identity_verified":bool(home and away),
            })
    return out, {"status":"base_model_policy_parity","historical_events":len(history or []),"base_model_gate":base_model_gate,"participant_enhancement_gate":participant_gate,"live_refresh":live_refresh_meta}

def main():
    rows=[]
    for key in DESK_FILTER_STATS:
        DESK_FILTER_STATS[key]=0
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
        "summary":{"events":len(final),"sports":dict(sorted(sports.items())),"dates":dict(sorted(dates.items())),"live":live_count,"pending_settlement":pending_settlement,"settled_hidden":len(SETTLED_EVENT_IDS),"virtual_model":virtual_meta,"live_core_refresh":live_meta,
                   "publication_filters":dict(DESK_FILTER_STATS)},
        "events":final,
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    # A compact sidecar lets the AI Analyst explain stale fixtures and weak
    # exact-line evidence without pulling the entire multi-sport board into AI context.
    high_line_under={}
    for row in final:
        if str(row.get("sport") or "").lower()!="virtual" or str(row.get("pick") or "").lower()!="under":
            continue
        ln=num(row.get("line"))
        product=str(row.get("product") or "unknown")
        if ln is None or ln<7.5:
            continue
        key=f"{product}|{ln:g}|under"
        previous=high_line_under.get(key)
        record={
            "product":product,"line":ln,"side":"under",
            "event_rows":1,
            "walkforward_n":int(row.get("walkforward_exact_line_n") or 0),
            "walkforward_hit_rate":row.get("walkforward_exact_line_hit_rate"),
            "walkforward_brier":row.get("walkforward_exact_line_brier"),
            "walkforward_model_variant":row.get("walkforward_exact_line_model_variant"),
            "qualification_status":row.get("qualification_status") or "NOT_QUALIFIED",
            "betting_qualified":bool(row.get("betting_qualified")),
        }
        if previous:
            previous["event_rows"]+=1
            previous["betting_qualified"]=previous["betting_qualified"] or record["betting_qualified"]
        else:
            high_line_under[key]=record
    desk_health={
        "generated_at":NOW.isoformat(),
        "horizon_days":7,
        "event_count":len(final),
        "live_count":live_count,
        "pending_settlement_count":pending_settlement,
        "publication_filters":dict(DESK_FILTER_STATS),
        "high_line_under_evidence":list(high_line_under.values()),
        "policy":"Past kickoff rows are removed from Upcoming unless still credibly live or inside the two-hour settlement-result grace. Archived evidence is not deleted. High VFootball Under lines require their own exact-line chronological sample before betting qualification.",
    }
    (DATA/"prediction_desk_health.json").write_text(json.dumps(desk_health,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],indent=2))

if __name__=="__main__":
    main()
