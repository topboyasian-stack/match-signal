/* Match Signal Virtual Lab v1 — confirmed eFootball watch only. */
(function(){
'use strict';
const WATCH='/data/virtual_lab_participants/efootball_confirmed_watch.json';
const PRODUCT='efootball_gt';
let watch=null;
const norm=v=>String(v||'').trim().toLowerCase();
const identity=v=>{const s=String(v||'').trim();const m=s.match(/\(([^()]+)\)\s*$/);return m&&m[1].trim()?m[1].trim():s;};

async function load(){
  try{
    const r=await fetch(WATCH+'?v=VL-V1-20260922&t='+Date.now(),{cache:'no-store',headers:{'Accept':'application/json'}});
    if(!r.ok)throw new Error('watchlist HTTP '+r.status);
    watch=await r.json();
    watch.participants=(Array.isArray(watch.participants)?watch.participants:[]).filter(x=>x&&x.product===PRODUCT);
    renderPanel();
    annotate();
    setInterval(annotate,5000);
  }catch(e){console.warn('Virtual Lab confirmed eFootball watch layer:',e);}
}
function match(name){
  const n=norm(identity(name));
  return (watch?.participants||[]).filter(x=>norm(identity(x.participant))===n);
}
function badge(text,cls){
  const s=document.createElement('span');s.className='confirmedWatchTag '+(cls||'');s.textContent=text;return s;
}
function annotate(){
  if(!watch)return;
  document.querySelectorAll('.liveCard').forEach(card=>{
    const teams=card.querySelector('.liveTeams');if(!teams)return;
    const product=String(card.dataset.product||'');
    if(product!==PRODUCT)return;
    teams.querySelectorAll('strong').forEach(node=>{
      if(!match(node.textContent).length)return;
      if(!node.parentElement.querySelector('.confirmedWatchTag'))node.insertBefore(badge('🔥 MANUAL WATCH'),node);
    });
  });
  document.querySelectorAll('.predictionDesk .predictionCard').forEach(card=>{
    if(String(card.dataset.product||'')!==PRODUCT)return;
    const text=card.textContent||'';
    const hits=(watch.participants||[]).some(x=>text.split(/\\s+vs\\s+/i).map(identity).map(norm).includes(norm(identity(x.participant))));
    if(hits&&!card.querySelector('.confirmedWatchTag'))card.prepend(badge('🔥 MONITORED','deskWatch'));
  });
}
function renderPanel(){
  const host=document.getElementById('participantLab');if(!host)return;
  const existing=document.getElementById('confirmedWatchPanel');if(existing)existing.remove();
  const panel=document.createElement('div');panel.id='confirmedWatchPanel';panel.className='confirmedWatchPanel';
  const title=document.createElement('div');title.innerHTML='<strong>🔥 Manual eFootball annotations</strong><span>Optional GT Sports League annotations</span>';panel.appendChild(title);
  const ul=document.createElement('div');ul.className='confirmedWatchList';
  (watch.participants||[]).forEach(x=>{const item=document.createElement('span');item.className='confirmedWatchItem';item.textContent=x.participant;ul.appendChild(item);});
  panel.appendChild(ul);
  const note=document.createElement('p');note.className='muted';note.textContent='These are optional manual annotations only. They do not define participant discovery, prediction eligibility, Builder access, or the automatic participant lifecycle. Automatic discovery comes from the current SportyBet live/upcoming feed plus settled results.';
  panel.appendChild(note);
  host.parentNode.insertBefore(panel,host);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load);else load();
})();
