"""Research-only NBA + Eredivisie expansion collector and model."""
import csv,io,json,math
from collections import defaultdict
from datetime import datetime,date,timedelta,timezone,time as day_end_time
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports'; NOW=datetime.now(timezone.utc)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; MatchSignal/1.0)'})
NBA_START=datetime(2026,10,20,tzinfo=timezone.utc)
NBA_TOTALS_MODEL_VERSION="nba-total-v5.1-pace-efficiency-calibrated"
NBA_TOTALS_MODEL_LABEL="NBA totals v5.1: frozen 0.8 pace/efficiency blend minus 0.3542 points; no bookmaker inputs"
NBA_TOTALS_PACE_BLEND_WEIGHT=0.8
NBA_TOTALS_BIAS_CORRECTION=0.3542
NBA_WINNER_MODEL_VERSION = "nba-winner-elo-form-v1"
NBA_WINNER_MODEL_LABEL = "NBA winner Elo + recent-form v1 (market-blind)"
NBA_WINNER_MODEL_PATH = DATA / "nba_winner_model.json"
NBA_WINNER_ELO_K = 25.0
NBA_WINNER_ELO_HOME_ADVANTAGE = 70.0
_NBA_WINNER_MODEL_CACHE = None
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
  is_date_only = (
   isinstance(raw_date,str) and len(raw_date.strip())==10
  ) or (isinstance(raw_date,date) and not isinstance(raw_date,datetime))
  if stamp and is_date_only:
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

def _load_nba_winner_model():
 global _NBA_WINNER_MODEL_CACHE
 if _NBA_WINNER_MODEL_CACHE is None:
  try:
   payload=json.loads(NBA_WINNER_MODEL_PATH.read_text(encoding="utf-8"))
  except Exception as exc:
   raise RuntimeError(f"NBA winner-model artifact is unavailable: {exc}") from exc
  if payload.get("version") != NBA_WINNER_MODEL_VERSION:
   raise RuntimeError("NBA winner-model artifact version does not match the production code.")
  standardization=payload.get("standardization") or {}
  coefficients=payload.get("coefficients") or []
  means=standardization.get("mean") or []
  scales=standardization.get("sd") or []
  if len(coefficients) != len(means)+1 or len(means) != len(scales) or not means:
   raise RuntimeError("NBA winner-model artifact has an invalid coefficient/feature shape.")
  if any(not math.isfinite(float(x)) for x in coefficients+means+scales):
   raise RuntimeError("NBA winner-model artifact contains non-finite values.")
  if any(float(x) <= 0 for x in scales):
   raise RuntimeError("NBA winner-model feature scales must be positive.")
  _NBA_WINNER_MODEL_CACHE=payload
 return _NBA_WINNER_MODEL_CACHE


def _nba_winner_day_key(value):
 stamp=dt(value)
 if stamp is None:
  return None
 # Historical NBA team-game logs are keyed to the Eastern calendar day.
 # Adding one day creates the same sortable key for date-only and tip-time rows.
 return stamp.astimezone(ZoneInfo("America/New_York")).date()+timedelta(days=1)


