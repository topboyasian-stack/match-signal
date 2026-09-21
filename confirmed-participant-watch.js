/* Confirmed participant watch layer — exact identities only. */
(function(){
'use strict';
const WATCH='./data/virtual_lab_confirmed_participants.json';
let watch=null;
const norm=v=>String(v||'').trim().casefold?String(v||'').trim().toLowerCase():String(v||'').trim().toLowerCase();
async function load(){
  try{const r=await fetch(WATCH+'?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('watchlist HTTP '+r.status);watch=await r.json();renderPanel();annotate();setInterval(annotate,5000);}
  catch(e){console.warn('Confirmed participant watch layer:',e);}
}
function match(name,product){
  const n=norm(name);
  return (watch?.participants||[]).filter(x=>norm(x.participant)===n && (!x.product||x.product===product||x.product==='all'));
}
function badge(text,cls){
  const s=document.createElement('span');s.className='confirmedWatchTag '+(cls||'');s.textContent=text;return s;
}
function annotate(){
  if(!watch)return;
  document.querySelectorAll('.liveTeams').forEach(el=>{
    const strong=[...el.querySelectorAll('strong')];
    strong.forEach(node=>{
      const product=el.closest('.liveCard')?.querySelector('.liveTop span')?.textContent||'';
      const hits=match(node.textContent,'efootball_gt');
      if(!hits.length)return;
      if(!node.parentElement.querySelector('.confirmedWatchTag'))node.insertBefore(badge('🔥 MONITORED'),node);
    });
  });
  document.querySelectorAll('.predictionDesk .predictionCard').forEach(card=>{
    const text=card.textContent||'';
    const hits=(watch.participants||[]).filter(x=>text.includes(x.participant));
    if(hits.length&&!card.querySelector('.confirmedWatchTag'))card.prepend(badge('🔥 MONITORED','deskWatch'));
  });
}
function renderPanel(){
  const host=document.getElementById('participantLab');if(!host)return;
  const existing=document.getElementById('confirmedWatchPanel');if(existing)existing.remove();
  const panel=document.createElement('div');panel.id='confirmedWatchPanel';panel.className='confirmedWatchPanel';
  const title=document.createElement('div');title.innerHTML='<strong>🔥 Confirmed participant watch</strong><span>Exact identities only · original ticket outcomes excluded from training</span>';panel.appendChild(title);
  const ul=document.createElement('div');ul.className='confirmedWatchList';
  (watch.participants||[]).forEach(x=>{const item=document.createElement('span');item.className='confirmedWatchItem';item.textContent=x.participant;ul.appendChild(item);});
  panel.appendChild(ul);
  const note=document.createElement('p');note.className='muted';note.textContent='When an exact identity reappears, the watch layer highlights it. Subsequent automatic settled results are tracked separately and may later contribute to participant recurrence only after time-safe evidence accumulates.';
  panel.appendChild(note);
  host.parentNode.insertBefore(panel,host);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load);else load();
})();
