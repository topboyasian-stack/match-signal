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
MIN_LEGS,MAX_LEGS=1,20
MIN_COMBINED_ODDS=4.0
VIRTUAL_MIN_PROB=0.65
PARTICIPANT_HISTORY_MIN_N=3
PARTICIPANT_HISTORY_MAX_BONUS=0.035
MAX_BATCHES=6


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
        stamp=x.get("odds_timestamp") or x.get("market_odds_timestamp")
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
        out.append(y)
    return out,join_diag

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
    return hit>=threshold,{"n":len(exact),"wins":wins,"hit_rate":round(hit,4),"threshold":threshold,"side":str(pick or "").lower()}

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

    templates={}
    for row in merged:
        if not isinstance(row,dict) or row.get("sport")!="virtual" or not row.get("betting_qualified"):
            continue
        line=row.get("line"); pick=str(row.get("pick") or "").lower()
        if line is None or pick not in {"over","under"}:
            continue
        try:
            key=template_key(row.get("product"),line,pick)
        except (TypeError,ValueError):
            continue
        try:
            prob=float(row.get("probability") or 0)
        except (TypeError,ValueError):
            prob=0.0
        prev=templates.get(key)
        if prev is None or prob>float(prev.get("probability") or 0):
            templates[key]=row

    out=[]
    diagnostics={
        "seen":0,"qualified":0,"evidence_pass":0,"rejected_evidence":0,
        "current_feed_events":0,"model_templates":len(templates),
        "current_market_candidates":0,"reasons":{}
    }
    diagnostics["current_feed_events"]=len({str(x.get("event_id") or "") for x in merged if isinstance(x,dict) and x.get("event_id")})
    diagnostics["model_template_keys"]=[list(k) for k in sorted(templates.keys())]
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
        if not upcoming(event,now):
            continue
        product=str(event.get("product") or "")
        line=event.get("line")
        pick=str(event.get("pick") or "").lower()
        if line is None or pick not in {"over","under"}:
            continue
        template=templates.get(template_key(product,line,pick))
        if not template:
            continue
        try:
            prob=float(template.get("probability") or 0)
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
            "line":line,"pick":pick,
            "probability":prob,"builder_probability":prob,
            "bookmaker_available":True,
            "sportybet_over_odds":over,"sportybet_under_odds":under,
            "bookmaker_odds":over if pick=="over" else under,
            "sportybet_odds":over if pick=="over" else under,
            "bookmaker_source":"SportyBet NG",
            "sportybet_event_id":str(event.get("sportybet_event_id") or event.get("event_id") or ""),
            "sportybet_match":event.get("sportybet_match") or event.get("match"),
            "market_odds_timestamp":event.get("market_odds_timestamp"),
            "sportybet_identity_match":True,
            "builder_pick":pick,"builder_market":"virtual_total",
            "price_snapshot_source":source,
        })
        passed,recent=virtual_recent_gate(product,line,pick)
        if not passed:
            diagnostics["rejected_evidence"]+=1
            reason=str(recent.get("reason") or "recent_evidence_below_threshold")
            diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1
            continue
        diagnostics["evidence_pass"]+=1
        y["recent_evidence"]=recent
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
    # Participant history is an informational ranking feature only. The batch
    # assembler now ranks by whole-ticket model probability and edge, so avoid
    # loading/scoring the profile artifact for every candidate leg.
    participant_history={"available":False,"score":0.5,"participants":[]}
    history_bonus=0.0
    selection_score=(edge if edge is not None else -1.0)
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
        "market_odds_timestamp":x.get("odds_timestamp") or x.get("market_odds_timestamp")
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
        vals=[p.strip() for p in re.split(r"\\s+vs\\s+",match,flags=re.I) if p.strip()]
    out=[]
    for v in vals:
        s=re.sub(r"[^a-z0-9]+"," ",str(v).lower()).strip()
        if s and s not in out: out.append(s)
    return out

