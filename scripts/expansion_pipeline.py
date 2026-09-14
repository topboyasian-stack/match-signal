"""Research-only NBA + Eredivisie expansion collector and model."""
import csv,io,json,math
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports'; NOW=datetime.now(timezone.utc)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; MatchSignal/1.0)'})
NBA_START=datetime(2026,10,20,tzinfo=timezone.utc)
def dt(x):
 try:
  d=datetime.fromisoformat(str(x).replace('Z','+00:00'));return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except: 
  for f in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):
   try:return datetime.strptime(str(x),f).replace(tzinfo=timezone.utc)
   except:pass
 return None
def get(u,p=None):r=S.get(u,params=p,timeout=40);r.raise_for_status();return r.json()
def text(u):r=S.get(u,timeout=45);r.raise_for_status();return r.text
def evs(slug,a,b):return get(f'{BASE}/{slug}/scoreboard',{'dates':f'{a:%Y%m%d}-{b:%Y%m%d}'}).get('events',[])
def team(c):t=c.get('team') or {};return str(t.get('id') or c.get('id') or ''),(t.get('displayName') or c.get('displayName') or '').strip()
def collect_espn(slug):
 rows=[];errs=[];seen=set();a=NOW-timedelta(days=365)
 while a<NOW:
  b=min(NOW,a+timedelta(days=30))
  try:es=evs(slug,a,b)
  except Exception as e:errs.append(str(e));es=[]
  for e in es:
   cs=(e.get('competitions') or [{}])[0].get('competitors',[])
   if len(cs)!=2 or not (e.get('status') or {}).get('type',{}).get('completed'):continue
   h=next((x for x in cs if x.get('homeAway')=='home'),cs[0]);a1=next((x for x in cs if x.get('homeAway')=='away'),cs[1]);hid,hn=team(h);aid,an=team(a1)
   try:hs=float(h.get('score'));as_=float(a1.get('score'))
   except:continue
   if not hn or not an:continue
   k=str(e.get('id') or f'{hn}|{an}|{e.get("date")}')
   if k in seen:continue
   seen.add(k);rows.append({'event_id':k,'date':e.get('date'),'home':hn,'away':an,'home_id':hid,'away_id':aid,'home_score':hs,'away_score':as_,'markets':{}})
  a=b+timedelta(days=1)
 return sorted(rows,key=lambda x:x['date']),errs
def ere_fallback():
 rows=[];errs=[]
 for y in (2025,2026):
  code=f'{y%100:02d}{(y+1)%100:02d}';u=f'https://www.football-data.co.uk/mmz4281/{code}/N1.csv'
  try:
   for r in csv.DictReader(io.StringIO(text(u))):
    d=dt(r.get('Date'));hg=r.get('FTHG');ag=r.get('FTAG');h=(r.get('HomeTeam') or '').strip();a=(r.get('AwayTeam') or '').strip()
    if not d or d<NOW-timedelta(days=365) or d>NOW or not h or not a or hg in ('',None) or ag in ('',None):continue
    rows.append({'event_id':f'fd|{code}|{d.date()}|{h}|{a}','date':d.isoformat(),'home':h,'away':a,'home_id':'','away_id':'','home_score':float(hg),'away_score':float(ag),'markets':{},'source':'football-data.co.uk'})
  except Exception as e:errs.append(f'{u}: {e}')
 return sorted({r['event_id']:r for r in rows}.values(),key=lambda x:x['date']),errs
def nba_fallback():
 errs=[]
 for u in ('https://raw.githubusercontent.com/nickth3man/basketball-data-index/main/csv/nba/games_index.csv','https://raw.githubusercontent.com/nickth3man/basketball-data-index/main/csv/nba/Games.csv'):
  try:
   rows=[]
   for r in csv.DictReader(io.StringIO(text(u))):
    k={x.lower().strip():x for x in r}
    def v(*ns):
     for n in ns:
      if n.lower() in k:return r[k[n.lower()]]
    d=dt(v('date','game_date','game_date_est','GAME_DATE_EST'));h=v('home_team','home','home_team_name');a=v('away_team','visitor_team','away','away_team_name','visitor');hs=v('home_score','home_team_score','pts_home','home_pts');as_=v('away_score','visitor_team_score','pts_away','away_pts')
    if not d or d<NOW-timedelta(days=365) or d>NOW or not h or not a or hs in ('',None) or as_ in ('',None):continue
    try:hs=float(hs);as_=float(as_)
    except:continue
    rows.append({'event_id':str(v('game_id','gameid','id') or f'nba|{d.date()}|{h}|{a}'),'date':d.isoformat(),'home':h.strip(),'away':a.strip(),'home_id':'','away_id':'','home_score':hs,'away_score':as_,'markets':{},'source':u})
   if rows:return sorted({r['event_id']:r for r in rows}.values(),key=lambda x:x['date']),errs
   errs.append(f'{u}: zero usable rows')
  except Exception as e:errs.append(f'{u}: {e}')
 return [],errs
