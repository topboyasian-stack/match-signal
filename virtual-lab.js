(function(){
'use strict';
const state={rows:[], filtered:[]};
const $=id=>document.getElementById(id);
const esc=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML};
const num=v=>{const n=Number(String(v??'').replace('%',''));return Number.isFinite(n)?n:null};
const date=v=>{const d=new Date(v);return isNaN(d.getTime())?String(v||'—'):d.toLocaleString()};
function normalize(r){
  const x={...r};
  x.product=String(x.product||'other').toLowerCase().trim();
  x.market=String(x.market||'other').toLowerCase().trim();
  x.timestamp=x.timestamp||x.date||x.datetime||'';
  x.odds=num(x.odds);
  x.result=String(x.result??'').trim().toLowerCase();
  x.selection=String(x.selection??'').trim().toLowerCase();
  if(x.win===''||x.win==null){
    if(x.selection && x.result) x.win=x.selection===x.result;
    else x.win=null;
  } else x.win=String(x.win).toLowerCase()==='true'||String(x.win)==='1';
  x.model_prob=num(x.model_prob||x.probability);
  return x;
}
function parseCSV(text){
  const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).filter(Boolean);
  if(!lines.length) return [];
  const parseLine=line=>{
    const out=[];let cur='',quote=false;
    for(let i=0;i<line.length;i++){const c=line[i];if(c==='"'){if(quote&&line[i+1]==='"'){cur+='"';i++;}else quote=!quote;}else if(c===','&&!quote){out.push(cur);cur='';}else cur+=c}
    out.push(cur);return out;
  };
  const headers=parseLine(lines[0]).map(h=>h.trim());
  return lines.slice(1).map(line=>{const vals=parseLine(line);const o={};headers.forEach((h,i)=>o[h]=vals[i]??'');return normalize(o)});
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
function applyFilters(){
  const product=$('product').value,market=$('market').value;
  state.filtered=state.rows.filter(r=>(product==='all'||r.product===product)&&(market==='all'||r.market===market));
  analyze();
}
function stats(rows){
  const valid=rows.filter(r=>typeof r.win==='boolean');
  const wins=valid.filter(r=>r.win).length;
  let roi=null;
  const priced=valid.filter(r=>r.odds&&r.odds>=1);
  if(priced.length) roi=priced.reduce((s,r)=>s+(r.win?(r.odds-1):-1),0)/priced.length;
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
  let prevWin=[],prevLoss=[];
  for(let i=1;i<v.length;i++){if(v[i-1].win)prevWin.push(v[i].win);else prevLoss.push(v[i].win)}
  const p=a=>a.length?a.filter(Boolean).length/a.length:null;
  const a=p(prevWin),b=p(prevLoss);
  return {n:v.length,afterWin:a,afterLoss:b,delta:a!=null&&b!=null?a-b:null};
}
function productTable(rows){
  const groups={};
  rows.forEach(r=>{(groups[r.product]??=[]).push(r)});
  const data=Object.entries(groups).map(([product,arr])=>({product,all:stats(arr),oos:stats(split(arr).test)}))
    .sort((a,b)=>(b.oos.rate??-1)-(a.oos.rate??-1));
  if(!data.length)return '<div class="empty">No completed win/loss observations in the selected data.</div>';
  return '<table><thead><tr><th>Product</th><th>Rounds</th><th>Win rate</th><th>OOS rate</th><th>Paper ROI</th></tr></thead><tbody>'+
    data.map(x=>'<tr><td>'+esc(x.product)+'</td><td>'+x.all.valid+'</td><td>'+fmtPct(x.all.rate)+'</td><td>'+fmtPct(x.oos.rate)+'</td><td>'+fmtPct(x.oos.roi)+'</td></tr>').join('')+
    '</tbody></table>';
}
function fmtPct(v){return v==null?'—':(v*100).toFixed(1)+'%'}
function fmtNum(v){return v==null?'—':Number(v).toFixed(3)}
function analyze(){
  const rows=state.filtered;
  const s=stats(rows),parts=split(rows),oos=stats(parts.test),sq=seq(rows);
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
function wilsonLower(successes,n,z=1.96){
  if(!n)return null;
  const phat=successes/n,denom=1+z*z/n,centre=phat+z*z/(2*n),spread=z*Math.sqrt((phat*(1-phat)+z*z/(4*n))/n);
  return (centre-spread)/denom;
}
function runStrategy(){
  const minOdds=Number($('minOdds').value);
  const rows=state.filtered.filter(r=>typeof r.win==='boolean'&&r.odds!=null&&r.odds>=minOdds).sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
  if(rows.length<30){$('strategyResult').className='strategyResult empty';$('strategyResult').textContent='Not enough priced, settled observations (need at least 30 for this exploratory test).';return}
  const parts=split(rows),a=stats(parts.train),b=stats(parts.test);
  $('strategyResult').className='strategyResult';
  $('strategyResult').innerHTML='<div class="resultGrid">'+
    statCard('Eligible rows',rows.length)+statCard('Discovery win rate',fmtPct(a.rate))+statCard('OOS win rate',fmtPct(b.rate))+statCard('OOS ROI',fmtPct(b.roi))+
    '</div><p class="muted">This test does not predict hidden RNG state. It asks whether a simple threshold defined before the unseen sample has remained useful out-of-sample. A positive result needs replication on another untouched period.</p>';
}
function statCard(title,value){return '<div class="resultStat"><small>'+esc(title)+'</small><b>'+esc(value)+'</b></div>'}
$('fileInput').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{state.rows=await parseFile(f);applyFilters()}catch(err){alert('Could not parse dataset: '+err.message)}});
$('product').addEventListener('change',applyFilters);$('market').addEventListener('change',applyFilters);$('split').addEventListener('change',analyze);$('runStrategy').addEventListener('click',runStrategy);
$('clear').addEventListener('click',()=>{state.rows=[];state.filtered=[];$('fileInput').value='';analyze()});
analyze();
})();