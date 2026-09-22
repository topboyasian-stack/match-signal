/* Match Signal Virtual Lab — live data + research analysis */
(function(){
'use strict';

const LIVE_API='https://match-signal.pages.dev/api/sportybet-virtual';
const LIVE_MARKETS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
const SNAPSHOT='./data/virtual_lab_live.json';
const LIVE_REFRESH_MS=30000;
const UI_BUILD='20260922-v26';
const HISTORY='./api/virtual-lab-history';
const HISTORY_FALLBACK='./data/virtual_lab_history.json';
const MODEL_EVAL='./data/virtual_lab_model_eval.json';
const ELIGIBILITY='./data/virtual_lab_eligibility.json';
const PARTICIPANT_PROFILES='./data/virtual_lab_participant_profiles.json';
const CONFIRMED_WATCH='./data/virtual_lab_confirmed_participants.json';
const state={rows:[],filtered:[],live:[],liveMode:'none',liveUpdated:null,picks:[],builder:[],historyLoaded:false,modelRows:[],modelEvents:[],modelGate:false,modelHoldout:null,modelEvaluation:null,participantProfiles:null,confirmedWatch:null,eligibility:{eligible_competitions:['Esoccer H2H GG League','Europa League','Volta Premier League'],eligible_ou_lines:[3.5,4.5],experimental_ou_lines:[1.5],priority_ou_lines:[1.5,3.5,4.5],eligible_markets:['ou']},predictionCache:new Map()};

const $=id=>document.getElementById(id);
const esc=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML};
const num=v=>{const n=Number(String(v??'').replace('%',''));return Number.isFinite(n)?n:null};
const date=v=>{const d=new Date(v);return isNaN(d.getTime())?String(v||'—'):d.toLocaleString()};
const fmtPct=v=>v==null?'—':(v*100).toFixed(1)+'%';
const fmtNum=v=>v==null?'—':Number(v).toFixed(3);

function participantIdentity(value){
  const s=String(value??'').trim();
  if(!s)return '';
  const m=s.match(/\\(([^()]+)\\)\\s*$/);
  return m&&m[1].trim()?m[1].trim():s;
}
function participantIdentityKey(value){return participantIdentity(value).trim().toLowerCase();}

function normalize(r){
  const x={...r};
  x.product=String(x.product||'other').toLowerCase().trim();
  x.market=String(x.market||'other').toLowerCase().trim();
  x.timestamp=x.timestamp||x.date||x.datetime||'';
  x.odds=num(x.odds);
  x.result=String(x.result??'').trim().toLowerCase();
  x.selection=String(x.selection??'').trim().toLowerCase();
  if(x.win===''||x.win==null){
    if(x.selection&&x.result)x.win=x.selection===x.result;
    else x.win=null;
  }else x.win=String(x.win).toLowerCase()==='true'||String(x.win)==='1';
  x.model_prob=num(x.model_prob||x.probability);
  return x;
}

function parseCSV(text){
  const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).filter(Boolean);
  if(!lines.length)return [];
  const parseLine=line=>{
    const out=[];let cur='',quote=false;
    for(let i=0;i<line.length;i++){
      const c=line[i];
      if(c==='"'){if(quote&&line[i+1]==='"'){cur+='"';i++;}else quote=!quote}
      else if(c===','&&!quote){out.push(cur);cur=''}
      else cur+=c;
    }
    out.push(cur);return out;
  };
  const headers=parseLine(lines[0]).map(h=>h.trim());
  return lines.slice(1).map(line=>{const vals=parseLine(line),o={};headers.forEach((h,i)=>o[h]=vals[i]??'');return normalize(o)});
}

async function parseFile(file){
  const text=await file.text();
  if(file.name.toLowerCase().endsWith('.json')){
    const data=JSON.parse(text);
    const arr=Array.isArray(data)?data:(Array.isArray(data.rows)?data.rows:[]);
    return arr.map(normalize);
  }
  return parseCSV(text);
}

function stats(rows){
  const valid=rows.filter(r=>typeof r.win==='boolean');
  const wins=valid.filter(r=>r.win).length;
  const priced=valid.filter(r=>r.odds&&r.odds>=1);
  let roi=null;
  if(priced.length)roi=priced.reduce((s,r)=>s+(r.win?(r.odds-1):-1),0)/priced.length;
  return {n:rows.length,valid:valid.length,wins,rate:valid.length?wins/valid.length:null,roi};
}

