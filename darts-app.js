(()=>{'use strict';
const FILES=["darts_status.json","darts_model.json","darts_upcoming.json","darts_candidates.json"];
const API="/api/sportybet-darts";
const $=id=>document.getElementById(id);
async function get(p){const r=await fetch("/data/"+p+"?v="+Date.now(),{cache:"no-store"});if(!r.ok)throw Error(p+" HTTP "+r.status);return r.json()}
function pct(v){return Number.isFinite(Number(v))?(Number(v)*100).toFixed(1)+"%":"—"}
function money(v){return Number.isFinite(Number(v))?Number(v).toFixed(2):"—"}
async function load(){
  const [status,model,upcoming,candidates]=await Promise.all(FILES.map(get));
  $("history").textContent=status.history_events??"—";$("upcoming").textContent=status.upcoming_events??"—";$("oos").textContent=pct(model.variants?.[model.selected_variant]?.holdout?.accuracy);$("model").textContent=model.selected_variant||"—";
  const gate=model.precision_gate||{}, sel=gate.selected||{};
  $("gateBadge").textContent=gate.promoted?"PROMOTED":"RESEARCH ONLY";
  $("gateBadge").className=gate.promoted?"good":"warn";
  const gateEl=$("gate");gateEl.className="gate "+(gate.promoted?"good":"warn");
  gateEl.innerHTML="High-confidence threshold <b>"+(sel.threshold??"—")+"</b> · OOS n="+(sel.n??0)+" · accuracy "+pct(sel.accuracy)+" · Wilson lower "+pct(sel.wilson_lower_90)+" · beats vFootball "+(gate.beats_vfootball?"YES":"NO")+" · mode PAPER ONLY";
  const rows=Array.isArray(upcoming)?upcoming:[]; const cand=Array.isArray(candidates.candidates)?candidates.candidates:[];
  $("feedMeta").textContent="Collector update "+(status.updated_at||"—")+" · "+rows.length+" SportyBet fixtures · qualified candidates "+cand.length;
  const byId=new Map(cand.map(x=>[String(x.event_id),x]));
  $("cards").innerHTML=rows.length?rows.slice(0,50).map(x=>{const c=byId.get(String(x.event_id))||x;const promoted=!!c.qualified;return '<article class="card"><div class="cardTop"><span>'+String(x.competition||"").replace(/</g,"&lt;")+'</span><span>'+new Date(Number(x.start_time_ms||0)).toLocaleString()+'</span></div><div class="match">'+String(x.player_1||"").replace(/</g,"&lt;")+' <span class="muted">vs</span> '+String(x.player_2||"").replace(/</g,"&lt;")+'</div><div class="pick">'+(promoted?'<b>QUALIFIED · '+String(c.pick||"").toUpperCase()+'</b> · '+pct(c.confidence):'NO QUALIFIED SIGNAL')+'<br><span class="muted">book '+money(c.book_odds)+' · fair '+money(c.fair_odds)+' · edge '+pct(c.edge)+'</span></div><div class="stats"><div class="stat"><small>Model p1</small><b>'+pct(c.model_prob_p1)+'</b></div><div class="stat"><small>Threshold</small><b>'+String(sel.threshold??"—")+'</b></div><div class="stat"><small>Status</small><b>'+(promoted?"PROMOTED":"WATCH")+'</b></div></div></article>'}).join(""):'<div class="gate">No current SportyBet fixtures were collected. The engine will retry on its next scheduled run.</div>';
}
async function refresh(){
  $("refresh").disabled=true;$("refresh").textContent="Checking…";
  try{const r=await fetch(API+"?pageSize=20&pageNum=1&timeline=24&_t="+Date.now(),{cache:"no-store"});const p=await r.json();$("feedMeta").textContent="Live SportyBet provider check: "+(p.events_count||0)+" fixtures · last generated research snapshot remains authoritative for model status."}catch(e){$("feedMeta").textContent="Live provider check failed: "+e.message}finally{$("refresh").disabled=false;$("refresh").textContent="↻ Refresh SportyBet"}
}
document.addEventListener("DOMContentLoaded",()=>{load().catch(e=>{$("gate").textContent="Research artifact load failed: "+e.message});$("refresh").addEventListener("click",refresh)})
})();