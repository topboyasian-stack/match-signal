(function(){
  'use strict';
  const pad=n=>String(n).padStart(2,'0');
  const format(ms)=>{
    const total=Math.max(0,Math.floor(ms/1000));
    const h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60;
    return h ? `${h}h ${pad(m)}m ${pad(s)}s` : `${m}m ${pad(s)}s`;
  };
  const readStart=card=>{
    const meta=card.querySelector('.meta span:last-child');
    if(!meta) return null;
    const d=new Date(meta.dataset.startTime || meta.textContent.trim());
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const ensure=card=>{
    let badge=card.querySelector('.live-timer');
    if(!badge){
      badge=document.createElement('span');
      badge.className='live-timer';
      const meta=card.querySelector('.meta');
      if(meta) meta.insertBefore(badge,meta.firstChild);
    }
    return badge;
  };
  const update=()=>document.querySelectorAll('.card').forEach(card=>{
    const start=readStart(card), badge=ensure(card);
    if(!start || !badge) return;
    const diff=start.getTime()-Date.now();
    if(diff>0){
      badge.textContent=`STARTS IN ${format(diff)}`;
      badge.classList.remove('live');
    }else{
      badge.textContent=`● LIVE ${format(-diff)}`;
      badge.classList.add('live');
    }
  });
  const style=document.createElement('style');
  style.textContent='.live-timer{font-weight:800;letter-spacing:.04em;color:var(--amber);margin-right:auto}.live-timer.live{color:var(--green)}.live-timer.live::first-letter{font-size:10px}';
  document.head.appendChild(style);
  new MutationObserver(update).observe(document.body,{childList:true,subtree:true});
  update();
  setInterval(update,1000);
})();