def nba_winner_features(r,hist):
 """Build market-blind Elo, recent-efficiency, venue and schedule inputs using prior days only."""
 cutoff_day=_nba_winner_day_key(r.get("date"))
 if cutoff_day is None:
  raise ValueError("NBA winner forecast requires a valid fixture date.")
 grouped=defaultdict(list)
 for row in hist or []:
  if not isinstance(row,dict):
   continue
  day=_nba_winner_day_key(row.get("date"))
  if day is None or day>=cutoff_day:
   continue
  home=str(row.get("home") or "").strip()
  away=str(row.get("away") or "").strip()
  try:
   hs=float(row.get("home_score"));ass=float(row.get("away_score"))
  except (TypeError,ValueError):
   continue
  if not home or not away or not math.isfinite(hs) or not math.isfinite(ass):
   continue
  grouped[day].append((row,home,away,hs,ass))

 ratings={}
 team_games=defaultdict(list)
 last_game_day={}
 for day in sorted(grouped):
  games=sorted(grouped[day],key=lambda x:str(x[0].get("event_id") or ""))
  rating_snapshot=dict(ratings)
  rating_deltas=defaultdict(float)
  # Predict every game on a date from the same pre-date rating snapshot.
  # NBA teams do not play twice on one date, but batching also prevents ordering leakage.
  for row,home,away,home_score,away_score in games:
   home_rating=rating_snapshot.get(home,1500.0)
   away_rating=rating_snapshot.get(away,1500.0)
   elo_difference=home_rating-away_rating+NBA_WINNER_ELO_HOME_ADVANTAGE
   expected_home=1.0/(1.0+10.0**(-elo_difference/400.0))
   actual_home=1.0 if home_score>away_score else 0.0
   point_margin=abs(home_score-away_score)
   mov_multiplier=((point_margin+3.0)**0.8)/max(7.5,7.5+0.006*elo_difference)
   update=NBA_WINNER_ELO_K*mov_multiplier*(actual_home-expected_home)
   rating_deltas[home]+=update
   rating_deltas[away]-=update
  for name,delta in rating_deltas.items():
   ratings[name]=rating_snapshot.get(name,1500.0)+delta

  # Append all same-day team records only after the entire date has been rated.
  for row,home,away,home_score,away_score in games:
   for name,opponent,score,opponent_score,side in (
    (home,away,home_score,away_score,"home"),
    (away,home,away_score,home_score,"away"),
   ):
    offensive=float(row.get(f"{side}_off_rating") or 0.0)
    defensive=float(row.get(f"{side}_def_rating") or 0.0)
    if not math.isfinite(offensive):
     offensive=0.0
    if not math.isfinite(defensive):
     defensive=0.0
    team_games[name].append({
     "day":day,
     "opponent":opponent,
     "margin":score-opponent_score,
     "net_rating":offensive-defensive,
     "venue":side,
    })
    last_game_day[name]=day

 home=str(r.get("home") or "").strip()
 away=str(r.get("away") or "").strip()
 if not home or not away:
  raise ValueError("NBA winner forecast requires named home and away teams.")
 home_games=team_games.get(home,[])
 away_games=team_games.get(away,[])

 def mean(records,key):
  return sum(float(item.get(key) or 0.0) for item in records)/len(records) if records else 0.0

 home_recent5=home_games[-5:]
 away_recent5=away_games[-5:]
 home_recent10=home_games[-10:]
 away_recent10=away_games[-10:]
 home_venue=[item for item in home_games if item.get("venue")=="home"]
 away_venue=[item for item in away_games if item.get("venue")=="away"]
 home_overall_margin=mean(home_games,"margin")
 away_overall_margin=mean(away_games,"margin")
 home_venue_shrink=len(home_venue)/(len(home_venue)+8.0)
 away_venue_shrink=len(away_venue)/(len(away_venue)+8.0)
 home_venue_margin=(
  home_venue_shrink*mean(home_venue,"margin")
  +(1.0-home_venue_shrink)*home_overall_margin
 )
 away_venue_margin=(
  away_venue_shrink*mean(away_venue,"margin")
  +(1.0-away_venue_shrink)*away_overall_margin
 )
 fixture_day=cutoff_day
 last_home=last_game_day.get(home)
 last_away=last_game_day.get(away)
 rest_home=(fixture_day-last_home).days if last_home else 3
 rest_away=(fixture_day-last_away).days if last_away else 3
 games_last_7_home=sum(1 for item in home_games if 0 < (fixture_day-item["day"]).days <= 7)
 games_last_7_away=sum(1 for item in away_games if 0 < (fixture_day-item["day"]).days <= 7)
 features=[
  (ratings.get(home,1500.0)-ratings.get(away,1500.0))/100.0,
  (mean(home_recent5,"net_rating")-mean(away_recent5,"net_rating"))/10.0,
  (mean(home_recent10,"net_rating")-mean(away_recent10,"net_rating"))/10.0,
  (home_venue_margin-away_venue_margin)/10.0,
  max(-3.0,min(3.0,float(rest_home-rest_away)))/3.0,
  max(-3.0,min(3.0,float(games_last_7_away-games_last_7_home))),
 ]
 names=["elo","recent5","recent10","venue","rest","schedule"]
 return {
  "feature_names":names,
  "feature_values":{name:round(value,6) for name,value in zip(names,features)},
  "raw_features":features,
  "history_days_used":len(grouped),
  "history_games_used":sum(len(items) for items in grouped.values()),
 }


def nba_winner_predict(r,hist):
 """Return the independently calibrated NBA winner probability; never reads bookmaker prices."""
 model=_load_nba_winner_model()
 built=nba_winner_features(r,hist)
 standardization=model["standardization"]
 means=[float(value) for value in standardization["mean"]]
 scales=[float(value) for value in standardization["sd"]]
 coefficients=[float(value) for value in model["coefficients"]]
 z=coefficients[0]
 for index,value in enumerate(built["raw_features"]):
  z+=coefficients[index+1]*((float(value)-means[index])/scales[index])
 z=max(-25.0,min(25.0,z))
 home_probability=1.0/(1.0+math.exp(-z))
 return {
  "moneyline":{"home":home_probability,"away":1.0-home_probability},
  "model":{
   "version":NBA_WINNER_MODEL_VERSION,
   "feature_values":built["feature_values"],
   "history_games_used":built["history_games_used"],
   "history_days_used":built["history_days_used"],
   "market_inputs_used":False,
   "paper_only":True,
  },
 }


def nba_predict(r,hist,pace_blend_weight=NBA_TOTALS_PACE_BLEND_WEIGHT,bias_adjustment=NBA_TOTALS_BIAS_CORRECTION):
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
 # Keep the totals/score projection independent from the winner probability model.
 rest_adj=max(-2,min(2,(components['rest_days']['home']-components['rest_days']['away'])*.35))
 score_margin=.58*(components['home_raw']-components['away_raw'])+2.5+2*rest_adj
 score_margin=max(-.8*expected_total,min(.8*expected_total,score_margin))
 hm=expected_total/2+score_margin/2
 am=expected_total/2-score_margin/2
 winner=nba_winner_predict(r,hist)
 probabilities=winner["moneyline"]
 return {
  'moneyline':probabilities,'expected_score':{'home':hm,'away':am},
  'expected_total':expected_total,'totals_model_version':NBA_TOTALS_MODEL_VERSION,
  'winner_model':winner["model"],
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
  'model':NBA_WINNER_MODEL_LABEL,'totals_model':NBA_TOTALS_MODEL_LABEL,
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
  if old and old_stamp and start and old_stamp < start and old.get('winner_model_version') == NBA_WINNER_MODEL_VERSION:
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
       'totals_model_version':model.get('totals_model_version'),'winner_model_version':model['winner_model']['version'],'winner_model_features':model['winner_model']['feature_values'],'model':model['model'],'totals_model':model['totals_model'],'market':r.get('markets') or {},
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
