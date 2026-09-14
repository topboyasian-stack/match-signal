"""Match Signal expansion pipeline: NBA + Eredivisie.

Research-only expansion pipeline. Uses real completed results and current fixtures,
with leakage-safe historical features. Independent model probabilities are kept
separate from market benchmarks. Nothing here authorizes live trading.
"""
import json, math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports'
HEAD={'User-Agent':'Mozilla/5.0 (compatible; MatchSignal/1.0)'}
S=requests.Session(); S.headers.update(HEAD)
NOW=datetime.now(timezone.utc)

SPORTS={'NBA':'basketball/nba','Eredivisie':'soccer/ned.1'}

def get(url, params=None):
    r=S.get(url, params=params, timeout=30); r.raise_for_status(); return r.json()

def parse_dt(x):
    try:
        d=datetime.fromisoformat(str(x).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError): return None

def american_prob(x):
    try:
        x=float(x); return 100/(x+100) if x>0 else -x/(-x+100)
    except (TypeError,ValueError,ZeroDivisionError): return None

def norm(xs):
    xs=[max(1e-9,float(x)) for x in xs]; z=sum(xs); return [x/z for x in xs]

def completed(e): return bool((e.get('status') or {}).get('type',{}).get('completed'))
def competitors(e): return ((e.get('competitions') or [{}])[0].get('competitors') or [])[:2]
def team(c):
    t=c.get('team') or {}; return str(t.get('id') or c.get('id') or ''),(t.get('displayName') or c.get('displayName') or '').strip()
def scores(e):
    cs=competitors(e)
    try: return [float(c.get('score',0)) for c in cs] if len(cs)==2 else None
    except (TypeError,ValueError): return None

def market(e):
    try:
        odds=((e.get('competitions') or [{}])[0].get('odds') or [])
        return odds[0] if odds else None
    except (IndexError,TypeError): return None

def markets(e):
    m=market(e) or {}; out={}
    ml=m.get('moneyline') or m.get('moneyLine') or {}
    vals=[]
    for side in ('home','away'):
        node=ml.get(side) or {}; q=node.get('close') or node.get('open') or {}
        vals.append(american_prob(q.get('odds')))
    if all(v is not None for v in vals): out['moneyline']={'home':norm(vals)[0],'away':norm(vals)[1]}
    total=m.get('total') or {}; ov=total.get('over') or {}; un=total.get('under') or {}
    oq=ov.get('close') or ov.get('open') or {}; uq=un.get('close') or un.get('open') or {}
    try: line=float(m.get('overUnder') or oq.get('line') or uq.get('line'))
    except (TypeError,ValueError): line=None
    op,up=american_prob(oq.get('odds')),american_prob(uq.get('odds'))
    if line is not None and op is not None and up is not None: out['total']={'line':line,'over':norm([op,up])[0],'under':norm([op,up])[1]}
    sp=m.get('pointSpread') or {}; h=sp.get('home') or {}; a=sp.get('away') or {}
    hq=h.get('close') or h.get('open') or {}; aq=a.get('close') or a.get('open') or {}
    hp,ap=american_prob(hq.get('odds')),american_prob(aq.get('odds'))
    try: sl=float(hq.get('line'))
    except (TypeError,ValueError): sl=None
    if sl is not None and hp is not None and ap is not None: out['spread']={'line':sl,'home_cover':norm([hp,ap])[0],'away_cover':norm([hp,ap])[1]}
    return out

def fetch(competition,start,end):
    slug=SPORTS[competition]
    return get(f'{BASE}/{slug}/scoreboard',{'dates':f'{start:%Y%m%d}-{end:%Y%m%d}'}).get('events',[])

def collect(competition,days=365):
    end=NOW; start=end-timedelta(days=days); rows=[]; seen=set(); cur=start
    errors=[]
    while cur<end:
        nxt=min(end,cur+timedelta(days=30))
        try: events=fetch(competition,cur,nxt)
        except Exception as exc:
            errors.append(str(exc)); events=[]
        for e in events:
            if not completed(e): continue
            cs=competitors(e); sc=scores(e)
            if len(cs)!=2 or not sc: continue
            home=next((c for c in cs if c.get('homeAway')=='home'),cs[0]); away=next((c for c in cs if c.get('homeAway')=='away'),cs[1])
            hid,hn=team(home); aid,an=team(away)
            if not hn or not an: continue
            key=str(e.get('id') or f'{competition}|{hn}|{an}|{e.get("date")}')
            if key in seen: continue
            seen.add(key)
            rows.append({'event_id':key,'date':e.get('date'),'home':hn,'away':an,'home_id':hid,'away_id':aid,'home_score':sc[0],'away_score':sc[1],'markets':markets(e)})
        cur=nxt+timedelta(days=1)
    rows.sort(key=lambda x:x.get('date') or '')
    return rows,errors

def current(competition,days=7):
    start=NOW-timedelta(days=1); end=NOW+timedelta(days=days); rows=[]
    for e in fetch(competition,start,end):
        cs=competitors(e)
        if len(cs)!=2: continue
        home=next((c for c in cs if c.get('homeAway')=='home'),cs[0]); away=next((c for c in cs if c.get('homeAway')=='away'),cs[1])
        hid,hn=team(home); aid,an=team(away)
        if hn and an: rows.append({'event_id':str(e.get('id')),'date':e.get('date'),'home':hn,'away':an,'home_id':hid,'away_id':aid,'markets':markets(e)})
    return rows

