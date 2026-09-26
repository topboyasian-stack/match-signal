"""Empirical risk gate for Match Signal.

Adds walk-forward-style diagnostics and a hard paper-trading gate. It never
replaces model probabilities; it annotates current picks with live eligibility.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
MIN_SETTLED=100
MIN_VALUE_TRIALS=30
MIN_VALUE_ROI=0.0

def load(name, default):
    try: return json.loads((DATA/name).read_text(encoding='utf-8'))
    except Exception: return default

def brier(p):
    q=p.get('probabilities') or {}; sport=str(p.get('sport','')).lower(); actual=p.get('actual')
    vals=[float(q.get('p1',0)),float(q.get('draw',0)),float(q.get('p2',0))] if sport=='football' else [float(q.get('p1',0)),float(q.get('p2',0))]
    idx={'p1':0,'draw':1,'p2':2}.get(actual)
    return None if idx is None else sum((v-(i==idx))**2 for i,v in enumerate(vals))

def evaluate(rows,sport):
    r=[p for p in rows if str(p.get('sport','')).lower()==sport and p.get('settled') and p.get('actual') in {'p1','p2','draw'}]
    baseline=2/3 if sport=='football' else .5
    if not r: return {'settled':0,'accuracy':None,'brier':None,'baseline_brier':baseline,'bins':[]}
    acc=sum(p.get('pick')==p.get('actual') for p in r)/len(r); bs=[brier(p) for p in r]; bs=[x for x in bs if x is not None]
    bins=[]
    for lo,hi in ((.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,.80),(.80,1.01)):
        z=[p for p in r if lo<=float(p.get('confidence') or 0)<hi]
        if z: bins.append({'range':f'{lo:.2f}-{min(hi,1):.2f}','n':len(z),'accuracy':round(sum(p.get('pick')==p.get('actual') for p in z)/len(z),4),'mean_confidence':round(sum(float(p.get('confidence') or 0) for p in z)/len(z),4)})
    return {'settled':len(r),'accuracy':round(acc,4),'brier':round(sum(bs)/len(bs),4) if bs else None,'baseline_brier':baseline,'bins':bins}


def american_to_decimal(odds):
    try:
        x=float(odds)
        if x>0:return 1+x/100
        if x<0:return 1+100/abs(x)
    except (TypeError,ValueError,ZeroDivisionError):
        return None
    return None

def value_trial(row):
    if not row.get('settled') or row.get('actual') not in {'p1','p2','draw'}:
        return None
    pick=str(row.get('pick') or '')
    if pick not in {'p1','p2','draw'}:
        return None
    insights=row.get('market_insights') or {}
    winner_odds=row.get('sportybet_winner_odds') or {}
    edge=insights.get('winner_model_edge_vs_market')
    snapshot_at=insights.get('snapshot_at') or (row.get('sportybet_market_snapshot') or {}).get('fetched_at')
    odds_map={'p1':winner_odds.get('p1'),'p2':winner_odds.get('p2'),'draw':winner_odds.get('draw')}
    if not isinstance(edge,(int,float)):
        edge=row.get('edge')
    legacy_ev=(row.get('value') or {}).get('expected_value')
    legacy_odds=row.get('market_odds')
    if isinstance(legacy_odds,list) and len(legacy_odds)>=3 and odds_map.get(pick) is None:
        odds_map={'p1':legacy_odds[0],'draw':legacy_odds[1],'p2':legacy_odds[2]}
    book=odds_map.get(pick)
    model_prob=(row.get('probabilities') or {}).get(pick)
    dec=None
    try:
        dec=float(book)
        if dec<=1.0: dec=None
    except (TypeError,ValueError):
        dec=None
    if isinstance(model_prob,(int,float)) and dec is not None:
        ev=float(model_prob)*dec-1.0
        book_edge=float(model_prob)-(1.0/dec)
    else:
        ev=float(legacy_ev) if isinstance(legacy_ev,(int,float)) else None
        book_edge=float(edge) if isinstance(edge,(int,float)) else None
    value_edge=float(edge) if isinstance(edge,(int,float)) else book_edge
    if value_edge is None or ev is None:
        return None
    if float(value_edge)<0.035 or float(ev)<0.05:
        return None
    if not snapshot_at or book is None or dec is None:
        return None
    roi=(dec-1.0) if row.get('actual')==pick else -1.0
    return {
        'event_id':row.get('event_id'),'sport':row.get('sport'),'league':row.get('league'),'pick':pick,
        'roi':roi,'won':row.get('actual')==pick,'edge':round(float(value_edge),6),
        'book_edge':round(float(book_edge),6),'expected_value':round(float(ev),6),
        'frozen_odds':float(book),'frozen_odds_at':snapshot_at,
        'source':'SportyBet NG frozen winner snapshot'
    }

def value_testing(rows,sport):
    trials=[x for r in rows if str(r.get('sport','')).lower()==sport for x in [value_trial(r)] if x]
    if not trials:
        return {'trials':0,'wins':0,'roi_units':0.0,'roi':None,'status':'NO_VALUE_TRIALS','required_trials':MIN_VALUE_TRIALS}
    units=sum(x['roi'] for x in trials)
    roi=units/len(trials)
    return {'trials':len(trials),'wins':sum(bool(x['won']) for x in trials),'roi_units':round(units,6),'roi':round(roi,6),'status':'PASS' if len(trials)>=MIN_VALUE_TRIALS and roi>MIN_VALUE_ROI else 'INSUFFICIENT_OR_NONPOSITIVE','required_trials':MIN_VALUE_TRIALS,'latest_frozen_snapshot':max((x.get('frozen_odds_at') or '' for x in trials),default=None)}

def main():
    history=load('prediction_history.json',[])+load('basketball_history.json',[])
    metrics={s:evaluate(history,s) for s in ('football','tennis','basketball')}
    gate={}
    for sport,m in metrics.items():
        enough=m['settled']>=MIN_SETTLED
        better=m['brier'] is not None and m['brier']<m['baseline_brier']
        value=value_testing(history,sport)
        reasons=[]
        if not enough:
            reasons.append(f"need >={MIN_SETTLED} settled picks (have {m['settled']})")
        if m['brier'] is not None and not better:
            reasons.append(f"Brier {m['brier']} has not beaten baseline {m['baseline_brier']}")
        if value['trials']<MIN_VALUE_TRIALS:
            reasons.append(f"need >={MIN_VALUE_TRIALS} settled value trials with frozen odds/value evidence (have {value['trials']})")
        elif value['roi'] is None or value['roi']<=MIN_VALUE_ROI:
            reasons.append(f"value-test realized ROI {value['roi']} is not > {MIN_VALUE_ROI}")
        model_risk_approval_passed=bool(
            enough and better and value['trials']>=MIN_VALUE_TRIALS and
            value['roi'] is not None and value['roi']>MIN_VALUE_ROI
        )
        gate[sport]={
            'live_eligible':False,
            'model_risk_approval_passed':model_risk_approval_passed,
            'live_trading_enabled':False,
            'paper_only':True,
            'value_testing':value,
            'reasons':reasons,
        }
    for name in ('predictions.json','basketball_predictions.json'):
        path=DATA/name; rows=load(name,[])
        for p in rows:
            g=gate.get(str(p.get('sport','')).lower(),{'live_eligible':False})
            p['live_eligible']=bool(g['live_eligible']); p['testing_mode']='paper'
        path.write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
    trial_ledger=[x for r in history for x in [value_trial(r)] if x]
    (DATA/'value_trial_ledger.json').write_text(json.dumps({'generated_at':datetime.now(timezone.utc).isoformat(),'mode':'PAPER_ONLY','policy':'Frozen SportyBet value evidence; never modifies settled outcomes or model probabilities.','trials':trial_ledger},indent=2,ensure_ascii=False),encoding='utf-8')
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'mode':'PAPER_ONLY','metrics':metrics,'gate':gate}
    (DATA/'risk_gate.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
