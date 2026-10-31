"""Research-only NBA + Eredivisie expansion collector and model."""
import csv,io,json,math
from collections import defaultdict
from datetime import datetime,timedelta,timezone,time as day_end_time
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports'; NOW=datetime.now(timezone.utc)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; MatchSignal/1.0)'})
NBA_START=datetime(2026,10,20,tzinfo=timezone.utc)
NBA_TOTALS_MODEL_VERSION="nba-total-v4-pace-efficiency-calibrated"
NBA_PARQUET='https://raw.githubusercontent.com/llimllib/nba_data/main/data/gamelogs.parquet'
NBA_DUCKDB_CATALOG='https://basketball-data.billmill.org/nba/nba.duckdb'
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
def evs(slug,a,b):
 return get(f'{BASE}/{slug}/scoreboard',{'dates':f'{a:%Y%m%d}-{b:%Y%m%d}'}).get('events',[])
def evs_daily(slug,a,b):
 # ESPN range requests returned HTTP 400 in production diagnostics. Query one
 # date at a time for current fixture windows and recovery.
 events={}; errors=[]; day=a.date()
 while day<=b.date():
  key=day.strftime('%Y%m%d')
  try:
   for e in get(f'{BASE}/{slug}/scoreboard',{'dates':key}).get('events',[]):
    event_key=str(e.get('id') or f'{slug}|{e.get("date")}')
    events[event_key]=e
  except Exception as exc:
   errors.append(f'{key}: {exc}')
  day+=timedelta(days=1)
 if errors and not events:
  raise RuntimeError('ESPN daily scoreboard failed: '+'; '.join(errors[:3]))
 return list(events.values())
def team(c):t=c.get('team') or {};return str(t.get('id') or c.get('id') or ''),(t.get('displayName') or c.get('displayName') or '').strip()
def nba_regular_season_start(year):
 # Official opening dates known for the current and previous seasons; use Oct 20
 # as a conservative fallback for future seasons. Preseason is not training data.
 known={2025: datetime(2025,10,21,tzinfo=timezone.utc), 2026: datetime(2026,10,20,tzinfo=timezone.utc)}
 return known.get(int(year),datetime(int(year),10,20,tzinfo=timezone.utc))

def is_nba_regular_season_date(value):
 d=dt(value)
 if not d:return False
 season_year=d.year if d.month>=10 else d.year-1
 return d>=nba_regular_season_start(season_year)

