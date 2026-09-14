"""Research-only NBA model candidate tournament.

Tests market-blind Elo variants against the current score-rate model. Selection is
based on chronological walk-forward log loss/Brier, then checked against the
closing market subset. No market data is used to generate candidate probabilities.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; NOW=datetime.now(timezone.utc)


def dt(x):
    try:
        d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:return None


def prob(diff): return 1/(1+10**(-diff/400.0))


def mov_multiplier(margin, elo_diff):
    margin=max(1.0,abs(float(margin)))
    den=7.5 + 0.006*elo_diff
    if den <= 0: den=7.5
    return ((margin+3.0)**0.8)/den


def elo_walk(hist,k=20.0,hca=100.0,mov=True,rest=0.0):
    ratings={}; last={}; rows=[]
    for r in sorted(hist,key=lambda x:x['date']):
        h,a=r['home'],r['away']; d=dt(r['date'])
        rh=ratings.get(h,1500.0); ra=ratings.get(a,1500.0)
        elo_diff=rh-ra+hca
        rest_adj=0.0
        if rest:
            hr=(d-last[h]).total_seconds()/86400 if h in last and d else 2.5
            ar=(d-last[a]).total_seconds()/86400 if a in last and d else 2.5
            rest_adj=max(-20.0,min(20.0,(hr-ar)*rest))
        p=prob(elo_diff+rest_adj)
        actual=1.0 if r['home_score']>r['away_score'] else 0.0
        margin=float(r['home_score'])-float(r['away_score'])
        m=mov_multiplier(margin,elo_diff) if mov else 1.0
        shift=k*m*(actual-p)
        ratings[h]=rh+shift; ratings[a]=ra-shift
        last[h]=d; last[a]=d
        rows.append({'event_id':r['event_id'],'date':r['date'],'home':h,'away':a,'p_home':p,
                     'actual':actual,'correct':(p>=.5)==bool(actual),'brier':(p-actual)**2,
                     'logloss':-math.log(max(1e-9,p if actual else 1-p))})
    return rows


def current_rows(hist):
    from expansion_pipeline import nba_predict
    out=[]
    for r in sorted(hist,key=lambda x:x['date']):
        p=nba_predict(r,hist)['moneyline']['home']; actual=1.0 if r['home_score']>r['away_score'] else 0.0
        out.append({'event_id':r['event_id'],'date':r['date'],'home':r['home'],'away':r['away'],'p_home':p,'actual':actual,
                    'correct':(p>=.5)==bool(actual),'brier':(p-actual)**2,'logloss':-math.log(max(1e-9,p if actual else 1-p))})
    return out


def summarize(rows):
    return {'n':len(rows),'accuracy':round(sum(r['correct'] for r in rows)/len(rows),4),
            'brier':round(sum(r['brier'] for r in rows)/len(rows),4),
            'logloss':round(sum(r['logloss'] for r in rows)/len(rows),4)} if rows else {'n':0}


def main():
    hist=json.loads((DATA/'nba_history.json').read_text())
    market=json.loads((DATA/'nba_market_matches.json').read_text()) if (DATA/'nba_market_matches.json').exists() else []
    market_ids={x['event_id']:x for x in market}
    candidates={'current':current_rows(hist)}
    for k in (15,20,25,30):
        for hca in (70,85,100):
            for mov in (False,True):
                name=f'elo_k{k}_hca{hca}_mov{int(mov)}'
                candidates[name]=elo_walk(hist,k,hca,mov,0)
                candidates[name+'__rest5']=elo_walk(hist,k,hca,mov,5)
    scores=[]
    for name,rows in candidates.items():
        s=summarize(rows)
        by={r['event_id']:r for r in rows}
        matched=[(by[i],m) for i,m in market_ids.items() if i in by]
        if matched:
            macc=sum(x['correct'] for x,_ in matched)/len(matched)
            # Use the recorded closing odds and model probability for a unit-stake value test.
            evs=[]; profits=[]
            for x,m in matched:
                pick_home=x['p_home']>=.5; p=x['p_home'] if pick_home else 1-x['p_home']
                ml=float(m['home_ml'] if pick_home else m['away_ml'])
                dec=1+ml/100 if ml>0 else 1+100/(-ml)
                ev=p*(dec-1)-(1-p)
                profit=(dec-1) if ((pick_home)==bool(x['actual'])) else -1
                evs.append(ev); profits.append(profit)
            s.update({'market_n':len(matched),'market_accuracy':round(macc,4),'mean_closing_ev':round(sum(evs)/len(evs),4),'roi_all':round(sum(profits)/len(profits),4)})
        else:s.update({'market_n':0})
        scores.append({'model':name,**s})
    # Primary ranking: log loss, then Brier, then accuracy. Market metrics are diagnostics only.
    ranked=sorted(scores,key=lambda x:(x.get('logloss',99),x.get('brier',99),-x.get('accuracy',0)))
    payload={'generated_at':NOW.isoformat(),'paper_only':True,'selection_rule':'walk-forward logloss, then Brier, then accuracy; market diagnostics never enter model fitting','top_15':ranked[:15],'current':next(x for x in scores if x['model']=='current'),'release_decision':'RESEARCH_ONLY'}
    (DATA/'nba_model_candidates.json').write_text(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2))

if __name__=='__main__':main()
