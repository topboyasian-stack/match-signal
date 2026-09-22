/* Independent live renderer for the Virtual Lab.
   Deliberately does not depend on virtual-lab.js so a research-engine parse/runtime
   failure cannot blank the live SportyBet fixture panel. */
(function(){
  'use strict';

  const API='./api/sportybet-virtual';
  const REFRESH_MS=30000;

  function $(id){return document.getElementById(id);}
  function esc(v){
    const d=document.createElement('div');
    d.textContent=String(v==null?'':v);
    return d.innerHTML;
  }
  function epochMs(v){
    const n=Number(v);
    if(!Number.isFinite(n)||n<=0)return null;
    return n<100000000000?n*1000:n;
  }
  function startMs(e){
    const n=epochMs(e&&e.start_time_ms);
    if(n!=null)return n;
    const p=epochMs(e&&e.estimateStartTime);
    if(p!=null)return p;
    const t=Date.parse(e&&e.start_time||'');
    return Number.isFinite(t)?t:null;
  }
  function localTime(ms){
    return ms==null?'Time unavailable':new Date(ms).toLocaleString();
  }
  function product(e){
    const p=String(e&&e.product||'').toLowerCase();
    if(p)return p;
    const blob=String((e&&e.tournament)||'')+' '+String((e&&e.category)||'');
    return /eadriatic/i.test(blob)?'efootball_adriatic':'efootball_gt';
  }
  function outcomeCode(m,o){
    const name=String(o&& (o.name||o.desc||o.title) || '').trim();
    const line=m&&m.line!=null?String(m.line):'';
    if(/^over/i.test(name))return 'O'+line;
    if(/^under/i.test(name))return 'U'+line;
    if(/^home$/i.test(name))return '1';
    if(/^draw$/i.test(name))return 'X';
    if(/^away$/i.test(name))return '2';
    return name;
  }
  function render(body){
    const raw=Array.isArray(body&&body.events)?body.events:[];
    // Backend already applies the authoritative upcoming/live window. Do not re-filter here.
    const events=raw.map(e=>Object.assign({},e,{_start:startMs(e),_product:product(e)}))
      
      .sort((a,b)=>(a._start||0)-(b._start||0))
      .slice(0,30);

    const grid=$('liveGrid'),empty=$('liveEmpty'),dot=$('liveDot'),title=$('liveTitle'),meta=$('liveMeta');
    if(!grid)return;

    if(!events.length){
      grid.innerHTML='';
      if(empty)empty.hidden=false;
      if(dot)dot.className='liveDot bad';
      if(title)title.textContent='SOURCE CONNECTED · NO UPCOMING EVENTS';
      if(meta)meta.textContent='API returned '+raw.length+' events, but none passed the 2-minute time window. The feed is being retried.';
      return;
    }

    if(empty)empty.hidden=true;
    if(dot)dot.className='liveDot';
    if(title)title.textContent='LIVE SOURCE ONLINE · '+events.length+' UPCOMING EVENTS';

    const counts={};
    events.forEach(e=>counts[e._product]=(counts[e._product]||0)+1);
    if(meta)meta.textContent='SportyBet NG · '+Object.entries(counts).map(([k,v])=>k+': '+v).join(' · ')+' · '+new Date().toLocaleTimeString();

    grid.innerHTML=events.map(e=>{
      const markets=Array.isArray(e.markets)?e.markets:[];
      const chips=markets.slice(0,4).flatMap(m=>{
        const outs=Array.isArray(m.outcomes)?m.outcomes:[];
        return outs.slice(0,4).map(o=>{
          const odds=Number(o.odds);
          return Number.isFinite(odds)?'<span class="liveChip"><span>'+esc(outcomeCode(m,o))+'</span> <b>'+odds.toFixed(2)+'</b></span>':'';
        });
      }).join('');
      const p1=String(e.participant_1||'').trim(),p2=String(e.participant_2||'').trim();
      const identity=(p1||p2)
        ?'<div class="participantIdentityLine"><span class="participantIdentityLabel">STABLE PARTICIPANT</span><strong>'+esc(p1||'UNVERIFIED')+'</strong><span>vs</span><strong>'+esc(p2||'UNVERIFIED')+'</strong><span class="participantIdentityStatus">'+(p1&&p2?'✓ VERIFIED':'⚠ PARTIAL')+'</span></div>'
        :'';
      return '<article class="liveCard">'+
        '<div class="liveTop"><span>'+esc(e.tournament||e.category||e._product)+'</span><span>'+esc(localTime(e._start))+'</span></div>'+
        '<div class="liveTeams"><strong>'+esc(e.team_1||e.home||'Unknown')+'</strong> <span>vs</span> <strong>'+esc(e.team_2||e.away||'Unknown')+'</strong>'+identity+'</div>'+
        '<div class="liveOdds">'+(chips||'<span class="liveMeta">Markets returned without readable odds</span>')+'</div>'+
        '<div class="liveMeta">Event '+esc(e.event_id||'—')+' · '+esc(e._product)+'</div>'+
      '</article>';
    }).join('');

    const pc=$('predictionCount');
    if(pc)pc.textContent=String(events.length);
    const desk=$('predictionDesk');
    if(desk && (!desk.children.length || /Waiting for live/i.test(desk.textContent))){
      desk.innerHTML='<div class="empty">Live fixtures are now connected. The research engine will populate qualified predictions when its analysis bundle is available.</div>';
    }
  }

  async function load(){
    const meta=$('liveMeta');
    try{
      const q=new URLSearchParams({pageSize:'100',pageNum:'1',timeline:'168',sources:'efootball,vfootball',_t:String(Date.now())});
      const r=await fetch(API+'?'+q,{cache:'no-store',headers:{Accept:'application/json'}});
      if(!r.ok)throw new Error('HTTP '+r.status);
      const body=await r.json();
      render(body);
    }catch(err){
      const dot=$('liveDot'),title=$('liveTitle');
      if(dot)dot.className='liveDot bad';
      if(title)title.textContent='LIVE SOURCE ERROR';
      if(meta)meta.textContent='SportyBet feed error · '+err.message+' · retrying automatically';
    }
  }

  function boot(){
    load();
    window.setInterval(load,REFRESH_MS);
    const btn=$('liveRefresh');
    if(btn)btn.addEventListener('click',load);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();