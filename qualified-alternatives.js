/* Compatibility contract: only Builder-qualified alternatives emit data-ticket-model-qualified="true"; research-only alternatives emit false. */
(()=>{'use strict';
const endpoint='/api/public/market-alternatives',escapeHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let rows=[],busy=false;
function key(s,e){return String(s||'').toLowerCase()+'|'+String(e||'');}
function button(x){const total=x.market==='total',pick=String(x.pick||'').toLowerCase(),line=x.line;
return '<div class="ms-alt-option"><div class="ms-alt-copy"><b>'+escapeHtml(total?(pick.toUpperCase()+' '+line):pick==='p1'?x.player_1:pick==='p2'?x.player_2:'Draw')+'</b><span>'+escapeHtml(x.market_label)+' · '+Math.round(x.probability*100)+'% model probability · '+Number(x.odds).toFixed(2)+' odds · '+(x.builder_qualified?'Builder-qualified':'Research only — Builder gate not passed')+'</span></div><button type="button" data-ms-ticket-add data-ticket-sport="'+escapeHtml(x.sport)+'" data-ticket-event="'+escapeHtml(x.event_id)+'" data-ticket-sportybet-event="'+escapeHtml(x.sportybet_event_id)+'" '+(x.sport==='efootball'?'data-ticket-product="'+escapeHtml(x.product)+'" ':'')+'data-ticket-model-qualified="'+String(x.builder_qualified===true)+'" data-ticket-market="'+escapeHtml(x.market)+'" data-ticket-pick="'+escapeHtml(pick)+'" data-ticket-line="'+(line==null?'':escapeHtml(line))+'" data-ticket-market-id="'+escapeHtml(x.market_id)+'" data-ticket-odds="'+escapeHtml(x.odds)+'" data-ticket-start="'+escapeHtml(x.start_time)+'" data-ticket-player1="'+escapeHtml(x.player_1)+'" data-ticket-player2="'+escapeHtml(x.player_2)+'" data-ticket-match="'+escapeHtml(x.match||x.player_1+' vs '+x.player_2)+'">Add to ticket</button></div>';}
function attach(){
 const cards=document.querySelectorAll('[data-ms-fixture-id]');
 cards.forEach(card=>{
  const event=card.getAttribute('data-ms-fixture-id'),sport=card.getAttribute('data-ms-fixture-sport');
  let host=card.querySelector('.ms-qualified-alternatives');
  const found=rows.filter(x=>x.event_id===event&&x.sport===sport).slice(0,2);
  if(!found.length){if(host)host.remove();return;}
  const signature=JSON.stringify(found.map(x=>[x.market,x.pick,x.line,x.probability,x.odds,x.quote_timestamp,x.builder_qualified]));
  if(host&&host.dataset.signature===signature)return;
  if(!host){host=document.createElement('section');host.className='ms-qualified-alternatives';card.appendChild(host);}
  host.dataset.signature=signature;
  host.innerHTML='<div class="ms-alt-heading"><b>System-recommended alternative'+(found.length>1?'s':'')+'</b><span>Fresh exact SportyBet quote · ≤15 min; qualification shown per pick</span></div>'+found.map(button).join('');
 });
}
async function load(){if(busy)return;busy=true;try{const response=await fetch(endpoint,{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);const payload=await response.json();rows=Array.isArray(payload.alternatives)?payload.alternatives:[];attach();}catch(error){/* Fail closed: no alternatives are displayed when evidence cannot be verified. */}finally{busy=false;}}
const style=document.createElement('style');style.textContent='.ms-qualified-alternatives{margin-top:14px;padding:12px;border:1px solid rgba(16,185,129,.24);border-radius:12px;background:rgba(16,185,129,.045)}.ms-alt-heading{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px;font-size:12px}.ms-alt-heading span,.ms-alt-copy span{color:var(--muted,#87939d);font-size:11px}.ms-alt-option{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-top:1px solid rgba(130,150,160,.14)}.ms-alt-copy{display:grid;gap:3px;min-width:0}.ms-alt-option button{flex:none;border:1px solid rgba(16,185,129,.45);border-radius:8px;padding:7px 10px;background:rgba(16,185,129,.12);color:inherit;font:inherit;font-size:12px;font-weight:700;cursor:pointer}';
document.head.appendChild(style);
new MutationObserver(attach).observe(document.body,{childList:true,subtree:true});
load();setInterval(load,60000);
})();