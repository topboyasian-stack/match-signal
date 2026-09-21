/* Match Signal Virtual Lab — live data + research analysis */
(function(){
'use strict';

const LIVE_API='https://match-signal.pages.dev/api/sportybet-virtual';
const LIVE_MARKETS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
const SNAPSHOT='./data/virtual_lab_live.json';
const LIVE_REFRESH_MS=30000;
const state={rows:[],filtered:[],live:[],liveMode:'none',liveUpdated:null};

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

function split(rows){
  const ordered=[...rows].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
  const pct=Number($('split').value),cut=Math.floor(ordered.length*pct);
  return {train:ordered.slice(0,cut),test:ordered.slice(cut)};
}

function seq(rows){
  const v=rows.filter(r=>typeof r.win==='boolean').sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
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
      '<tr><td>Rows used</td><td>'+sq.n+'</td></tr><tr><td>P(win next | previous win)</td><td>'+fmtPct(sq.afterWin)+'</td></tr><tr><td>P(win next | previous loss)</td><td>'+fmtPct(sq.afterLoss)+'</td></tr><tr><td>Conditional delta</td><td>'+fmtPct(sq.delta)+'</td></tr></tbody></table>'+
      '<p class="muted">A non-zero delta is only an investigation trigger. It must survive unseen testing before a rule is trusted.</p>';
  }else $('sequence').innerHTML='Need at least 3 settled observations.';
  $('oosLabel').textContent=parts.test.length+' rows';
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

function renderLive(){
  const product=$('product').value,market=$('market').value;
  const events=state.live.filter(e=>(product==='all'||e.product===product));
  const now=Date.now();
  const sorted=[...events].sort((a,b)=>{
    const aLive=a.start_time&&new Date(a.start_time).getTime()<=now?0:1;
    const bLive=b.start_time&&new Date(b.start_time).getTime()<=now?0:1;
    return aLive-bLive||((new Date(a.start_time||0).getTime())-(new Date(b.start_time||0).getTime()));
  });
  const list=sorted.map(e=>{
    const markets=e.markets.filter(m=>matchesMarket(m,market)).slice(0,3);
    const chips=markets.flatMap(m=>m.outcomes.slice(0,4).map(o=>
      '<span class="liveChip"><span>'+esc(shortOutcome(o.name))+'</span> <b>'+Number(o.odds).toFixed(2)+'</b></span>'
    )).join('');
    const line=markets.map(m=>m.line!=null?' '+m.line:'').filter(Boolean)[0]||'';
    return '<article class="liveCard"><div class="liveTop"><span>'+esc(e.competition||e.product)+'</span><span>'+esc((e.start_time?date(e.start_time):'Time n/a')+line)+'</span></div>'+
      '<div class="liveTeams">'+esc(e.home)+' <span>vs</span> '+esc(e.away)+'</div>'+
      '<div class="liveOdds">'+(chips||'<span class="liveMeta">Markets returned without readable odds</span>')+'</div></article>';
  }).slice(0,30);
  $('liveGrid').innerHTML=list.join('');
  $('liveEmpty').hidden=!!list.length;
  if(state.liveMode==='remote'){
    $('liveDot').className='liveDot';
    $('liveTitle').textContent='LIVE SOURCE ONLINE';
  }else if(state.liveMode==='snapshot'){
    $('liveDot').className='liveDot wait';
    $('liveTitle').textContent='SNAPSHOT FALLBACK';
  }else{
    $('liveDot').className='liveDot wait';
    $('liveTitle').textContent='CONNECTING TO LIVE SOURCE…';
  }
  const counts={};
  state.live.forEach(e=>counts[e.product]=(counts[e.product]||0)+1);
  const countText=Object.entries(counts).map(([k,v])=>k+': '+v).join(' · ')||'0 virtual events';
  $('liveMeta').textContent=(state.liveUpdated?'Feed timestamp '+date(state.liveUpdated)+' · ':'')+countText;
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
  return {events:Array.isArray(body.events)?body.events:[],updated_at:body.updated_at||null};
}

async function loadLive(){
  const button=$('liveRefresh');
  button.disabled=true;
  try{
    const live=await fetchLiveRemote();
    state.live=live.events;
    state.liveMode='remote';
    state.liveUpdated=live.updated_at;
    renderLive();
    $('liveMeta').textContent='LIVE · '+$('liveMeta').textContent+' · '+live.endpoint;
    return;
  }catch(remoteError){
    try{
      const snap=await fetchLiveSnapshot();
      const ageMs=snap.updated_at?Date.now()-new Date(snap.updated_at).getTime():Infinity;
      if(!snap.events.length)throw new Error('snapshot has zero events');
      state.live=snap.events;
      state.liveMode='snapshot';
      state.liveUpdated=snap.updated_at;
      renderLive();
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

function applyFilters(){
  const product=$('product').value,market=$('market').value;
  state.filtered=state.rows.filter(r=>(product==='all'||r.product===product)&&(market==='all'||r.market===market));
  analyze();
  renderLive();
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

$('fileInput').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{state.rows=await parseFile(f);applyFilters()}catch(err){alert('Could not parse dataset: '+err.message)}});
$('product').addEventListener('change',applyFilters);
$('market').addEventListener('change',applyFilters);
$('split').addEventListener('change',analyze);
$('runStrategy').addEventListener('click',runStrategy);
$('liveRefresh').addEventListener('click',loadLive);
$('clear').addEventListener('click',()=>{state.rows=[];state.filtered=[];$('fileInput').value='';analyze()});

analyze();
loadLive();
window.setInterval(loadLive,LIVE_REFRESH_MS);
})();