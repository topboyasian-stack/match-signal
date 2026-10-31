#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source=fs.readFileSync('virtual-lab-app.js','utf8');
function block(startMarker,endMarker){
  const start=source.indexOf(startMarker);
  assert.notEqual(start,-1,'missing source marker: '+startMarker);
  const end=source.indexOf(endMarker,start);
  assert.notEqual(end,-1,'missing end marker: '+endMarker);
  return source.slice(start,end);
}
const gateSource=block('function recentProductPerformanceGate(product){','\nfunction qualifiesResearchPick(c){');
const researchSource=block('function qualifiesResearchPick(c){','\nfunction qualifiesBaseResearchPick(c,e){');
const baseSource=block('function qualifiesBaseResearchPick(c,e){','\nfunction competitionKey(value){');
function makeState(recent,generatedAt=new Date().toISOString()){
  return {historyLoaded:true,modelGate:true,deskLearning:{
    generated_at:generatedAt,
    by_product:recent||{}
  }};
}
function gateFor(state){
  return new Function('state',gateSource+'; return recentProductPerformanceGate;')(state);
}
function qualifiersFor(state,gate){
  return new Function('state','recentProductPerformanceGate','isModelQualifiedResearchEvent','isModelQualifiedOU',
    researchSource+'\n'+baseSource+'\nreturn {qualifiesResearchPick,qualifiesBaseResearchPick};'
  )(state,gate,()=>true,()=>true);
}
const goodCandidate={marketType:'ou',eventProduct:'efootball_gt',product:'efootball_gt',calibratedProb:0.8,bookImplied:0.65,calibrationN:50};
const gtBad=makeState({efootball_gt:{recent_window:{n:50,accuracy:0.50}}});
const gtGate=gateFor(gtBad);
const gt=gtGate('efootball_gt');
assert.equal(gt.blocked,true);
assert.equal(gt.reason,'RECENT_ACCURACY_BELOW_55_PERCENT');
assert.equal(gt.n,50);
assert.equal(gt.accuracy,0.50);
const gtQualifiers=qualifiersFor(gtBad,gtGate);
assert.equal(gtQualifiers.qualifiesResearchPick(goodCandidate),false);
assert.equal(gtQualifiers.qualifiesBaseResearchPick(goodCandidate,{product:'efootball_gt'}),false);

const adriaticState=makeState({efootball_gt:{recent_window:{n:50,accuracy:0.50}}});
assert.equal(gateFor(adriaticState)('efootball_adriatic').blocked,true);
assert.equal(gateFor(adriaticState)('efootball_adriatic').reason,'RECENT_PERFORMANCE_EVIDENCE_INSUFFICIENT');

const vfootballState=makeState({vfootball:{recent_window:{n:50,accuracy:0.40}}});
assert.equal(gateFor(vfootballState)('vfootball').blocked,false);

const gtRecovered=makeState({efootball_gt:{recent_window:{n:50,accuracy:0.56}}});
const recoveredGate=gateFor(gtRecovered);
assert.equal(recoveredGate('efootball_gt').blocked,false);
const recoveredQualifiers=qualifiersFor(gtRecovered,recoveredGate);
assert.equal(recoveredQualifiers.qualifiesResearchPick(goodCandidate),true);
assert.equal(recoveredQualifiers.qualifiesBaseResearchPick(goodCandidate,{product:'efootball_gt'}),true);

const lowSample=makeState({efootball_gt:{recent_window:{n:29,accuracy:0.70}}});
assert.equal(gateFor(lowSample)('efootball_gt').reason,'RECENT_PERFORMANCE_EVIDENCE_INSUFFICIENT');
const stale=makeState({efootball_gt:{recent_window:{n:50,accuracy:0.70}}},new Date(Date.now()-61*60*1000).toISOString());
assert.equal(gateFor(stale)('efootball_gt').reason,'RECENT_PERFORMANCE_DATA_UNAVAILABLE');
const missing=makeState(null);
assert.equal(gateFor(missing)('efootball_gt').blocked,true);

assert.ok(source.includes("const DESK_LEARNING='/data/efootball_desk_learning.json'"));
assert.ok(source.includes('await loadDeskLearning()'));
assert.ok(source.includes('const learningChanged=await loadDeskLearning()'));
assert.ok(source.includes('state.builder=(state.builder||[]).filter(p=>!recentProductPerformanceGate(p?.product).blocked)'));
assert.ok(source.includes('candidate_status:status,recent_performance:recentPerformance'));
assert.ok(source.includes("p.candidate_status==='RECENT_PERFORMANCE_GUARD'"));
assert.ok(source.includes('EFOOTBALL QUALIFICATION PAUSED'));
assert.ok(source.includes('recentGate.blocked'));
console.log('Virtual Lab eFootball recent-performance guard: 10 assertions passed.');
