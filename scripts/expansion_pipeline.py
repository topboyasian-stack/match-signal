"""Research-only NBA + Eredivisie expansion collector and model."""
import csv,io,json,math
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import requests
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports'; NOW=datetime.now(timezone.utc)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; MatchSignal/1.0)'})
NBA_START=datetime(2026,10,20,tzinfo=timezone.utc)
NBA_PARQUET='https://raw.githubusercontent.com/llimllib/nba_data/main/data/espn/team_box.parquet'
NBA_ELO_CSV='https://datahub.io/fivethirtyeight/nba-elo/_r/-/data/nbaallelo.csv'
def dt(x):
 try:
  d=datetime.fromisoformat(str(x).replace('Z','+00:00'));return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except:
  for f in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):
   try:return datetime.strptime(str(x),f).replace(tzinfo=timezone.utc)
   except:pass
 return None
def get(u,p=None):r=S.get(u,params=p,timeout=40);r.raise_for_status();return r.json()
def text(u):r=S.get(u,timeout=60);r.raise_for_status();return r.text
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
def nba_parquet_fallback():
 r=S.get(NBA_PARQUET,timeout=60);r.raise_for_status();df=pd.read_parquet(io.BytesIO(r.content));df.columns=[str(c).strip() for c in df.columns]
 def col(*names):
  lower={c.lower():c for c in df.columns}
  for n in names:
   if n.lower() in lower:return lower[n.lower()]
  return None
 date_c=col('game_date','date','game_date_time');gid_c=col('game_id','gameid','id');home_c=col('home_display_name','home_team','home_team_name');away_c=col('away_display_name','away_team','away_team_name');hs_c=col('home_score','home_team_score','pts_home','home_pts');as_c=col('away_score','away_team_score','pts_away','away_pts');rows=[]
 if date_c and home_c and away_c and hs_c and as_c:
  for _,r0 in df.iterrows():
   d=dt(r0.get(date_c))
   if not d or d<NOW-timedelta(days=365) or d>NOW:continue
   h=str(r0.get(home_c) or '').strip();a=str(r0.get(away_c) or '').strip()
   try:hs=float(r0.get(hs_c));as_=float(r0.get(as_c))
   except:continue
   if not h or not a:continue
   rows.append({'event_id':str(r0.get(gid_c)) if gid_c else f'nba|{d.date()}|{h}|{a}','date':d.isoformat(),'home':h,'away':a,'home_id':'','away_id':'','home_score':hs,'away_score':as_,'markets':{},'source':NBA_PARQUET})
 else:
  team_id=col('team_id');opp_id=col('opponent_team_id');side_c=col('team_home_away','home_away');name_c=col('team_display_name','team_name');score_c=col('team_score','score');opp_name_c=col('opponent_team_display_name','opponent_team_name');opp_score_c=col('opponent_team_score')
  if not (date_c and gid_c and side_c and name_c and score_c and opp_name_c and opp_score_c):raise ValueError(f'unexpected NBA parquet schema: {list(df.columns)[:20]}')
  for _,r0 in df.iterrows():
   d=dt(r0.get(date_c))
   if not d or d<NOW-timedelta(days=365) or d>NOW or str(r0.get(side_c)).lower()!='home':continue
   h=str(r0.get(name_c) or '').strip();a=str(r0.get(opp_name_c) or '').strip()
   try:hs=float(r0.get(score_c));as_=float(r0.get(opp_score_c))
   except:continue
   if not h or not a:continue
   rows.append({'event_id':str(r0.get(gid_c)),'date':d.isoformat(),'home':h,'away':a,'home_id':str(r0.get(team_id) or ''),'away_id':str(r0.get(opp_id) or ''),'home_score':hs,'away_score':as_,'markets':{},'source':NBA_PARQUET})
 if not rows:raise ValueError(f'{NBA_PARQUET}: zero usable rows')
 return sorted({r['event_id']:r for r in rows}.values(),key=lambda x:x['date'])
def nba_elo_fallback():
 df=pd.read_csv(io.StringIO(text(NBA_ELO_CSV)),usecols=['game_id','lg_id','date_game','team_id','fran_id','pts','opp_id','opp_fran','opp_pts','game_location'])
 df=df[df['lg_id'].astype(str).str.upper().eq('NBA')]
 df['date']=pd.to_datetime(df['date_game'],errors='coerce',utc=True)
 cutoff=pd.Timestamp(NOW-timedelta(days=365));end=pd.Timestamp(NOW)
 df=df[(df['date']>=cutoff)&(df['date']<=end)]
 rows=[]
 for gid,g in df.groupby('game_id',sort=False):
  h=g[g['game_location'].astype(str).str.upper().eq('H')]
  a=g[g['game_location'].astype(str).str.upper().eq('A')]
  if h.empty or a.empty:continue
  hr=h.iloc[0];ar=a.iloc[0]
  rows.append({'event_id':f'elo|{gid}','date':hr['date'].isoformat(),'home':str(hr['fran_id']).strip(),'away':str(ar['fran_id']).strip(),'home_id':str(hr['team_id']),'away_id':str(ar['team_id']),'home_score':float(hr['pts']),'away_score':float(hr['opp_pts']),'markets':{},'source':NBA_ELO_CSV})
 if not rows:raise ValueError(f'{NBA_ELO_CSV}: zero usable NBA games in 365-day window')
 return sorted({r['event_id']:r for r in rows}.values(),key=lambda x:x['date'])
def nba_fallback():
 errors=[]
 for name,fn in (('nba_parquet',nba_parquet_fallback),('nba_elo_csv',nba_elo_fallback)):
  try:return fn(),[]
  except Exception as e:errors.append(f'{name}: {e}')
 return [],errors
def collect(name):
 rows,errs=collect_espn('basketball/nba' if name=='NBA' else 'soccer/ned.1')
 if rows:return rows,[]
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
 status={'updated_at':NOW.isoformat(),'paper_only':True,'live_trading_approved':False,'competitions':{'NBA':{'historical_events':len(nh),'current_fixtures':len(nc),'collection_errors':len(ne),'status':'research','source':'ESPN primary; llimllib/nba_data parquet; DataHub/FiveThirtyEight NBA Elo CSV fallback'},'Eredivisie':{'historical_events':len(eh),'current_fixtures':len(ec),'collection_errors':len(ee),'status':'research'}},'release_gate':{'minimum_walk_forward_settled':100,'requires_market_benchmark':True,'requires_calibration':True,'requires_positive_out_of_sample_evidence':True},'notes':['Independent probabilities never consume market probabilities.','Expansion outputs remain research-only until walk-forward validation passes.','Historical fallback sources are source-tagged and retained for auditability.','NBA fallback order: ESPN, verified team-box parquet, then stable DataHub/FiveThirtyEight NBA Elo CSV. The Elo dataset is updated periodically and may end before the current season, so its coverage date is retained in the source URL.']};(DATA/'expansion_status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2))
if __name__=='__main__':run()
