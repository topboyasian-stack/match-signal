"""Build a guarded 3-4 leg Match Signal research slip.

Analysis layer only: it never places or stakes a wager. Football and tennis
candidates are accepted only when they pass the existing research gate or the
strict tennis paper-selection gate, then still match live SportyBet markets.
"""
from __future__ import annotations
import difflib, json, math, re
from datetime import datetime, timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"; CANDIDATES=DATA/"selection_candidates.json"; PREDICTIONS=DATA/"predictions.json"; OUTPUT=DATA/"odds_builder.json"
SPORTY_BASE="https://www.sportybet.com"; SPORTY_REGION="ng"; MIN_LEGS=3; MAX_LEGS=4; MIN_MODEL_PROB=0.65; MIN_EDGE=0.03; TENNIS_MIN_PROB=0.65
SESSION=requests.Session(); SESSION.headers.update({"Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Current-Country":"NG","User-Agent":"Mozilla/5.0 (compatible; MatchSignal/1.0; +https://match-signal.pages.dev)"})

def load(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError): return default

def norm(value):
    s=re.sub(r"[^a-z0-9]+"," ",str(value or "").lower().replace("&"," and ")).strip()
    aliases={"man utd":"manchester united","man united":"manchester united","man city":"manchester city","psv eindhoven":"psv","sporting lisbon":"sporting cp","internazionale":"inter milan","inter":"inter milan"}
    return aliases.get(s,s)

