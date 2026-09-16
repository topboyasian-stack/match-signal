"""Build an isolated football performance ledger from settled prediction history. PAPER ONLY."""
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
def load(name, default):
    try:return json.loads((DATA/name).read_text(encoding='utf-8'))
    except Exception:return default
rows=[p for p in load('prediction_history.json',[]) if str(p.get('sport','')).lower()=='football' and p.get('settled')]
correct=sum(bool(p.get('correct')) for p in rows)
leagues={}
for p in rows:
    l=p.get('league') or 'Unknown'; g=leagues.setdefault(l,{'settled':0,'correct':0});g['settled']+=1;g['correct']+=bool(p.get('correct'))
for g in leagues.values():g['accuracy']=round(g['correct']/g['settled'],4) if g['settled'] else 0
buckets=[]
for label,lo,hi in [('50-55%',.50,.55),('55-60%',.55,.60),('60-65%',.60,.65),('65-70%',.65,.70),('70%+',.70,1.01)]:
    x=[p for p in rows if lo<=float(p.get('confidence',0))<hi];c=sum(bool(p.get('correct')) for p in x);buckets.append({'label':label,'settled':len(x),'correct':c,'accuracy':round(c/len(x),4) if x else None})
recent=sorted(rows,key=lambda p:p.get('settled_at') or p.get('start_time') or '',reverse=True)[:50]
(DATA/'football_performance.json').write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),'status':'PAPER_RESEARCH_ONLY','settled':len(rows),'correct':correct,'accuracy':round(correct/len(rows),4) if rows else 0,'by_league':leagues,'confidence_buckets':buckets,'recent_settled':recent},indent=2,ensure_ascii=False),encoding='utf-8')
print(f'Football performance: {correct}/{len(rows)} = {correct/len(rows):.2%}' if rows else 'Football performance: no settled rows')
