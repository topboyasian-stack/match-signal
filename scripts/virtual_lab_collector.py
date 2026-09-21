#!/usr/bin/env python3
"""Match Signal Virtual Lab collector.

Uses the verified Cloudflare SportyBet proxy for both upcoming fixtures and
completed-result ingestion. The pipeline is read-only and paper-only.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
PENDING_PATH=DATA/"virtual_lab_pending.json"
HISTORY_PATH=DATA/"virtual_lab_history.json"
STATUS_PATH=DATA/"virtual_lab_status.json"

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
    home=str(raw.get("participant_1") or raw.get("homeTeamName") or "").strip()
    away=str(raw.get("participant_2") or raw.get("awayTeamName") or "").strip()
    product=str(raw.get("product") or "").strip()
    if not event_id or not home or not away or not product:
        return None
    start_ms=num(raw.get("start_time_ms") if raw.get("start_time_ms") is not None else raw.get("estimateStartTime"))
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
        "participant_1":home,
        "participant_2":away,
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
                "sources":"efootball,srl,vfootball",
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
    body=payload.get("payload")
    if not isinstance(body,dict):
        return []
    data=body.get("data")
    if isinstance(data,dict) and isinstance(data.get("tournaments"),list):
        rows=[]
        for tournament in data["tournaments"]:
            if isinstance(tournament,dict):
                rows.extend(x for x in tournament.get("events") or [] if isinstance(x,dict))
        return rows
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
        return [],0,[]
    grouped={}
    for item in unresolved:
        source=str(item.get("source") or "")
        if source not in {"srl","efootball","vfootball"}:
            if item.get("product")=="srl": source="srl"
            elif str(item.get("product") or "").startswith("efootball"): source="efootball"
            elif item.get("product") in {"vfootball","zoom"}: source="vfootball"
        start=int(num(item.get("start_time_ms")) or (time.time()*1000-86400000))
        prev=grouped.get(source)
        grouped[source]=(start,start) if prev is None else (min(prev[0],start),max(prev[1],start))

    index={}
    errors=[]
    for source,(start,end) in grouped.items():
        if source not in {"srl","efootball","vfootball"}:
            continue
        start_q=start-6*3600000
        end_q=max(end+6*3600000,int(time.time()*1000))
        for page_num in range(1,9):
            try:
                body=proxy_json(RESULT_API,{
                    "source":source,
                    "pageSize":100,
                    "pageNum":page_num,
                    "startTime":start_q,
                    "endTime":end_q,
                })
                batch=result_events(body)
                if not batch:
                    break
                for event in batch:
                    event_id=str(event.get("eventId") or event.get("event_id") or "").strip()
                    if event_id:
                        index[event_id]=event
                if len(batch)<100:
                    break
            except Exception as exc:
                errors.append(f"{source} results page {page_num}: {exc}")
                break

    history=[]
    settled_count=0
    for item in pending.values():
        if item.get("settled"):
            continue
        result=index.get(str(item.get("event_id")))
        if not result:
            continue
        final_score=score(result)
        if final_score is None:
            continue
        actual=actual_code(item,final_score)
        win=None if actual=="PUSH" else actual==item.get("selection")
        settled_at=now_iso()
        item.update({
            "settled":True,
            "settled_at":settled_at,
            "actual_result":actual,
            "final_score":[final_score[0],final_score[1]],
            "win":win,
            "settlement_source":"SportyBet NG eventResultList via Match Signal proxy",
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
            "settlement_source":item["settlement_source"],
            "prediction_source":item.get("prediction_source"),
            "overround":item.get("overround"),
            "source":item.get("source"),
        })
        settled_count+=1
    return history,settled_count,errors


def main():
    DATA.mkdir(parents=True,exist_ok=True)
    pending_raw=load_json(PENDING_PATH,[])
    history=load_json(HISTORY_PATH,[])
    pending_raw=pending_raw if isinstance(pending_raw,list) else []
    history=history if isinstance(history,list) else []
    pending={
        str(item["observation_id"]):item
        for item in pending_raw
        if isinstance(item,dict) and item.get("observation_id")
    }

    events,capture_errors=fetch_upcoming()
    added=capture(events,pending)
    settled_rows,newly_settled,settle_errors=settle(pending)
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

    errors=capture_errors+settle_errors
    save_json(PENDING_PATH,list(pending.values()))
    save_json(HISTORY_PATH,history)
    save_json(STATUS_PATH,{
        "updated_at":now_iso(),
        "collector_version":"1.1",
        "upcoming_events":len(events),
        "upcoming_by_product":products,
        "pending_observations":len(pending),
        "settled_observations":len(history),
        "settled_decisions":len(settled),
        "settled_wins":wins,
        "settled_accuracy":round(wins/len(settled),4) if settled else None,
        "new_observations":added,
        "newly_settled":newly_settled,
        "result_source":"SportyBet NG eventResultList via Match Signal Cloudflare proxy",
        "prediction_source":"SportyBet live no-vig market baseline",
        "errors":errors[-20:],
        "paper_only":True,
    })
    print(f"Virtual Lab collector: {len(events)} upcoming events | +{added} observations | +{newly_settled} settled | {len(history)} history rows | {len(pending)} pending")
    for error in errors[-10:]:
        print("WARNING:",error)


if __name__=="__main__":
    main()
