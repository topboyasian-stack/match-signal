"""Walk-forward calibration tournament for the best NBA Elo research candidate.

Candidate probabilities are generated market-blind. Temperature is selected only
from prior completed games, then applied to the next game. Market odds are used
only after prediction generation to test value/ROI.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; NOW=datetime.now(timezone.utc)


def prob(diff): return 1/(1+10**(-diff/400.0))

def mov_multiplier(margin, elo_diff):
    margin=max(1.0,abs(float(margin))); den=max(7.5,7.5+0.006*elo_diff)
    return ((margin+3.0)**0.8)/den

def elo_raw(hist,k=25,hca=70):
    ratings={}; rows=[]
    for r in sorted(hist,key=lambda x:x['date']):
        h,a=r['home'],r['away']; rh=ratings.get(h,1500.0); ra=ratings.get(a,1500.0)
        ed=rh-ra+hca; p=prob(ed); actual=1.0 if r['home_score']>r['away_score'] else 0.0
        shift=k*mov_multiplier(r['home_score']-r['away_score'],ed)*(actual-p)
        ratings[h]=rh+shift; ratings[a]=ra-shift
        rows.append({'event_id':r['event_id'],'date':r['date'],'raw_p':p,'actual':actual})
    return rows

def calibrate(raw, window=300, grid=None):
    if grid is None: grid=[1.0,1.05,1.1,1.15,1.2,1.3,1.4,1.5,1.7,2.0]
    out=[]
    for i,x in enumerate(raw):
        if i < 100:
            T=1.0
        else:
            train=raw[max(0,i-window):i]
            best=(1e9,1.0)
            for t in grid:
                ll=0.0
                for z in train:
                    q=.5+(z['raw_p']-.5)/t; q=max(1e-6,min(1-1e-6,q)); ll += -math.log(q if z['actual'] else 1-q)
                ll/=len(train)
                if ll<best[0]: best=(ll,t)
            T=best[1]
        p=.5+(x['raw_p']-.5)/T; p=max(1e-6,min(1-1e-6,p))
        out.append({**x,'p_home':p,'temperature':T})
    return out

def main():
    hist=json.loads((DATA/'nba_history.json').read_text()); raw=elo_raw(hist); cal=calibrate(raw)
    market={x['event_id']:x for x in json.loads((DATA/'nba_market_matches.json').read_text())}
    def summary(rows):
        b=sum((x['p_home']-x['actual'])**2 for x in rows)/len(rows); ll=sum(-math.log(max(1e-9,x['p_home'] if x['actual'] else 1-x['p_home'])) for x in rows)/len(rows)
        acc=sum((x['p_home']>=.5)==bool(x['actual']) for x in rows)/len(rows)
        return {'n':len(rows),'accuracy':round(acc,4),'brier':round(b,4),'logloss':round(ll,4),'mean_temperature':round(sum(x['temperature'] for x in rows)/len(rows),4)}
    all_rows=[]
    priced=[]
    for x in cal:
        m=market.get(x['event_id'])
        if not m: continue
        pick_home=x['p_home']>=.5; p=x['p_home'] if pick_home else 1-x['p_home']; ml=float(m['home_ml'] if pick_home else m['away_ml'])
        dec=1+ml/100 if ml>0 else 1+100/(-ml); ev=p*(dec-1)-(1-p); profit=(dec-1) if pick_home==bool(x['actual']) else -1
        priced.append({**x,'market_prob':m['market_home_prob'] if pick_home else m['market_away_prob'],'ev':ev,'profit':profit})
    thresholds=[0.0,0.01,0.02,0.025,0.03,0.04,0.05]
    bands=[]
    for th in thresholds:
        s=[x for x in priced if x['ev']>th]
        bands.append({'ev_threshold':th,'n':len(s),'roi':round(sum(x['profit'] for x in s)/len(s),4) if s else None,'accuracy':round(sum((x['p_home']>=.5)==bool(x['actual']) for x in s)/len(s),4) if s else None})
    payload={'generated_at':NOW.isoformat(),'paper_only':True,'candidate':'elo_k25_hca70_mov1','calibration':'walk-forward temperature; 300-game rolling window after 100-game warmup',
             'overall':summary(cal),'priced_games':len(priced),'threshold_results':bands,'release_decision':'RESEARCH_ONLY'}
    (DATA/'nba_calibration_tournament.json').write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2))
if __name__=='__main__':main()
