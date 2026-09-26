#!/usr/bin/env python3
"""Match Signal Virtual Lab collector.

Uses the verified Cloudflare SportyBet proxy for both upcoming fixtures and
completed-result ingestion. The pipeline is read-only and paper-only.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
PENDING_PATH=DATA/"virtual_lab_pending.json"
HISTORY_PATH=DATA/"virtual_lab_history.json"
STATUS_PATH=DATA/"virtual_lab_status.json"
PARTICIPANT_REGISTRY_PATH=DATA/"virtual_lab_participants"/"registry.json"
PARTICIPANT_LIFECYCLE_PATH=DATA/"virtual_lab_participant_lifecycle.json"
PARTICIPANT_ARCHIVE_DIR=DATA/"virtual_lab_archive"/"settlements"

BASE="https://match-signal.pages.dev"
UPCOMING_API=BASE+"/api/sportybet-virtual"
RESULT_API=BASE+"/api/sportybet-virtual-results"

SESSION=requests.Session()
SESSION.headers.update({
    "Accept":"application/json",
    "User-Agent":"MatchSignal-VirtualLab/1.1",
})

PENDING_CAP=12000
HISTORY_CAP=30000
COLLECTOR_VERSION="3.0.0-v1"
SCHEMA_VERSION=1
SUPPORTED_PRODUCTS={"efootball_gt","efootball_adriatic","vfootball","zoom"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")


def num(value):
    try:
        result=float(str(value).replace(",","").replace("%","").strip())
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):
        return None


def proxy_json(url, params):
    last=None
    for attempt in range(3):
        try:
            response=SESSION.get(url,params=params,timeout=25)
            response.raise_for_status()
            payload=response.json()
            if not isinstance(payload,dict):
                raise RuntimeError("proxy returned non-object JSON")
            if payload.get("ok") is False:
                raise RuntimeError(str(payload.get("error") or "proxy returned ok=false"))
            return payload
        except Exception as exc:
            last=exc
            time.sleep(1+attempt)
    raise RuntimeError(f"{url} failed: {last}")


def line_from_specifier(value):
    text=str(value or "").lower()
    for marker in ("total=","line="):
        if marker in text:
            try:
                return float(text.split(marker,1)[1].split("&",1)[0])
            except (TypeError,ValueError):
                pass
    return None


def market_name(market):
    return str(market.get("name") or market.get("desc") or market.get("title") or "").strip()


def outcome_name(outcome):
    return str(outcome.get("name") or outcome.get("desc") or outcome.get("title") or "").strip()


def is_winner_market(market):
    mid=str(market.get("id") or "")
    name=market_name(market).lower()
    return mid in {"1","186"} or "1x2" in name or "winner" in name or "match result" in name


def is_ou_market(market):
    mid=str(market.get("id") or "")
    name=market_name(market).lower()
    return mid in {"18","189"} or "over/under" in name or "total" in name


def normalized_market(raw):
    outcomes=[]
    for outcome in raw.get("outcomes") or []:
        if not isinstance(outcome,dict):
            continue
        odds=num(outcome.get("odds"))
        name=outcome_name(outcome)
        if odds is None or odds<=1 or not name:
            continue
        outcomes.append({
            "id":str(outcome.get("id") or ""),
            "name":name,
            "odds":odds,
            "active":outcome.get("isActive") is not False,
        })
    if len(outcomes)<2:
        return None
    implied=sum(1/item["odds"] for item in outcomes)
    if implied<=0:
        return None
    for item in outcomes:
        item["implied_probability"]=1/item["odds"]
        item["fair_probability"]=item["implied_probability"]/implied
    return {
        "id":str(raw.get("id") or ""),
        "name":market_name(raw),
        "specifier":raw.get("specifier"),
        "line":line_from_specifier(raw.get("specifier")),
        "status":raw.get("status"),
        "overround":max(0.0,implied-1.0),
        "outcomes":outcomes,
        "pick":max(outcomes,key=lambda x:x["fair_probability"]),
        "market_type":"winner" if is_winner_market(raw) else "ou",
    }


def normalize_proxy_event(raw):
    event_id=str(raw.get("event_id") or raw.get("eventId") or "").strip()
    team_1=str(raw.get("team_1") or raw.get("participant_1") or raw.get("homeTeamName") or "").strip()
    team_2=str(raw.get("team_2") or raw.get("participant_2") or raw.get("awayTeamName") or "").strip()
    explicit_1=str(raw.get("participant_1") or raw.get("homeParticipant") or raw.get("homePlayer") or raw.get("homeCompetitor") or "").strip()
    explicit_2=str(raw.get("participant_2") or raw.get("awayParticipant") or raw.get("awayPlayer") or raw.get("awayCompetitor") or "").strip()
    def derived(value):
        import re
        m=re.search(r"\\(([^()]+)\\)\\s*$",str(value or ""))
        return m.group(1).strip() if m else ""
    participant_1=explicit_1 or derived(team_1)
    participant_2=explicit_2 or derived(team_2)
    product=str(raw.get("product") or "").strip()
    if product not in SUPPORTED_PRODUCTS:
        return None
    if not event_id or not team_1 or not team_2 or not product:
        return None
    start_ms=num(raw.get("start_time_ms") if raw.get("start_time_ms") is not None else raw.get("estimateStartTime"))
    if start_ms is not None and 0 < start_ms < 100000000000:
        start_ms*=1000
    if start_ms is not None and start_ms < time.time()*1000-120000:
        return None
    start_time=(datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat() if start_ms is not None else None)
    markets=[]
    for raw_market in raw.get("markets") or []:
        if not isinstance(raw_market,dict) or not (is_winner_market(raw_market) or is_ou_market(raw_market)):
            continue
        market=normalized_market(raw_market)
        if market:
            markets.append(market)
    if not markets:
        return None
    return {
        "product":product,
        "provider":"SportyBet NG via Match Signal Cloudflare proxy",
        "source":str(raw.get("source") or product),
        "event_id":event_id,
        "competition":str(raw.get("tournament") or raw.get("competition") or "Unclassified"),
        "category":str(raw.get("category") or ""),
        "tournament_id":str(raw.get("tournament_id") or ""),
        "category_id":str(raw.get("category_id") or ""),
        "team_1":team_1,
        "team_2":team_2,
        "participant_1":participant_1,
        "participant_2":participant_2,
        "identity_verified":bool(participant_1 and participant_2),
        "start_time_ms":int(start_ms) if start_ms is not None else None,
        "start_time":start_time,
        "match_status":raw.get("match_status") or raw.get("matchStatus"),
        "markets":markets,
        "captured_at":now_iso(),
    }


def fetch_upcoming():
    events=[]
    errors=[]
    seen=set()
    for page_num in (1,2):
        try:
            body=proxy_json(UPCOMING_API,{
                "pageSize":100,
                "pageNum":page_num,
                "timeline":168,
                "sources":"efootball,vfootball",
                "_t":int(time.time()*1000),
            })
            for raw in body.get("events") or []:
                event=normalize_proxy_event(raw)
                if event and event["event_id"] not in seen:
                    seen.add(event["event_id"])
                    events.append(event)
            if len(body.get("events") or [])<100:
                break
        except Exception as exc:
            errors.append(f"upcoming page {page_num}: {exc}")
            break
    return events,errors


def outcome_code(market,outcome):
    name=outcome["name"].strip().lower()
    line=market.get("line")
    line_text="" if line is None else str(line).replace(".0","")
    if name.startswith("over"):
        return "O"+line_text
    if name.startswith("under"):
        return "U"+line_text
    if name=="home":
        return "1"
    if name=="draw":
        return "X"
    if name=="away":
        return "2"
    return outcome["name"].strip()


def build_predictions(event):
    rows=[]
    winner_added=False
    for market in event["markets"]:
        if market["market_type"]=="winner" and not winner_added:
            pick=market["pick"]
            rows.append({
                "observation_id":f'{event["event_id"]}|winner|{pick["id"]}',
                "market":"winner",
                "market_id":market["id"],
                "specifier":market.get("specifier"),
                "line":None,
                "selection":outcome_code(market,pick),
                "selection_name":pick["name"],
                "odds":pick["odds"],
                "model_prob":pick["fair_probability"],
                "overround":market["overround"],
                "prediction_source":"sportybet_de_vig_market_baseline",
            })
            winner_added=True
        elif market["market_type"]=="ou" and market.get("line") is not None:
            pick=market["pick"]
            rows.append({
                "observation_id":f'{event["event_id"]}|ou|{market.get("specifier")}|{pick["id"]}',
                "market":"ou",
                "market_id":market["id"],
                "specifier":market.get("specifier"),
                "line":market.get("line"),
                "selection":outcome_code(market,pick),
                "selection_name":pick["name"],
                "odds":pick["odds"],
                "model_prob":pick["fair_probability"],
                "overround":market["overround"],
                "prediction_source":"sportybet_de_vig_market_baseline",
            })
    return rows


def capture(events,pending):
    added=0
    for event in events:
        for prediction in build_predictions(event):
            key=prediction["observation_id"]
            if key in pending:
                continue
            pending[key]={
                **prediction,
                "product":event["product"],
                "provider":event["provider"],
                "source":event["source"],
                "event_id":event["event_id"],
                "competition":event["competition"],
                "category":event["category"],
                "tournament_id":event.get("tournament_id"),
                "category_id":event.get("category_id"),
                "participant_1":event["participant_1"],
                "participant_2":event["participant_2"],
                "start_time":event.get("start_time"),
                "start_time_ms":event.get("start_time_ms"),
                "captured_at":event["captured_at"],
                "settled":False,
            }
            added+=1
    return added


def result_events(payload):
    """Extract result events from the Match Signal Cloudflare result proxy."""
    if not isinstance(payload,dict):
        return []

    # Current proxy envelope: {ok, source, scopes, events, errors}.
    events=payload.get("events")
    if isinstance(events,list):
        return [x for x in events if isinstance(x,dict)]

    # Backward-compatible nested SportyBet shapes.
    body=payload.get("payload")
    if not isinstance(body,dict):
        body=payload
    data=body.get("data")
    if isinstance(data,dict):
        tournaments=data.get("tournaments")
        if isinstance(tournaments,list):
            rows=[]
            for tournament in tournaments:
                if isinstance(tournament,dict):
                    rows.extend(x for x in tournament.get("events") or [] if isinstance(x,dict))
            if rows:
                return rows
        events=data.get("events")
        if isinstance(events,list):
            return [x for x in events if isinstance(x,dict)]
    if isinstance(data,list):
        return [x for x in data if isinstance(x,dict)]
    events=body.get("events")
    return [x for x in events if isinstance(x,dict)] if isinstance(events,list) else []


def score(event):
    def pair(a,b):
        aa,bb=num(a),num(b)
        return (aa,bb) if aa is not None and bb is not None else None
    for key in ("setScore","score","finalScore"):
        value=event.get(key)
        if isinstance(value,str) and ":" in value:
            hit=pair(*value.replace(" ","").rsplit(":",1))
            if hit:
                return hit
        elif isinstance(value,dict):
            hit=pair(value.get("home") or value.get("homeScore") or value.get("home_score"),
                     value.get("away") or value.get("awayScore") or value.get("away_score"))
            if hit:
                return hit
        elif isinstance(value,list) and len(value)>=2:
            hit=pair(value[0],value[1])
            if hit:
                return hit
    for hk in ("homeTeamScore","homeScore","home_score","homeGoals","homeGoalsCount"):
        for ak in ("awayTeamScore","awayScore","away_score","awayGoals","awayGoalsCount"):
            hit=pair(event.get(hk),event.get(ak))
            if hit:
                return hit
    nested=event.get("result") or event.get("resultScore")
    if isinstance(nested,dict):
        hit=pair(nested.get("home") or nested.get("homeScore"),
                 nested.get("away") or nested.get("awayScore"))
        if hit:
            return hit
    return None


def actual_code(item,final_score):
    home,away=final_score
    if item["market"]=="winner":
        return "1" if home>away else "2" if away>home else "X"
    line=num(item.get("line"))
    if line is None:
        return ""
    total=home+away
    line_text=str(line).replace(".0","")
    if total>line:
        return "O"+line_text
    if total<line:
        return "U"+line_text
    return "PUSH"


def settle(pending):
    unresolved=[x for x in pending.values() if not x.get("settled") and x.get("event_id")]
    if not unresolved:
        return [],0,[],{"sportybet_settled":0,"conflicts":0}

    # Keep the exact SportyBet result scope captured with the original fixture.
    # Discovering scopes only from CURRENT upcoming events is unsafe because a
    # competition disappears from the upcoming feed as soon as its fixtures finish.
    groups={}
    for item in unresolved:
        source=str(item.get("source") or "")
        if source not in {"efootball","vfootball"}:
            if str(item.get("product") or "").startswith("efootball"):
                source="efootball"
            elif item.get("product") in {"vfootball","zoom"}:
                source="vfootball"
        if source not in {"efootball","vfootball"}:
            continue
        category_id=str(item.get("category_id") or "")
        tournament_id=str(item.get("tournament_id") or "")
        start=int(num(item.get("start_time_ms")) or (time.time()*1000-86400000))
        key=(source,category_id,tournament_id)
        prev=groups.get(key)
        groups[key]=(start,start) if prev is None else (min(prev[0],start),max(prev[1],start))

    index={}
    errors=[]

    for (source,category_id,tournament_id),(start,end) in groups.items():
        start_q=start-6*3600000
        end_q=max(end+6*3600000,int(time.time()*1000))
        for page_num in range(1,9):
            try:
                params={
                    "source":source,
                    "pageSize":100,
                    "pageNum":page_num,
                    "startTime":start_q,
                    "endTime":end_q,
                }
                # Critical fix: query the exact result scope saved with the
                # original event whenever it is available. Fall back to proxy
                # discovery only for legacy rows that lack scope IDs.
                if category_id and tournament_id:
                    params["categoryId"]=category_id
                    params["tournamentId"]=tournament_id
                body=proxy_json(RESULT_API,params)
                batch=result_events(body)
                for event in batch:
                    event_id=str(event.get("eventId") or event.get("event_id") or "").strip()
                    if event_id:
                        index[event_id]=event
                if len(batch)<100:
                    break
            except Exception as exc:
                errors.append(
                    f"{source} results scope={category_id}/{tournament_id} "
                    f"page {page_num}: {exc}"
                )
                break

    history=[]
    settled_count=0
    conflicts=0

    for item in unresolved:
        primary_event=index.get(str(item.get("event_id")))
        primary_score=score(primary_event) if primary_event else None
        if primary_score is None:
            continue

        final_score=primary_score
        settlement_source="SportyBet NG eventResultList via Match Signal proxy"
        actual=actual_code(item,final_score)
        win=None if actual=="PUSH" else actual==item.get("selection")
        settled_at=now_iso()

        item.update({
            "settled":True,
            "settled_at":settled_at,
            "actual_result":actual,
            "final_score":[final_score[0],final_score[1]],
            "win":win,
            "settlement_source":settlement_source,
        })
        history.append({
            "product":item["product"],
            "provider":item["provider"],
            "event_id":item["event_id"],
            "timestamp":item.get("start_time"),
            "competition":item["competition"],
            "participant_1":item["participant_1"],
            "participant_2":item["participant_2"],
            "market":item["market"],
            "market_id":item.get("market_id"),
            "specifier":item.get("specifier"),
            "selection":item["selection"],
            "selection_name":item.get("selection_name"),
            "odds":item.get("odds"),
            "model_prob":item.get("model_prob"),
            "result":actual,
            "win":win,
            "line":item.get("line"),
            "score":f"{int(final_score[0])}:{int(final_score[1])}",
            "captured_at":item.get("captured_at"),
            "settled_at":settled_at,
            "settlement_source":settlement_source,
            "prediction_source":item.get("prediction_source"),
            "overround":item.get("overround"),
            "source":item.get("source"),
            "record_id":f'{item["event_id"]}|{item["market"]}|{item.get("line") if item.get("line") is not None else ""}|{item["selection"]}',
            "schema_version":SCHEMA_VERSION,
            "pipeline_version":COLLECTOR_VERSION,
            "participant_1_key":stable_participant_key(item["product"],item.get("participant_1")),
            "participant_2_key":stable_participant_key(item["product"],item.get("participant_2")),
            "trace_source":"sportybet_ng_result_proxy",
            "trace_id":f'{item["event_id"]}|{item["market"]}|{item.get("line") if item.get("line") is not None else ""}|{item["selection"]}',
            "collector_run_id":os.getenv("GITHUB_RUN_ID") or "local",
        })
        settled_count+=1

    return history,settled_count,errors,{"sportybet_settled":settled_count,"conflicts":conflicts}

def stable_participant_identity(product, raw_name):
    name=" ".join(str(raw_name or "").split()).strip()
    if not name:
        return None
    product=str(product or "")
    if product.startswith("efootball"):
        import re
        match=re.search(r"\(([^()]+)\)\s*$",name)
        return match.group(1).strip() if match else None
    if product in {"vfootball","zoom"}:
        return name
    return None


def stable_participant_key(product, raw_name):
    identity=stable_participant_identity(product, raw_name)
    return f"{product}|{identity.casefold()}" if identity else None


def with_trace_metadata(row):
    product=str(row.get("product") or "")
    event_id=str(row.get("event_id") or "")
    market=str(row.get("market") or "")
    line="" if row.get("line") is None else str(row.get("line"))
    selection=str(row.get("selection") or "")
    row.setdefault("record_id", f"{event_id}|{market}|{line}|{selection}")
    row.setdefault("trace_id", row["record_id"])
    row.setdefault("collector_run_id", os.getenv("GITHUB_RUN_ID") or "local")
    row.setdefault("schema_version", SCHEMA_VERSION)
    row.setdefault("pipeline_version", COLLECTOR_VERSION)
    row.setdefault("participant_1_key", stable_participant_key(product,row.get("participant_1")))
    row.setdefault("participant_2_key", stable_participant_key(product,row.get("participant_2")))
    row.setdefault("trace_source", "sportybet_ng_result_proxy")
    return row


def load_archived_settlements():
    rows=[]
    if not PARTICIPANT_ARCHIVE_DIR.exists():
        return rows
    for path in sorted(PARTICIPANT_ARCHIVE_DIR.glob('*.jsonl')):
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                try:
                    item=json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item,dict):
                    rows.append(item)
        except OSError:
            continue
    return rows


def build_participant_registry(history):
    groups={}
    combined=[]
    seen=set()
    for raw_row in list(load_archived_settlements())+list(history):
        if not isinstance(raw_row,dict):
            continue
        record_id=str(raw_row.get('record_id') or (str(raw_row.get('event_id',''))+'|'+str(raw_row.get('market',''))+'|'+str(raw_row.get('line',''))+'|'+str(raw_row.get('selection',''))))
        if record_id in seen:
            continue
        seen.add(record_id)
        combined.append(raw_row)
    for raw_row in combined:
        if not isinstance(raw_row,dict) or raw_row.get("product") not in SUPPORTED_PRODUCTS:
            continue
        row=with_trace_metadata(raw_row)
        for side in ("participant_1","participant_2"):
            identity=stable_participant_identity(row.get("product"),row.get(side))
            if not identity:
                continue
            key=stable_participant_key(row.get("product"),row.get(side))
            item=groups.setdefault(key,{
                "participant_key":key,
                "participant":identity,
                "product":row.get("product"),
                "identity_source":"historical_parenthetical_identity" if str(row.get("product")).startswith("efootball") else "historical_participant_field",
                "first_seen":None,
                "last_seen":None,
                "appearances":0,
                "settled_appearances":0,
                "ou_observations":0,
                "ou_wins":0,
                "lines":{}
            })
            ts=row.get("timestamp") or row.get("settled_at")
            if ts and (item["first_seen"] is None or ts<item["first_seen"]): item["first_seen"]=ts
            if ts and (item["last_seen"] is None or ts>item["last_seen"]): item["last_seen"]=ts
            item["appearances"]+=1
            item["settled_appearances"]+=1
            if row.get("market")=="ou" and row.get("win") is not None:
                item["ou_observations"]+=1
                if row.get("win") is True: item["ou_wins"]+=1
                line=row.get("line")
                if line is not None:
                    lk=str(line)
                    bucket=item["lines"].setdefault(lk,{"n":0,"wins":0})
                    bucket["n"]+=1
                    if row.get("win") is True: bucket["wins"]+=1
    participants=sorted(groups.values(), key=lambda x:(x["product"],x["participant"].casefold()))
    for item in participants:
        item["ou_win_rate"]=(item["ou_wins"]/item["ou_observations"]) if item["ou_observations"] else None
        for bucket in item["lines"].values():
            bucket["win_rate"]=(bucket["wins"]/bucket["n"]) if bucket["n"] else None
    return {
        "schema_version":SCHEMA_VERSION,
        "generated_at":now_iso(),
        "source_contract":"Automatic settled SportyBet history only; user ticket evidence excluded.",
        "collector_version":COLLECTOR_VERSION,
        "participant_count":len(participants),
        "participants":participants
    }


def build_participant_lifecycle(history, current_events, previous_state):
    """Build a feed-driven participant lifecycle from current feed + settled history."""
    previous_profiles={}
    if isinstance(previous_state,dict):
        for p in previous_state.get("profiles") or []:
            if isinstance(p,dict) and p.get("participant_key"):
                previous_profiles[str(p["participant_key"])]=p

    event_map={}
    for row in history:
        if not isinstance(row,dict) or row.get("win") is None:
            continue
        product=str(row.get("product") or "")
        if product not in SUPPORTED_PRODUCTS:
            continue
        event_id=str(row.get("event_id") or "")
        stamp=str(row.get("timestamp") or "")
        if not event_id or not stamp:
            continue
        score_text=str(row.get("score") or "")
        m=re.search(r"(\d+(?:\.\d+)?)\s*[:\-]\s*(\d+(?:\.\d+)?)",score_text)
        if not m:
            continue
        home=float(m.group(1)); away=float(m.group(2))
        key=f"{product}|{event_id}|{stamp}"
        event_map.setdefault(key,{
            "product":product,"event_id":event_id,"timestamp":stamp,
            "competition":str(row.get("competition") or ""),
            "participant_1":str(row.get("participant_1") or ""),
            "participant_2":str(row.get("participant_2") or ""),
            "score_home":home,"score_away":away,
        })

    current_by_key={}
    now=datetime.now(timezone.utc)
    for event in current_events if isinstance(current_events,list) else []:
        if not isinstance(event,dict):
            continue
        product=str(event.get("product") or "")
        if product not in SUPPORTED_PRODUCTS:
            continue
        start_ms=num(event.get("start_time_ms"))
        if start_ms is None:
            continue
        if start_ms<100000000000:
            start_ms*=1000
        start=datetime.fromtimestamp(start_ms/1000,timezone.utc)
        status_text=str(event.get("match_status") or "").lower()
        is_live=bool(event.get("live")) or bool(re.search(r"(live|started|inprogress|playing)",status_text))
        for side in (1,2):
            raw=str(event.get("participant_1" if side==1 else "participant_2") or "")
            identity=stable_participant_identity(product,raw)
            if not identity:
                continue
            key=stable_participant_key(product,raw)
            item=current_by_key.setdefault(key,{
                "participant_key":key,"participant":identity,"product":product,
                "today_upcoming":0,"today_live":0,"today_fixtures":[],"current_fixture_ids":[],
                "last_current_seen":None,"last_current_live":None,
            })
            if is_live:
                item["today_live"]+=1
            else:
                item["today_upcoming"]+=1
            item["current_fixture_ids"].append(str(event.get("event_id") or ""))
            item["today_fixtures"].append({
                "event_id":str(event.get("event_id") or ""),
                "start_time":start.isoformat(),
                "competition":str(event.get("competition") or ""),
                "opponent":str(event.get("participant_2" if side==1 else "participant_1") or ""),
                "live":is_live,
            })
            stamp=start.isoformat()
            if item["last_current_seen"] is None or stamp>item["last_current_seen"]:
                item["last_current_seen"]=stamp
            if is_live and (item["last_current_live"] is None or stamp>item["last_current_live"]):
                item["last_current_live"]=stamp

    history_groups={}
    for ev in event_map.values():
        for side in (1,2):
            raw=ev["participant_1"] if side==1 else ev["participant_2"]
            identity=stable_participant_identity(ev["product"],raw)
            if not identity:
                continue
            key=stable_participant_key(ev["product"],raw)
            gf=ev["score_home"] if side==1 else ev["score_away"]
            ga=ev["score_away"] if side==1 else ev["score_home"]
            history_groups.setdefault(key,[]).append({
                "timestamp":ev["timestamp"],
                "event_id":ev["event_id"],
                "competition":ev["competition"],
                "goals_for":gf,"goals_against":ga,
                "total":gf+ga,
                "opponent":stable_participant_identity(ev["product"],ev["participant_2"] if side==1 else ev["participant_1"]) or (ev["participant_2"] if side==1 else ev["participant_1"]),
            })

    profiles=[]
    all_keys=set(previous_profiles)|set(history_groups)|set(current_by_key)
    for key in all_keys:
        previous=previous_profiles.get(key,{})
        product=key.split("|",1)[0] if "|" in key else ""
        cur=current_by_key.get(key,{})
        identity=cur.get("participant") or previous.get("participant")
        if not identity and history_groups.get(key):
            raw=(history_groups[key][0].get("opponent") or "")
            identity=previous.get("participant") or raw
        if not identity:
            continue
        settled_events=sorted(history_groups.get(key,[]),key=lambda x:str(x["timestamp"]))
        n=len(settled_events)
        wins=sum(1 for x in settled_events if x["goals_for"]>x["goals_against"])
        draws=sum(1 for x in settled_events if x["goals_for"]==x["goals_against"])
        losses=n-wins-draws
        recent=settled_events[-10:]
        style={}
        for line in (1.5,3.5,4.5):
            decisive=[x for x in settled_events if x["total"]!=line]
            recent_dec=[x for x in recent if x["total"]!=line]
            over=sum(x["total"]>line for x in decisive)
            rover=sum(x["total"]>line for x in recent_dec)
            style[str(line)]={
                "n":len(decisive),"over":over,"under":len(decisive)-over,
                "over_rate":over/len(decisive) if decisive else None,
                "recent_n":len(recent_dec),
                "recent_over_rate":rover/len(recent_dec) if recent_dec else None,
            }

        monitor=[]
        for line in (1.5,3.5,4.5):
            s=style[str(line)]
            if s["n"]<8 or s["over_rate"] is None:
                continue
            shrunk=(s["over"]+2)/(s["n"]+4)
            recent_rate=s["recent_over_rate"]
            for direction,p in (("OVER",shrunk),("UNDER",1-shrunk)):
                directional=max(p,1-p)
                edge=directional-0.5
                recency_boost=0
                if recent_rate is not None:
                    recency_value=recent_rate if direction=="OVER" else 1-recent_rate
                    recency_boost=max(0,recency_value-0.5)
                strength=edge*0.7+recency_boost*0.3
                if strength>=0.10:
                    monitor.append({"line":line,"direction":direction,"strength":round(strength,4),"n":s["n"],"smoothed_rate":round(p,4),"recent_rate":recent_rate})
        monitor.sort(key=lambda x:(-x["strength"],-x["n"],x["line"]))
        grade="INSUFFICIENT"
        if monitor:
            grade="HOT_WATCH" if monitor[0]["strength"]>=0.18 and monitor[0]["n"]>=12 else "WATCH"

        last_settled=settled_events[-1]["timestamp"] if settled_events else previous.get("last_settled_at")
        last_upcoming=cur.get("last_current_seen") or previous.get("last_upcoming_at")
        last_live=cur.get("last_current_live") or previous.get("last_live_at")
        if cur.get("today_live",0):
            status="LIVE"
        elif cur.get("today_upcoming",0):
            status="UPCOMING"
        elif last_settled:
            status="DORMANT"
        else:
            status="DISCOVERED"

        profile={
            "participant_key":key,"product":product,"participant":identity,
            "status":status,"active_now":status in {"LIVE","UPCOMING"},
            "rediscovered":bool(cur and not previous.get("active_now")),
            "first_seen_at":previous.get("first_seen_at") or (settled_events[0]["timestamp"] if settled_events else cur.get("last_current_seen")),
            "last_seen_at":cur.get("last_current_seen") or previous.get("last_seen_at") or last_settled,
            "last_upcoming_at":last_upcoming,"last_live_at":last_live,"last_settled_at":last_settled,
            "lifetime_feed_appearances":int(previous.get("lifetime_feed_appearances") or 0)+int(cur.get("today_upcoming",0)+cur.get("today_live",0)),
            "today_upcoming":int(cur.get("today_upcoming",0)),
            "today_live":int(cur.get("today_live",0)),
            "settled_matches":n,"wins":wins,"draws":draws,"losses":losses,
            "win_rate":wins/n if n else None,
            "avg_goals_for":sum(x["goals_for"] for x in settled_events)/n if n else None,
            "avg_goals_against":sum(x["goals_against"] for x in settled_events)/n if n else None,
            "avg_total_goals":sum(x["total"] for x in settled_events)/n if n else None,
            "recent_form":recent[::-1],"last10":recent[::-1],
            "style":style,"monitor_candidates":monitor[:10],
            "monitor_grade":grade,
            "current_fixtures":cur.get("today_fixtures",[]),
            "current_fixture_ids":cur.get("current_fixture_ids",[]),
            "source_mode":"daily_live_feed_plus_settled_history",
        }
        if last_upcoming:
            try:
                lu=datetime.fromisoformat(str(last_upcoming).replace("Z","+00:00"))
                profile["days_since_current_feed"]=max(0,round((now-lu).total_seconds()/86400,2))
            except Exception:
                profile["days_since_current_feed"]=None
        else:
            profile["days_since_current_feed"]=None
        profile["lines"]={k:{
            "n":v["n"],"over":v["over"],"over_rate":v["over_rate"],
            "recent_n":v["recent_n"],"recent_over_rate":v["recent_over_rate"]
        } for k,v in style.items()}
        top=monitor[0] if monitor else None
        profile["hot"]={"line":top["line"],"direction":top["direction"],"strength":top["strength"],"basis_n":top["n"]} if top else None
        profiles.append(profile)

    profiles.sort(key=lambda x:(0 if x["active_now"] else 1,0 if x["monitor_grade"]=="HOT_WATCH" else 1,-(x["settled_matches"] or 0),str(x["participant"]).casefold()))
    return {
        "schema_version":1,
        "generated_at":now_iso(),
        "source_contract":"Daily SportyBet upcoming/live feed + automatic settled history; no fixed participant roster.",
        "product_scope":sorted(SUPPORTED_PRODUCTS),
        "discovery_mode":"feed_driven",
        "retirement_rule":"Absence from current future/live feed makes a participant DORMANT; history is retained for learning and reappearance reactivates the same identity key.",
        "participant_count":len(profiles),
        "active_count":sum(1 for p in profiles if p["active_now"]),
        "live_count":sum(1 for p in profiles if p["status"]=="LIVE"),
        "upcoming_count":sum(1 for p in profiles if p["status"]=="UPCOMING"),
        "dormant_count":sum(1 for p in profiles if p["status"]=="DORMANT"),
        "hot_watch_count":sum(1 for p in profiles if p["monitor_grade"]=="HOT_WATCH"),
        "profiles":profiles,
    }


def append_settlement_archive(rows):
    if not rows:
        return 0
    PARTICIPANT_ARCHIVE_DIR.mkdir(parents=True,exist_ok=True)
    day=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path=PARTICIPANT_ARCHIVE_DIR/f"{day}.jsonl"
    existing_ids=set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item=json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item,dict) and item.get("record_id"):
                existing_ids.add(item["record_id"])
    added=0
    with path.open("a",encoding="utf-8") as handle:
        for raw in rows:
            item=with_trace_metadata(dict(raw))
            if item["record_id"] in existing_ids:
                continue
            handle.write(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n")
            existing_ids.add(item["record_id"])
            added+=1
    return added

def participant_fingerprint(history):
    """Summarize recurring participant/team O/U behavior from settled history."""
    groups={}
    for row in history:
        if not isinstance(row,dict) or row.get("market")!="ou" or row.get("win") is None:
            continue
        line=num(row.get("line"))
        if line is None:
            continue
        for raw_name in (row.get("participant_1"),row.get("participant_2")):
            name=" ".join(str(raw_name or "").split()).strip()
            if not name:
                continue
            if str(row.get("product") or "") not in SUPPORTED_PRODUCTS:
                continue
            name=stable_participant_identity(row.get("product"),name)
            if not name:
                continue
            product=str(row.get("product") or "other")
            key=product+"|"+name.casefold()
            item=groups.setdefault(key,{"participant":name,"n":0,"wins":0,"lines":{},"products":{}})
            item["n"]+=1
            item["wins"]+=1 if row.get("win") else 0
            bucket=item["lines"].setdefault(str(line),{"n":0,"wins":0})
            bucket["n"]+=1
            bucket["wins"]+=1 if row.get("win") else 0
            item["products"][product]=item["products"].get(product,0)+1
    ranked=[]
    for item in groups.values():
        item["win_rate"]=item["wins"]/item["n"] if item["n"] else None
        ranked.append(item)
    ranked.sort(key=lambda x:(-x["n"],-(x["win_rate"] or 0),x["participant"].casefold()))
    return ranked

def main():
    DATA.mkdir(parents=True,exist_ok=True)
    pending_raw=load_json(PENDING_PATH,[])
    history=load_json(HISTORY_PATH,[])
    pending_raw=pending_raw if isinstance(pending_raw,list) else []
    history=history if isinstance(history,list) else []
    history=[with_trace_metadata(x) for x in history if isinstance(x,dict)]
    pending={
        str(item["observation_id"]):item
        for item in pending_raw
        if isinstance(item,dict) and item.get("observation_id")
    }

    events,capture_errors=fetch_upcoming()
    added=capture(events,pending)
    settled_rows,newly_settled,settle_errors,settlement_meta=settle(pending)
    merged_keys={
        (str(x.get("event_id")),str(x.get("market")),str(x.get("line")),str(x.get("selection")))
        for x in history if isinstance(x,dict)
    }
    for row in settled_rows:
        key=(str(row.get("event_id")),str(row.get("market")),str(row.get("line")),str(row.get("selection")))
        if key not in merged_keys:
            history.append(row)
            merged_keys.add(key)
    history.sort(key=lambda x:str(x.get("timestamp") or ""))
    history=history[-HISTORY_CAP:]
    pending={key:item for key,item in pending.items() if not item.get("settled")}
    if len(pending)>PENDING_CAP:
        rows=sorted(pending.values(),key=lambda x:str(x.get("start_time") or ""))
        pending={str(x["observation_id"]):x for x in rows[-PENDING_CAP:]}

    settled=[x for x in history if x.get("win") is not None]
    wins=sum(bool(x.get("win")) for x in settled)
    products={}
    for event in events:
        products[event["product"]]=products.get(event["product"],0)+1

    participant_rows=participant_fingerprint(history)
    participant_ou15=[]
    for item in participant_rows:
        line=item.get("lines",{}).get("1.5")
        if line and line.get("n",0)>0:
            participant_ou15.append({
                "participant":item["participant"],
                "n":line["n"],
                "wins":line["wins"],
                "win_rate":line["wins"]/line["n"]
            })
    participant_ou15.sort(key=lambda x:(-x["n"],-x["win_rate"],x["participant"].casefold()))

    errors=capture_errors+settle_errors
    save_json(PENDING_PATH,list(pending.values()))
    save_json(HISTORY_PATH,history)
    registry=build_participant_registry(history)
    PARTICIPANT_REGISTRY_PATH.parent.mkdir(parents=True,exist_ok=True)
    save_json(PARTICIPANT_REGISTRY_PATH,registry)
    previous_lifecycle=load_json(PARTICIPANT_LIFECYCLE_PATH,{})
    lifecycle=build_participant_lifecycle(history,events,previous_lifecycle)
    save_json(PARTICIPANT_LIFECYCLE_PATH,lifecycle)
    archived_new=append_settlement_archive(settled_rows)
    save_json(STATUS_PATH,{
        "updated_at":now_iso(),
        "collector_version":COLLECTOR_VERSION,
        "schema_version":SCHEMA_VERSION,
        "build_commit":os.getenv("GITHUB_SHA") or "local",
        "upcoming_events":len(events),
        "upcoming_by_product":products,
        "pending_observations":len(pending),
        "settled_observations":len(history),
        "settled_decisions":len(settled),
        "settled_wins":wins,
        "settled_accuracy":round(wins/len(settled),4) if settled else None,
        "new_observations":added,
        "newly_settled":newly_settled,
        "archive_new_records":archived_new,
        "sportybet_settled":settlement_meta["sportybet_settled"],
        "settlement_conflicts":settlement_meta["conflicts"],
        "participant_fingerprint_count":len(participant_rows),
        "participant_lifecycle_count":lifecycle["participant_count"],
        "participant_lifecycle_active":lifecycle["active_count"],
        "participant_lifecycle_live":lifecycle["live_count"],
        "participant_lifecycle_upcoming":lifecycle["upcoming_count"],
        "participant_lifecycle_dormant":lifecycle["dormant_count"],
        "participant_lifecycle_hot_watch":lifecycle["hot_watch_count"],
        "participant_ou15_leaders":participant_ou15[:25],
        "participant_model_policy":{
            "same_product_only":True,
            "time_safe":True,
            "minimum_exact_line_observations":8,
            "maximum_probability_weight":0.25,
            "note":"Participant history is a model feature only after enough prior settled events; user-reported tickets are not injected into the automatic training dataset."
        },
        "result_source":"SportyBet NG eventResultList via Match Signal Cloudflare proxy",
        "prediction_source":"SportyBet live no-vig market baseline",
        "errors":errors[-20:],
        "paper_only":True,
        "walk_forward_model_artifact":"data/virtual_lab_model_eval.json",
        "walk_forward_model_policy":"strict chronological holdout; participant feature cannot activate without untouched dual-loss improvement",
        "active_product_contract":sorted(SUPPORTED_PRODUCTS),
        "trace_contract":"Every settled row has deterministic record_id/trace_id plus collector_run_id.",
    })
    print(f"Virtual Lab collector: {len(events)} upcoming events | +{added} observations | +{newly_settled} settled | {len(history)} history rows | {len(pending)} pending")
    for error in errors[-10:]:
        print("WARNING:",error)


if __name__=="__main__":
    main()
