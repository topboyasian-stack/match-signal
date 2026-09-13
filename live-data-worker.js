/* Client-side live data helpers. PAPER ONLY. */
(function(){'use strict';
const pad=n=>String(Math.max(0,Math.floor(Number(n)||0))).padStart(2,'0');
const clockState=new Map();
function text(e){const s=e?.status||{},t=s.type||{};return [t.description,t.shortDetail,s.description].filter(Boolean).join(' ');}
function isBreak(e){return /half.?time|halftime|interval|break/i.test(text(e));}
function parseClock(v){if(typeof v==='number'&&Number.isFinite(v))return {seconds:v};const m=String(v||'').match(/^(\d+):([0-5]\d)$/);return m?{seconds:Number(m[1])*60+Number(m[2])}:null;}
window.MatchSignalLiveData={
  formatClock:function(e){
    const s=e?.status||{},t=s.type||{}; if(isBreak(e))return 'HALFTIME BREAK';
    const raw=s.displayClock||s.clock;const parsed=parseClock(raw);if(parsed&&e?.id){
      const key=String(e.id),now=Date.now(),old=clockState.get(key);
      const basketball=/basketball/i.test(String(e?.sport||e?.league||''));
      if(!old||old.raw!==String(raw)){clockState.set(key,{raw:String(raw),seconds:parsed.seconds,at:now,basketball});}
      const cur=clockState.get(key),delta=Math.floor((now-cur.at)/1000);
      let sec=cur.basketball?Math.max(0,cur.seconds-delta):cur.seconds+delta;
      return Math.floor(sec/60)+':'+pad(sec%60);
    }
    return raw||t.shortDetail||t.description||'—';
  },
  isBreak,
  kickoff:function(p){if(!p?.start_time)return '—';const d=new Date(p.start_time);return d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});},
  elapsed:function(p,e){if(isBreak(e))return 'HALFTIME BREAK';const t=new Date(p?.start_time||0).getTime();if(!t)return '—';const sec=Math.max(0,Math.floor((Date.now()-t)/1000));return Math.floor(sec/60)+':'+pad(sec%60)+' elapsed';},
  clockAge:function(lastFetch){return lastFetch?Math.max(0,Math.floor((Date.now()-lastFetch)/1000))+'s since refresh':'—';}
};
/* Make the live desk visually energetic rather than muted. */
const css=`
:root{--bg:#050816;--panel:#0b1224;--panel2:#111a31;--border:#26385d;--text:#f7f9ff;--muted:#9eafd2;--accent:#6d5dfc;--green:#19e6a2;--amber:#ffd166;--red:#ff4d6d;--cyan:#22d3ee;--pink:#f472b6}
body{background:radial-gradient(circle at 10% 0%,#182554 0,#080d1d 35%,#03050c 75%);}
.mark{background:linear-gradient(135deg,#ff4d6d,#7c3aed 45%,#22d3ee)!important;box-shadow:0 0 28px #7c3aed66}.btn{background:#0d1730;border-color:#30466f}.btn:hover,.btn.active{background:linear-gradient(135deg,#6d5dfc,#22d3ee);border-color:#7dd3fc;box-shadow:0 6px 24px #6d5dfc55}.status,.panel,.metric{box-shadow:0 10px 35px #0007}.card{background:linear-gradient(145deg,#121d38,#0b1328);border-color:#314a79;box-shadow:0 10px 28px #0008}.liveBadge{color:#19e6a2;text-shadow:0 0 12px #19e6a2}.score strong{color:#fff;text-shadow:0 0 18px #6d5dfc88}.clock{color:#ffd166;text-shadow:0 0 10px #ffd16655}.detail{background:#081127;border-color:#2a416d}.bar{background:#1b2b4d}.fill{background:linear-gradient(90deg,#7c3aed,#06b6d4,#19e6a2)}.analysis{background:linear-gradient(135deg,#6d5dfc18,#22d3ee14);border-color:#6d5dfc55}.dot{background:#19e6a2;box-shadow:0 0 16px #19e6a2}
`;
const style=document.createElement('style');style.textContent=css;document.head.appendChild(style);
setInterval(()=>document.querySelectorAll('.clock').forEach(x=>{if(x.dataset.msStatic)return;}),1000);
})();