def collect_espn(slug,daily=False):
 rows=[];errs=[];seen=set();a=NOW-timedelta(days=365)
 # ESPN scoreboard date ranges are bounded; ask for at most seven calendar days.
 # The prior 30-day request caused the NBA history pull to return empty.
 while a<NOW:
  b=min(NOW,a+timedelta(days=6))
  try:es=(evs_daily(slug,a,b) if daily else evs(slug,a,b))
  except Exception as e:errs.append(f"{a.date()}..{b.date()}: {e}");es=[]
  for e in es:
   cs=(e.get('competitions') or [{}])[0].get('competitors',[])
   if len(cs)!=2 or not (e.get('status') or {}).get('type',{}).get('completed'):continue
   event_date=dt(e.get('date'))
   if slug=='basketball/nba' and not is_nba_regular_season_date(event_date):continue
   h=next((x for x in cs if x.get('homeAway')=='home'),cs[0]);a1=next((x for x in cs if x.get('homeAway')=='away'),cs[1]);hid,hn=team(h);aid,an=team(a1)
   try:hs=float(h.get('score'));as_=float(a1.get('score'))
   except:continue
   if not hn or not an:continue
   k=str(e.get('id') or f'{hn}|{an}|{e.get("date")}')
   if k in seen:continue
   seen.add(k);rows.append({'event_id':k,'date':e.get('date'),'home':hn,'away':an,'home_id':hid,'away_id':aid,'home_score':hs,'away_score':as_,'markets':{},'source':'ESPN'})
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
 r=S.get(NBA_PARQUET,timeout=60);r.raise_for_status()
 df=pd.read_parquet(io.BytesIO(r.content));df.columns=[str(c).strip() for c in df.columns]
 def col(*names):
  lower={c.lower():c for c in df.columns}
  for n in names:
   if n.lower() in lower:return lower[n.lower()]
  return None
 date_c=col('game_date','date','game_date_time')
 gid_c=col('game_id','gameid','id')
 team_c=col('team_name','team_display_name','team')
 matchup_c=col('matchup')
 score_c=col('pts','team_score','score')
 teamid_c=col('team_id','team_abbreviation')
 rows=[]
 # Current nba_data archive: two dated team rows per game.
 # "vs." marks the home row and "@" marks the away row.
 if date_c and gid_c and team_c and matchup_c and score_c:
  grouped=defaultdict(list)
  for _,r0 in df.iterrows():
   d=dt(r0.get(date_c))
   if not d or d<NOW-timedelta(days=365) or d>NOW or not is_nba_regular_season_date(d):continue
   name=str(r0.get(team_c) or '').strip()
   matchup=' '.join(str(r0.get(matchup_c) or '').upper().replace('VS.','VS').split())
   if not name:continue
   if ' VS ' in f' {matchup} ':side='home'
   elif ' @ ' in f' {matchup} ':side='away'
   else:continue
   try:score=float(r0.get(score_c))
   except (TypeError,ValueError):continue
   if not math.isfinite(score):continue
   grouped[str(r0.get(gid_c))].append({'date':d,'side':side,'team':name,'team_id':str(r0.get(teamid_c) or ''),'score':score})
  for gid,parts in grouped.items():
   home=next((x for x in parts if x['side']=='home'),None)
   away=next((x for x in parts if x['side']=='away'),None)
   if not home or not away:continue
   rows.append({'event_id':gid,'date':home['date'].isoformat(),'home':home['team'],'away':away['team'],
     'home_id':home['team_id'],'away_id':away['team_id'],'home_score':home['score'],'away_score':away['score'],
     'markets':{},'source':NBA_PARQUET})
 else:
  # Compatibility path for already-normalized single-row team box schemas.
  home_c=col('home_display_name','home_team','home_team_name')
  away_c=col('away_display_name','away_team','away_team_name')
  hs_c=col('home_score','home_team_score','pts_home','home_pts')
  as_c=col('away_score','away_team_score','pts_away','away_pts')
  if date_c and home_c and away_c and hs_c and as_c:
   for _,r0 in df.iterrows():
    d=dt(r0.get(date_c))
    if not d or d<NOW-timedelta(days=365) or d>NOW or not is_nba_regular_season_date(d):continue
    h=str(r0.get(home_c) or '').strip();a=str(r0.get(away_c) or '').strip()
    try:hs=float(r0.get(hs_c));as_=float(r0.get(as_c))
    except (TypeError,ValueError):continue
    if not h or not a:continue
    gid=str(r0.get(gid_c) or f'nba|{d.date()}|{h}|{a}')
    rows.append({'event_id':gid,'date':d.isoformat(),'home':h,'away':a,'home_id':'','away_id':'',
      'home_score':hs,'away_score':as_,'markets':{},'source':NBA_PARQUET})
  else:
   raise ValueError(f'unexpected NBA gamelog schema: {list(df.columns)[:20]}')
 if not rows:raise ValueError(f'{NBA_PARQUET}: zero usable dated NBA regular-season rows in 365-day window')
 return sorted({r['event_id']:r for r in rows}.values(),key=lambda x:x['date'])