def similarity(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    if a in b or b in a:return 0.94
    return difflib.SequenceMatcher(None,a,b).ratio()

def sporty_response_json(response, label):
    content_type=(response.headers.get("content-type") or "").lower()
    text=response.text or ""
    diagnostic={"http_status":response.status_code,"content_type":content_type,"body_prefix":re.sub(r"\s+"," ",text[:500])}
    if not text.strip(): raise RuntimeError(f"{label}: EMPTY_RESPONSE {json.dumps(diagnostic,ensure_ascii=False)}")
    try: return response.json()
    except ValueError as exc:
        if "text/html" in content_type or re.search(r"<html|<!doctype",text[:300],re.I): kind="HTML_OR_CHALLENGE"
        elif response.status_code in (401,403,429): kind=f"HTTP_ACCESS_{response.status_code}"
        else: kind="NON_JSON_RESPONSE"
        raise RuntimeError(f"{label}: {kind} {json.dumps(diagnostic,ensure_ascii=False)}") from exc

def sportyevents(sport_id,market_ids,label):
    url=f"{SPORTY_BASE}/api/{SPORTY_REGION}/factsCenter/pcUpcomingEvents"
    params={"sportId":sport_id,"marketId":",".join(market_ids),"pageSize":100,"pageNum":1,"todayGames":"false","timeline":168,"_t":int(datetime.now(timezone.utc).timestamp()*1000)}
    r=SESSION.get(url,params=params,timeout=30)
    if r.status_code in (401,403,429): raise RuntimeError(f"{label}: HTTP_ACCESS_{r.status_code} url={url} content_type={r.headers.get('content-type','')} body={re.sub(r'\s+',' ',(r.text or '')[:300])}")
    r.raise_for_status(); body=sporty_response_json(r,label)
    if not isinstance(body,dict): raise RuntimeError(f"{label}: INVALID_JSON_ROOT type={type(body).__name__}")
    if body.get("bizCode") not in (None,10000): raise RuntimeError(f"{label}: SPORTY_BIZCODE_{body.get('bizCode')} message={body.get('message') or body.get('msg')}")
    data=body.get("data") or {}
    tournaments=data.get("tournaments") or data.get("tournamentList") or []
    events=[]
    for tournament in tournaments:
        if not isinstance(tournament,dict): continue
        for event in tournament.get("events") or tournament.get("eventList") or []:
            if isinstance(event,dict): event["_tournament"]=tournament.get("name") or tournament.get("tournamentName"); events.append(event)
    if not events:
        raise RuntimeError(f"{label}: VALID_RESPONSE_BUT_NO_EVENTS schema_keys={sorted(data.keys()) if isinstance(data,dict) else []}")
    return events

def match_candidate(candidate,events):
    best,best_score=None,0.0
    for event in events:
        score=(similarity(candidate.get("player_1"),event.get("homeTeamName"))+similarity(candidate.get("player_2"),event.get("awayTeamName")))/2
        if score>best_score: best,best_score=event,score
    return best if best_score>=0.84 else None

def market_outcomes(event,market_ids):
    for market in event.get("markets") or []:
        if str(market.get("id")) in market_ids:
            outcomes={str(x.get("id")):x for x in market.get("outcomes") or [] if x.get("isActive",True)}
            if outcomes:return market,outcomes
    return None,{}

def football_candidates():
    raw=load(CANDIDATES,[])
    return [x for x in raw if isinstance(x,dict) and x.get("candidate_status")=="SELECTED" and x.get("sport")=="football"] if isinstance(raw,list) else []

def tennis_candidates():
    raw=load(PREDICTIONS,[]); out=[]
    if not isinstance(raw,list): return out
    for x in raw:
        if not isinstance(x,dict) or x.get("sport")!="tennis": continue
        probs=x.get("probabilities") or {}; pick=x.get("pick"); match_prob=float(probs.get(pick,0) or 0) if pick else 0.0
        total=(x.get("analytics") or {}).get("total_games") or {}; ou_pick=total.get("pick"); ou_prob=float(total.get(ou_pick,0) or 0) if ou_pick else 0.0
        if match_prob>=TENNIS_MIN_PROB: out.append({**x,"builder_market":"winner","builder_probability":match_prob,"builder_pick":pick,"candidate_status":"PAPER_SELECTED"})
        elif ou_prob>=TENNIS_MIN_PROB and total.get("line") is not None: out.append({**x,"builder_market":"total_games","builder_probability":ou_prob,"builder_pick":ou_pick,"candidate_status":"PAPER_SELECTED"})
    return out

def main():
    football=football_candidates(); football.sort(key=lambda x:(float(x.get("confidence",0) or 0),float((x.get("signal_quality") or {}).get("components",0) or 0)),reverse=True)
    tennis=tennis_candidates(); tennis.sort(key=lambda x:float(x.get("builder_probability",0) or 0),reverse=True)
    result={"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"PAPER_ONLY","target_legs":"3-4","sports_supported":["football","tennis"],"selection_policy":{"min_model_probability":MIN_MODEL_PROB,"min_model_edge_vs_sporty_implied":MIN_EDGE,"tennis_min_probability":TENNIS_MIN_PROB,"requires_upstream_selection_gate_for_football":True,"tennis_source":"existing predictions.json paper analytics","public_prediction_feed_unchanged":True},"sportybet":{"status":"NOT_RUN","booking_code":None,"share_url":None,"legs":[],"expires_at":None},"stake":{"status":"MANUAL_SHARE_INTERFACE_REQUIRED","booking_url":None,"booking_code":None},"candidates_considered":{"football":len(football),"tennis":len(tennis)},"qualified_legs":[],"notes":["Football selections must come from the existing research gate.","Tennis selections use existing paper predictions only and require a probability of at least 0.65 for either match winner or a published total-games O/U market.","No slip is generated unless 3-4 selections also match live SportyBet markets with the required edge/probability checks.","Stake automatic betslip creation remains disabled until a stable supported share interface is verified."]}
    legs=[]
    try: football_events=sportyevents("sr:sport:1",["1"],"FOOTBALL_SOURCE")
    except Exception as exc: football_events=[]; result["sportybet"]["football_source_error"]=str(exc)
    for candidate in football:
        if len(legs)>=MAX_LEGS: break
        event=match_candidate(candidate,football_events); market,outcomes=market_outcomes(event,{"1"}) if event else (None,{})
        outcome_id={"p1":"1","draw":"2","p2":"3"}.get(candidate.get("pick"))
        if not market or outcome_id not in outcomes: continue
        try: odds=float(outcomes[outcome_id].get("odds")); model_prob=float((candidate.get("probabilities") or {}).get(candidate.get("pick"),candidate.get("confidence",0)))
        except (TypeError,ValueError): continue
        implied=1/odds if odds>1 else 1.0; edge=model_prob-implied
        if model_prob<MIN_MODEL_PROB or edge<MIN_EDGE: continue
        legs.append({"sport":"football","league":candidate.get("league"),"event_id":candidate.get("event_id"),"sporty_event_id":str(event.get("eventId")),"home":event.get("homeTeamName"),"away":event.get("awayTeamName"),"market":"1X2","pick":candidate.get("pick"),"selection":outcomes[outcome_id].get("desc"),"model_probability":round(model_prob,6),"sporty_odds":odds,"implied_probability":round(implied,6),"edge":round(edge,6),"market_id":str(market.get("id")),"outcome_id":str(outcomes[outcome_id].get("id")),"specifier":market.get("specifier")})
    if len(legs)<MAX_LEGS:
        try: tennis_events=sportyevents("sr:sport:5",["186","189"],"TENNIS_SOURCE")
        except Exception as exc: tennis_events=[]; result["sportybet"]["tennis_source_error"]=str(exc)
        for candidate in tennis:
            if len(legs)>=MAX_LEGS: break
            event=match_candidate(candidate,tennis_events)
            if not event: continue
            if candidate.get("builder_market")=="winner":
                market,outcomes=market_outcomes(event,{"186"}); outcome_id={"p1":"4","p2":"5"}.get(candidate.get("builder_pick"))
                if not market or outcome_id not in outcomes: continue
                pick_name=outcomes[outcome_id].get("desc"); model_prob=float(candidate.get("builder_probability",0)); odds=float(outcomes[outcome_id].get("odds")); specifier=market.get("specifier")
            else:
                market,outcomes=market_outcomes(event,{"189"}); total=(candidate.get("analytics") or {}).get("total_games") or {}; target_line=str(total.get("line")); target_outcome="12" if candidate.get("builder_pick")=="over" else "13"; matching=None
                for oid,outcome in outcomes.items():
                    if oid==target_outcome and (target_line in str(market.get("specifier", "")) or target_line in str(outcome.get("desc",""))): matching=outcome; break
                if not market or not matching: continue
                outcome_id=str(matching.get("id")); pick_name=matching.get("desc"); model_prob=float(candidate.get("builder_probability",0)); odds=float(matching.get("odds")); specifier=market.get("specifier")
            implied=1/odds if odds>1 else 1.0; edge=model_prob-implied
            if model_prob<TENNIS_MIN_PROB or edge<MIN_EDGE: continue
            legs.append({"sport":"tennis","tour":candidate.get("league"),"event_id":candidate.get("event_id"),"sporty_event_id":str(event.get("eventId")),"home":event.get("homeTeamName"),"away":event.get("awayTeamName"),"market":"winner" if candidate.get("builder_market")=="winner" else "total_games","pick":candidate.get("builder_pick"),"selection":pick_name,"model_probability":round(model_prob,6),"sporty_odds":odds,"implied_probability":round(implied,6),"edge":round(edge,6),"market_id":str(market.get("id")),"outcome_id":outcome_id,"specifier":specifier,"line":(candidate.get("analytics") or {}).get("total_games",{}).get("line")})
    result["qualified_legs"]=legs; result["sportybet"]["legs"]=legs
    if len(legs)<MIN_LEGS: result["sportybet"]["status"]="NO_3_LEG_QUALIFIED_SET"
    else:
        result["sportybet"]["status"]="QUALIFIED_BETSLIP"; result["sportybet"]["combined_odds"]=round(math.prod(x["sporty_odds"] for x in legs),4)
        payload={"selections":[{"eventId":x["sporty_event_id"],"marketId":x["market_id"],"specifier":x.get("specifier"),"outcomeId":x["outcome_id"]} for x in legs]}
        try:
            response=SESSION.post(f"{SPORTY_BASE}/api/{SPORTY_REGION}/orders/share",json=payload,timeout=30); response.raise_for_status(); data=sporty_response_json(response,"BOOKING_ENDPOINT").get("data") or {}; unavailable=data.get("unavailableOutcomes") or []
            if unavailable: result["sportybet"]["status"]="BOOKING_PARTIAL_OR_UNAVAILABLE"; result["sportybet"]["unavailable_outcomes"]=unavailable
            else: result["sportybet"]["booking_code"]=data.get("shareCode"); result["sportybet"]["share_url"]=data.get("shareURL"); result["sportybet"]["expires_at"]=data.get("deadline")
        except Exception as exc: result["sportybet"]["status"]="BOOKING_ENDPOINT_ERROR"; result["sportybet"]["error"]=str(exc)
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps(result,indent=2))

if __name__=="__main__": main()
