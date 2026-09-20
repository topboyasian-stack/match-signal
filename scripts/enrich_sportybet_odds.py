"""Attach current SportyBet NG market prices to Match Signal predictions.

Read-only. Uses the production Cloudflare proxy because GitHub-hosted runners can
be rejected by SportyBet directly. Never substitutes model fair odds for bookmaker
prices: if SportyBet data is unavailable, the bookmaker fields remain absent.
"""
from __future__ import annotations
import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
BASE=os.getenv('MATCH_SIGNAL_PUBLIC_BASE','https://match-signal.pages.dev').rstrip('/')
ENDPOINT=f'{BASE}/api/sportybet'
SPORT_IDS={'tennis':'sr:sport:5','football':'sr:sport:1'}
MARKET_IDS={'tennis':'186,210,202,204,189,203,188,187','football':'1,18,10,14,16,29,45,47'}


def load(path, default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default


def norm(s):
    s=str(s or '').lower()
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())


def number(v):
    try:
        x=float(v)
        return x if x>0 else None
    except (TypeError,ValueError):return None


def line_from_specifier(spec):
    m=re.search(r'(?:total|line)=([0-9]+(?:\\.[0-9]+)?)',str(spec or ''),re.I)
    return float(m.group(1)) if m else None


def fetch(sport, page=1):
    params={'sportId':SPORT_IDS[sport],'marketId':MARKET_IDS[sport],'pageSize':'100','pageNum':str(page),'timeline':'168'}
    headers={'Accept':'application/json','Content-Type':'application/json','Current-Country':'NG','Origin':'https://www.sportybet.com','Referer':'https://www.sportybet.com/ng/','User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'}
    direct_error=None
    # GitHub runners may be challenged by SportyBet. curl_cffi first gives the
    # upstream the same TLS/browser fingerprint shape used by normal browsers.
    if curl_requests is not None:
        try:
            r=curl_requests.get('https://www.sportybet.com/api/ng/factsCenter/pcUpcomingEvents',params=params,headers=headers,timeout=30,impersonate='chrome')
            if r.status_code==200 and r.text.strip():
                body=r.json()
                if isinstance(body,dict) and not body.get('ok'):
                    return body
            direct_error=f'HTTP {r.status_code}' if r is not None else 'no response'
        except Exception as exc:
            direct_error=str(exc)
    try:
        r=requests.get(ENDPOINT,params=params,timeout=30,headers={'Accept':'application/json','User-Agent':'MatchSignal/5.2'})
        r.raise_for_status()
        body=r.json()
        if not isinstance(body,dict):raise RuntimeError('SportyBet proxy returned non-object JSON')
        if body.get('ok') is False:raise RuntimeError(body.get('error') or 'SportyBet proxy error')
        return body
    except Exception as proxy_error:
        raise RuntimeError(f'direct SportyBet={direct_error}; proxy={proxy_error}')


def flatten(body):
    data=body.get('data') or {}
    tournaments=data.get('tournaments') or []
    out=[]
    for t in tournaments:
        for e in t.get('events') or []:
            e=dict(e)
            e['_league']=t.get('name')
            e['_category']=t.get('categoryName')
            out.append(e)
    return out


def market_rows(event):
    rows=[]
    for m in event.get('markets') or []:
        desc=str(m.get('desc') or m.get('name') or m.get('title') or '').strip()
        low=desc.lower()
        spec=m.get('specifier')
        line=line_from_specifier(spec)
        outcomes=[]
        for o in m.get('outcomes') or []:
            odds=number(o.get('odds'))
            if odds is None:continue
            outcomes.append({'name':str(o.get('desc') or o.get('name') or ''),'odds':odds,'id':str(o.get('id') or '')})
        rows.append({'id':str(m.get('id') or ''),'desc':desc,'specifier':spec,'line':line,'outcomes':outcomes,'lastOddsChangeTime':m.get('lastOddsChangeTime')})
    return rows


def find_event(pred, events):
    pid=str(pred.get('event_id') or '')
    if pid:
        for e in events:
            if str(e.get('eventId') or '')==pid:return e,'event_id'
    pnames={norm(pred.get('player_1')),norm(pred.get('player_2'))}
    if pred.get('sport')=='football':pnames={norm(pred.get('home_team')),norm(pred.get('away_team'))}
    if '' in pnames or len(pnames)!=2:return None,None
    pstart=pred.get('start_time')
    try:pt=datetime.fromisoformat(str(pstart).replace('Z','+00:00')).astimezone(timezone.utc) if pstart else None
    except ValueError:pt=None
    best=None
    for e in events:
        names={norm(e.get('homeTeamName')),norm(e.get('awayTeamName'))}
        if names!=pnames:continue
        est=e.get('estimateStartTime')
        try:et=datetime.fromtimestamp(float(est)/1000,tz=timezone.utc) if est else None
        except (TypeError,ValueError):et=None
        delta=abs((et-pt).total_seconds()) if et and pt else 0
        if delta<=18*3600 and (best is None or delta<best[0]):best=(delta,e)
    return (best[1],'name_time') if best else (None,None)