def normalize_nba_duckdb_rows(rows,now=None):
 """Normalize the public v2 NBA team-game logs with pace and efficiency."""
 now=now or NOW
 cutoff=now-timedelta(days=365)
 normalized=[]
 fields=('home_pace','away_pace','home_off_rating','away_off_rating',
         'home_def_rating','away_def_rating','home_possessions','away_possessions')
 for raw in rows or []:
  if not isinstance(raw,dict):continue
  if str(raw.get('game_type') or '').strip().lower()!='regular_season':continue
  raw_date=raw.get('date') or raw.get('game_date') or raw.get('start_time')
  stamp=dt(raw_date)
  # The NBA stats catalog records a game_date, not a tip timestamp.
  # Make it available only after 23:59:59 UTC on that date to avoid
  # using any same-day game result in another pre-game forecast.
  if stamp and isinstance(raw_date,str) and len(raw_date.strip())==10:
   # game_date is defined by the NBA in US Eastern time. End the day in
   # America/New_York, then convert to UTC; midnight-UTC would leak the
   # results of late Eastern games into next-morning pregame forecasts.
   stamp=datetime.combine(
    stamp.date(),day_end_time.max,tzinfo=ZoneInfo('America/New_York')
   ).astimezone(timezone.utc)
  home=str(raw.get('home') or '').strip()
  away=str(raw.get('away') or '').strip()
  try:hs=float(raw.get('home_score'));aws=float(raw.get('away_score'))
  except (TypeError,ValueError):continue
  if not stamp or stamp<cutoff or stamp>now or not home or not away:continue
  if not all(math.isfinite(x) and x>=0 for x in (hs,aws)):continue
  row={'event_id':str(raw.get('event_id') or ''),
       'date':stamp.isoformat(),'home':home,'away':away,
       'home_id':str(raw.get('home_id') or ''),'away_id':str(raw.get('away_id') or ''),
       'home_score':hs,'away_score':aws,'markets':{},
       'source':'nba_data_v2_team_game_logs'}
  for key in fields:
   try:value=float(raw.get(key))
   except (TypeError,ValueError):value=None
   row[key]=value if value is not None and math.isfinite(value) and value>0 else None
  if row['event_id']:normalized.append(row)
 return sorted({r['event_id']:r for r in normalized}.values(),key=lambda x:(x['date'],x['event_id']))

