#!/usr/bin/env python3
"""Build fixture-specific tennis O/U probabilities.

The O/U probability is derived from the current fixture's set probability and
expected set count, then lightly shrunk toward the historical over rate.
Historical results never replace the fixture signal and future results are
never used for an upcoming fixture. PAPER ONLY.
"""
from __future__ import annotations
import json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
PREDICTIONS=DATA/'predictions.json'
ARCHIVE=DATA/'tennis_prediction_archive.json'

def load(path, default):
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,(list,dict)) else default
    except (FileNotFoundError,json.JSONDecodeError): return default

def clamp(v,lo=0.05,hi=0.95): return max(lo,min(hi,float(v)))
def logit(p):
    p=clamp(p,0.001,0.999); return math.log(p/(1-p))
def sigmoid(x): return 1/(1+math.exp(-max(-20,min(20,x))))

def historical_over_rate(archive):
    over=total=0
    for row in archive:
        if row.get('sport')!='tennis' or row.get('evaluation_eligible') is not True: continue
        result=str((row.get('actual_markets') or {}).get('total_games_result') or '').lower()
        if result in {'over','under'}:
            total+=1; over+=result=='over'
    return (over/total) if total>=20 else 0.5

def fixture_raw_probability(row):
    analytics=row.get('analytics') or {}
    games=analytics.get('total_games') or {}
    line=float(games.get('line') or 22.5)
    sp=analytics.get('set_win_prob') or {}
    q=clamp(float(sp.get('p1') or 0.5),0.05,0.95)
    # Recompute expected sets from the current set probability so stale cached
    # O/U fields cannot feed back into the next calibration cycle.
    expected_sets=2+2*q*(1-q)
    competitiveness=1-2*abs(q-0.5)
    expected_games_per_set=9.0+2.2*competitiveness
    expected_total=expected_games_per_set*expected_sets
    raw=sigmoid((expected_total-line)/2.15)
    return raw,line,expected_total,competitiveness

def main():
    predictions=load(PREDICTIONS,[]); archive=load(ARCHIVE,[])
    if not isinstance(predictions,list): raise SystemExit('predictions.json is not a list')
    if not isinstance(archive,list): archive=[]
    prior=historical_over_rate(archive); changed=0; varied=set(); sample=[]
    for row in predictions:
        if row.get('sport')!='tennis': continue
        analytics=row.setdefault('analytics',{}); games=analytics.setdefault('total_games',{})
        if not games: continue
        raw,line,expected_total,competitiveness=fixture_raw_probability(row)
        # Keep the fixture model dominant; historical rate is a light prior.
        calibrated=sigmoid(0.88*logit(raw)+0.12*logit(prior))
        calibrated=round(clamp(calibrated),4)
        games['line']=line
        games['expected_total_games']=round(expected_total,2)
        games['base_model_over']=round(raw,4)
        games['base_model_under']=round(1-raw,4)
        games['over']=calibrated
        games['under']=round(1-calibrated,4)
        games['pick']='over' if calibrated>=0.5 else 'under'
        games['source']='fixture-specific set probability + expected sets + historical calibration v3'
        games['calibration_status']='PAPER_RESEARCH'
        games['calibration_version']='tennis-ou-v3'
        games['competitiveness']=round(competitiveness,4)
        games['historical_over_rate']=round(prior,4)
        varied.add(calibrated); changed+=1
        if len(sample)<5: sample.append({'match':row.get('player_1','')+' vs '+row.get('player_2',''),'over':calibrated,'under':round(1-calibrated,4),'expected_total_games':round(expected_total,2)})
    PREDICTIONS.write_text(json.dumps(predictions,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    summary={'status':'ok','version':'tennis-ou-v3','predictions_updated':changed,'historical_over_prior':round(prior,4),'distinct_over_probabilities':len(varied),'min_over':min(varied) if varied else None,'max_over':max(varied) if varied else None,'sample':sample,'paper_only':True,'note':'Fixture-specific O/U probabilities restored; stale cached O/U values are never used as the next prior.'}
    (DATA/'tennis_ou_calibration.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
