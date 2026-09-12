"""Empirical risk gate for Match Signal.

Adds walk-forward-style diagnostics and a hard paper-trading gate. It never
replaces model probabilities; it annotates current picks with live eligibility.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'

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

def main():
    history=load('prediction_history.json',[])+load('basketball_history.json',[])
    metrics={s:evaluate(history,s) for s in ('football','tennis','basketball')}
    gate={}
    for sport,m in metrics.items():
        enough=m['settled']>=100
        better=m['brier'] is not None and m['brier']<m['baseline_brier']
        gate[sport]={'live_eligible':False,'paper_only':True,'reasons':([f"need >=100 settled picks (have {m['settled']})"] if not enough else [])+([f"Brier {m['brier']} has not beaten baseline {m['baseline_brier']}"] if m['brier'] is not None and not better else [])+['positive-EV testing also requires contemporaneous market odds']}
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