def nba_duckdb_fallback():
 """Collect NBA team-game logs from public season Parquet files, bypassing the catalog WAL."""
 try:
  import duckdb
 except Exception as exc:
  raise RuntimeError(f'DuckDB dependency unavailable: {exc}')
 active_season=NOW.year+1 if NOW.month>=7 else NOW.year
 seasons=[active_season-1,active_season]
 base='https://basketball-data.billmill.org/nba/stats'
 def parquet_list(dataset):
  return '['+','.join("'"+base+'/'+dataset+'/season='+str(season)+'/data.parquet'+"'" for season in seasons)+']'
 con=duckdb.connect(database=':memory:')
 try:
  con.execute('SET threads=2')
  con.execute('INSTALL httpfs')
  con.execute('LOAD httpfs')
  team_logs=parquet_list('team_game_logs')
  games=parquet_list('games')
  team_seasons=parquet_list('team_seasons')
  query=f"""
   SELECT CAST(h.game_id AS VARCHAR) AS event_id,
          CAST(h.game_date AS VARCHAR) AS date,
          g.game_type AS game_type,
          home_team.full_name AS home,
          away_team.full_name AS away,
          CAST(h.team_id AS VARCHAR) AS home_id,
          CAST(a.team_id AS VARCHAR) AS away_id,
          CAST(h.pts AS DOUBLE) AS home_score,
          CAST(a.pts AS DOUBLE) AS away_score,
          CAST(h.pace AS DOUBLE) AS home_pace,
          CAST(a.pace AS DOUBLE) AS away_pace,
          CAST(h.off_rating AS DOUBLE) AS home_off_rating,
          CAST(a.off_rating AS DOUBLE) AS away_off_rating,
          CAST(h.def_rating AS DOUBLE) AS home_def_rating,
          CAST(a.def_rating AS DOUBLE) AS away_def_rating,
          CAST(h.poss AS DOUBLE) AS home_possessions,
          CAST(a.poss AS DOUBLE) AS away_possessions
     FROM read_parquet({team_logs}, union_by_name=true) h
     JOIN read_parquet({team_logs}, union_by_name=true) a
       ON a.season=h.season AND a.game_id=h.game_id
      AND a.team_id=h.opp_team_id AND a.opp_team_id=h.team_id
     JOIN read_parquet({games}, union_by_name=true) g
       ON g.season=h.season AND g.game_id=h.game_id
     JOIN read_parquet({team_seasons}, union_by_name=true) home_team
       ON home_team.season=h.season AND home_team.team_id=h.team_id
     JOIN read_parquet({team_seasons}, union_by_name=true) away_team
       ON away_team.season=a.season AND away_team.team_id=a.team_id
    WHERE g.game_type='regular_season'
      AND h.home IS TRUE
      AND h.game_date>=CAST('{(NOW-timedelta(days=365)).date().isoformat()}' AS DATE)
      AND h.game_date<=CAST('{NOW.date().isoformat()}' AS DATE)
    ORDER BY h.game_date,h.game_id
  """
  frame=con.execute(query).fetchdf()
  rows=normalize_nba_duckdb_rows(frame.to_dict(orient='records'),NOW)
  if not rows:
   raise ValueError('public NBA team-game-log Parquet files returned zero usable regular-season games in the 365-day window')
  return rows
 finally:
  con.close()

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
 for name,fn in (('nba_data_v2',nba_duckdb_fallback),('nba_parquet_legacy',nba_parquet_fallback),('nba_elo_csv',nba_elo_fallback)):
  try:return fn(),[]
  except Exception as e:errors.append(f'{name}: {e}')
 return [],errors
def collect(name):
 if name=='NBA':
  try:return nba_duckdb_fallback(),[]
  except Exception as exc:errors=[f'nba_data_v2_team_game_logs: {exc}']
  rows,espn_errors=collect_espn('basketball/nba',daily=True);errors.extend(espn_errors)
  if rows:return rows,errors
  try:return nba_elo_fallback(),errors
  except Exception as exc:return [],errors+[f'nba_elo_csv: {exc}']
 rows,errs=collect_espn('soccer/ned.1')
 if rows:return rows,errs
 fallback_rows,fallback_errors=ere_fallback()
 return fallback_rows,errs+fallback_errors
def _finite_number(value):
 try:
  number=float(value)
  return number if math.isfinite(number) else None
 except (TypeError,ValueError):return None

def weights(hist,cut,half_life_days=30):
 """Build strictly pre-tip scoring, recent-total, pace and efficiency profiles."""
 s=defaultdict(lambda:{'pf':0.,'pa':0.,'n':0.,'last':None,'recent_totals':[],
                       'pace_sum':0.,'pace_n':0.,'off_sum':0.,'off_n':0.,
                       'def_sum':0.,'def_n':0.,'poss_sum':0.,'poss_n':0.})
 half_life=max(1.0,float(half_life_days))
 ordered=sorted(hist,key=lambda r:dt(r.get('date')) or datetime.min.replace(tzinfo=timezone.utc))
 for r in ordered:
  d=dt(r.get('date'))
  if not d or d>=cut:continue
  w=math.exp(-math.log(2)*max(0,(cut-d).total_seconds()/86400)/half_life)
  try:game_total=float(r['home_score'])+float(r['away_score'])
  except (TypeError,ValueError,KeyError):continue
  if not math.isfinite(game_total) or game_total<0:continue
  for side,name,p,o in (('home',r.get('home'),r.get('home_score'),r.get('away_score')),
                        ('away',r.get('away'),r.get('away_score'),r.get('home_score'))):
   try:p=float(p);o=float(o)
   except (TypeError,ValueError):continue
   if not name or not math.isfinite(p) or not math.isfinite(o):continue
   q=s[name];q['pf']+=w*p;q['pa']+=w*o;q['n']+=w
   q['recent_totals'].append(game_total)
   if len(q['recent_totals'])>12:q['recent_totals'].pop(0)
   for metric,field in (('pace',f'{side}_pace'),('off',f'{side}_off_rating'),
                        ('def',f'{side}_def_rating'),('poss',f'{side}_possessions')):
    value=_finite_number(r.get(field))
    if value is not None and value>0:
     q[metric+'_sum']+=w*value;q[metric+'_n']+=w
   if q['last'] is None or d>q['last']:q['last']=d
 return s