def collect(name):
 rows,errs=collect_espn('basketball/nba' if name=='NBA' else 'soccer/ned.1')
 if rows:return rows,errs
 return nba_fallback() if name=='NBA' else ere_fallback()
def weights(hist,cut):
 s=defaultdict(lambda:{'pf':0.,'pa':0.,'n':0.,'last':None})
 for r in hist:
  d=dt(r['date'])
  if not d or d>=cut:continue
  w=math.exp(-math.log(2)*max(0,(cut-d).total_seconds()/86400)/120)
  for n,p,o in ((r['home'],r['home_score'],r['away_score']),(r['away'],r['away_score'],r['home_score'])):
   q=s[n];q['pf']+=w*p;q['pa']+=w*o;q['n']+=w
   if q['last'] is None or d>q['last']:q['last']=d
 return s
def nba_predict(r,hist):
 cut=dt(r['date']) or NOW;s=weights(hist,cut);h=s.get(r['home'],{});a=s.get(r['away'],{});hp=h.get('pf',0)/max(h.get('n',1),1e-9);ap=a.get('pf',0)/max(a.get('n',1),1e-9);hd=h.get('pa',0)/max(h.get('n',1),1e-9);ad=a.get('pa',0)/max(a.get('n',1),1e-9);lp=sum(x['pf'] for x in s.values())/max(sum(x['n'] for x in s.values()),1e-9);hm=.58*(hp+ad)/2+.42*lp+2.5;am=.58*(ap+hd)/2+.42*lp;hr=(cut-h['last']).total_seconds()/86400 if h.get('last') else 4;ar=(cut-a['last']).total_seconds()/86400 if a.get('last') else 4;adj=max(-2,min(2,(hr-ar)*.35));hm+=adj;am-=adj;p=1/(1+math.exp(-(hm-am)/7.5));return {'moneyline':{'home':p,'away':1-p},'expected_score':{'home':hm,'away':am},'expected_total':hm+am,'rest_days':{'home':hr,'away':ar},'model':'NBA independent recency-weighted offense/defense + home/rest; no market input','paper_only':True}
def current(name):
 if name=='NBA' and NOW<NBA_START:return []
 try:es=evs('basketball/nba' if name=='NBA' else 'soccer/ned.1',NOW-timedelta(days=1),NOW+timedelta(days=7))
 except:return []
 out=[]
 for e in es:
  cs=(e.get('competitions') or [{}])[0].get('competitors',[])
  if len(cs)!=2:continue
  h=next((x for x in cs if x.get('homeAway')=='home'),cs[0]);a=next((x for x in cs if x.get('homeAway')=='away'),cs[1]);_,hn=team(h);_,an=team(a)
  if hn and an:out.append({'event_id':str(e.get('id')),'date':e.get('date'),'home':hn,'away':an,'markets':{}})
 return out
def run():
 nh,ne=collect('NBA');eh,ee=collect('Eredivisie');nc=current('NBA');ec=current('Eredivisie');np=[{'sport':'basketball','league':'NBA','event_id':r['event_id'],'start_time':r['date'],'player_1':r['home'],'player_2':r['away'],'independent':nba_predict(r,nh),'market':r['markets'],'prediction_status':'research_only','paper_only':True} for r in nc];ep=[]
 try:
  from independent_football_model import independent_prediction;hist=[{'sport':'football','settled':True,'final_score':[x['home_score'],x['away_score']],'event_id':x['event_id'],'start_time':x['date'],'league':'Eredivisie','player_1':x['home'],'player_2':x['away']} for x in eh]
  for r in ec:
   e={'id':r['event_id'],'competitions':[{'competitors':[{'homeAway':'home','team':{'displayName':r['home']}},{'homeAway':'away','team':{'displayName':r['away']}}]}]};p=independent_prediction(e,'Eredivisie',hist,cutoff=r['date'])
   ep.append({'sport':'football','league':'Eredivisie','event_id':r['event_id'],'start_time':r['date'],'player_1':r['home'],'player_2':r['away'],'probabilities':{'p1':p['p1'],'draw':p['draw'],'p2':p['p2']} if p else {},'prediction_status':'research_only','paper_only':True})
 except Exception:pass
 for fn,obj in [('nba_history.json',nh),('ere_divisie_history.json',eh),('nba_predictions.json',np),('ere_divisie_predictions.json',ep)]: (DATA/fn).write_text(json.dumps(obj,indent=2))
 status={'updated_at':NOW.isoformat(),'paper_only':True,'live_trading_approved':False,'competitions':{'NBA':{'historical_events':len(nh),'current_fixtures':len(nc),'collection_errors':len(ne),'status':'research'},'Eredivisie':{'historical_events':len(eh),'current_fixtures':len(ec),'collection_errors':len(ee),'status':'research'}},'release_gate':{'minimum_walk_forward_settled':100,'requires_market_benchmark':True,'requires_calibration':True,'requires_positive_out_of_sample_evidence':True},'notes':['Independent probabilities never consume market probabilities.','Expansion outputs remain research-only until walk-forward validation passes.','Historical fallback sources are source-tagged and retained for auditability.']};(DATA/'expansion_status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2))
if __name__=='__main__':run()
