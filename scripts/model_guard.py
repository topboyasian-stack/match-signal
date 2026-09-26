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
    edge=row.get('edge')
    ev=(row.get('value') or {}).get('expected_value')
    odds=row.get('market_odds')
    pick=str(row.get('pick') or '')
    if not isinstance(edge,(int,float)) or not isinstance(ev,(int,float)):
        return None
    if float(edge)<0.035 or float(ev)<0.05:
        return None
    if pick not in {'p1','draw','p2'} or not isinstance(odds,list) or len(odds)!=3:
        return None
    dec=american_to_decimal(odds[{'p1':0,'draw':1,'p2':2}[pick]])
    if dec is None:return None
    roi=(dec-1.0) if row.get('actual')==pick else -1.0
    return {'roi':roi,'won':row.get('actual')==pick,'edge':float(edge),'expected_value':float(ev)}

def value_testing(rows,sport):
    trials=[x for r in rows if str(r.get('sport','')).lower()==sport for x in [value_trial(r)] if x]
    if not trials:
        return {'trials':0,'wins':0,'roi_units':0.0,'roi':None,'status':'NO_VALUE_TRIALS'}
    units=sum(x['roi'] for x in trials)
    roi=units/len(trials)
    return {'trials':len(trials),'wins':sum(bool(x['won']) for x in trials),'roi_units':round(units,6),'roi':round(roi,6),'status':'PASS' if len(trials)>=MIN_VALUE_TRIALS and roi>MIN_VALUE_ROI else 'INSUFFICIENT_OR_NONPOSITIVE'}

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
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'mode':'PAPER_ONLY','metrics':metrics,'gate':gate}
    (DATA/'risk_gate.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