def nba_total_components(r,hist):
 """Return score-form and independent pace/efficiency estimates for one fixture."""
 cut=dt(r.get('date')) or NOW
 s=weights(hist,cut,half_life_days=30)
 h=s.get(r.get('home'),{});a=s.get(r.get('away'),{})
 hp=h.get('pf',0)/max(h.get('n',1),1e-9)
 ap=a.get('pf',0)/max(a.get('n',1),1e-9)
 hd=h.get('pa',0)/max(h.get('n',1),1e-9)
 ad=a.get('pa',0)/max(a.get('n',1),1e-9)
 league_team_points=sum(x['pf'] for x in s.values())/max(sum(x['n'] for x in s.values()),1e-9)
 fallback_total=2*league_team_points if league_team_points>0 else 225.0
 hform=h.get('recent_totals') or [];aform=a.get('recent_totals') or []
 h_recent=sum(hform[-12:])/len(hform[-12:]) if hform else fallback_total
 a_recent=sum(aform[-12:])/len(aform[-12:]) if aform else fallback_total
 matchup=(hp+ad+ap+hd)/2 if h.get('n',0)>0 and a.get('n',0)>0 else fallback_total
 base_total=.5*matchup+.5*((h_recent+a_recent)/2)
 def avg(team,key):
  count=team.get(key+'_n',0)
  return team.get(key+'_sum',0)/count if count>0 else None
 h_pace,a_pace=avg(h,'pace'),avg(a,'pace')
 h_off,a_off=avg(h,'off'),avg(a,'off')
 h_def,a_def=avg(h,'def'),avg(a,'def')
 pace_available=all(x is not None for x in (h_pace,a_pace,h_off,a_off,h_def,a_def))
 pace_total=None;game_pace=None;home_expected_eff=None;away_expected_eff=None
 if pace_available:
  game_pace=(h_pace+a_pace)/2
  home_expected_eff=(h_off+a_def)/2
  away_expected_eff=(a_off+h_def)/2
  if 75<=game_pace<=115 and 75<=home_expected_eff<=145 and 75<=away_expected_eff<=145:
   pace_total=game_pace*(home_expected_eff+away_expected_eff)/100
  else:
   pace_available=False;game_pace=None;home_expected_eff=None;away_expected_eff=None
 return {
  'base_total':base_total,'pace_total':pace_total,'pace_available':bool(pace_available and pace_total is not None),
  'game_pace':game_pace,'home_expected_off_rating':home_expected_eff,
  'away_expected_off_rating':away_expected_eff,'fallback_total':fallback_total,
  'rest_days':{
   'home':(cut-h['last']).total_seconds()/86400 if h.get('last') else 4,
   'away':(cut-a['last']).total_seconds()/86400 if a.get('last') else 4
  },
  'home_raw':(hp+ad)/2 if h.get('n',0)>0 and a.get('n',0)>0 else base_total/2,
  'away_raw':(ap+hd)/2 if h.get('n',0)>0 and a.get('n',0)>0 else base_total/2,
  'recency_half_life_days':30,'recent_team_total_window':12
 }