function eventCluster(rows){
  const groups=new Map();
  rows.filter(r=>typeof r.win==='boolean').forEach(r=>{
    const id=String(r.event_id||r.eventId||'')||String(r.timestamp||'')+'|'+String(r.product||'');
    const key=id+'|'+String(r.timestamp||'');
    const prev=groups.get(key);
    if(!prev){groups.set(key,r);return;}
    // Prefer a single winner observation as the event-level representative.
    if(prev.market!=='winner'&&r.market==='winner')groups.set(key,r);
  });
  return [...groups.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
}
function split(rows){
  const ordered=[...rows].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
  const groups=[];
  const seen=new Set();
  ordered.forEach(r=>{
    const key=String(r.event_id||r.eventId||'')+'|'+String(r.timestamp||'');
    if(!seen.has(key)){seen.add(key);groups.push(key);}
  });
  const pct=Number($('split').value),cut=Math.floor(groups.length*pct);
  const trainKeys=new Set(groups.slice(0,cut)),train=[],test=[];
  ordered.forEach(r=>{
    const key=String(r.event_id||r.eventId||'')+'|'+String(r.timestamp||'');
    (trainKeys.has(key)?train:test).push(r);
  });
  return {train,test,groups:groups.length};
}

function seq(rows){
  const v=eventCluster(rows);
  if(v.length<3)return null;
  const afterWin=[],afterLoss=[];
  for(let i=1;i<v.length;i++){(v[i-1].win?afterWin:afterLoss).push(v[i].win)}
  const p=a=>a.length?a.filter(Boolean).length/a.length:null;
  const a=p(afterWin),b=p(afterLoss);
  return {n:v.length,afterWin:a,afterLoss:b,delta:a!=null&&b!=null?a-b:null};
}

function productTable(rows){
  const groups={};
  rows.forEach(r=>(groups[r.product]??=[]).push(r));
  const data=Object.entries(groups).map(([product,arr])=>({product,all:stats(arr),oos:stats(split(arr).test)}))
    .sort((a,b)=>(b.oos.rate??-1)-(a.oos.rate??-1));
  if(!data.length)return '<div class="empty">No completed win/loss observations in the selected data.</div>';
  return '<table><thead><tr><th>Product</th><th>Rounds</th><th>Win rate</th><th>OOS rate</th><th>Paper ROI</th></tr></thead><tbody>'+
    data.map(x=>'<tr><td>'+esc(x.product)+'</td><td>'+x.all.valid+'</td><td>'+fmtPct(x.all.rate)+'</td><td>'+fmtPct(x.oos.rate)+'</td><td>'+fmtPct(x.oos.roi)+'</td></tr>').join('')+
    '</tbody></table>';
}

function wilsonLower(successes,n,z=1.96){
  if(!n)return null;
  const phat=successes/n,denom=1+z*z/n,centre=phat+z*z/(2*n),spread=z*Math.sqrt((phat*(1-phat)+z*z/(4*n))/n);
  return (centre-spread)/denom;
}

function bestCandidate(rows,testRows){
  const groups={};
  rows.filter(r=>typeof r.win==='boolean'&&r.selection).forEach(r=>{
    const key=[r.product,r.market,r.selection].join('|');
    (groups[key]??=[]).push(r);
  });
  const candidates=[];
  for(const [key,trainRows] of Object.entries(groups)){
    const [product,market,selection]=key.split('|');
    if(trainRows.length<60)continue;
    const test=testRows.filter(r=>r.product===product&&r.market===market&&r.selection===selection&&typeof r.win==='boolean'&&r.odds!=null);
    if(test.length<30)continue;
    const tr=stats(trainRows),te=stats(test),lower=wilsonLower(te.wins,te.valid);
    const priced=trainRows.filter(r=>r.odds!=null&&r.odds>=1);
    const minPrice=priced.length?Math.max(1.01,Math.min(...priced.map(r=>r.odds))):99;
    if(te.rate==null||te.roi==null||te.rate<.80||lower<.72||te.roi<=0)continue;
    candidates.push({product,market,selection,train:tr,test:te,lower,minPrice});
  }
  candidates.sort((a,b)=>(b.test.roi-a.test.roi)||(b.lower-a.lower));
  return candidates[0]||null;
}

function statCard(title,value){return '<div class="resultStat"><small>'+esc(title)+'</small><b>'+esc(value)+'</b></div>'}

function updateResearchConclusion(best){
  const el=$('researchConclusion');
  if(!best){
    el.className='conclusion negative';
    el.innerHTML='<div class="gateTitle">NO SIGNAL</div><p>No candidate currently clears the minimum sample, unseen-test, lower-confidence and positive-ROI gates.</p><p class="muted">Do not choose a game because it is on a streak. Wait for validated evidence.</p>';
    return;
  }
  el.className='conclusion positive';
  el.innerHTML='<div class="gateTitle">RESEARCH-QUALIFIED</div>'+
    '<p><strong>Product:</strong> '+esc(best.product)+' · <strong>Market:</strong> '+esc(best.market)+' · <strong>Selection:</strong> '+esc(best.selection)+'</p>'+
    '<div class="resultGrid">'+statCard('Discovery n',best.train.valid)+statCard('OOS n',best.test.valid)+statCard('OOS win rate',fmtPct(best.test.rate))+statCard('OOS ROI',fmtPct(best.test.roi))+'</div>'+
    '<p><strong>Instruction:</strong> only use this exact product/market/selection when the live price is at least <strong>'+best.minPrice.toFixed(2)+'</strong> and the market definition matches the research dataset.</p>'+
    '<p class="muted">This is a paper-research signal, not a guarantee. Replicate it on another untouched period before treating it as reproducible.</p>';
}

function analyze(){
  const rows=state.filtered,s=stats(rows),parts=split(rows),oos=stats(parts.test),sq=seq(rows);
  $('rounds').textContent=String(s.valid);
  $('winRate').textContent=fmtPct(s.rate);
  $('oosRate').textContent=fmtPct(oos.rate);
  $('roi').textContent=fmtPct(s.roi);
  $('seqDelta').textContent=fmtPct(sq&&sq.delta);
  $('fingerprint').className='tableWrap';
  $('fingerprint').innerHTML=productTable(rows);
  $('fingerprintStatus').textContent=new Set(rows.map(r=>r.product).filter(Boolean)).size+' product families';
  if(sq){
    $('sequence').className='tableWrap';
    $('sequence').innerHTML='<table><thead><tr><th>Observation</th><th>Value</th></tr></thead><tbody>'+
      '<tr><td>Independent event groups</td><td>'+sq.n+'</td></tr><tr><td>P(win next | previous win)</td><td>'+fmtPct(sq.afterWin)+'</td></tr><tr><td>P(win next | previous loss)</td><td>'+fmtPct(sq.afterLoss)+'</td></tr><tr><td>Conditional delta</td><td>'+fmtPct(sq.delta)+'</td></tr></tbody></table>'+
      '<p class="muted">A non-zero delta is only an investigation trigger. It must survive unseen testing before a rule is trusted.</p>';
  }else $('sequence').innerHTML='Need at least 3 settled observations.';
  $('oosLabel').textContent=parts.test.length+' rows · '+(parts.groups||0)+' event groups';
  if(parts.test.length){
    $('oos').className='tableWrap';
    $('oos').innerHTML='<table><thead><tr><th>Metric</th><th>Discovery</th><th>Unseen test</th></tr></thead><tbody>'+
      '<tr><td>Settled rows</td><td>'+stats(parts.train).valid+'</td><td>'+oos.valid+'</td></tr>'+
      '<tr><td>Win rate</td><td>'+fmtPct(stats(parts.train).rate)+'</td><td>'+fmtPct(oos.rate)+'</td></tr>'+
      '<tr><td>Paper ROI</td><td>'+fmtPct(stats(parts.train).roi)+'</td><td>'+fmtPct(oos.roi)+'</td></tr></tbody></table>';
  }else $('oos').innerHTML='Need more observations for an out-of-sample test.';
  const candidate=bestCandidate(rows,parts.test);
  const gate=rows.length<100?'INSUFFICIENT DATA':(oos.valid<30?'PAPER WATCH':(candidate?'RESEARCH THRESHOLD REACHED':'NO VERIFIED SIGNAL'));
  const cls=gate==='RESEARCH THRESHOLD REACHED'?'positive':gate==='PAPER WATCH'?'warning':'negative';
  $('signalGate').className='gate '+cls;
  $('signalGate').innerHTML='<div class="gateTitle">'+gate+'</div><div>'+(
    gate==='INSUFFICIENT DATA'?'Collect more completed observations.':
    gate==='PAPER WATCH'?'The unseen sample is too small for a serious selection rule.':
    gate==='RESEARCH THRESHOLD REACHED'?'A candidate crossed the research threshold; read the Research conclusion before acting.':
    'Current observations do not support an 80% out-of-sample candidate.'
  )+'</div>';
  updateResearchConclusion(candidate);
}

function classifyEvent(tournament,category,home,away){
  const blob=(tournament+' '+category+' '+home+' '+away).toLowerCase();
  if(blob.includes('eadriatic'))return'efootball_adriatic';
  if(blob.includes('gt sports league')||blob.includes('gt leagues')||blob.includes('efootball')||blob.includes('e soccer')||blob.includes('esoccer'))return'efootball_gt';
  if(blob.includes('simulated reality')||/\bsrl\b/i.test(blob))return'srl';
  if(blob.includes('virtual football'))return'vfootball';
  if(blob.includes('zoom')||blob.includes('turbo'))return'zoom';
  if(blob.includes('virtual')||blob.includes('simulated'))return'other';
  return null;
}

function lineFromSpecifier(value){
  const m=String(value||'').match(/(?:total|line)=([0-9]+(?:\.[0-9]+)?)/i);
  return m?Number(m[1]):null;
}

function normalizeLiveEvent(event,tournament,category){
  const home=String(event.team_1||event.homeTeamName||event.home||'');
  const away=String(event.team_2||event.awayTeamName||event.away||'');
  const homeParticipant=participantIdentity(event.participant_1||event.homeParticipant||event.homePlayer||event.homeCompetitor||'');
  const awayParticipant=participantIdentity(event.participant_2||event.awayParticipant||event.awayPlayer||event.awayCompetitor||'');
  const product=classifyEvent(tournament,category,home,away);
  if(!product)return null;
  const markets=(event.markets||[]).map(m=>{
    const outcomes=(m.outcomes||[]).map(o=>{
      const odds=num(o.odds);
      return odds!=null?{id:String(o.id||''),name:String(o.desc||o.name||''),odds,active:o.isActive!==false}:null;
    }).filter(Boolean);
    if(!outcomes.length)return null;
    return {id:String(m.id||''),name:String(m.desc||m.name||m.title||''),specifier:m.specifier,line:lineFromSpecifier(m.specifier),status:m.status,outcomes,lastOddsChangeTime:m.lastOddsChangeTime};
  }).filter(Boolean);
  let start=null;
  const ms=Number(event.estimateStartTime);
  if(Number.isFinite(ms)&&ms>0)start=new Date(ms).toISOString();
  return {product,competition:String(tournament||'Unclassified'),category:String(category||''),event_id:String(event.eventId||''),home,away,participant_1:homeParticipant,participant_2:awayParticipant,participant_identity_source:event.participant_identity_source||((homeParticipant||awayParticipant)?'event_metadata_or_explicit_name':null),identity_verified:!!(homeParticipant&&awayParticipant),start_time:start,match_status:event.matchStatus,markets};
}

function matchesMarket(market,chosen){
  if(chosen==='all')return true;
  const x=(market.name||'').toLowerCase();
  if(chosen==='1x2'||chosen==='winner')return market.id==='1'||market.id==='186'||x.includes('winner')||x==='win'||x.includes('1x2')||x==='match result';
  if(chosen==='ou')return market.id==='18'||market.id==='189'||x.includes('total');
  if(chosen==='btts')return market.id==='29'||x.includes('both teams')||x.includes('btts');
  if(chosen==='handicap')return market.id==='14'||x.includes('handicap');
  return true;
}

function shortOutcome(name){
  const s=String(name||'').trim();
  if(/over/i.test(s))return'Over';
  if(/under/i.test(s))return'Under';
  if(/^home$/i.test(s))return'1';
  if(/^draw$/i.test(s))return'X';
  if(/^away$/i.test(s))return'2';
  return s.length>24?s.slice(0,22)+'…':s;
}


function marketLabel(m){
  const name=String(m&&m.name||'').trim();
  const line=m&&m.line!=null?' '+m.line:'';
  return (name||'Market')+line;
}
function outcomeCode(m,o){
  const name=String(o&&o.name||'').trim(),lower=name.toLowerCase();
  const line=m&&m.line!=null?String(m.line):'';
  if(lower.indexOf('over')===0)return 'O'+line;
  if(lower.indexOf('under')===0)return 'U'+line;
  if(lower==='home')return '1';
  if(lower==='draw')return 'X';
  if(lower==='away')return '2';
  return name;
}
function clamp01(v){return Math.max(0.0005,Math.min(0.9995,Number(v)||0.5));}
function poissonOver(lambda,line){
  lambda=Math.max(0.05,Math.min(30,Number(lambda)||5));
  const k=Math.floor(Number(line));
  if(!Number.isFinite(k))return null;
  let pmf=Math.exp(-lambda),cdf=pmf;
  if(k>=1){
    for(let i=1;i<=k;i++){pmf*=lambda/i;cdf+=pmf;}
  }
  return clamp01(1-cdf);
}
function fitLambdaFromLadder(points){
  const usable=(points||[]).filter(p=>Number.isFinite(p.line)&&Number.isFinite(p.overProb)&&p.line>=0);
  if(!usable.length)return null;
  const loss=lambda=>usable.reduce((s,p)=>{const d=poissonOver(lambda,p.line)-p.overProb;return s+d*d;},0)/usable.length;
  let best={lambda:5,loss:Infinity};
  for(let l=0.25;l<=20;l+=0.05){const z=loss(l);if(z<best.loss)best={lambda:l,loss:z};}
  for(let l=Math.max(0.1,best.lambda-0.1);l<=Math.min(25,best.lambda+0.1);l+=0.005){const z=loss(l);if(z<best.loss)best={lambda:l,loss:z};}
  return {lambda:best.lambda,rmse:Math.sqrt(best.loss),n:usable.length,points:usable};
}
function marketOverPoint(m){
  if(!m||m.line==null)return null;
  const calc=calculateMarket(m);
  if(!calc)return null;
  const over=calc.market.outcomes.find(o=>/^over/i.test(String(o.name||'')));
  if(!over)return null;
  const fair=calc.market.outcomes.map(o=>({o,p:(1/Number(o.odds))})).reduce((s,x)=>s+x.p,0);
  return {line:Number(m.line),overProb:(1/Number(over.odds))/fair};
}
function eventKey(r){return String(r.event_id||r.eventId||'')+'|'+String(r.timestamp||'');}
function scoreTotal(r){
  const m=String(r.score||'').match(/(\d+)\s*[:\-]\s*(\d+)/);
  return m?Number(m[1])+Number(m[2]):null;
}
function historicalOUEvents(rows){
  const groups=new Map();
  rows.filter(r=>r.market==='ou'&&r.event_id&&r.timestamp).forEach(r=>{
    const key=eventKey(r);
    let g=groups.get(key);
    if(!g){g={key,event_id:r.event_id,timestamp:r.timestamp,product:r.product,home:participantIdentity(r.participant_1||r.home||''),away:participantIdentity(r.participant_2||r.away||''),rows:[],total:scoreTotal(r)};groups.set(key,g);}
    g.rows.push(r);
    if(g.total==null)g.total=scoreTotal(r);
  });
  return [...groups.values()].map(g=>{
    const points=[];
    g.rows.forEach(r=>{
      if(r.line==null||r.model_prob==null)return;
      const p=String(r.selection||'').toUpperCase().startsWith('U')?1-Number(r.model_prob):Number(r.model_prob);
      points.push({line:Number(r.line),overProb:clamp01(p)});
    });
    const dedup={};
    points.forEach(p=>dedup[p.line]=dedup[p.line]==null?p:({line:p.line,overProb:(dedup[p.line].overProb+p.overProb)/2}));
    const ladder=fitLambdaFromLadder(Object.values(dedup));
    return Object.assign(g,{ladder});
  }).filter(g=>g.total!=null&&g.ladder);
}
function productPrior(events,product,line,cutoff){
  const eligible=(events||[]).filter(e=>e.product===product&&e.total!=null&&(!cutoff||new Date(e.timestamp).getTime()<cutoff));
  const n=eligible.length;
  if(!n)return {prob:null,n:0};
  const over=eligible.filter(e=>e.total>line).length;
  const under=eligible.filter(e=>e.total<line).length;
  const pushes=n-over-under;
  const decisive=over+under;
  if(!decisive)return {prob:null,n:0};
  // Beta(2,2) shrinkage prevents tiny product/line samples from creating extreme probabilities.
  return {prob:(over+2)/(decisive+4),n:decisive,pushes};
}
function recurrenceEvidence(events,event,line){
  const cutoff=new Date(event?.timestamp||0).getTime(),product=event?.product||'',home=participantIdentityKey(event?.participant_1||event?.home||''),away=participantIdentityKey(event?.participant_2||event?.away||''),target=Number(line);
  if(!home&&!away)return {entityN:0,totalN:0,entityOver:0,entityOverRate:null,totalOverRate:null,entityAvgTotal:null,pairN:0,pairOver:0,pairOverRate:null,pairAvgTotal:null,entityNames:[]};
  const prior=(events||[]).filter(e=>{const t=new Date(e?.timestamp||0).getTime();if(!e||e.product!==product||e.total==null||!Number.isFinite(t)||t>=cutoff)return false;const eh=participantIdentityKey(e.participant_1||e.home||''),ea=participantIdentityKey(e.participant_2||e.away||'');return eh===home||eh===away||ea===home||ea===away;});
  const entityDecisive=prior.filter(e=>e.total!==target),entityOver=entityDecisive.filter(e=>e.total>target);
  const pairRelevant=prior.filter(e=>{const eh=String(e.home||'').trim().toLowerCase(),ea=String(e.away||'').trim().toLowerCase();return (eh===home&&ea===away)||(eh===away&&ea===home);});
  const pairDecisive=pairRelevant.filter(e=>e.total!==target),pairOver=pairDecisive.filter(e=>e.total>target);
  return {
    entityN:entityDecisive.length,totalN:prior.length,entityOver:entityOver.length,
    entityOverRate:entityDecisive.length?entityOver.length/entityDecisive.length:null,
    totalOverRate:prior.length?prior.filter(e=>e.total>target).length/prior.length:null,
    entityAvgTotal:prior.length?prior.reduce((s,e)=>s+Number(e.total||0),0)/prior.length:null,
    pairN:pairDecisive.length,pairOver:pairOver.length,
    pairOverRate:pairDecisive.length?pairOver.length/pairDecisive.length:null,
    pairAvgTotal:pairRelevant.length?pairRelevant.reduce((s,e)=>s+Number(e.total||0),0)/pairRelevant.length:null,
    entityNames:[participantIdentity(event.participant_1||event.home),participantIdentity(event.participant_2||event.away)].filter(Boolean)
  };
}
function participantPrior(events,event,line){
  const rec=recurrenceEvidence(events,event,line);
  if(rec.entityN<3)return {prob:null,n:rec.entityN,totalN:rec.totalN,pairProb:null,pairN:rec.pairN,weight:0,entityProb:null};
  let prob=(rec.entityOver+2)/(rec.entityN+4);
  let pairProb=null;
  if(rec.entityN>=8){
    const exactProb=(rec.entityOver+2)/(rec.entityN+4);
    prob=exactProb;
  }
  if(rec.pairN>=6){
    pairProb=(rec.pairOver+2)/(rec.pairN+4);
    prob=.75*prob+.25*pairProb;
  }
  const weight=Math.min(.15,Math.max(.05,(rec.entityN-2)/35));
  return {prob,n:rec.entityN,totalN:rec.totalN,pairProb,pairN:rec.pairN,weight,entityProb:prob};
}
function hotParticipantForEvent(e,line){
  const profiles=state.participantProfiles?.profiles||[];
  const names=[e.participant_1||e.home,e.participant_2||e.away].filter(Boolean).map(participantIdentityKey);
  const matches=profiles.filter(p=>p.product===e.product&&names.includes(String(p.participant||'').trim().toLowerCase())&&p.hot&&Number(p.hot.line)===Number(line));
  if(!matches.length)return null;
  matches.sort((a,b)=>(b.hot?.strength||0)-(a.hot?.strength||0));
  return matches[0];
}
function blendForEvent(event,priorEvents){
  if(!event||!event.ladder)return null;
  const points=event.ladder.points;
  const rows=[];
  const prior=productPrior(priorEvents,event.product,points.length?points[0].line:0,new Date(event.timestamp).getTime());
  // Product-specific blend weight is selected on earlier events only.
  const candidates=[0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1];
  let alpha=0.3,bestLoss=Infinity,bestN=0;
  const earlier=(priorEvents||[]).filter(e=>e.product===event.product&&e.total!=null&&new Date(e.timestamp).getTime()<new Date(event.timestamp).getTime());
  if(earlier.length>=20){
    for(const a of candidates){
      let loss=0,n=0;
      for(let i=10;i<earlier.length;i++){
        const cur=earlier[i],before=earlier.slice(0,i);
        for(const rr of cur.rows){
          if(rr.line==null||typeof rr.win!=='boolean')continue;
          const pprior=productPrior(before,event.product,Number(rr.line),new Date(cur.timestamp).getTime());
          if(!pprior.prob||!cur.ladder)continue;
          const over=poissonOver(cur.ladder.lambda,Number(rr.line));
          const pOver=clamp01((1-a)*over+a*pprior.prob);
          const p=String(rr.selection||'').toUpperCase().startsWith('U')?1-pOver:pOver;
          const y=rr.win?1:0;
          loss+=-(y*Math.log(p)+(1-y)*Math.log(1-p));n++;
        }
      }
      if(n>=20&&loss/n<bestLoss){bestLoss=loss/n;bestN=n;alpha=a;}
    }
  }else if(earlier.length<20){alpha=0;}
  return {alpha,alphaN:bestN,priorN:prior.n};
}
function modelOverForEvent(event,priorEvents,line){
  if(!event||!event.ladder)return null;
  const market=poissonOver(event.ladder.lambda,line);
  const prior=productPrior(priorEvents,event.product,line,new Date(event.timestamp).getTime());
  const blend=blendForEvent(event,priorEvents);
  const base=(prior?.prob&&blend&&blend.alpha>0)?clamp01((1-blend.alpha)*market+blend.alpha*prior.prob):market;
  const participant=participantPrior(priorEvents,event,line);
  const prob=participant.prob!=null?clamp01((1-participant.weight)*base+participant.weight*participant.prob):base;
  return {
    prob,
    marketProb:market,
    priorProb:prior?.prob??null,
    alpha:blend?.alpha||0,
    lambda:event.ladder.lambda,
    n:prior?.n||0,
    participantProb:participant.prob,
    participantN:participant.n,participantTotalN:participant.totalN,
    participantPairProb:participant.pairProb,
    participantPairN:participant.pairN,
    participantWeight:participant.weight,participantTotalN:participant.totalN,
    participantEntityProb:participant.entityProb||null
  };
}
function buildModelBacktest(rows){
  const events=historicalOUEvents(rows).sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
  const outputs=[];
  for(const e of events){
    const prior=events.filter(x=>x.product===e.product&&new Date(x.timestamp).getTime()<new Date(e.timestamp).getTime());
    for(const r of e.rows){
      if(r.line==null||typeof r.win!=='boolean'||r.model_prob==null)continue;
      const overModel=modelOverForEvent(e,prior,Number(r.line));
      if(!overModel)continue;
      const baseline=String(r.selection||'').toUpperCase().startsWith('U')?1-Number(r.model_prob):Number(r.model_prob);
      const model=String(r.selection||'').toUpperCase().startsWith('U')?1-overModel.prob:overModel.prob;
      outputs.push(Object.assign({},r,{baselineProb:clamp01(baseline),modelProb:clamp01(model),ladderLambda:overModel.lambda,productPriorProb:overModel.priorProb,blendAlpha:overModel.alpha,participantProb:overModel.participantProb,participantN:overModel.participantN,participantWeight:overModel.participantWeight,participantPairN:overModel.participantPairN,modelEventKey:e.key}));
    }
  }
  state.modelRows=outputs;
  return outputs;
}
function scoreProbabilities(rows){
  const valid=(rows||[]).filter(r=>typeof r.win==='boolean'&&Number.isFinite(r.baselineProb)&&Number.isFinite(r.modelProb));
  const calc=key=>{
    if(!valid.length)return null;
    let b=0,l=0;
    valid.forEach(r=>{const p=clamp01(r[key]);const y=r.win?1:0;b+=(y-p)*(y-p);l+=-(y*Math.log(p)+(1-y)*Math.log(1-p));});
    return {n:valid.length,brier:b/valid.length,logLoss:l/valid.length};
  };
  const by={};
  valid.forEach(r=>(by[r.product]??=[]).push(r));
  const keys=[...new Set(valid.map(r=>r.modelEventKey))];
  const cut=Math.max(1,Math.floor(keys.length*0.8)),holdKeys=new Set(keys.slice(cut));
  const holdout=valid.filter(r=>holdKeys.has(r.modelEventKey));
  const scoreSet=a=>{if(!a.length)return null;const fn=key=>{let b=0,l=0;a.forEach(r=>{const q=clamp01(r[key]),y=r.win?1:0;b+=(y-q)*(y-q);l+=-(y*Math.log(q)+(1-y)*Math.log(1-q));});return {n:a.length,brier:b/a.length,logLoss:l/a.length};};return {baseline:fn('baselineProb'),model:fn('modelProb'),events:new Set(a.map(r=>r.modelEventKey)).size};};
  return {all:{baseline:calc('baselineProb'),model:calc('modelProb')},holdout:scoreSet(holdout),holdoutEvents:holdKeys.size,products:Object.fromEntries(Object.entries(by).map(([p,a])=>[p,scoreSet(a)]))};
}
function participantLabRows(events){
  const groups=new Map();
  for(const e of (events||[])){
    if(e.total==null||!e.product)continue;
    for(const raw of [e.home,e.away]){
      const name=String(raw||'').trim();
      if(!name)continue;
      const key=e.product+'|'+participantIdentityKey(name);
      let g=groups.get(key);
      if(!g){g={product:e.product,participant:participantIdentity(name),n:0,lines:{}};groups.set(key,g);}
      g.n++;
      for(const line of [1.5,3.5,4.5]){
        const b=g.lines[line]||(g.lines[line]={n:0,over:0});
        if(e.total===line)continue;
        b.n++;
        if(e.total>line)b.over++;
      }
    }
  }
  return [...groups.values()].map(g=>{
    const lineStats={};
    for(const line of [1.5,3.5,4.5]){
      const b=g.lines[line]||{n:0,over:0};
      lineStats[line]={n:b.n,rate:b.n?b.over/b.n:null};
    }
    return {...g,lineStats};
  }).sort((a,b)=>(b.lineStats[1.5].n-a.lineStats[1.5].n)||(b.n-a.n)||a.participant.localeCompare(b.participant)).slice(0,40);
}
function renderParticipantLab(){
  const host=$('participantLab');if(!host)return;
  const rows=participantLabRows(state.modelEvents||[]);
  const seen=rows.filter(r=>r.lineStats[1.5].n>0);
  if(!seen.length){
    host.innerHTML='<div class="empty">No settled participant recurrence evidence at O/U 1.5 yet. The desk will track it automatically as more events settle.</div>';
    return;
  }
  const qualified=seen.filter(r=>r.lineStats[1.5].n>=8);
  let html='<p class="muted">This panel tracks recurring team/player identifiers at the exact O/U line. The participant feature does not activate until at least 8 prior decisive observations on the same product and line; smaller samples remain context only.</p>';
  html+='<table><thead><tr><th>Product</th><th>Participant</th><th>O1.5 n</th><th>O1.5 over rate</th><th>O3.5</th><th>O4.5</th><th>Total prior</th></tr></thead><tbody>';
  html+=seen.slice(0,30).map(r=>'<tr><td>'+esc(r.product)+'</td><td><strong>'+esc(r.participant)+'</strong></td><td>'+r.lineStats[1.5].n+'</td><td>'+fmtPct(r.lineStats[1.5].rate)+'</td><td>'+r.lineStats[3.5].n+' / '+fmtPct(r.lineStats[3.5].rate)+'</td><td>'+r.lineStats[4.5].n+' / '+fmtPct(r.lineStats[4.5].rate)+'</td><td>'+r.n+'</td></tr>').join('');
  html+='</tbody></table>';
  html+='<p class="muted"><strong>Activation-ready participant samples:</strong> '+qualified.length+'. O/U1.5 remains experimental until its own product/line walk-forward evidence clears the model gate.</p>';
  host.innerHTML=html;
}

async function renderModelLab(){
  const host=$('modelLab');if(!host)return;
  const artifact=state.modelEvaluation;
  if(artifact){
    const fmt=v=>v==null?'—':Number(v).toFixed(4);
    const pct=v=>v==null?'—':(Number(v)*100).toFixed(1)+'%';
    const row=(name,a,b)=>'<tr><td>'+esc(name)+'</td><td>'+((a&&a.n)||'—')+'</td><td>'+fmt(a&&a.brier)+'</td><td>'+fmt(b&&b.brier)+'</td><td>'+fmt(a&&a.log_loss)+'</td><td>'+fmt(b&&b.log_loss)+'</td><td>'+pct(b&&b.hit_rate)+'</td><td>'+pct(b&&b.ece)+'</td></tr>';
    const h=artifact.holdout_metrics||{};
    let html='<div class="modelGrid"><div><h3>Strict walk-forward evaluation</h3><p class="muted">Every event is scored chronologically using only settled events that occurred before it. The final '+pct(artifact.holdout?.fraction)+' event block is untouched during discovery. No user-reported tickets enter the dataset.</p></div><div><h3>Model gate</h3><p class="muted">Lower Brier/log loss are better. Calibration is measured with expected calibration error. Hit rate is the selected-side hit rate at p≥0.50.</p><p><strong>Participant feature:</strong> '+(artifact.participant_feature_gate?.pass?'QUALIFIED ON HOLDOUT':'NOT QUALIFIED YET')+'</p></div></div>';
    html+='<table><thead><tr><th>Variant</th><th>Holdout N</th><th>Brier</th><th>Δ vs market</th><th>Log loss</th><th>Δ vs market</th><th>Hit rate</th><th>ECE</th></tr></thead><tbody>';
    const market=h.market||{}; for(const [name,label] of [['market','SportyBet de-vig baseline'],['poisson','Line-ladder Poisson'],['poisson_prior','Poisson + product prior'],['participant_model','Participant-aware model']]){
      const m=h[name]; const db=m&&market.brier!=null?m.brier-market.brier:null; const dl=m&&market.log_loss!=null?m.log_loss-market.log_loss:null;
      html+='<tr><td><strong>'+label+'</strong></td><td>'+((m&&m.n)||'—')+'</td><td>'+fmt(m&&m.brier)+'</td><td>'+fmt(db)+'</td><td>'+fmt(m&&m.log_loss)+'</td><td>'+fmt(dl)+'</td><td>'+pct(m&&m.hit_rate)+'</td><td>'+pct(m&&m.ece)+'</td></tr>';
    }
    html+='</tbody></table>';
    html+='<h3>Holdout by O/U line</h3><table><thead><tr><th>Line</th><th>N</th><th>Market Brier</th><th>Participant Brier</th><th>Market Log loss</th><th>Participant Log loss</th><th>Participant hit</th></tr></thead><tbody>';
    Object.entries(artifact.by_line||{}).forEach(([line,x])=>{const a=x.holdout?.market,b=x.holdout?.participant_model;html+='<tr><td>'+esc(line)+'</td><td>'+((b&&b.n)||'—')+'</td><td>'+fmt(a&&a.brier)+'</td><td>'+fmt(b&&b.brier)+'</td><td>'+fmt(a&&a.log_loss)+'</td><td>'+fmt(b&&b.log_loss)+'</td><td>'+pct(b&&b.hit_rate)+'</td></tr>';});
    html+='</tbody></table>';
    html+='<p class="muted"><strong>Untouched participant rows:</strong> '+((artifact.holdout&&artifact.holdout.participant_rows)||0)+' · required '+((artifact.participant_feature_gate&&artifact.participant_feature_gate.minimum_untouched_participant_rows)||0)+'. <strong>Gate:</strong> '+(artifact.participant_feature_gate?.pass?'PASS':'WAIT')+'.</p>';
    html+='<p class="muted">O/U 1.5 is evaluated separately and remains experimental unless its own untouched evidence clears the same discipline. The Odds Builder never uses the experimental watch as a qualified signal.</p>';
    host.innerHTML=html;
    return;
  }
  const rows=state.modelRows||[],scores=scoreProbabilities(rows);
  if(!rows.length){host.innerHTML='<div class="empty">Need settled O/U observations with complete pre-event line data. Collect more events before trusting this model.</div>';return;}
  const cell=(v,d=4)=>v==null?'—':Number(v).toFixed(d),delta=(a,b)=>a==null||b==null?'—':(a-b).toFixed(4);
  let html='<div class="modelGrid"><div><h3>O/U line-ladder model</h3><p class="muted">Local fallback scoring is active while the collector-generated strict evaluation artifact is unavailable.</p></div></div>';
  html+='<table><thead><tr><th>Product</th><th>N</th><th>Market Brier</th><th>Model Brier</th><th>Δ Brier</th><th>Market LogLoss</th><th>Model LogLoss</th><th>Δ LogLoss</th></tr></thead><tbody>';
  Object.entries(scores.products).forEach(([p,x])=>{html+='<tr><td>'+esc(p)+'</td><td>'+x.model.n+'</td><td>'+cell(x.baseline.brier)+'</td><td>'+cell(x.model.brier)+'</td><td>'+delta(x.baseline.brier,x.model.brier)+'</td><td>'+cell(x.baseline.logLoss)+'</td><td>'+cell(x.model.logLoss)+'</td><td>'+delta(x.baseline.logLoss,x.model.logLoss)+'</td></tr>';});
  html+='</tbody></table>';
  state.modelHoldout=scores.holdout;
  state.modelGate=!!(scores.holdout&&scores.holdout.n>=20&&scores.holdout.model.brier<scores.holdout.baseline.brier&&scores.holdout.model.logLoss<scores.holdout.baseline.logLoss);
  host.innerHTML=html;
}

function calculateMarket(m){
  const outs=(m&&m.outcomes||[]).filter(o=>Number(o.odds)>1);
  if(outs.length<2)return null;
  const total=outs.reduce((sum,o)=>sum+(1/Number(o.odds)),0);
  const norm=outs.map(o=>Object.assign({},o,{fairProb:(1/Number(o.odds))/total}));
  const pick=norm.reduce((a,b)=>b.fairProb>a.fairProb?b:a);
  return {market:m,pick:pick,pickCode:outcomeCode(m,pick),fairProb:pick.fairProb,fairOdds:1/pick.fairProb,bookmakerOdds:Number(pick.odds),bookImplied:1/Number(pick.odds),overround:Math.max(0,total-1)};
}
function historicalCalibration(product,marketType,pickCode,rawProb,startTime){
  if(!state.historyLoaded||!state.rows.length)return {prob:rawProb,n:0,source:'market'};
  const cutoff=startTime?new Date(startTime).getTime():Infinity;
  const exact=state.rows.filter(r=>{
    if(r.product!==product||r.market!==marketType||r.selection!==String(pickCode).toLowerCase()||typeof r.win!=='boolean')return false;
    const t=new Date(r.timestamp||0).getTime();
    return !Number.isFinite(cutoff)||!Number.isFinite(t)||t<cutoff;
  });
  const priorN=20;
  if(exact.length>=20){
    const wins=exact.filter(r=>r.win).length;
    return {prob:(wins+rawProb*priorN)/(exact.length+priorN),n:exact.length,source:'exact-selection'};
  }
  const bucket=Math.max(0,Math.min(9,Math.floor(rawProb*10)));
  const broad=state.rows.filter(r=>{
    if(r.product!==product||r.market!==marketType||typeof r.win!=='boolean'||r.model_prob==null)return false;
    const t=new Date(r.timestamp||0).getTime();
    if(Number.isFinite(cutoff)&&Number.isFinite(t)&&t>=cutoff)return false;
    return Math.max(0,Math.min(9,Math.floor(Number(r.model_prob)*10)))===bucket;
  });
  if(broad.length>=30){
    const wins=broad.filter(r=>r.win).length;
    const observed=wins/broad.length;
    return {prob:(wins+rawProb*priorN)/(broad.length+priorN),n:broad.length,source:'probability-bucket'};
  }
  return {prob:rawProb,n:Math.max(exact.length,broad.length),source:'market'};
}
function qualifiesResearchPick(c){
  if(!c)return false;
  const edge=c.calibratedProb-c.bookImplied;
  const modelOk=c.marketType==='ou'?state.modelGate:true;
  return state.historyLoaded && modelOk && c.calibrationN>=30 && edge>=0.02;
}
function isEligibleResearchEvent(e){
  return (state.eligibility.eligible_competitions||[]).includes(String(e.competition||e.tournament||''));
}
function isPriorityOU(c){ return !!(c&&c.marketType==='ou'&&state.eligibility.priority_ou_lines.some(x=>Math.abs(Number(x)-Number(c.market.line))<0.001)); }
function isEligibleOU(c){
  return !!(c&&c.marketType==='ou'&&state.eligibility.eligible_markets.includes('ou')&&
    state.eligibility.eligible_ou_lines.some(x=>Math.abs(Number(x)-Number(c.market.line))<0.001));
}
function isExperimentalOU(c){
  return !!(c&&c.marketType==='ou'&&state.eligibility.eligible_markets.includes('ou')&&
    state.eligibility.experimental_ou_lines.some(x=>Math.abs(Number(x)-Number(c.market.line))<0.001));
}
function enrichCandidate(c,e){
  const cal=historicalCalibration(e.product,c.marketType,c.pickCode,c.fairProb,e.start_time);
  let calibrated=cal.prob,source=cal.source,modelMeta=null;
  if(c.marketType==='ou'&&e.start_time&&(isEligibleOU(c)||isExperimentalOU(c))){
    const ladder=fitLambdaFromLadder((e.markets||[]).map(m=>marketOverPoint(m)).filter(Boolean));
    if(ladder){
      const priorEvents=state.modelEvents||[];
      const pseudo={product:e.product,participant_1:participantIdentity(e.participant_1||e.home||''),participant_2:participantIdentity(e.participant_2||e.away||''),home:participantIdentity(e.participant_1||e.home||''),away:participantIdentity(e.participant_2||e.away||''),timestamp:e.start_time,ladder,total:null};
      const mm=modelOverForEvent(pseudo,priorEvents,Number(c.market.line));
      if(mm){
        calibrated=String(c.pickCode).toUpperCase().startsWith('U')?1-mm.prob:mm.prob;
        source='ou-line-ladder-product-model';modelMeta=mm;
      }
    }
  }
  const recurrence=(c.marketType==='ou')?recurrenceEvidence(state.modelEvents||[],{product:e.product,participant_1:participantIdentity(e.participant_1||e.home||''),participant_2:participantIdentity(e.participant_2||e.away||''),home:participantIdentity(e.participant_1||e.home||''),away:participantIdentity(e.participant_2||e.away||''),timestamp:e.start_time},Number(c.market.line)):null;
  const hotParticipant=(c.marketType==='ou')?hotParticipantForEvent(e,Number(c.market.line)):null;
  return Object.assign(c,{calibratedProb:calibrated,calibrationN:cal.n,calibrationSource:source,edge:calibrated-c.bookImplied,modelMeta,recurrence,hotParticipant,experimental:isExperimentalOU(c)});
}
function predictionForEvent(e){
  const id=String(e.event_id||e.eventId||'');
  if(state.predictionCache.has(id))return state.predictionCache.get(id);
  if(!isEligibleResearchEvent(e))return null;
  const candidates=[];
  (e.markets||[]).forEach(m=>{
    const mid=String(m.id||''),name=String(m.name||'').toLowerCase();
    const isTotals=mid==='18'||mid==='189'||name.indexOf('over/under')>=0||name.indexOf('total')>=0;
    if(!isTotals)return;
    const c=calculateMarket(m);
    if(c){c.marketType='ou';candidates.push(c);}
  });
  const active=candidates.filter(isEligibleOU).sort((a,b)=>b.fairProb-a.fairProb);
  const experimental=candidates.filter(isExperimentalOU).sort((a,b)=>b.fairProb-a.fairProb);
  if(!active.length&&!experimental.length)return null;
  const bestOU=active.length?enrichCandidate(active[0],e):null;
  const experimentalOU=experimental.length?enrichCandidate(experimental[0],e):null;
  const primaryCandidate=bestOU||experimentalOU;
  const out={product:e.product,competition:e.competition||e.tournament||'',event_id:id,
    home:String(e.home||e.participant_1||''),away:String(e.away||e.participant_2||''),
    start_time:e.start_time||null,primary:primaryCandidate&&qualifiesResearchPick(primaryCandidate)?primaryCandidate:null,
    bestWinner:null,bestOU,experimentalOU,candidates:[bestOU,experimentalOU].filter(Boolean)};
  state.predictionCache.set(id,out);
  return out;
}
function isConfirmedWatchedEvent(e){
  const list=Array.isArray(state.confirmedWatch?.participants)?state.confirmedWatch.participants:[];
  const names=[participantIdentityKey(e?.participant_1||e?.home||''),participantIdentityKey(e?.participant_2||e?.away||'')];
  const product=String(e?.product||'').trim();
  return list.some(x=>{
    const p=participantIdentityKey(x?.participant||'');
    if(!p||!names.includes(p))return false;
    return !x.product||x.product==='all'||x.product===product;
  });
}
function confirmedWatchParticipantsForEvent(e){
  const list=Array.isArray(state.confirmedWatch?.participants)?state.confirmedWatch.participants:[];
  const names=[String(e?.home||e?.participant_1||'').trim().toLowerCase(),String(e?.away||e?.participant_2||'').trim().toLowerCase()];
  const product=String(e?.product||'').trim();
  return list.filter(x=>{
    const p=participantIdentityKey(x?.participant||'');
    return p&&names.includes(p)&&(!x.product||x.product==='all'||x.product===product);
  });
}
function isUpcoming(e){
  if(!e||!e.start_time)return true;
  const t=new Date(e.start_time).getTime();
  return Number.isFinite(t)&&t>=Date.now()-120000;
}
function upcomingEventsFrom(events){
  return (events||[]).filter(isUpcoming).sort((a,b)=>new Date(a.start_time||0).getTime()-new Date(b.start_time||0).getTime());
}
function renderLive(){
  const product=$('product').value,market=$('market').value;
  const events=upcomingEventsFrom(state.live).filter(e=>isEligibleResearchEvent(e)||isConfirmedWatchedEvent(e)).filter(e=>product==='all'||e.product===product).sort((a,b)=>Number(isConfirmedWatchedEvent(b))-Number(isConfirmedWatchedEvent(a))||new Date(a.start_time||0)-new Date(b.start_time||0)).slice(0,30);
  const list=events.slice(0,30).map(e=>{
    const p=predictionForEvent(e);
    const shown=(e.markets||[]).filter(m=>matchesMarket(m,market)).slice(0,3);
    const chips=shown.flatMap(m=>(m.outcomes||[]).slice(0,4).map(o=>'<span class="liveChip"><span>'+esc(outcomeCode(m,o))+'</span> <b>'+Number(o.odds).toFixed(2)+'</b></span>')).join('');
    const pick=p&&p.primary?'<div class="predictionBox"><div class="predictionTop"><span class="predictionLabel">RESEARCH PICK</span><span class="predictionType">'+(p.primary.marketType==='ou'?'TOTALS':'MATCH RESULT')+'</span></div><div class="predictionPick">'+esc(p.primary.pickCode)+' <b>'+fmtPct(p.primary.calibratedProb)+'</b></div><div class="predictionMeta">Book '+p.primary.bookmakerOdds.toFixed(2)+' · Edge '+fmtPct(p.primary.edge)+' · n='+p.primary.calibrationN+'</div></div>':'<div class="predictionBox mutedPrediction"><div class="predictionLabel">NO QUALIFIED SIGNAL</div><div class="predictionPick">MARKET BASELINE ONLY</div><div class="predictionMeta">Needs ≥30 historical calibration observations and ≥2% calibrated edge.</div></div>';
    const identityLine=(e.participant_1||e.participant_2)?'<div class="participantIdentityLine"><span class="participantIdentityLabel">STABLE PARTICIPANT</span><strong>'+esc(e.participant_1||'UNVERIFIED')+'</strong><span>vs</span><strong>'+esc(e.participant_2||'UNVERIFIED')+'</strong><span class="participantIdentityStatus">'+(e.identity_verified?'✓ VERIFIED':'⚠ IDENTITY UNVERIFIED')+'</span></div>':'<div class="participantIdentityLine participantIdentityUnknown"><span class="participantIdentityLabel">STABLE PARTICIPANT</span><strong>IDENTITY NOT EXPOSED BY LIVE FEED</strong><span class="participantIdentityStatus">⚠ NO GUESSING</span></div>';
    return '<article class="liveCard"><div class="liveTop"><span>'+esc(e.competition||e.product)+'</span><span>'+esc(e.start_time?date(e.start_time):'Time n/a')+'</span></div><div class="liveTeams"><strong>'+esc(e.home||'Unknown team')+'</strong> <span>vs</span> <strong>'+esc(e.away||'Unknown team')+'</strong>'+identityLine+'</div>'+pick+'<div class="liveOdds">'+(chips||'<span class="liveMeta">No readable markets</span>')+'</div></article>';
  }).join('');
  $('liveGrid').innerHTML=list;
  $('liveEmpty').hidden=!!list;
  $('liveDot').className='liveDot '+(state.liveMode==='remote'?'':state.liveMode==='snapshot'?'wait':'bad');
  $('liveTitle').textContent=state.liveMode==='remote'?'LIVE SOURCE ONLINE · UPCOMING ONLY':state.liveMode==='snapshot'?'SNAPSHOT FALLBACK · UPCOMING ONLY':'LIVE SOURCE UNAVAILABLE';
  const counts={};events.forEach(e=>counts[e.product]=(counts[e.product]||0)+1);
  $('liveMeta').textContent=(state.liveUpdated?'Feed timestamp '+date(state.liveUpdated)+' · ':'')+(Object.keys(counts).map(k=>k+': '+counts[k]).join(' · ')||'0 upcoming events');
}
function renderPredictionDesk(){
  const host=$('predictionDesk');if(!host)return;
  const picks=state.picks.slice(0,40);
  $('predictionCount').textContent=String(picks.length);
  if(!picks.length){host.innerHTML='<div class="empty">No upcoming fixture currently has a readable 1X2 or O/U market.</div>';return;}
  host.innerHTML=picks.map(function(p,i){
    function row(x,label){
      if(!x)return '<div class="calcRow"><span>'+label+'</span><b>—</b><span>—</span><span>—</span><span>—</span></div>';
      const modelP=x.calibratedProb!=null?x.calibratedProb:x.fairProb;
      return '<div class="calcRow"><span>'+label+(x.market.line!=null?' '+x.market.line:'')+(x.experimental?' <em class="experimentalTag">EXPERIMENTAL</em>':'')+'</span><b>'+esc(x.pickCode)+'</b><span>Fair '+fmtPct(x.fairProb)+' · Model '+fmtPct(modelP)+'</span><span>Fair '+x.fairOdds.toFixed(2)+'</span><span>Book '+x.bookmakerOdds.toFixed(2)+'</span></div>';
    }
    const watch=p.experimentalOU;
    const hot=p.bestOU&&p.bestOU.hotParticipant?p.bestOU.hotParticipant:(p.experimentalOU&&p.experimentalOU.hotParticipant?p.experimentalOU.hotParticipant:null);
    const hotBadge=hot?'<em class="hotParticipantTag">🔥 HOT '+esc(hot.hot.direction)+' · '+hot.hot.line+'</em>':'';
    const primaryHtml=p.primary?'<div class="primaryPick">'+hotBadge+'<span>RESEARCH QUALIFIED</span><strong>'+esc(p.primary.pickCode)+'</strong><b>'+fmtPct(p.primary.calibratedProb)+'</b><small>edge '+fmtPct(p.primary.edge)+' · n='+p.primary.calibrationN+'</small></div>':watch?'<div class="primaryPick mutedPrediction">'+hotBadge+'<span>O/U 1.5 RESEARCH WATCH</span><strong>'+esc(watch.pickCode)+'</strong><b>'+fmtPct(watch.calibratedProb)+'</b><small>participant n='+(watch.recurrence?watch.recurrence.entityN:0)+' · model is experimental</small></div>':'<div class="primaryPick mutedPrediction"><span>NO QUALIFIED SIGNAL</span><strong>WAIT</strong><b>Market baseline only</b></div>';
    const addLabel=p.primary?'＋ Add qualified pick':'Locked · no qualified signal';
    const activeRec=p.bestOU&&p.bestOU.recurrence;
    const expRec=p.experimentalOU&&p.experimentalOU.recurrence;
    const recurrenceText=(activeRec||expRec)?
      'Recurring participant evidence: prior-participant n='+(activeRec?activeRec.entityN:0)+' · total-history n='+(activeRec?activeRec.totalN:0)+' · '+(activeRec&&activeRec.entityOverRate!=null?fmtPct(activeRec.entityOverRate):'—')+
      ' · O/U 1.5 n='+(expRec?expRec.entityN:0)+' · '+(expRec&&expRec.entityOverRate!=null?fmtPct(expRec.entityOverRate):'—')+
      ' · exact-pair O1.5 n='+(expRec?expRec.pairN:0):'No prior participant recurrence sample yet.';
    const identityHtml=(p.participant_1||p.participant_2)?'<div class="participantIdentityLine"><span class="participantIdentityLabel">STABLE PARTICIPANT</span><strong>'+esc(p.participant_1||'UNVERIFIED')+'</strong><span>vs</span><strong>'+esc(p.participant_2||'UNVERIFIED')+'</strong><span class="participantIdentityStatus">'+(p.identity_verified?'✓ VERIFIED':'⚠ IDENTITY UNVERIFIED')+'</span></div>':'<div class="participantIdentityLine participantIdentityUnknown"><span class="participantIdentityLabel">STABLE PARTICIPANT</span><strong>IDENTITY NOT EXPOSED BY LIVE FEED</strong><span class="participantIdentityStatus">⚠ NO GUESSING</span></div>';
    return '<article class="predictionCard"><div class="predictionHeader"><div><small>'+esc(p.product)+' · '+esc(p.competition)+'</small><h3>'+esc(p.home)+' <span>vs</span> '+esc(p.away)+'</h3>'+identityHtml+'</div><time>'+esc(p.start_time?date(p.start_time):'—')+'</time></div>'+primaryHtml+'<div class="calcTable"><div class="calcHead"><span>Market</span><span>Pick</span><span>Fair / model probability</span><span>Fair odds</span><span>SportyBet</span></div>'+row(p.bestWinner,'1X2')+row(p.bestOU,'O/U')+row(p.experimentalOU,'O/U 1.5')+'</div><div class="recurrenceNote">'+recurrenceText+'</div><div class="calcNote">Fair probability is the current de-vig SportyBet market baseline. Model probability adds the walk-forward line-ladder/product model and, using prior participant totals across different opponents, with shrinkage; exact-line history is a secondary refinement. O/U 1.5 remains a research watch and is not activated from ticket streaks alone.</div><button class="btn builderAdd" data-pick="'+i+'" '+(p.primary?'':'disabled')+'>'+addLabel+'</button></article>';
  }).join('');
  host.querySelectorAll('.builderAdd').forEach(function(btn){btn.addEventListener('click',function(){const p=picks[Number(btn.dataset.pick)];if(p&&!state.builder.some(function(x){return x.event_id===p.event_id;})){state.builder.push(p);state.builder=state.builder.slice(-4);renderBuilder();}});});
}
function renderBuilder(){
  const host=$('builderList'),summary=$('builderSummary');if(!host||!summary)return;
  if(!state.builder.length){host.innerHTML='<div class="empty">Add upcoming predictions to build a 2–4 leg paper slip.</div>';summary.innerHTML='<span>0 legs</span>';return;}
  const unique=[],seen={};
  state.builder.forEach(function(p){if(!seen[p.event_id]){seen[p.event_id]=1;unique.push(p);}});state.builder=unique.slice(-4);
  state.builder=state.builder.filter(function(p){return p&&p.primary&&qualifiesResearchPick(p.primary);}).slice(-4);
  if(!state.builder.length){host.innerHTML='<div class="empty">No qualified research picks are currently eligible for the paper builder.</div>';summary.innerHTML='<span>0 legs · builder locked until a validated signal exists</span>';return;}
  const combined=state.builder.reduce(function(a,p){return a*p.primary.bookmakerOdds;},1);
  const fairCombined=state.builder.reduce(function(a,p){return a*p.primary.fairOdds;},1);
  const baselineHit=state.builder.reduce(function(a,p){return a*p.primary.calibratedProb;},1);
  host.innerHTML=state.builder.map(function(p,i){return '<div class="builderRow"><span class="builderPick">'+esc(p.primary.pickCode)+'</span><span>'+esc(p.home+' vs '+p.away)+'</span><b>'+p.primary.bookmakerOdds.toFixed(2)+'</b><button class="btn removeLeg" data-i="'+i+'">×</button></div>';}).join('');
  host.querySelectorAll('.removeLeg').forEach(function(btn){btn.addEventListener('click',function(){state.builder.splice(Number(btn.dataset.i),1);renderBuilder();});});
  const ready=state.builder.length>=2;
  summary.innerHTML='<span><b>'+state.builder.length+'</b> legs</span><span>Combined odds <b>'+combined.toFixed(2)+'</b></span><span>Baseline hit probability <b>'+fmtPct(baselineHit)+'</b></span><span>Fair combined odds <b>'+fairCombined.toFixed(2)+'</b></span><strong class="'+(ready?'builderReady':'')+'">'+(ready?'READY · PAPER BUILDER':'ADD AT LEAST 2 LEGS')+'</strong>';
}
function autoBuild(){
  const candidates=state.picks.filter(function(p){return p.primary&&qualifiesResearchPick(p.primary);}).sort(function(a,b){return b.primary.edge-a.primary.edge;});
  const chosen=[],seen={};
  for(const p of candidates){if(chosen.length>=4||seen[p.event_id])continue;chosen.push(p);seen[p.event_id]=1;}
  state.builder=chosen;renderBuilder();
}

function collectLiveFromBody(body){
  const data=body&&body.data||{};
  const tournaments=data.tournaments||[];
  const out=[];
  tournaments.forEach(t=>{
    const tn=t.name||'',cn=t.categoryName||'';
    (t.events||[]).forEach(e=>{
      const row=normalizeLiveEvent(e,tn,cn);
      if(row&&row.event_id)out.push(row);
    });
  });
  return out;
}

async function fetchLiveRemote(){
  const urls=[
    './api/sportybet-virtual',
    LIVE_API
  ];
  let lastError=null;
  for(const base of urls){
    try{
      const pages=[];
      for(let pageNum=1;pageNum<=2;pageNum++){
        const params=new URLSearchParams({pageSize:'100',pageNum:String(pageNum),timeline:'168',sources:'efootball,srl,vfootball',_t:String(Date.now())});
        const controller=new AbortController();
        const timeout=setTimeout(()=>controller.abort(),8000);
        let r;
        try{r=await fetch(base+'?'+params.toString(),{cache:'no-store',headers:{'Accept':'application/json'},signal:controller.signal});}
        finally{clearTimeout(timeout)}
        if(!r.ok)throw new Error(base+' HTTP '+r.status);
        const body=await r.json();
        if(body?.ok===false)throw new Error(body.error||base+' returned an error');
        pages.push(body);
        const batch=Array.isArray(body?.events)?body.events:[];
        if(batch.length<100)break;
      }
      const merged=[];
      const seen=new Set();
      for(const body of pages){
        for(const e of (Array.isArray(body?.events)?body.events:[])){
          const id=String(e.event_id||e.eventId||'');
          if(id&&!seen.has(id)){seen.add(id);merged.push(e)}
        }
      }
      if(merged.length){
        const latestTimestamp=pages.map(p=>p?.updated_at).filter(Boolean).sort().pop()||new Date().toISOString();
        return {events:merged,updated_at:latestTimestamp,endpoint:base};
      }
      lastError=new Error(base+' returned zero virtual/eFootball/SRL events');
    }catch(e){lastError=e;}
  }
  throw lastError||new Error('No live virtual source available');
}
async function fetchLiveSnapshot(){
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),8000);
  let r;try{r=await fetch(SNAPSHOT,{cache:'no-store',signal:controller.signal});}finally{clearTimeout(timeout)}
  if(!r.ok)throw new Error('Live snapshot HTTP '+r.status);
  const body=await r.json();
  const events=(Array.isArray(body.events)?body.events:[]).map(e=>({
    ...e,
    home:String(e.home||e.team_1||e.homeTeamName||''),
    away:String(e.away||e.team_2||e.awayTeamName||''),
    participant_1:String(e.participant_1||''),
    participant_2:String(e.participant_2||''),
    identity_verified:!!(e.participant_1&&e.participant_2),
    event_id:String(e.event_id||e.eventId||''),
    start_time:e.start_time||null,
    match_status:e.match_status||e.matchStatus||null,
    markets:Array.isArray(e.markets)?e.markets:[]
  })).filter(e=>e.event_id);
  return {events,updated_at:body.updated_at||null};
}

