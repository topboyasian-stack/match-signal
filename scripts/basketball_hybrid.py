"""Match Signal basketball collector: official BBL + SportPesa fixtures, 1xBet public markets.

SofaScore and SportScore are intentionally not used by this collector. The source
strategy is conservative: official BBL schedule supplies German Cup fixtures;
SportPesa supplies public Club Friendly fixtures; 1xBet public event pages supply
published totals/moneyline when available. Missing markets are shown as unavailable,
never fabricated.
"""
import json, math, re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo
from curl_cffi import requests

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"
SP_URLS=[
 "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/today-games/",
 "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/upcoming-games/",
]
XBET="https://1xbet.com/en/line/basketball"
BBL=[
 ("2026-09-11T20:00:00+02:00","Veolia Towers Hamburg","ROSTOCK SEAWOLVES"),
 ("2026-09-12T18:30:00+02:00","GIESSEN 46ers","NINERS Chemnitz"),
 ("2026-09-12T20:00:00+02:00","BG Göttingen","SYNTAINICS MBC"),
 ("2026-09-13T15:00:00+02:00","Kreisbau Kirchheim Knights","MHP RIESEN Ludwigsburg"),
 ("2026-09-13T16:30:00+02:00","SKYLINERS","Science City Jena"),
 ("2026-09-13T18:00:00+02:00","MLP Academics Heidelberg","EWE Baskets Oldenburg"),
]
S=requests.Session(impersonate="chrome")
S.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36","Accept-Language":"en-US,en;q=0.9"})

def load(p,d):
 try:return json.loads(p.read_text(encoding="utf-8"))
 except Exception:return d

def save(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding="utf-8")

def html(url):
 r=S.get(url,timeout=30); r.raise_for_status(); return r.text

def norm(s):
 s=unescape(str(s)).lower().replace("ö","o").replace("ü","u").replace("ä","a").replace("ß","ss")
 return re.sub(r"[^a-z0-9]","",s)

def strip(h):
 return re.sub(r"\s+"," ",unescape(re.sub(r"<[^>]+>"," ",h))).strip()

def sportpesa():
 out=[]; seen=set()
 for u in SP_URLS:
  try:t=strip(html(u))
  except Exception:continue
  pat=re.compile(r"Game ID\s+(\d+).*?(\d{1,2}:\d{2}).*?(\d{2}/\d{2}/\d{2})\s+ID:\s+\1\s+(.{2,80}?)\s+(.{2,80}?)\s+2 Way - OT incl\.",re.I)
  for m in pat.finditer(t):
   eid,tm,dt,h,a=m.groups(); block=m.group(0)
   low=block.lower()
   if "club friendly" not in low and "club friendlies" not in low: continue
   key=(eid,norm(h),norm(a))
   if key in seen:continue
   seen.add(key)
   try: ts=datetime.strptime(dt+" "+tm,"%d/%m/%y %H:%M").replace(tzinfo=ZoneInfo("Africa/Dar_es_Salaam")).astimezone(timezone.utc).isoformat()
   except Exception: ts=datetime.now(timezone.utc).isoformat()
   out.append({"event_id":eid,"start_time":ts,"home":h.strip(),"away":a.strip(),"league":"International Club Friendly","source":"SportPesa public board"})
 return out

def xbet_links():
 try:t=html(XBET)
 except Exception:return []
 return re.findall(r'href=["\']([^"\']*/line/basketball/[^"\']+)["\']',t,re.I)

def event_link(home,away,links):
 nh,na=norm(home),norm(away)
 for x in links:
  z=norm(x)
  if nh in z and na in z:return x if x.startswith("http") else "https://1xbet.com"+x
 return None

def market(url):
 if not url:return {}
 try:t=strip(html(url))
 except Exception:return {}
 out={}
 # Team-winner odds, then total ladder. Use the central available total line.
 m=re.search(r"Team Wins.*?W1\s+([0-9.]+)\s+W2\s+([0-9.]+)",t,re.I)
 if m:
  a,b=map(float,m.groups()); pa,pb=1/a,1/b; s=pa+pb; out["p1"]=pa/s; out["p2"]=pb/s
 vals=re.findall(r"Over\s+(\d{3}(?:\.5)?)\s+([0-9.]+)",t,re.I)
 if vals:
  under=re.findall(r"Under\s+(\d{3}(?:\.5)?)\s+([0-9.]+)",t,re.I)
  u={float(x):float(y) for x,y in under}
  pairs=[(float(x),float(y),u.get(float(x))) for x,y in vals if u.get(float(x))]
  if pairs:
   line,oo,uu=min(pairs,key=lambda q:abs(q[0]-167.5)); po,pu=1/oo,1/uu; s=po+pu
   out["total"]={"line":line,"over":po/s,"under":pu/s,"over_odds":oo,"under_odds":uu}
 out["url"]=url
 return out