def nba_predict(r,hist,pace_blend_weight=0.0,bias_adjustment=0.0):
 components=nba_total_components(r,hist)
 try:weight=max(0.0,min(1.0,float(pace_blend_weight)))
 except (TypeError,ValueError):weight=0.0
 try:bias=float(bias_adjustment)
 except (TypeError,ValueError):bias=0.0
 if not math.isfinite(bias):bias=0.0
 if not components['pace_available']:weight=0.0
 base=components['base_total']
 pace=components['pace_total'] if components['pace_available'] else base
 expected_total=max(100.0,min(320.0,base+weight*(pace-base)-bias))
 hr=components['rest_days']['home'];ar=components['rest_days']['away']
 rest_adj=max(-2,min(2,(hr-ar)*.35))
 margin=.58*(components['home_raw']-components['away_raw'])+2.5+2*rest_adj
 margin=max(-.8*expected_total,min(.8*expected_total,margin))
 hm=expected_total/2+margin/2;am=expected_total/2-margin/2
 p=1/(1+math.exp(-margin/7.5))
 return {
  'moneyline':{'home':p,'away':1-p},'expected_score':{'home':hm,'away':am},
  'expected_total':expected_total,'totals_model_version':NBA_TOTALS_MODEL_VERSION,
  'rest_days':components['rest_days'],
  'total_model_features':{
   'recency_half_life_days':30,'recent_team_total_window':12,
   'pace_efficiency_available':components['pace_available'],
   'pace_blend_weight':weight,'pace_efficiency_total':components['pace_total'],
   'score_form_reference_total':base,'bias_correction_points':bias,
   'game_pace':components['game_pace'],
   'home_expected_off_rating':components['home_expected_off_rating'],
   'away_expected_off_rating':components['away_expected_off_rating']
  },
  'model':'NBA totals v4: development-calibrated score-form plus team-game pace/efficiency; no bookmaker inputs',
  'paper_only':True
}
def current(name):
 if name=='NBA' and NOW<NBA_START:return []
 start=NOW-timedelta(days=1)
 if name=='NBA':start=max(start,NBA_START)
 end=NOW+timedelta(days=6)
 try:es=evs_daily('basketball/nba' if name=='NBA' else 'soccer/ned.1',start,end)
 except:return []
 out=[]
 for e in es:
  cs=(e.get('competitions') or [{}])[0].get('competitors',[])
  if len(cs)!=2:continue
  event_date=dt(e.get('date'))
  # Never place preseason or stale past events in the regular-season feed.
  if not event_date or (name=='NBA' and event_date<NBA_START):continue
  h=next((x for x in cs if x.get('homeAway')=='home'),cs[0]);a=next((x for x in cs if x.get('homeAway')=='away'),cs[1]);_,hn=team(h);_,an=team(a)
  if hn and an:out.append({'event_id':str(e.get('id')),'date':event_date.isoformat(),'home':hn,'away':an,'markets':{}})
 return out
