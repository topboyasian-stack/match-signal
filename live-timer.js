(function(){
  'use strict';
  const pad=n=>String(n).padStart(2,'0');
  const format=ms=>{
    const total=Math.max(0,Math.floor(ms/1000));
    const h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60;
    return h ? `${h}h ${pad(m)}m ${pad(s)}s` : `${m}m ${pad(s)}s`;
  };
  const normalise=v=>String(v||'').toLowerCase().replace(/\s+/g,' ').trim();
  const state={predictions:[],history:[]};
  const cache={};

  async function loadJson(path){
    try{
      const u=new URL(`./${path}`,location.href);
      u.searchParams.set('v',Date.now());
      const r=await fetch(u.href,{cache:'no-store'});
      return r.ok?await r.json():[];
    }catch(e){ return []; }
  }

  function matchRecord(card){
    const teams=card.querySelector('.teams');
    if(!teams) return null;
    const text=normalise(teams.textContent);
    const source=[...state.history,...state.predictions];
    return source.find(p=>{
      const a=normalise(p.player_1),b=normalise(p.player_2);
      return a && b && text.includes(a) && text.includes(b);
    }) || null;
  }

  function ensure(card){
    let badge=card.querySelector('.live-timer');
    if(!badge){
      badge=document.createElement('span');
      badge.className='live-timer';
      const meta=card.querySelector('.meta');
      if(meta) meta.insertBefore(badge,meta.firstChild);
    }
    return badge;
  }

  function update(){
    document.querySelectorAll('.card').forEach(card=>{
      const badge=ensure(card), p=matchRecord(card);
      if(!badge || !p) return;
      if(p.settled){
        const score=p.final_score||[];
        badge.textContent=`FT ${score.length>=2?score[0]+'–'+score[1]:''}`.trim();
        badge.classList.remove('live');
        badge.classList.add('finished');
        return;
      }
      const start=new Date(p.start_time);
      if(Number.isNaN(start.getTime())) return;
      const diff=start.getTime()-Date.now();
      if(diff>0){
        badge.textContent=`STARTS IN ${format(diff)}`;
        badge.classList.remove('live','finished');
      }else{
        badge.textContent=`● LIVE ${format(-diff)}`;
        badge.classList.add('live');
        badge.classList.remove('finished');
      }
    });
  }

  async function refreshData(){
    const [predictions,history]=await Promise.all([
      loadJson('data/predictions.json'),
      loadJson('data/prediction_history.json')
    ]);
    state.predictions=Array.isArray(predictions)?predictions:[];
    state.history=Array.isArray(history)?history.filter(p=>p.settled):[];
    update();
  }

  const style=document.createElement('style');
  style.textContent='.live-timer{font-weight:800;letter-spacing:.04em;color:var(--amber);margin-right:auto}.live-timer.live{color:var(--green)}.live-timer.finished{color:var(--muted)}';
  document.head.appendChild(style);
  new MutationObserver(update).observe(document.body,{childList:true,subtree:true});
  refreshData();
  setInterval(update,1000);
  setInterval(refreshData,30000);
})();
