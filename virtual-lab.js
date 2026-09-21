/* Match Signal Virtual Lab — live data + research analysis */
(function(){
'use strict';

const LIVE_API='https://match-signal.pages.dev/api/sportybet-virtual';
const LIVE_MARKETS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
const SNAPSHOT='./data/virtual_lab_live.json';
const LIVE_REFRESH_MS=30000;
const UI_BUILD='20260921-v12';
const HISTORY='./api/virtual-lab-history';
const HISTORY_FALLBACK='./data/virtual_lab_history.json';
const state={rows:[],filtered:[],live:[],liveMode:'none',liveUpdated:null,picks:[],builder:[],historyLoaded:false,modelRows:[],modelEvents:[]};

const $=id=>document.getElementById(id);
const esc=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML};
const num=v=>{const n=Number(String(v??'').replace('%',''));return Number.isFinite(n)?n:null};
const date=v=>{const d=new Date(v);return isNaN(d.getTime())?String(v||'—'):d.toLocaleString()};
const fmtPct=v=>v==null?'—':(v*100).toFixed(1)+'%';
const fmtNum=v=>v==null?'—':Number(v).toFixed(3);

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
  const home=String(event.homeTeamName||'');
  const away=String(event.awayTeamName||'');
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
  return {product,competition:String(tournament||'Unclassified'),category:String(category||''),event_id:String(event.eventId||''),home,away,start_time:start,match_status:event.matchStatus,markets};
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
    if(!g){g={key,event_id:r.event_id,timestamp:r.timestamp,product:r.product,rows:[],total:scoreTotal(r)};groups.set(key,g);}
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
        const cur=earlier[i],before=earlier.slice(0,i),pprior=productPrior(before,event.product,cur.ladder.points[0].line,new Date(cur.timestamp).getTime());
        if(!pprior.prob||!cur.ladder)continue;
        const p=clamp01((1-a)*poissonOver(cur.ladder.lambda,cur.ladder.points[0].line)+a*pprior.prob);
        const y=cur.total>cur.ladder.points[0].line?1:cur.total<cur.ladder.points[0].line?0:null;
        if(y==null)continue;
        loss+=-(y*Math.log(p)+(1-y)*Math.log(1-p));n++;
      }
      if(n>=10&&loss/n<bestLoss){bestLoss=loss/n;bestN=n;alpha=a;}
    }
  }else if(earlier.length<20){alpha=0;}
  return {alpha,alphaN:bestN,priorN:prior.n};
}
function modelOverForEvent(event,priorEvents,line){
  if(!event||!event.ladder)return null;
  const market=poissonOver(event.ladder.lambda,line);
  const prior=productPrior(priorEvents,event.product,line,new Date(event.timestamp).getTime());
  const blend=blendForEvent(event,priorEvents);
  if(!prior.prob||!blend||blend.alpha<=0)return {prob:market,marketProb:market,priorProb:prior.prob,alpha:0,lambda:event.ladder.lambda,n:prior.n};
  return {prob:clamp01((1-blend.alpha)*market+blend.alpha*prior.prob),marketProb:market,priorProb:prior.prob,alpha:blend.alpha,lambda:event.ladder.lambda,n:prior.n};
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
      outputs.push(Object.assign({},r,{baselineProb:clamp01(baseline),modelProb:clamp01(model),ladderLambda:overModel.lambda,productPriorProb:overModel.priorProb,blendAlpha:overModel.alpha}));
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
  return {all:{baseline:calc('baselineProb'),model:calc('modelProb')},products:Object.fromEntries(Object.entries(by).map(([p,a])=>{const old=valid;const fn=key=>{let b=0,l=0;a.forEach(r=>{const q=clamp01(r[key]),y=r.win?1:0;b+=(y-q)*(y-q);l+=-(y*Math.log(q)+(1-y)*Math.log(1-q));});return {n:a.length,brier:b/a.length,logLoss:l/a.length};};return [p,{baseline:fn('baselineProb'),model:fn('modelProb')}]}))};
}
function renderModelLab(){
  const host=$('modelLab');if(!host)return;
  const rows=state.modelRows||[],scores=scoreProbabilities(rows);
  if(!rows.length){host.innerHTML='<div class="empty">Need settled O/U observations with complete pre-event line data. Collect more events before trusting this model.</div>';return;}
  const cell=(v,d=4)=>v==null?'—':Number(v).toFixed(d);
  const delta=(a,b)=>a==null||b==null?'—':(a-b).toFixed(4);
  let html='<div class="modelGrid"><div><h3>O/U line-ladder model</h3><p class="muted">Fits a Poisson total-goals distribution to the full observed O/U ladder, then blends it with a product-specific historical prior using only earlier settled events. No current-event result is used.</p></div><div><h3>Scoring rules</h3><p class="muted">Brier and log loss are lower-is-better probability losses. The market baseline is the SportyBet de-vig probability; the model must improve on it out-of-sample before becoming eligible.</p></div></div>';
  html+='<table><thead><tr><th>Product</th><th>N</th><th>Market Brier</th><th>Model Brier</th><th>Δ Brier</th><th>Market LogLoss</th><th>Model LogLoss</th><th>Δ LogLoss</th></tr></thead><tbody>';
  Object.entries(scores.products).forEach(([p,s])=>{html+='<tr><td>'+esc(p)+'</td><td>'+s.model.n+'</td><td>'+cell(s.baseline.brier)+'</td><td>'+cell(s.model.brier)+'</td><td>'+delta(s.baseline.brier,s.model.brier)+'</td><td>'+cell(s.baseline.logLoss)+'</td><td>'+cell(s.model.logLoss)+'</td><td>'+delta(s.baseline.logLoss,s.model.logLoss)+'</td></tr>';});
  if(scores.all.model)html+='<tr><td><strong>ALL O/U</strong></td><td>'+scores.all.model.n+'</td><td>'+cell(scores.all.baseline.brier)+'</td><td>'+cell(scores.all.model.brier)+'</td><td>'+delta(scores.all.baseline.brier,scores.all.model.brier)+'</td><td>'+cell(scores.all.baseline.logLoss)+'</td><td>'+cell(scores.all.model.logLoss)+'</td><td>'+delta(scores.all.baseline.logLoss,scores.all.model.logLoss)+'</td></tr>';
  html+='</tbody></table>';
  const qualified=Object.entries(scores.products).filter(([p,s])=>s.model.n>=30&&s.model.brier<s.baseline.brier&&s.model.logLoss<s.baseline.logLoss).map(([p])=>p);
  html+='<p class="muted"><strong>Model gate:</strong> '+(qualified.length?esc(qualified.join(', '))+' currently beats the market on both scoring losses in-sample walk-forward rows. This still requires a fresh untouched validation block before money use.':'NO PRODUCT QUALIFIES YET — the model is research-only.')+'</p>';
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
  return state.historyLoaded && c.calibrationN>=30 && edge>=0.02;
}
function enrichCandidate(c,e){
  const cal=historicalCalibration(e.product,c.marketType,c.pickCode,c.fairProb,e.start_time);
  let calibrated=cal.prob,source=cal.source,modelMeta=null;
  if(c.marketType==='ou'&&e.start_time){
    const ladder=fitLambdaFromLadder((e.markets||[]).map(m=>marketOverPoint(m)).filter(Boolean));
    if(ladder){
      const hist=state.modelRows||[];
      const priorEvents=historicalOUEvents(state.rows);
      const pseudo={product:e.product,timestamp:e.start_time,ladder,total:null};
      const mm=modelOverForEvent(pseudo,priorEvents,Number(c.market.line));
      if(mm){
        const overSelected=String(c.pickCode).toUpperCase().startsWith('U')?1-mm.prob:mm.prob;
        calibrated=overSelected;
        source='ou-line-ladder-product-model';
        modelMeta=mm;
      }
    }
  }
  return Object.assign(c,{calibratedProb:calibrated,calibrationN:cal.n,calibrationSource:source,edge:calibrated-c.bookImplied,modelMeta});
}
function predictionForEvent(e){
  const candidates=[];
  (e.markets||[]).forEach(m=>{
    const id=String(m.id||''),name=String(m.name||'').toLowerCase();
    const isWinner=id==='1'||id==='186'||name.indexOf('1x2')>=0||name.indexOf('winner')>=0||name.indexOf('match result')>=0;
    const isTotals=id==='18'||id==='189'||name.indexOf('over/under')>=0||name.indexOf('total')>=0;
    if(!isWinner&&!isTotals)return;
    const c=calculateMarket(m);
    if(c){c.marketType=isTotals?'ou':'winner';candidates.push(c);}
  });
  if(!candidates.length)return null;
  const winner=candidates.filter(x=>x.marketType==='winner').sort((a,b)=>b.fairProb-a.fairProb)[0]||null;
  const ou=candidates.filter(x=>x.marketType==='ou').sort((a,b)=>b.fairProb-a.fairProb)[0]||null;
  const enriched=candidates.map(c=>enrichCandidate(c,e));
  enriched.sort((a,b)=>(b.calibratedProb-b.bookImplied)-(a.calibratedProb-a.bookImplied)||b.calibratedProb-a.calibratedProb);
  const primary=enriched[0]||null;
  const winnerEnriched=enriched.filter(x=>x.marketType==='winner').sort((a,b)=>b.calibratedProb-a.calibratedProb)[0]||null;
  const ouEnriched=enriched.filter(x=>x.marketType==='ou').sort((a,b)=>b.calibratedProb-a.calibratedProb)[0]||null;
  return {product:e.product,competition:e.competition||e.tournament||'',event_id:String(e.event_id||e.eventId||''),home:String(e.home||e.participant_1||''),away:String(e.away||e.participant_2||''),start_time:e.start_time||null,primary:qualifiesResearchPick(primary)?primary:null,bestWinner:winnerEnriched,bestOU:ouEnriched,candidates:enriched};
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
  const events=upcomingEventsFrom(state.live).filter(e=>product==='all'||e.product===product);
  const list=events.slice(0,30).map(e=>{
    const p=predictionForEvent(e);
    const shown=(e.markets||[]).filter(m=>matchesMarket(m,market)).slice(0,3);
    const chips=shown.flatMap(m=>(m.outcomes||[]).slice(0,4).map(o=>'<span class="liveChip"><span>'+esc(outcomeCode(m,o))+'</span> <b>'+Number(o.odds).toFixed(2)+'</b></span>')).join('');
    const pick=p&&p.primary?'<div class="predictionBox"><div class="predictionTop"><span class="predictionLabel">RESEARCH PICK</span><span class="predictionType">'+(p.primary.marketType==='ou'?'TOTALS':'MATCH RESULT')+'</span></div><div class="predictionPick">'+esc(p.primary.pickCode)+' <b>'+fmtPct(p.primary.calibratedProb)+'</b></div><div class="predictionMeta">Book '+p.primary.bookmakerOdds.toFixed(2)+' · Edge '+fmtPct(p.primary.edge)+' · n='+p.primary.calibrationN+'</div></div>':'<div class="predictionBox mutedPrediction"><div class="predictionLabel">NO QUALIFIED SIGNAL</div><div class="predictionPick">MARKET BASELINE ONLY</div><div class="predictionMeta">Needs ≥30 historical calibration observations and ≥2% calibrated edge.</div></div>';
    return '<article class="liveCard"><div class="liveTop"><span>'+esc(e.competition||e.product)+'</span><span>'+esc(e.start_time?date(e.start_time):'Time n/a')+'</span></div><div class="liveTeams"><strong>'+esc(e.home||e.participant_1||'Unknown player/team')+'</strong> <span>vs</span> <strong>'+esc(e.away||e.participant_2||'Unknown player/team')+'</strong></div>'+pick+'<div class="liveOdds">'+(chips||'<span class="liveMeta">No readable markets</span>')+'</div></article>';
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
      return '<div class="calcRow"><span>'+label+(x.market.line!=null?' '+x.market.line:'')+'</span><b>'+esc(x.pickCode)+'</b><span>'+fmtPct(x.fairProb)+'</span><span>Fair '+x.fairOdds.toFixed(2)+'</span><span>Book '+x.bookmakerOdds.toFixed(2)+'</span></div>';
    }
    const primaryHtml=p.primary?'<div class="primaryPick"><span>RESEARCH QUALIFIED</span><strong>'+esc(p.primary.pickCode)+'</strong><b>'+fmtPct(p.primary.calibratedProb)+'</b><small>edge '+fmtPct(p.primary.edge)+' · n='+p.primary.calibrationN+'</small></div>':'<div class="primaryPick mutedPrediction"><span>NO QUALIFIED SIGNAL</span><strong>WAIT</strong><b>Market baseline only</b></div>';
    const addLabel=p.primary?'＋ Add qualified pick':'Locked · no qualified signal';
    return '<article class="predictionCard"><div class="predictionHeader"><div><small>'+esc(p.product)+' · '+esc(p.competition)+'</small><h3>'+esc(p.home)+' <span>vs</span> '+esc(p.away)+'</h3></div><time>'+esc(p.start_time?date(p.start_time):'—')+'</time></div>'+primaryHtml+'<div class="calcTable"><div class="calcHead"><span>Market</span><span>Pick</span><span>Probability</span><span>Fair odds</span><span>SportyBet</span></div>'+row(p.bestWinner,'1X2')+row(p.bestOU,'O/U')+'</div><div class="calcNote">Displayed probabilities are the SportyBet de-vig market baseline. A research pick is shown only after historical calibration and edge gates pass. This is not a guarantee.</div><button class="btn builderAdd" data-pick="'+i+'" '+(p.primary?'':'disabled')+'>'+addLabel+'</button></article>';
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
        const r=await fetch(base+'?'+params.toString(),{cache:'no-store',headers:{'Accept':'application/json'}});
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
  const r=await fetch(SNAPSHOT,{cache:'no-store'});
  if(!r.ok)throw new Error('Live snapshot HTTP '+r.status);
  const body=await r.json();
  const events=(Array.isArray(body.events)?body.events:[]).map(e=>({
    ...e,
    home:String(e.home||e.participant_1||e.homeTeamName||''),
    away:String(e.away||e.participant_2||e.awayTeamName||''),
    event_id:String(e.event_id||e.eventId||''),
    start_time:e.start_time||null,
    match_status:e.match_status||e.matchStatus||null,
    markets:Array.isArray(e.markets)?e.markets:[]
  })).filter(e=>e.event_id);
  return {events,updated_at:body.updated_at||null};
}

async function loadLive(){
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
  }finally{button.disabled=false}
}

function rebuildPredictionDesk(){
  state.picks=upcomingEventsFrom(state.live).map(predictionForEvent).filter(Boolean);
  const product=$('product').value;
  if(product!=='all')state.picks=state.picks.filter(function(p){return p.product===product;});
  renderPredictionDesk();renderBuilder();
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
      buildModelBacktest(state.rows);
      applyFilters(false);
      rebuildPredictionDesk();
      renderModelLab();
      const status=$('historyStatus');if(status)status.textContent='AUTO-COLLECTED · '+arr.length+' settled observations';
      const meta=$('historyMeta');if(meta)meta.textContent='Historical rows are collected automatically from the Virtual Lab paper pipeline. Latest refresh '+new Date().toLocaleString();
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
loadHistory();
loadLive();
window.setInterval(loadLive,LIVE_REFRESH_MS);
window.setInterval(loadHistory,120000);
})();