let liveInFlight=false;
async function loadLive(){
  if(liveInFlight)return;
  liveInFlight=true;
  const button=$('liveRefresh');
  button.disabled=true;
  try{
    const live=await fetchLiveRemote();
    state.live=upcomingEventsFrom(live.events);
    state.liveMode='remote';
    state.liveUpdated=live.updated_at;
    renderLive();
    rebuildPredictionDesk();
    $('liveMeta').textContent='LIVE · '+$('liveMeta').textContent+' · '+live.endpoint;
    return;
  }catch(remoteError){
    try{
      const snap=await fetchLiveSnapshot();
      const ageMs=snap.updated_at?Date.now()-new Date(snap.updated_at).getTime():Infinity;
      if(!snap.events.length)throw new Error('snapshot has zero events');
      state.live=upcomingEventsFrom(snap.events);
      if(!state.live.length)throw new Error('snapshot has no upcoming events');
      state.liveMode='snapshot';
      state.liveUpdated=snap.updated_at;
      renderLive();
      rebuildPredictionDesk();
      const stale=ageMs>120000;
      $('liveDot').className='liveDot '+(stale?'bad':'wait');
      $('liveTitle').textContent=stale?'STALE SNAPSHOT — LIVE SOURCE DOWN':'SNAPSHOT FALLBACK';
      $('liveMeta').textContent=(stale?'Remote source unavailable and snapshot is older than 2 minutes · ':'Remote live source unavailable · ')+$('liveMeta').textContent;
      console.warn('Virtual Lab live source failed; snapshot used:',remoteError);
      return;
    }catch(snapshotError){
      state.live=[];
      state.liveMode='none';
      renderLive();
      $('liveDot').className='liveDot bad';
      $('liveTitle').textContent='LIVE SOURCE UNAVAILABLE';
      $('liveMeta').textContent=remoteError.message+' · '+snapshotError.message;
      console.error('Virtual Lab live feed failed:',remoteError,snapshotError);
    }
  }finally{button.disabled=false;liveInFlight=false}
}

