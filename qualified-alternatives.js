/* Research alternatives remain visible; only the existing ticket-supported markets expose an Add button. */
/* Tennis set-winner alternatives: preserve exact Set 1/Set 2 market scope and route manual picks into the shared ticket drawer. */
(()=>{'use strict';
const endpoint='/api/public/market-alternatives';
const escapeHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let rows=[],busy=false,lastError='';
function displayPick(x){
 const pick=String(x.pick||'').toLowerCase();
 if(x.market==='total')return pick.toUpperCase()+' '+(x.line==null?'':x.line);
 if(x.market==='btts')return 'BTTS '+pick.toUpperCase();
 if(x.market==='double_chance')return 'DOUBLE CHANCE '+pick.toUpperCase();
 if(x.market==='set_winner')return 'SET '+String(x.set_number||'')+' WINNER · '+(pick==='p1'?(x.player_1||'Player 1'):(x.player_2||'Player 2'));
 if(pick==='p1')return x.player_1||'Participant 1';
 if(pick==='p2')return x.player_2||'Participant 2';
 if(pick==='draw')return 'Draw';
 return pick.toUpperCase();
}
function quoteLabel(x){
 const status=String(x.quote_status||'UNVERIFIED');
 if(status==='FRESH_EXACT')return 'Fresh exact quote · live recheck still required';
 if(status==='STALE')return 'Last-seen quote is stale · live recheck required';
 if(status==='INVALID_TIMESTAMP')return 'Quote timestamp invalid · live recheck required';
 if(status==='NOT_VERIFIED_EXACT')return 'Exactness not verified · live recheck required';
 if(status==='NOT_MARKED_EXACT')return 'Quote not verified as exact · live recheck required';
 if(status==='PRICE_UNAVAILABLE')return 'No exact side price in snapshot · live recheck required';
 return 'No verified current quote · live recheck required';
}
function qualificationLabel(x){
 if(x.builder_qualified===true)return 'Builder-qualified';
 if(!x.sportybet_event_id||!x.market_id)return 'Research visible · SportyBet event/market mapping missing';
 if(x.ticket_selectable!==true)return 'Research display only · ticket mapping not enabled';
 if(x.quote_status!=='FRESH_EXACT')return 'Research only · current quote not verified';
 if(x.below_research_baseline===true)return 'Research only · below the 55% display baseline';
 return 'Research only · Builder gate not passed';
}
function comparisonLabel(x){
 if(x.primary_comparison_status==='MORE_LIKELY_THAN_PRIMARY')return 'Higher model probability than primary pick';
 if(x.primary_comparison_status==='MARKET_SCOPE_NOT_COMPARABLE')return 'Set probability is assessed separately from match-winner probability';
 return 'Primary probability unavailable for direct comparison';
}
function ticketButton(x){
 const pick=String(x.pick||'').toLowerCase(),line=x.line;
 return '<button type="button" data-ms-ticket-add data-ticket-sport="'+escapeHtml(x.sport)+'" data-ticket-event="'+escapeHtml(x.event_id)+'" data-ticket-sportybet-event="'+escapeHtml(x.sportybet_event_id)+'" '+(x.sport==='efootball'?'data-ticket-product="'+escapeHtml(x.product)+'" ':'')+'data-ticket-model-qualified="'+String(x.builder_qualified===true)+'" data-ticket-market="'+escapeHtml(x.market)+'" data-ticket-pick="'+escapeHtml(pick)+'" data-ticket-line="'+(line==null?'':escapeHtml(line))+'" data-ticket-set-number="'+(x.set_number==null?'':escapeHtml(x.set_number))+'" data-ticket-market-id="'+escapeHtml(x.market_id)+'" data-ticket-odds="'+(x.odds==null?'':escapeHtml(x.odds))+'" data-ticket-start="'+escapeHtml(x.start_time)+'" data-ticket-player1="'+escapeHtml(x.player_1)+'" data-ticket-player2="'+escapeHtml(x.player_2)+'" data-ticket-match="'+escapeHtml(x.match||((x.player_1||'')+' vs '+(x.player_2||'')))+'">Add to ticket</button>';
}
function optionMarkup(x){
 const probability=Number(x.probability);
 const odds=Number(x.odds);
 const price=Number.isFinite(odds)&&odds>1
   ? (x.quote_status==='FRESH_EXACT'?'SportyBet '+odds.toFixed(2):'Last-seen '+odds.toFixed(2))
   : 'SportyBet price unavailable';
 const probabilityText=Number.isFinite(probability)?Math.round(probability*100)+'% model probability':'Model probability unavailable';
 const scopeNote=x.market==='set_winner'?'<span>Shared per-set estimate · not adjusted for the previous set outcome</span>':'';
 const control=x.ticket_selectable===true?ticketButton(x):'<span class="ms-alt-research-note">Research display only · ticket mapping not enabled</span>';
 return '<div class="ms-alt-option"><div class="ms-alt-copy"><b>'+escapeHtml(displayPick(x))+'</b><span>'+escapeHtml(x.market_label||x.market||'Market')+' · '+escapeHtml(probabilityText)+' · '+escapeHtml(price)+'</span><span>'+escapeHtml(quoteLabel(x))+'</span><span>'+escapeHtml(comparisonLabel(x))+'</span>'+scopeNote+'<span>'+escapeHtml(qualificationLabel(x))+'</span></div>'+control+'</div>';
}
function attach(){
 const cards=document.querySelectorAll('[data-ms-fixture-id]');
 cards.forEach(card=>{
  const event=card.getAttribute('data-ms-fixture-id'),sport=card.getAttribute('data-ms-fixture-sport');
  let host=card.querySelector('.ms-qualified-alternatives');
  const matching=rows.filter(x=>x.event_id===event&&x.sport===sport);
  const found=matching.slice(0,(sport==='tennis'&&matching.some(x=>x.market==='set_winner'))?4:2);
  if(!found.length){if(host)host.remove();return;}
  const signature=JSON.stringify(found.map(x=>[x.market,x.set_number,x.pick,x.line,x.probability,x.odds,x.quote_status,x.builder_qualified,x.ticket_selectable,x.qualification_status,x.below_research_baseline,x.primary_comparison_status]));
  if(host&&host.dataset.signature===signature)return;
  if(!host){host=document.createElement('section');host.className='ms-qualified-alternatives';card.appendChild(host);}
  host.dataset.signature=signature;
  host.setAttribute('data-ms-alt-contract','research-visible-v2');
  host.innerHTML='<div class="ms-alt-heading"><b>System-recommended alternatives</b><span>Research candidates stay visible; SportyBet prices are rechecked before code generation.</span></div>'+found.map(optionMarkup).join('');
 });
}
async function load(){
 if(busy)return;busy=true;
 try{
  const response=await fetch(endpoint,{cache:'no-store',headers:{'Accept':'application/json'}});
  if(!response.ok)throw Error('HTTP '+response.status);
  const payload=await response.json();
  rows=Array.isArray(payload.alternatives)?payload.alternatives:[];
  lastError='';
  attach();
 }catch(error){
  lastError=String(error&&error.message||error);
  /* Keep already-rendered rows; never replace a failed refresh with a false empty state. */
 }finally{busy=false;}
}
const style=document.createElement('style');
style.textContent='.ms-qualified-alternatives{margin-top:14px;padding:12px;border:1px solid rgba(16,185,129,.24);border-radius:12px;background:rgba(16,185,129,.045)}.ms-alt-heading{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:8px;font-size:12px}.ms-alt-heading span,.ms-alt-copy span{color:var(--muted,#87939d);font-size:11px}.ms-alt-option{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-top:1px solid rgba(130,150,160,.14)}.ms-alt-copy{display:grid;gap:3px;min-width:0}.ms-alt-option button{flex:none;border:1px solid rgba(16,185,129,.45);border-radius:8px;padding:7px 10px;background:rgba(16,185,129,.12);color:inherit;font:inherit;font-size:12px;font-weight:700;cursor:pointer}.ms-alt-research-note{flex:none;max-width:180px;text-align:right;color:var(--muted,#87939d);font-size:11px}';
document.head.appendChild(style);
new MutationObserver(attach).observe(document.body,{childList:true,subtree:true});
load();setInterval(load,60000);
})();