def run():
 nh,ne=collect('NBA');eh,ee=collect('Eredivisie');nc=current('NBA');ec=current('Eredivisie')
 # Preserve the first pre-game forecast for each event so later refreshes cannot
 # rewrite a pick after tip-off and make the settlement record look predictive.
 old_nba=[]
 try: old_nba=json.loads((DATA/'nba_predictions.json').read_text())
 except Exception: old_nba=[]
 old_by_id={str(x.get('event_id')):x for x in old_nba if isinstance(x,dict)}
 np=[]; seen=set()
 for r in nc:
  eid=str(r['event_id']); start=dt(r['date']); old=old_by_id.get(eid)
  old_stamp=dt(old.get('generated_at')) if old else None
  if old and old_stamp and start and old_stamp < start:
   p=dict(old)
  else:
   # Do not create a first-time "prediction" for a game that has already started.
   if not start or start <= NOW:
    if old: p=dict(old)
    else: continue
   else:
    model=nba_predict(r,nh); probs=model['moneyline']; pick='p1' if probs['home']>=probs['away'] else 'p2'
    p={'sport':'basketball','league':'NBA','event_id':eid,'start_time':r['date'],
       'player_1':r['home'],'player_2':r['away'],
       'probabilities':{'p1':round(probs['home'],6),'p2':round(probs['away'],6)},
       'pick':pick,'confidence':round(max(probs['home'],probs['away']),6),
       'expected_score':model['expected_score'],'expected_total':model['expected_total'],
       'totals_model_version':model.get('totals_model_version'),'model':model['model'],'market':r.get('markets') or {},
       'signal_quality':{'status':'LIVE_EXPERIMENTAL','market_odds_available':False},
       'generated_at':NOW.isoformat(),'prediction_created_at':NOW.isoformat(),
       'accuracy_eligible':True,'prediction_status':'live_experimental',
       'live_experimental':True,'paper_only':True}
  np.append(p); seen.add(eid)
 # Retain recent pre-game snapshots long enough for the settlement collector to
 # match final scores; the settlement ledger remains the durable history.
 for old in old_nba:
  if not isinstance(old,dict): continue
  eid=str(old.get('event_id') or '')
  start=dt(old.get('start_time'))
  stamp=dt(old.get('generated_at') or old.get('prediction_created_at'))
  if eid and eid not in seen and start and stamp and stamp < start and start >= NOW-timedelta(hours=30):
   np.append(dict(old)); seen.add(eid)
 np.sort(key=lambda x:x.get('start_time',''))
 ep=[]
 try:
  from independent_football_model import independent_prediction;hist=[{'sport':'football','settled':True,'final_score':[x['home_score'],x['away_score']],'event_id':x['event_id'],'start_time':x['date'],'league':'Eredivisie','player_1':x['home'],'player_2':x['away']} for x in eh]
  for r in ec:
   e={'id':r['event_id'],'competitions':[{'competitors':[{'homeAway':'home','team':{'displayName':r['home']}},{'homeAway':'away','team':{'displayName':r['away']}}]}]};p=independent_prediction(e,'Eredivisie',hist,cutoff=r['date'])
   ep.append({'sport':'football','league':'Eredivisie','event_id':r['event_id'],'start_time':r['date'],'player_1':r['home'],'player_2':r['away'],'probabilities':{'p1':p['p1'],'draw':p['draw'],'p2':p['p2']} if p else {},'prediction_status':'research_only','paper_only':True})
 except Exception:pass
 for fn,obj in [('nba_history.json',nh),('ere_divisie_history.json',eh),('nba_predictions.json',np),('ere_divisie_predictions.json',ep)]: (DATA/fn).write_text(json.dumps(obj,indent=2))
 status={'updated_at':NOW.isoformat(),'paper_only':True,'live_trading_approved':False,'competitions':{'NBA':{'historical_events':len(nh),'current_fixtures':len(nc),'collection_errors':len(ne),'status':'research','source':'llimllib/nba_data gamelogs.parquet; ESPN daily scoreboard; DataHub/FiveThirtyEight NBA Elo CSV fallback'},'Eredivisie':{'historical_events':len(eh),'current_fixtures':len(ec),'collection_errors':len(ee),'status':'research'}},'release_gate':{'minimum_walk_forward_settled':100,'requires_market_benchmark':True,'requires_calibration':True,'requires_positive_out_of_sample_evidence':True},'notes':['Independent probabilities never consume market probabilities.','Expansion outputs remain research-only until walk-forward validation passes.','Historical fallback sources are source-tagged and retained for auditability.','NBA historical priority: dated gamelogs.parquet archive, then ESPN daily scoreboard, then DataHub/FiveThirtyEight NBA Elo CSV. Regular-season date filtering excludes preseason rows. The Elo dataset is updated periodically and may end before the current season, so its coverage date is retained in the source URL.']};(DATA/'expansion_status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status,indent=2))
if __name__=='__main__':run()