def weights(rows,cutoff):
    stats=defaultdict(lambda:{'pf':0.,'pa':0.,'n':0.,'last':None})
    for r in rows:
        dt=parse_dt(r.get('date'))
        if not dt or dt>=cutoff: continue
        age=max(0,(cutoff-dt).total_seconds()/86400); w=math.exp(-math.log(2)*age/120)
        for name,pts,opp in ((r['home'],r['home_score'],r['away_score']),(r['away'],r['away_score'],r['home_score'])):
            q=stats[name]; q['pf']+=w*pts; q['pa']+=w*opp; q['n']+=w
            if q['last'] is None or dt>q['last']: q['last']=dt
    return stats

def nba_independent(r,hist):
    cutoff=parse_dt(r['date']) or NOW; st=weights(hist,cutoff)
    h=st.get(r['home'],{}); a=st.get(r['away'],{})
    hp=h.get('pf',0)/max(h.get('n',1),1e-9); ap=a.get('pf',0)/max(a.get('n',1),1e-9)
    hd=h.get('pa',0)/max(h.get('n',1),1e-9); ad=a.get('pa',0)/max(a.get('n',1),1e-9)
    league_pf=sum(x['pf'] for x in st.values())/max(sum(x['n'] for x in st.values()),1e-9)
    home_mu=.58*(hp+ad)/2+.42*league_pf+2.5; away_mu=.58*(ap+hd)/2+.42*league_pf
    for q in (h,a):
        last=q.get('last'); q['rest']=((cutoff-last).total_seconds()/86400 if last else 4.0)
    rest_adj=max(-2,min(2,(h['rest']-a['rest'])*.35)); home_mu+=rest_adj; away_mu-=rest_adj
    margin=home_mu-away_mu; home_p=1/(1+math.exp(-margin/7.5)); total=home_mu+away_mu
    return {'moneyline':{'home':home_p,'away':1-home_p},'expected_score':{'home':home_mu,'away':away_mu},'expected_total':total,'rest_days':{'home':h.get('rest',4),'away':a.get('rest',4)},'model':'NBA independent recency-weighted offense/defense + home/rest; no market input','paper_only':True}

def ere_independent(r,hist):
    from independent_football_model import independent_prediction
    ev={'id':r['event_id'],'competitions':[{'competitors':[{'homeAway':'home','team':{'displayName':r['home']}},{'homeAway':'away','team':{'displayName':r['away']}}]}]}
    h=[{'sport':'football','settled':True,'final_score':[x['home_score'],x['away_score']],'event_id':x['event_id'],'start_time':x['date'],'league':'Eredivisie','player_1':x['home'],'player_2':x['away']} for x in hist]
    return independent_prediction(ev,'Eredivisie',h,cutoff=r.get('date'))

def run():
    nba_hist,nba_errors=collect('NBA',365); ere_hist,ere_errors=collect('Eredivisie',365)
    nba_cur=current('NBA'); ere_cur=current('Eredivisie')
    nba=[]
    for r in nba_cur:
        p=nba_independent(r,nba_hist); nba.append({'sport':'basketball','league':'NBA','event_id':r['event_id'],'start_time':r['date'],'player_1':r['home'],'player_2':r['away'],'independent':p,'market':r.get('markets',{}),'prediction_status':'research_only','paper_only':True})
    ere=[]
    for r in ere_cur:
        p=ere_independent(r,ere_hist)
        ere.append({'sport':'football','league':'Eredivisie','event_id':r['event_id'],'start_time':r['date'],'player_1':r['home'],'player_2':r['away'],'probabilities':{'p1':p['p1'],'draw':p['draw'],'p2':p['p2']} if p else {},'expected_goals':{'p1':p['xg_home'],'p2':p['xg_away'],'total':p['xg_home']+p['xg_away']} if p else {},'model':p.get('method') if p else 'unavailable','market':r.get('markets',{}),'prediction_status':'research_only','paper_only':True})
    (DATA/'nba_history.json').write_text(json.dumps(nba_hist,indent=2)); (DATA/'ere_divisie_history.json').write_text(json.dumps(ere_hist,indent=2)); (DATA/'nba_predictions.json').write_text(json.dumps(nba,indent=2)); (DATA/'ere_divisie_predictions.json').write_text(json.dumps(ere,indent=2))
    status={'updated_at':NOW.isoformat(),'paper_only':True,'live_trading_approved':False,'competitions':{'NBA':{'historical_events':len(nba_hist),'current_fixtures':len(nba_cur),'collection_errors':len(nba_errors),'status':'research'},'Eredivisie':{'historical_events':len(ere_hist),'current_fixtures':len(ere_cur),'collection_errors':len(ere_errors),'status':'research'}},'release_gate':{'minimum_walk_forward_settled':100,'requires_market_benchmark':True,'requires_calibration':True,'requires_positive_out_of_sample_evidence':True},'notes':['Independent probabilities never consume market probabilities.','Expansion outputs remain research-only until walk-forward validation passes.','No fabricated odds or predictions are promoted to production.']}
    (DATA/'expansion_status.json').write_text(json.dumps(status,indent=2)); print(json.dumps(status,indent=2))

if __name__=='__main__': run()
