"""Basketball coverage for BBL-Pokal and international club friendlies."""
import json, math, re
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASE = "https://api.sofascore.com/api/v1"
TOURNAMENTS = {"German Basketball Cup": 359, "International Club Friendly": 1195}
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0 Safari/537.36","Accept":"application/json,text/plain,*/*","Referer":"https://www.sofascore.com/"})

def get(path):
    r=S.get(BASE+path,timeout=25); r.raise_for_status(); return r.json()
def load(path, default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return default
def save(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")
def done(e):
    s=e.get("status") or {}; return s.get("type") in {"finished","ended"} or s.get("code")==100
def score(e):
    try:return float((e.get("homeScore") or {}).get("current")),float((e.get("awayScore") or {}).get("current"))
    except (TypeError,ValueError):return None
def season(tid):
    try:
        rows=get(f"/unique-tournament/{tid}/seasons").get("seasons") or []
        return rows[0] if rows else None
    except Exception:return None

def events_for(tid):
    se=season(tid)
    if not se:return [],None
    out=[]; seen=set()
    for page in range(2):
        for direction in ("next","last"):
            try: payload=get(f"/unique-tournament/{tid}/season/{se['id']}/events/{direction}/{page}")
            except Exception: continue
            for e in payload.get("events") or []:
                eid=str(e.get("id") or "")
                if eid and eid not in seen:seen.add(eid);out.append(e)
    return out,se

def prob(x):
    try:
        x=float(x);return 1/x if x>1 else None
    except (TypeError,ValueError,ZeroDivisionError):return None
def norm(a):
    a=[max(.0001,float(x)) for x in a];t=sum(a);return [x/t for x in a]
def markets(payload):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            c=x.get("choices"); n=str(x.get("marketName") or x.get("name") or "")
            if isinstance(c,list) and c:out.append((n,c))
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(payload);return out

def odds(eid):
    try:p=get(f"/event/{eid}/odds/1/all")
    except Exception:return {"moneyline":None,"total":None,"spread":None}
    r={"moneyline":None,"total":None,"spread":None}
    for name,choices in markets(p):
        n=name.lower(); parsed=[(str(c.get("name") or ""),prob(c.get("decimalValue"))) for c in choices]
        parsed=[x for x in parsed if x[1]]
        if r["total"] is None and any(k in n for k in ("total","over/under","over under")):
            rows=[]
            for label,p in parsed:
                m=re.search(r"(over|under)\s*([0-9]+(?:\.[0-9])?)",label,re.I)
                if m:rows.append((m.group(1).lower(),float(m.group(2)),p))
            for line in sorted({x[1] for x in rows}):
                ov=next((p for side,l,p in rows if side=="over" and l==line),None);un=next((p for side,l,p in rows if side=="under" and l==line),None)
                if ov and un:
                    ov,un=norm([ov,un]);r["total"]={"line":line,"over":round(ov,4),"under":round(un,4),"source":"SofaScore odds"};break
        if r["moneyline"] is None and ("winner" in n or "moneyline" in n or n in {"1x2","full time"}):
            h=next((p for label,p in parsed if label.lower() in {"1","home"}),None);a=next((p for label,p in parsed if label.lower() in {"2","away"}),None)
            if h and a:
                h,a=norm([h,a]);r["moneyline"]={"home":round(h,4),"away":round(a,4),"source":"SofaScore odds"}
        if r["spread"] is None and ("handicap" in n or "spread" in n) and len(parsed)>=2:r["spread"]={"choices":parsed[:2],"source":"SofaScore odds"}
    return r

def form(rows):
    f={}
    for e in sorted(rows,key=lambda x:x.get("startTimestamp",0)):
        if not done(e):continue
        s=score(e)
        if not s:continue
        for key,i,j in (("homeTeam",0,1),("awayTeam",1,0)):
            t=e.get(key) or {};tid=str(t.get("id") or "")
            if not tid:continue
            b=f.setdefault(tid,{"wins":[],"totals":[]});b["wins"].append(int(s[i]>s[j]));b["totals"].append(s[0]+s[1])
    for b in f.values():
        b["wins"]=b["wins"][-8:];b["totals"]=b["totals"][-8:];b["win_rate"]=sum(b["wins"])/len(b["wins"]) if b["wins"] else .5;b["avg_total"]=sum(b["totals"])/len(b["totals"]) if b["totals"] else None
    return f

def predict(e,league,se,f):
    h=e.get("homeTeam") or {};a=e.get("awayTeam") or {};hn,an=h.get("name"),a.get("name")
    if not hn or not an or hn.lower()==an.lower():return None
    hf=f.get(str(h.get("id")),{});af=f.get(str(a.get("id")),{});hfwr=hf.get("win_rate",.5);afwr=af.get("win_rate",.5);m=odds(str(e.get("id")))
    hp=.92*m["moneyline"]["home"]+.08*(.5+.5*(hfwr-afwr)) if m["moneyline"] else .525+.22*(hfwr-afwr);hp=max(.08,min(.92,hp));ap=1-hp
    ft=(hf.get("avg_total")+af.get("avg_total"))/2 if hf.get("avg_total") is not None and af.get("avg_total") is not None else None;t=m["total"]
    if t:
        fs=.5 if ft is None else 1/(1+math.exp(-(ft-t["line"])/8));ov=max(.05,min(.95,.9*t["over"]+.1*fs));un=1-ov;td={**t,"over":round(ov,4),"under":round(un,4),"pick":"over" if ov>un else "under","expected_total":round(t["line"]+(ov-.5)*8,1)}
    else:td={"line":None,"over":.5,"under":.5,"pick":None,"expected_total":round(ft,1) if ft is not None else None,"source":"No published total odds"}
    td["settlement"]="Official final score including overtime"
    q=sum(bool(x) for x in (m["moneyline"],m["total"],m["spread"],len(hf.get("wins",[]))>=3,len(af.get("wins",[]))>=3));conf=.5+(max(hp,ap)-.5)*(.92 if q>=3 else .8)
    return {"sport":"basketball","league":league,"source":"SofaScore","event_id":str(e.get("id")),"season":se.get("name") if se else None,"start_time":datetime.fromtimestamp(e.get("startTimestamp",0),timezone.utc).isoformat(),"player_1":hn,"player_2":an,"probabilities":{"p1":round(hp,4),"p2":round(ap,4)},"pick":"p1" if hp>=ap else "p2","confidence":round(conf,4),"markets":{"moneyline":m["moneyline"],"total_ou":td,"spread":m["spread"]},"form":{"p1_win_rate":round(hfwr,3),"p2_win_rate":round(afwr,3),"p1_sample":len(hf.get("wins",[])),"p2_sample":len(af.get("wins",[]))},"signal_quality":{"components":q,"max_components":5,"moneyline_available":bool(m["moneyline"]),"total_available":bool(m["total"]),"spread_available":bool(m["spread"])},"model":"SofaScore odds + recent form" if m["moneyline"] else "recent form + home edge","rules_note":"Basketball total settlement uses the official final score, including overtime."}

def settle(history):
    for p in history:
        if p.get("settled"):continue
        try:
            e=get(f"/event/{p['event_id']").get("event",{})
            if not done(e):continue
            s=score(e)
            if not s:continue
            h,a=s;p["final_score"]=[h,a];p["actual_pick"]="p1" if h>a else "p2";p["correct"]=p["pick"]==p["actual_pick"];line=p.get("markets",{}).get("total_ou",{}).get("line")
            if line is not None:
                total=h+a;p["actual_total"]=total;p["actual_total_pick"]="over" if total>line else "under" if total<line else "push";p["total_correct"]=p.get("markets",{}).get("total_ou",{}).get("pick") in {"over","under"} and p["actual_total_pick"]==p["markets"]["total_ou"]["pick"]
            p["settled"]=True;p["settled_at"]=datetime.now(timezone.utc).isoformat()
        except Exception:continue
    return history

def main():
    predictions=[];src=[];now=datetime.now(timezone.utc).timestamp()
    for league,tid in TOURNAMENTS.items():
        ev,se=events_for(tid);f=form(ev);accepted=0
        for e in ev:
            if done(e) or (e.get("startTimestamp") or 0)<now-3600:continue
            p=predict(e,league,se or {},f)
            if p:predictions.append(p);accepted+=1
        src.append({"competition":league,"tournament_id":tid,"season":se.get("name") if se else None,"events_seen":len(ev),"events":accepted})
    history=load(DATA/"basketball_history.json",[]);known={(str(x.get("event_id")),x.get("league")) for x in history}
    for p in predictions:
        if (p["event_id"],p["league"]) not in known:history.append(p)
    history=settle(history);settled=[x for x in history if x.get("settled")];tot=[x for x in settled if x.get("total_correct") is not None]
    save(DATA/"basketball_predictions.json",sorted(predictions,key=lambda x:x["start_time"]));save(DATA/"basketball_history.json",history);save(DATA/"basketball_accuracy.json",{"updated_at":datetime.now(timezone.utc).isoformat(),"settled":len(settled),"correct":sum(bool(x.get("correct")) for x in settled),"accuracy":sum(bool(x.get("correct")) for x in settled)/len(settled) if settled else None,"total_ou_settled":len(tot),"total_ou_correct":sum(bool(x.get("total_correct")) for x in tot),"total_ou_accuracy":sum(bool(x.get("total_correct")) for x in tot)/len(tot) if tot else None})
    status=load(DATA/"pipeline_status.json",{});status.update({"basketball_count":len(predictions),"basketball_settled":len(settled),"basketball_sources":src,"basketball_source_status":"SofaScore public JSON","basketball_updated_at":datetime.now(timezone.utc).isoformat(),"basketball_rules":"Totals settle on official final score including overtime"});save(DATA/"pipeline_status.json",status)
    print(f"SofaScore basketball: {len(predictions)} predictions; sources={src}; settled={len(settled)}")

if __name__=="__main__":main()
