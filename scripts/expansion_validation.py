"""Deep walk-forward validation for NBA + Eredivisie expansion.

Uses only information available before each historical kickoff. All outputs are
research-only and are never promoted to the production signal desk.
"""
import json, math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from expansion_pipeline import collect, nba_predict
from independent_football_model import independent_prediction

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
NOW=datetime.now(timezone.utc)


def dt(x):
    try:
        d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def brier(probs, actual):
    return sum((float(probs.get(k, 0))-(1.0 if k == actual else 0.0))**2 for k in probs)


def logloss(p, actual, eps=1e-6):
    return -math.log(max(eps, min(1-eps, float(p.get(actual, 0)))))


def summarize(rows):
    if not rows:
        return {'n': 0}
    return {
        'n': len(rows),
        'wins': sum(bool(r['correct']) for r in rows),
        'accuracy': round(sum(bool(r['correct']) for r in rows)/len(rows), 4),
        'brier': round(sum(r['brier'] for r in rows)/len(rows), 4),
        'logloss': round(sum(r['logloss'] for r in rows)/len(rows), 4),
        'last_14d': sum(1 for r in rows if dt(r['date']) and NOW-dt(r['date']) <= timedelta(days=14)),
        'last_21d': sum(1 for r in rows if dt(r['date']) and NOW-dt(r['date']) <= timedelta(days=21)),
        'market_coverage': round(sum(bool(r.get('market')) for r in rows)/len(rows), 4),
    }


def nba_walkforward(hist):
    rows=[]
    for r in sorted(hist, key=lambda x: x.get('date') or ''):
        probs=(nba_predict(r, hist).get('moneyline') or {})
        actual='home' if r['home_score'] > r['away_score'] else 'away'
        pred='home' if probs.get('home', .5) >= .5 else 'away'
        rows.append({
            'event_id':r['event_id'],'date':r['date'],'home':r['home'],'away':r['away'],
            'actual':actual,'p_home':probs.get('home', .5),'prediction':pred,
            'correct':pred == actual,'brier':brier(probs, actual),
            'logloss':logloss(probs, actual),'market':r.get('markets', {}),
        })
    return rows


def _football_event(r):
    return {
        'id': r['event_id'],
        'competitions': [{
            'competitors': [
                {'homeAway':'home','team':{'displayName':r['home']}},
                {'homeAway':'away','team':{'displayName':r['away']}},
            ]
        }]
    }


def _football_history(hist):
    return [{
        'sport':'football',
        'settled':True,
        'final_score':[r['home_score'], r['away_score']],
        'event_id':r['event_id'],
        'start_time':r['date'],
        'calculated_at':r['date'],
        'league':'Eredivisie',
        'player_1':r['home'],
        'player_2':r['away'],
    } for r in hist]


def ere_walkforward(hist):
    rows=[]
    model_history=_football_history(hist)
    for r in sorted(hist, key=lambda x: x.get('date') or ''):
        p=independent_prediction(_football_event(r), 'Eredivisie', model_history, cutoff=r['date'])
        if not p:
            continue
        hg,ag=r['home_score'],r['away_score']
        actual='home' if hg>ag else 'draw' if hg==ag else 'away'
        probs={'home':p['p1'],'draw':p['draw'],'away':p['p2']}
        pred=max(probs,key=probs.get)
        rows.append({
            'event_id':r['event_id'],'date':r['date'],'home':r['home'],'away':r['away'],
            'actual':actual,'p_home':p['p1'],'prediction':pred,'correct':pred == actual,
            'brier':brier(probs,actual),'logloss':logloss(probs,actual),'market':r.get('markets',{}),
            'effective_sample':p.get('effective_sample',0),
        })
    return rows


def team_snapshot(hist, days=21):
    cutoff=NOW-timedelta(days=days)
    out=defaultdict(lambda:{'games':0,'wins':0,'losses':0,'draws':0,'for':0,'against':0})
    for r in hist:
        d=dt(r.get('date'))
        if not d or d < cutoff:
            continue
        h,a=r['home'],r['away']
        hs,as_=r['home_score'],r['away_score']
        out[h]['games'] += 1; out[h]['for'] += hs; out[h]['against'] += as_
        out[a]['games'] += 1; out[a]['for'] += as_; out[a]['against'] += hs
        if hs>as_:
            out[h]['wins'] += 1; out[a]['losses'] += 1
        elif hs<as_:
            out[a]['wins'] += 1; out[h]['losses'] += 1
        else:
            out[h]['draws'] += 1; out[a]['draws'] += 1
    return {
        k:{**v,
           'win_rate':round(v['wins']/v['games'],4) if v['games'] else 0,
           'net_per_game':round((v['for']-v['against'])/v['games'],2) if v['games'] else 0}
        for k,v in sorted(out.items())
    }


def main():
    nba_hist,nba_errors=collect('NBA')
    ere_hist,ere_errors=collect('Eredivisie')
    nba_rows=nba_walkforward(nba_hist)
    ere_rows=ere_walkforward(ere_hist)
    payload={
        'generated_at':NOW.isoformat(),
        'paper_only':True,
        'nba':{
            'history_events':len(nba_hist),
            'collection_errors':len(nba_errors),
            'walkforward':summarize(nba_rows),
            'recent_form_21d':team_snapshot(nba_hist,21),
            'recent_form_14d':team_snapshot(nba_hist,14),
        },
        'eredivisie':{
            'history_events':len(ere_hist),
            'collection_errors':len(ere_errors),
            'walkforward':summarize(ere_rows),
            'recent_form_21d':team_snapshot(ere_hist,21),
            'recent_form_14d':team_snapshot(ere_hist,14),
        },
        'release_decision':{'NBA':'RESEARCH_ONLY','Eredivisie':'RESEARCH_ONLY'},
        'reasons':[
            'Walk-forward evidence is built from completed games only.',
            'No signal is promoted without positive out-of-sample evidence, calibration and market benchmark coverage.',
            'NBA 2026-27 has not started yet; the completed 365-day history window is used for research.',
        ],
    }
    (DATA/'expansion_validation.json').write_text(json.dumps(payload,indent=2))
    (DATA/'expansion_team_form.json').write_text(json.dumps({'NBA':payload['nba']['recent_form_21d'],'Eredivisie':payload['eredivisie']['recent_form_21d']},indent=2))
    print(json.dumps(payload,indent=2))


if __name__=='__main__':
    main()