def extract_markets(pred,event):
    p1=norm(pred.get('player_1') or pred.get('home_team'))
    p2=norm(pred.get('player_2') or pred.get('away_team'))
    winner=None; totals=[]
    for m in market_rows(event):
        desc=m['desc'].lower()
        if 'total games' in desc:
            for o in m['outcomes']:
                ol=norm(o['name'])
                side='over' if 'over' in desc+' '+ol else 'under' if 'under' in desc+' '+ol else None
                if side and m['line'] is not None:totals.append({'line':m['line'],'side':side,'odds':o['odds'],'outcome':o['name'],'market_id':m['id'],'specifier':m['specifier'],'lastOddsChangeTime':m['lastOddsChangeTime']})
        elif ('winner' in desc or 'match winner' in desc or desc in {'win','1x2'}) and not winner:
            mapped={}
            for o in m['outcomes']:
                ol=norm(o['name'])
                if ol==p1:mapped['p1']=o['odds']
                elif ol==p2:mapped['p2']=o['odds']
            if len(mapped)==2:winner={'p1':mapped['p1'],'p2':mapped['p2'],'market_id':m['id'],'market':m['desc'],'lastOddsChangeTime':m['lastOddsChangeTime']}
    return winner,totals


def main():
    predictions=load(DATA/'predictions.json',[])
    fetched_at=datetime.now(timezone.utc).isoformat()
    all_events=[]; errors=[]; diagnostics={'sportybet_samples':{},'prediction_samples':{}}
    for sport in ('football','tennis'):
        try:
            events=[]
            for page in range(1,6):
                body=fetch(sport,page=page)
                batch=flatten(body)
                events.extend(batch)
                if len(batch)<100:break
            dedup={str(e.get('eventId')):e for e in events if e.get('eventId')}
            events=list(dedup.values())
            all_events.extend((sport,e) for e in events)
            diagnostics['sportybet_samples'][sport]=[{'event_id':e.get('eventId'),'home':e.get('homeTeamName'),'away':e.get('awayTeamName'),'start':e.get('estimateStartTime'),'market_count':len(e.get('markets') or [])} for e in events[:10]]
            print(f'SportyBet {sport}: {len(events)} fixtures received across pages')
        except Exception as exc:
            errors.append(f'{sport}:{exc}')
            print(f'SportyBet {sport}: ERROR {exc}')
    matched=0; winner_prices=0; total_prices=0
    for sport in ('football','tennis'):
        diagnostics['prediction_samples'][sport]=[{'event_id':p.get('event_id'),'p1':p.get('player_1') or p.get('home_team'),'p2':p.get('player_2') or p.get('away_team'),'start':p.get('start_time')} for p in predictions if p.get('sport')==sport][:10]
    for p in predictions:
        sport=p.get('sport')
        if sport not in SPORT_IDS:continue
        event,match_type=find_event(p,[e for s,e in all_events if s==sport])
        if not event:continue
        winner,totals=extract_markets(p,event)
        snap={'source':'SportyBet NG web API via Cloudflare proxy','fetched_at':fetched_at,'match_type':match_type,'sportybet_event_id':event.get('eventId'),'league':event.get('_league'),'sportybet_start_time':event.get('estimateStartTime')}
        if winner:
            snap['winner']=winner; winner_prices+=1
        if totals:
            snap['total_games']=totals; total_prices+=len(totals)
        if winner or totals:
            p['sportybet_market_snapshot']=snap
            p['market_source']='SportyBet NG'
            p['odds_timestamp']=fetched_at
            if winner:
                p['sportybet_winner_odds']=winner
            if totals:
                p['sportybet_total_games_odds']=totals
            matched+=1
    status={'updated_at':fetched_at,'source':'SportyBet NG web API via Cloudflare proxy','endpoint':ENDPOINT,'sports_requested':['football','tennis'],'fixtures_received':len(all_events),'predictions_matched':matched,'winner_price_records':winner_prices,'total_games_price_records':total_prices,'errors':errors,'status':'LIVE_MARKET_SYNC' if matched else 'NO_CURRENT_SPORTYBET_MATCHES','diagnostics':diagnostics}
    (DATA/'sportybet_odds_snapshot.json').write_text(json.dumps(status,indent=2)+'\\n',encoding='utf-8')
    (DATA/'predictions.json').write_text(json.dumps(predictions,indent=2,ensure_ascii=False)+'\\n',encoding='utf-8')
    print(json.dumps(status,indent=2))


if __name__=='__main__':main()