def _batch_metrics(legs):
    probs=[max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0))) for x in legs if float(x.get("model_probability") or 0.0)>0]
    edges=[float(x.get("model_edge") or 0.0) for x in legs]
    if not probs:
        return {
            "model_rating":0.0,
            "combined_model_probability":0.0,
            "leg_strength_rating":0.0,
            "avg_model_probability":0.0,
            "avg_model_edge_percent":0.0
        }
    combined=math.prod(probs)
    geometric=math.exp(sum(math.log(p) for p in probs)/len(probs))
    return {
        # Headline rating is the whole-ticket naive joint model probability,
        # expressed on a 0-100 scale. It is a transparent proxy, not a guarantee.
        "model_rating":round(combined*100.0,2),
        "combined_model_probability":round(combined,6),
        "leg_strength_rating":round(geometric*100.0,2),
        "avg_model_probability":round(sum(probs)/len(probs)*100.0,2),
        "avg_model_edge_percent":round(sum(edges)/len(edges)*100.0,2) if edges else 0.0,
    }


def build_value_batches(candidates):
    """Create several disjoint 4.00+ paper batches using odds efficiency.

    The objective is not to minimize the number of legs. It is to find batches
    whose product of model probabilities is as strong as possible while the
    actual SportyBet combined odds clear 4.00. vFootball receives priority as
    the current strongest validated research lane.
    """
    built=[make_leg(x) for x in candidates]
    eligible_all=[x for x in built if x.get("builder_eligible")]
    # vFootball is the primary research lane. Use it exclusively while there
    # are enough qualified legs to form the requested batch set; only fall back
    # to other Virtual products when vFootball cannot supply another batch.
    vfootball_pool=[x for x in eligible_all if str(x.get("product") or "")=="vfootball"]
    other_pool=[x for x in eligible_all if str(x.get("product") or "")!="vfootball"]
    remaining=vfootball_pool if len(vfootball_pool)>=2 else eligible_all
    fallback_pool=other_pool
    batches=[]
    used_events=set()
    used_leg_keys=set()
    product_priority={"vfootball":3,"efootball_gt":2,"efootball_adriatic":1}

    def efficiency(leg):
        try:
            p=max(0.0005,min(0.9995,float(leg.get("model_probability") or 0.0)))
            odds=float(leg.get("bookmaker_odds") or 1.0)
            if odds<=1.0:
                return 999.0
            return -math.log(p)/math.log(odds)
        except (TypeError,ValueError,ZeroDivisionError):
            return 999.0

    for _ in range(MAX_BATCHES):
        if not remaining:
            break
        remaining.sort(key=lambda x:(
            efficiency(x),
            -product_priority.get(str(x.get("product") or ""),0),
            -float(x.get("model_edge") or 0),
            -float(x.get("model_probability") or 0),
            -float(x.get("bookmaker_odds") or 0)
        ))
        batch=[]
        batch_events=set()
        batch_participants=set()
        combined=1.0
        for leg in remaining:
            eid=str(leg.get("event_id") or "")
            if eid and eid in batch_events:
                continue
            pids=set(_participants(leg))
            if pids & batch_participants:
                continue
            batch.append(leg)
            if eid:
                batch_events.add(eid)
            batch_participants.update(pids)
            combined*=float(leg.get("bookmaker_odds") or 1.0)
            if combined>=MIN_COMBINED_ODDS or len(batch)>=MAX_LEGS:
                break
        if not batch or combined<MIN_COMBINED_ODDS:
            # If participant-correlation prevents a 4.00+ batch, retry using
            # event uniqueness only. This still prevents same-event market
            # duplication while avoiding an accidental empty Builder.
            batch=[];batch_events=set();batch_participants=set();combined=1.0
            for leg in remaining:
                eid=str(leg.get("event_id") or "")
                if eid and eid in batch_events:
                    continue
                batch.append(leg)
                if eid:
                    batch_events.add(eid)
                combined*=float(leg.get("bookmaker_odds") or 1.0)
                if combined>=MIN_COMBINED_ODDS or len(batch)>=MAX_LEGS:
                    break
        if not batch or combined<MIN_COMBINED_ODDS:
            # Exhaust the primary vFootball lane before opening other Virtual
            # products. This preserves the intended research priority.
            if remaining is vfootball_pool and fallback_pool:
                remaining=fallback_pool
                fallback_pool=[]
                continue
            break

        metrics=_batch_metrics(batch)
        products=sorted({str(x.get("product") or "") for x in batch if x.get("product")})
        batch_id=f"BATCH-{len(batches)+1:02d}"
        batches.append({
            "batch_id":batch_id,
            "label":f"{batch_id} · Combined Model Rating {metrics['model_rating']:.1f}/100",
            "rank_pending":True,
            "legs":batch,
            "leg_count":len(batch),
            "combined_odds":round(combined,3),
            "combined_model_rating":metrics["model_rating"],
            "combined_model_probability":metrics["combined_model_probability"],
            "leg_strength_rating":metrics["leg_strength_rating"],
            "avg_model_probability":metrics["avg_model_probability"],
            "avg_model_edge_percent":metrics["avg_model_edge_percent"],
            "products":products,
            "primary_lane": "vfootball" if any(str(x.get("product") or "")=="vfootball" for x in batch) else "fallback_virtual",
            "paper_only":True,
            "real_money_execution":False,
            "correlation_policy":"same-event prevented; participant reuse used only as fallback if strict disjoint construction cannot reach 4.00+"
        })
        chosen_keys={(str(x.get("event_id") or ""),str(x.get("pick") or ""),str(x.get("line") or "")) for x in batch}
        used_leg_keys.update(chosen_keys)
        used_events.update(batch_events)
        # A fixture may carry many O/U lines, but a fixture belongs to only one
        # batch. Remove every remaining leg for the events already assigned.
        remaining=[x for x in remaining if str(x.get("event_id") or "") not in used_events]

    batches.sort(key=lambda b:(b.get("combined_model_rating",0),b.get("avg_model_edge_percent",0),b.get("combined_odds",0)),reverse=True)
    for i,b in enumerate(batches,1):
        b["rank"]=i
        b["batch_id"]=f"BATCH-{i:02d}"
        b["rank_pending"]=False
        b["label"]=f"BATCH-{i:02d} · Combined Model Rating {float(b.get('combined_model_rating') or 0):.1f}/100"
    return batches,built,{
        "batch_count":len(batches),
        "max_batches":MAX_BATCHES,
        "disjoint":True,
        "min_combined_odds":MIN_COMBINED_ODDS,
        "priority_product":"vfootball",
        "used_unique_events":len(used_events),
        "ranking_metric":"naive joint model probability; leg-strength rating reported separately",
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
    # The accumulator must never bypass the upstream research/risk gate.
    # This prevents the builder from turning a losing public prediction feed
    # into an apparent betting recommendation.
    upstream_blocked = gate_status not in {"ok","PASS"} or selected_predictions <= 0 or not tennis_live_eligible
    football=football_candidates(now)
    tennis=tennis_candidates(now)
    virtual,virtual_diag=virtual_candidates(now)
    core_pool=[] if upstream_blocked else (football+tennis)
    batches,built,batch_diag=build_value_batches(core_pool+virtual)
    primary=batches[0] if batches else None
    selected=list(primary.get("legs") or []) if primary else []
    combined=float(primary.get("combined_odds") or 1.0) if primary else 1.0
    selection_diag={"participant_correlation_skips":0,"unique_participants":len({_p for leg in selected for _p in _participants(leg)}) if selected else 0}
    previous=load(OUTPUT,{})
    previous_ids={str(x) for x in (previous.get("builder_event_ids",[]) if isinstance(previous,dict) else []) if x}
    previous_ids.update(str(x.get("event_id")) for x in (previous.get("qualified_legs",[]) if isinstance(previous,dict) else []) if isinstance(x,dict) and x.get("event_id"))
    known=previous_ids|{"183724","183769"}
    settled_ids={str(x.get("event_id")) for x in load(HISTORY,[]) if isinstance(x,dict) and x.get("settled") and x.get("event_id")}
    selected=[x for x in selected if str(x.get("event_id")) not in settled_ids]
    sports=sorted({x["sport"] for x in selected})
    target_met=combined>=MIN_COMBINED_ODDS and bool(selected)
    status="LIVE_VALUE_SET" if target_met else ("BELOW_4_TARGET_AVAILABLE" if selected else "NO_BET")
    rejection_counts={}
    for leg in built:
        leg_status=str(leg.get("status") or "REJECTED")
        rejection_counts[leg_status]=rejection_counts.get(leg_status,0)+1
    result={
        "generated_at":now.isoformat(),"engine_version":"V6.1-RESEARCH-GATED",
        "mode":"PAPER_ONLY","target_legs":"variable until combined odds >= 4.00","sports_supported":["football","tennis","virtual"],
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
            "virtual_candidates":len(virtual),
            "virtual_gate_diagnostics":virtual_diag,
            "evaluated":len(built),
            "rejections":rejection_counts,"selection_diversity":selection_diag,
            "batch_diagnostics":batch_diag,
            "participant_history_weighting":{
                "enabled":True,
                "min_n":PARTICIPANT_HISTORY_MIN_N,
                "max_bonus":PARTICIPANT_HISTORY_MAX_BONUS,
                "role":"ranking_only_after_all_existing_eligibility_gates",
                "source":"data/virtual_lab_participant_profiles.json"
            }
        },
        "selection_policy":{"min_calibrated_probability":MIN_PROB,"virtual_min_probability":VIRTUAL_MIN_PROB,"virtual_builder_lines":"all current O/U lines with exact-side evidence; no forced line list","minimum_combined_odds":MIN_COMBINED_ODDS,"min_model_edge":MIN_EDGE,
            "max_odds_age_seconds":MAX_ODDS_AGE_SECONDS,"max_uncertainty":MAX_UNCERTAINTY,
            "min_data_quality":MIN_DATA_QUALITY,"requires_live_sportybet_price":True,
            "requires_complete_market_for_devig":True,"avoid_same_event_correlation":True,
            "participant_history_weighting":"qualified-leg ranking only; conservative exact-line settled O/U history; no eligibility bypass",
            "never_force_accumulator":True,"real_money_execution":False},
        "bookmaker_odds":{"status":"LIVE_SPORTYBET_SNAPSHOT","sportybet_direct_feed":"VIA_CLOUDFLARE_PROXY",
            "stake_direct_feed":"NOT_CONNECTED","instruction":"Verify the displayed SportyBet price immediately before any manual wager."},
        "candidates_considered":{"football":len(football),"tennis":len(tennis),"virtual":len(virtual),"all_built":len(built)},
        "qualified_legs":selected if target_met else [],
        "best_available_legs":selected,
        "combined_odds_selected":round(combined,3) if selected else None,
        "naive_independence_hit_proxy":round(math.prod(float(x.get("model_probability") or 0) for x in selected),6) if selected else None,
        "batch_count":len(batches),
        "batch_policy":{
            "min_combined_odds":MIN_COMBINED_ODDS,
            "max_batches":MAX_BATCHES,
            "disjoint_batches":True,
            "ranking":"combined_model_rating descending, then average model edge, then combined odds",
            "model_rating_definition":"100 × product of leg model probabilities (naive joint proxy)",
            "leg_strength_definition":"100 × geometric mean of leg model probabilities",
            "primary_lane":"vfootball"
        },
        "batches":batches,
        "rejected_candidates":[x for x in built if not x["real_money_eligible"]][:20],
        "settled_legs":recent_settled(load(HISTORY,[]),now,known),
        "builder_event_ids":sorted(known),"leg_count":len(selected),"sports_selected":sports,
        "status":("UPSTREAM_RESEARCH_GATE_BLOCKED" if upstream_blocked and not virtual else ("LIVE_VALUE_SET" if target_met else ("BELOW_4_TARGET_AVAILABLE" if selected else "NO_BET"))),
        "reference_combined_odds":round(math.prod(x["model_fair_odds"] for x in selected),3) if selected else None,
        "reference_odds_type":"MODEL_FAIR_ODDS_NOT_BOOKMAKER_PRICE",
        "market_price_combined_odds":round(combined,3) if selected else None,
        "theme":{"name":"Midnight Graphite / Electric Cyan / Signal Green","accent":"#28D7E8","positive":"#35D07F","background":"#080D14"},
        "notes":["V6 qualifies on market edge, not probability alone.","Missing or stale SportyBet prices produce NO_BET/REJECTED.","Model fair odds never overwrite bookmaker odds.","Each Builder batch is a separate disjoint paper ticket at 4.00+ combined bookmaker odds; batches are ranked by combined model rating.","vFootball is prioritized because its existing untouched O/U evidence is currently the strongest active research lane.","Paper-only until V6 demonstrates stable calibration, edge and closing-line value over a meaningful sample."]
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()

# Refresh marker: exact-side virtual evidence gate is active.
# Batch marker: vFootball-priority disjoint 4.00+ research batches.