function rebuildPredictionDesk(){
  const product=$('product').value;
  const eligible=upcomingEventsFrom(state.live).filter(e=>isEligibleResearchEvent(e)||isConfirmedWatchedEvent(e)).filter(e=>product==='all'||e.product===product).sort((a,b)=>Number(isConfirmedWatchedEvent(b))-Number(isConfirmedWatchedEvent(a))||new Date(a.start_time||0)-new Date(b.start_time||0);
  state.picks=eligible.slice(0,24).map(predictionForEvent).filter(Boolean);
  renderPredictionDesk();renderBuilder();
}
async function loadConfirmedWatch(){
  try{
    const r=await fetch(CONFIRMED_WATCH+'?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!r.ok)throw new Error('confirmed watch HTTP '+r.status);
    state.confirmedWatch=await r.json();
    state.predictionCache.clear();
    return true;
  }catch(e){state.confirmedWatch=null;console.warn('Virtual Lab confirmed watch fallback:',e);return false;}
}
async function loadParticipantProfiles(){
  try{
    const r=await fetch(PARTICIPANT_PROFILES+'?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!r.ok)throw new Error('participant profiles HTTP '+r.status);
    state.participantProfiles=await r.json();
    state.predictionCache.clear();
    return true;
  }catch(e){state.participantProfiles=null;console.warn('Virtual Lab participant profiles fallback:',e);return false;}
}
async function loadEligibility(){
  try{
    const r=await fetch(ELIGIBILITY+'?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!r.ok)throw new Error('eligibility HTTP '+r.status);
    const d=await r.json();
    if(Array.isArray(d.eligible_competitions))state.eligibility.eligible_competitions=d.eligible_competitions;
    if(Array.isArray(d.priority_ou_lines))state.eligibility.priority_ou_lines=d.priority_ou_lines.map(Number);
    if(Array.isArray(d.eligible_ou_lines))state.eligibility.eligible_ou_lines=d.eligible_ou_lines.map(Number);
    if(Array.isArray(d.experimental_ou_lines))state.eligibility.experimental_ou_lines=d.experimental_ou_lines.map(Number);
    if(Array.isArray(d.policy?.eligible_markets))state.eligibility.eligible_markets=d.policy.eligible_markets;
    state.predictionCache.clear();
    renderEligibilityNotice();
  }catch(e){console.warn('Virtual Lab eligibility fallback:',e);}
}
function renderEligibilityNotice(){
  const host=$('historyMeta');if(!host)return;
  host.textContent='Research filter active · '+state.eligibility.eligible_competitions.length+' eligible leagues · active O/U '+state.eligibility.eligible_ou_lines.join(', ')+' · experimental O/U '+state.eligibility.experimental_ou_lines.join(', ')+' · recurring participant patterns are tracked separately.';
}
async function loadModelEvaluation(){
  try{
    const r=await fetch(MODEL_EVAL+'?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!r.ok)throw new Error('model eval HTTP '+r.status);
    state.modelEvaluation=await r.json();
    const gate=state.modelEvaluation.participant_feature_gate;
    state.modelGate=!!(gate&&gate.pass);
    return true;
  }catch(e){
    state.modelEvaluation=null;
    console.warn('Virtual Lab model evaluation fallback:',e);
    return false;
  }
}
async function loadHistory(){
  const urls=[HISTORY,HISTORY_FALLBACK];
  let lastError=null;
  for(const url of urls){
    try{
      const r=await fetch(url+'?t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
      if(!r.ok)throw new Error(url+' HTTP '+r.status);
      const data=await r.json();
      const arr=Array.isArray(data)?data:(Array.isArray(data.rows)?data.rows:[]);
      state.rows=arr.map(normalize);
      state.historyLoaded=true;
      state.predictionCache.clear();
      await loadModelEvaluation();
      await loadConfirmedWatch();
      renderLive();
      await loadParticipantProfiles();
      buildModelBacktest(state.rows);
      state.modelEvents=historicalOUEvents(state.rows);
      applyFilters(false);
      renderModelLab();
      renderParticipantLab();
      rebuildPredictionDesk();
      const status=$('historyStatus');if(status)status.textContent='AUTO-COLLECTED · '+arr.length+' settled observations';
      const meta=$('historyMeta');if(meta)meta.textContent='Research filter active · '+state.eligibility.eligible_competitions.length+' eligible leagues · active O/U '+state.eligibility.eligible_ou_lines.join(', ')+' · experimental O/U '+state.eligibility.experimental_ou_lines.join(', ')+' · historical refresh '+new Date().toLocaleString();
      return;
    }catch(e){lastError=e;}
  }
  const status=$('historyStatus');if(status)status.textContent='HISTORY SOURCE UNAVAILABLE';
  const meta=$('historyMeta');if(meta)meta.textContent='No automatic history was loaded. '+(lastError?lastError.message:'');
}
function applyFilters(rebuildLive=true){
  const product=$('product').value,market=$('market').value;
  state.filtered=state.rows.filter(r=>(product==='all'||r.product===product)&&(market==='all'||r.market===market));
  analyze();
  if(rebuildLive){renderLive();rebuildPredictionDesk();}
}

function runStrategy(){
  const minOdds=Number($('minOdds').value);
  const rows=state.filtered.filter(r=>typeof r.win==='boolean'&&r.odds!=null&&r.odds>=minOdds).sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
  if(rows.length<30){
    $('strategyResult').className='strategyResult empty';
    $('strategyResult').textContent='Not enough priced, settled observations (need at least 30 for this exploratory test).';
    return;
  }
  const parts=split(rows),a=stats(parts.train),b=stats(parts.test);
  $('strategyResult').className='strategyResult';
  $('strategyResult').innerHTML='<div class="resultGrid">'+
    statCard('Eligible rows',rows.length)+statCard('Discovery win rate',fmtPct(a.rate))+statCard('OOS win rate',fmtPct(b.rate))+statCard('OOS ROI',fmtPct(b.roi))+
    '</div><p class="muted">This test does not predict hidden RNG state. It asks whether a simple threshold defined before the unseen sample has remained useful out-of-sample. A positive result needs replication on another untouched period.</p>';
}

$('fileInput').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{state.rows=await parseFile(f);applyFilters(true)}catch(err){alert('Could not parse dataset: '+err.message)}});
$('product').addEventListener('change',applyFilters);
$('market').addEventListener('change',applyFilters);
$('split').addEventListener('change',analyze);
$('runStrategy').addEventListener('click',runStrategy);
$('liveRefresh').addEventListener('click',loadLive);
$('autoBuild').addEventListener('click',autoBuild);
$('clearBuilder').addEventListener('click',function(){state.builder=[];renderBuilder();});
$('clear').addEventListener('click',()=>{state.rows=[];state.filtered=[];state.builder=[];const hs=$('historyStatus');if(hs)hs.textContent='MANUAL DATASET CLEARED';$('fileInput').value='';analyze();renderBuilder()});

analyze();
loadEligibility();
loadHistory();
loadConfirmedWatch().then(()=>loadLive());
window.setInterval(loadLive,LIVE_REFRESH_MS);
window.setInterval(loadHistory,120000);
})();