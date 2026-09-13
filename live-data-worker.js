/* Client-side live data worker helpers. PAPER ONLY. */
(function(){'use strict';
window.MatchSignalLiveData={
  formatClock:function(e){const s=e?.status||{};return s.displayClock||s.clock||s.type?.shortDetail||s.type?.description||'—';},
  kickoff:function(p){if(!p?.start_time)return '—';const d=new Date(p.start_time);return d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});},
  elapsed:function(p,e){const t=new Date(p?.start_time||0).getTime();if(!t)return '—';const now=Date.now();let sec=Math.max(0,Math.floor((now-t)/1000));if(e?.sport==='basketball')return Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0')+' elapsed';return Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0')+' elapsed';}
};})();