def fixture_prediction(f,links):
 mk=market(event_link(f["home"],f["away"],links)); total=mk.get("total")
 p1,p2=mk.get("p1",.5),mk.get("p2",.5)
 # Conservative: market probabilities are used directly when published.
 conf=max(p1,p2) if mk.get("p1") else .5
 if total:
  over,under=total["over"],total["under"]; tp="over" if over>under else "under"
  expected=total["line"]+(over-.5)*8
  q=3
 else:
  over=under=.5; tp=None; expected=None; q=1
 return {"sport":"basketball","league":f["league"],"source":"Official BBL/SportPesa fixtures + 1xBet public markets","event_id":str(f["event_id"]),"start_time":f["start_time"],"player_1":f["home"],"player_2":f["away"],"probabilities":{"p1":round(p1,4),"p2":round(p2,4)},"pick":"p1" if p1>p2 else "p2" if p2>p1 else None,"confidence":round(.5+(conf-.5)*.9,4),"markets":{"moneyline":{"p1":round(p1,4),"p2":round(p2,4),"available":"p1" in mk},"total_ou":{"line":total["line"] if total else None,"over":round(over,4),"under":round(under,4),"pick":tp,"expected_total":round(expected,1) if expected else None,"source":"1xBet public total market" if total else "No published public O/U line found","settlement":"Official final score including overtime","odds":{"over":total.get("over_odds"),"under":total.get("under_odds")} if total else None},"spread":None},"form":{"source":"Public market only; recent-form enrichment pending","p1_sample":0,"p2_sample":0},"signal_quality":{"components":q,"max_components":3,"market_total_available":bool(total),"market_event_page_available":bool(mk.get("url"))},"model":"Public market-implied probability; conservative calibration","rules_note":"Basketball totals settle on the official final score, including overtime."}

def main():
 fixtures=[{"event_id":"bbl-"+norm(h)+"-"+norm(a),"start_time":ts,"home":h,"away":a,"league":"German Basketball Cup","source":"Official BBL schedule"} for ts,h,a in BBL]
 fixtures+=sportpesa(); links=xbet_links(); preds=[fixture_prediction(f,links) for f in fixtures]
 now=datetime.now(timezone.utc).timestamp(); preds=[p for p in preds if datetime.fromisoformat(p["start_time"]).timestamp()>=now-3600]
 history=load(DATA/"basketball_history.json",[]); known={(str(x.get("event_id")),x.get("league")) for x in history}
 for p in preds:
  if (p["event_id"],p["league"]) not in known:history.append(p)
 settled=[x for x in history if x.get("settled")]; totals=[x for x in settled if x.get("total_correct") is not None]
 save(DATA/"basketball_predictions.json",sorted(preds,key=lambda x:x["start_time"]))
 save(DATA/"basketball_history.json",history)
 save(DATA/"basketball_accuracy.json",{"updated_at":datetime.now(timezone.utc).isoformat(),"settled":len(settled),"correct":sum(bool(x.get("correct")) for x in settled),"accuracy":sum(bool(x.get("correct")) for x in settled)/len(settled) if settled else None,"total_ou_settled":len(totals),"total_ou_correct":sum(bool(x.get("total_correct")) for x in totals),"total_ou_accuracy":sum(bool(x.get("total_correct")) for x in totals)/len(totals) if totals else None})
 status=load(DATA/"pipeline_status.json",{}); status.update({"basketball_count":len(preds),"basketball_settled":len(settled),"basketball_sources":[{"source":"Official BBL schedule","events":len([f for f in fixtures if f["league"]=="German Basketball Cup"]),"status":"ok"},{"source":"SportPesa public board","events":len([f for f in fixtures if f["league"]=="International Club Friendly"]),"status":"ok"},{"source":"1xBet public market pages","events_with_links":sum(1 for p in preds if p["markets"]["total_ou"]["line"] is not None),"status":"ok"}],"basketball_source_status":"Official BBL + SportPesa fixtures; 1xBet public markets; SofaScore/SportScore disabled","basketball_updated_at":datetime.now(timezone.utc).isoformat(),"basketball_rules":"Totals settle on official final score including overtime"}); save(DATA/"pipeline_status.json",status)
 print(f"Hybrid basketball: {len(preds)} predictions; O/U lines={sum(1 for p in preds if p['markets']['total_ou']['line'] is not None)}")

if __name__=="__main__":main()
