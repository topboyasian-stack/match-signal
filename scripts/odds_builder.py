"""Build a guarded 3-4 selection accumulator for manual betting.

Research-only: never places or shares/stakes a wager. The builder selects
existing Match Signal paper candidates, keeps only fixtures that have not
started, and calculates model fair odds plus a reference accumulator. Actual
bookmaker odds are intentionally left for the user to verify manually.

Daily mixed-build trigger marker: football is included whenever qualified;
tennis fills remaining slots only when it independently passes the gate.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
CANDIDATES=DATA/'selection_candidates.json'
PREDICTIONS=DATA/'predictions.json'
OUTPUT=DATA/'odds_builder.json'
HISTORY=DATA/'prediction_history.json'
MIN_LEGS,MAX_LEGS=3,4
MIN_PROB=0.65


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default


def upcoming(x, now):
    try:
        raw=x.get('start_time')
        if not raw:return False
        dt=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        return dt.astimezone(timezone.utc)>now
    except (TypeError,ValueError):return False


def settled_event_ids():
    raw=load(HISTORY,[])
    if not isinstance(raw,list):return set()
    return {str(x.get('event_id')) for x in raw if isinstance(x,dict) and x.get('settled') is True and x.get('event_id')}


def fair_odds(p):
    return round(1.0/float(p),3) if float(p)>0 else 0.0


def football_candidates(now):
    raw=load(CANDIDATES,[])
    out=[]
    if not isinstance(raw,list):return out
    for x in raw:
        if not isinstance(x,dict) or x.get('candidate_status')!='SELECTED' or x.get('sport')!='football' or not upcoming(x,now):continue
        probs=x.get('probabilities') or {}
        pick=x.get('pick')
        try:p=float(probs.get(pick,x.get('confidence',0)) or 0)
        except (TypeError,ValueError):continue
        if p>=MIN_PROB and pick in {'p1','draw','p2'}:
            out.append({**x,'builder_market':'1X2','builder_probability':p,'builder_pick':pick})
    return out


def tennis_candidates(now):
    raw=load(PREDICTIONS,[])
    out=[]
    if not isinstance(raw,list):return out
    for x in raw:
        if not isinstance(x,dict) or x.get('sport')!='tennis' or not upcoming(x,now):continue
        probs=x.get('probabilities') or {}
        pick=x.get('pick')
        try:match_prob=float(probs.get(pick,0) or 0) if pick else 0.0
        except (TypeError,ValueError):match_prob=0.0
        total=(x.get('analytics') or {}).get('total_games') or {}
        ou_pick=total.get('pick')
        try:ou_prob=float(total.get(ou_pick,0) or 0) if ou_pick else 0.0
        except (TypeError,ValueError):ou_prob=0.0
        if match_prob>=MIN_PROB:
            out.append({**x,'builder_market':'winner','builder_probability':match_prob,'builder_pick':pick})
        elif ou_pick in {'over','under'} and ou_prob>=MIN_PROB and total.get('line') is not None:
            out.append({**x,'builder_market':'total_games','builder_probability':ou_prob,'builder_pick':ou_pick})
    return out


def make_leg(x):
    p=float(x['builder_probability'])
    reference=fair_odds(p)
    if x.get('sport')=='tennis':
        if x.get('builder_market')=='total_games':
            total=x.get('analytics',{}).get('total_games',{})
            market=f"Total Games {x.get('builder_pick')} {total.get('line')}"
            pick=f"{x.get('player_1')} vs {x.get('player_2')} — {market}"
        else:
            pick=f"{x.get('player_1')} vs {x.get('player_2')} — {x.get('builder_pick')}"
        return {
            'sport':'tennis','competition':x.get('league'),'event_id':x.get('event_id'),
            'start_time':x.get('start_time'),'match':f"{x.get('player_1')} vs {x.get('player_2')}",
            'market':x.get('builder_market'),'pick':pick,'model_probability':round(p,6),
            'model_fair_odds':reference,'source':x.get('model'),'decision':x.get('decision','PAPER ONLY')
        }
    return {
        'sport':'football','competition':x.get('league'),'event_id':x.get('event_id'),
        'start_time':x.get('start_time'),'match':f"{x.get('home_team')} vs {x.get('away_team')}",
        'market':'1X2','pick':x.get('builder_pick'),'model_probability':round(p,6),
        'model_fair_odds':reference,'source':x.get('model'),'decision':x.get('decision','PAPER ONLY')
    }


def recent_settled_legs(history, now):
    """Return recently settled high-confidence tennis O/U selections for result visibility.

    These are displayed separately from the active 3-4 selection set so a completed
    leg cannot disappear without a visible WON/LOST result when the daily odds set
    refreshes. The list is bounded to today's settled model selections.
    """
    if not isinstance(history, list):
        return []
    today = now.date().isoformat()
    out = []
    for x in history:
        if not isinstance(x, dict) or not x.get('settled') or str(x.get('start_time',''))[:10] != today:
            continue
        if x.get('sport') != 'tennis':
            continue
        total = (x.get('analytics') or {}).get('total_games') or {}
        ou_pick = total.get('pick')
        if ou_pick not in {'over','under'} or total.get('line') is None:
            continue
        try:
            probability = float(total.get(ou_pick, 0) or 0)
        except (TypeError, ValueError):
            continue
        if probability < MIN_PROB:
            continue
        actual_markets = x.get('actual_markets') or {}
        correct = actual_markets.get('total_games_correct')
        if correct is None:
            result = actual_markets.get('total_games_result')
            correct = (result == ou_pick) if result in {'over','under'} else x.get('correct')
        if not isinstance(correct, bool):
            continue
        out.append({
            'sport': 'tennis',
            'competition': x.get('league'),
            'event_id': x.get('event_id'),
            'start_time': x.get('start_time'),
            'match': f"{x.get('player_1')} vs {x.get('player_2')}",
            'market': 'total_games',
            'pick': f"{x.get('player_1')} vs {x.get('player_2')} — Total Games {ou_pick} {total.get('line')}",
            'model_probability': round(probability, 6),
            'model_fair_odds': fair_odds(probability),
            'source': x.get('model'),
            'decision': 'PAPER ONLY',
            'settlement': {'finished': True, 'correct': bool(correct)},
            'final_score': x.get('final_score'),
            'actual_markets': actual_markets,
            'settled_at': x.get('settled_at'),
        })
    out.sort(key=lambda x: str(x.get('settled_at') or ''), reverse=True)
    return out[:4]


def select_mixed(football, tennis):
    """Prefer a mixed set when qualified football exists, without forcing it.

    At least one qualified football leg is reserved when available. Up to two
    football legs can be included; the remaining slots are filled by the
    strongest eligible candidates across both sports. If no football passes
    the existing gate, tennis can fill the set normally.
    """
    football=sorted(football,key=lambda x:float(x.get('builder_probability',0) or 0),reverse=True)
    tennis=sorted(tennis,key=lambda x:float(x.get('builder_probability',0) or 0),reverse=True)
    all_candidates=football+tennis
    all_candidates.sort(key=lambda x:float(x.get('builder_probability',0) or 0),reverse=True)

    selected=[]
    if football:
        selected.append(football[0])
        if len(football)>1 and MAX_LEGS >= 4:
            selected.append(football[1])

    for candidate in all_candidates:
        if len(selected)>=MAX_LEGS:
            break
        if candidate in selected:
            continue
        selected.append(candidate)
    return selected


def main():
    now=datetime.now(timezone.utc)
    football=football_candidates(now)
    tennis=tennis_candidates(now)
    fresh=[make_leg(x) for x in select_mixed(football,tennis)]
    settled_ids=settled_event_ids()
    settled_legs=recent_settled_legs(load(HISTORY,[]), now)
    previous=load(OUTPUT,{})
    retained=[]
    if isinstance(previous,dict):
        for leg in previous.get('qualified_legs',[]):
            if not isinstance(leg,dict) or not leg.get('event_id'):continue
            if str(leg.get('event_id')) in settled_ids:continue
            try:started=datetime.fromisoformat(str(leg.get('start_time')).replace('Z','+00:00')).astimezone(timezone.utc)<=now
            except (TypeError,ValueError):started=False
            if started:retained.append(leg)
    selected=[]
    seen=set()
    for leg in retained+fresh:
        eid=str(leg.get('event_id') or '')
        if not eid or eid in seen:continue
        selected.append(leg);seen.add(eid)
        if len(selected)>=MAX_LEGS:break
    sports=sorted({x['sport'] for x in selected})
    if {'football','tennis'} <= set(sports):
        selection_status='MIXED_QUALIFIED_ACCUMULATOR'
    elif len(selected)>=MIN_LEGS:
        selection_status='QUALIFIED_ACCUMULATOR'
    else:
        selection_status='NO_3_LEG_QUALIFIED_SET'

    result={
        'generated_at':now.isoformat(),
        'mode':'PAPER_ONLY',
        'target_legs':'3-4',
        'sports_supported':['football','tennis'],
        'selection_policy':{
            'min_model_probability':MIN_PROB,
            'requires_existing_research_gate_for_football':True,
            'requires_paper_probability_threshold_for_tennis':True,
            'upcoming_fixture_only':True,
            'retain_started_legs_until_settled':True,
            'daily_automated_build':True,
            'mix_qualified_football_when_available':True,
            'football_reserved_slots':1,
            'football_max_slots':2,
            'public_prediction_feed_unchanged':True
        },
        'bookmaker_odds':{
            'status':'MANUAL_CONFIRMATION_REQUIRED',
            'sportybet_direct_feed':'BLOCKED_FROM_GITHUB_RUNNER',
            'stake_direct_feed':'NOT_CONNECTED',
            'instruction':'Verify each displayed selection and enter the actual current bookmaker odds in your betslip before placing any wager.'
        },
        'candidates_considered':{'football':len(football),'tennis':len(tennis)},
        'qualified_legs':selected,
        'settled_legs':settled_legs,
        'leg_count':len(selected),
        'sports_selected':sports,
        'status':selection_status,
        'reference_combined_odds':round(math.prod(x['model_fair_odds'] for x in selected),3) if selected else None,
        'reference_odds_type':'MODEL_FAIR_ODDS_NOT_BOOKMAKER_PRICE',
        'actual_combined_odds':None,
        'notes':[
            'Booking/share-code generation has been removed.',
            'The user manually builds the accumulator on SportyBet or Stake.',
            'Reference combined odds are the product of 1/model-probability and are NOT a quoted bookmaker price.',
            'New started fixtures are excluded from fresh selection, but previously qualified legs are retained until explicit settlement.',
            'When qualified football exists, at least one football selection is reserved and up to two may be included.',
            'No accumulator is forced when fewer than three selections pass the existing research threshold.',
            'Recently settled model selections remain visible separately with their confirmed WON/LOST result; they are not part of the active accumulator.'
        ]
    }
    OUTPUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
