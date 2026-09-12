"""Structural QA + empirical risk report for Match Signal."""
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; OUT=ROOT/'qa'/'report.json'

def load(name,default):
    try:return json.loads((DATA/name).read_text(encoding='utf-8'))
    except Exception:return default

def ok_prob(v):
    try:return 0<=float(v)<=1
    except Exception:return False

def valid_market_probs(q,sport):
    vals=[q.get('p1'),q.get('draw'),q.get('p2')] if sport=='football' else [q.get('p1'),q.get('p2')]
    return all(ok_prob(v) for v in vals) and abs(sum(float(v) for v in vals)-1)<=.02

def check(rows,label):
    issues=[]; seen=set()
    for i,p in enumerate(rows):
        sport=str(p.get('sport','')).lower(); key=(str(p.get('event_id')),str(p.get('player_1')),str(p.get('player_2')))
        if key in seen: issues.append(f'{label}: duplicate fixture at index {i}')
        seen.add(key)
        if not p.get('player_1') or not p.get('player_2'): issues.append(f'{label}: missing name at index {i}')
        if not valid_market_probs(p.get('probabilities') or {},sport): issues.append(f'{label}: invalid probabilities at index {i}')
        if not ok_prob(p.get('confidence')): issues.append(f'{label}: invalid confidence at index {i}')
        if 'Player 1' in str(p.get('player_1')) or 'Player 2' in str(p.get('player_2')): issues.append(f'{label}: placeholder name at index {i}')
    return issues

def main():
    fb=load('predictions.json',[]); bb=load('basketball_predictions.json',[]); status=load('pipeline_status.json',{}); risk=load('risk_gate.json',{})
    issues=check(fb,'football/tennis')+check(bb,'basketball')
    sources=status.get('basketball_sources') or []
    warnings=[f"No accepted events for {s.get('competition','unknown')}" for s in sources if s.get('events',0)==0]
    empirical=risk.get('metrics',{})
    live_approved=any(v.get('live_eligible') for v in (risk.get('gate') or {}).values())
    score=max(0,100-min(60,len(issues)*5)-min(20,len(warnings)*10))
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'status':'PASS' if not issues else 'FAIL','qa_score':score,'live_trading_approved':bool(live_approved),'testing_mode':risk.get('mode','PAPER_ONLY'),'empirical_metrics':empirical,'prediction_counts':{'football_tennis':len(fb),'basketball':len(bb)},'issues':issues[:100],'warnings':warnings,'checks':{'probabilities_valid':not any('invalid probabilities' in x for x in issues),'confidence_valid':not any('invalid confidence' in x for x in issues),'duplicates_checked':True,'placeholder_names_checked':True,'basketball_source_coverage_checked':True,'empirical_risk_gate_checked':bool(risk)}}
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(report,indent=2))
    if issues: raise SystemExit(1)
if __name__=='__main__':main()
