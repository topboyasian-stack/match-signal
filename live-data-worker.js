/* Client-side live data helpers. PAPER ONLY. */
(function(){'use strict';
const pad=n=>String(Math.max(0,Math.floor(Number(n)||0))).padStart(2,'0');
window.MatchSignalLiveData={
  formatClock:function(e){
    const s=e?.status||{}; const t=s.type||{};
    const desc=String(t.description||t.shortDetail||s.description||'');
    if(/half.?time|halftime|interval|break/i.test(desc))return 'HALFTIME BREAK';
    if(/end of|final|full time|game over/i.test(desc))return desc.toUpperCase();
    return s.displayClock||s.clock||t.shortDetail||t.description||'—';
  },
  isBreak:function(e){
    const s=e?.status||{},t=s.type||{}; const text=[t.description,t.shortDetail,s.description].filter(Boolean).join(' ');
    return /half.?time|halftime|interval|break/i.test(text);
  },
  kickoff:function(p){if(!p?.start_time)return '—';const d=new Date(p.start_time);return d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});},
  elapsed:function(p,e){
    const t=new Date(p?.start_time||0).getTime(); if(!t)return '—';
    if(this.isBreak(e))return 'HALFTIME BREAK';
    const now=Date.now(), sec=Math.max(0,Math.floor((now-t)/1000));
    return Math.floor(sec/60)+':'+pad(sec%60)+' elapsed';
  },
  clockAge:function(lastFetch){return lastFetch?Math.max(0,Math.floor((Date.now()-lastFetch)/1000))+'s since refresh':'—';}
};
})();
