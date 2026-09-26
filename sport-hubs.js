(()=>{'use strict';const Q=s=>document.querySelector(s),E=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML},N=v=>Number.isFinite(Number(v))?Number(v):null,P=v=>N(v)==null?'—':Math.round(N(v)*100)+'%',OD=p=>N(p)>0?(1/N(p)).toFixed(2):'—',DT=v=>{const d=new Date(v);return isNaN(d)?'—':d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})};async function get(path){const r=await fetch(path+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()}function mergeRows(base,pdl){const out=new Map();[...(Array.isArray(base)?base:[]),...(Array.isArray(pdl)?pdl:[])].forEach(row=>{if(!row||!row.event_id)return;out.set(String(row.event_id),row)});return [...out.values()]}const nav=()=>'<nav class="ms-nav"><a class="ms-brand ms-brand-link" href="./index.html" aria-label="Return to Match Signal main desk"><div class="ms-mark" aria-hidden="true"><svg viewBox="0 0 48 48" width="32" height="32" fill="none"><path d="M9 28.5a15 15 0 0 1 30 0" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/><path d="M14 29a10 10 0 0 1 20 0M19 29a5 5 0 0 1 10 0" stroke="#42e59a" stroke-width="2.4" stroke-linecap="round"/><path d="M24 29l9-11" stroke="#eef7fb" stroke-width="3" stroke-linecap="round"/><circle cx="24" cy="29" r="3.2" fill="#37e7ff"/><path d="M8 35h32" stroke="#7c6cff" stroke-width="1.8" stroke-linecap="round"/></svg></div><div><h1>Match Signal</h1><p>Real-data, market-calibrated sports prediction desk</p></div></a><div class="ms-tabs"><a class="ms-btn" href="./index.html">📅 Upcoming</a><a class="ms-btn" href="./football.html">⚽ Football</a><a class="ms-btn" href="./tennis.html">🎾 Tennis</a><a class="ms-btn" href="./basketball.html">🏀 Basketball</a><a class="ms-btn" href="./darts.html">🏹 Darts</a><a class="ms-btn" href="./table-tennis.html">🏓 Table Tennis</a><a class="ms-btn" href="./live.html">🔴 Live</a><a class="ms-btn" href="./reports.html">📊 Reports</a><a class="ms-btn" href="./virtual-lab/">🧪 Lab</a></div></nav>';function injectNav(){const n=Q('#msNav');if(n)n.innerHTML=nav()}function footballLeagues(rows){const base=['EPL','La Liga','Bundesliga','Serie A','Ligue 1','Champions League','MLS','Primeira Liga','Eredivisie','Saudi Pro League','England Amateur - U21 Professional Development League'];return [...new Set([...base,...rows.filter(x=>x.sport==='football').map(x=>x.league).filter(Boolean)])]}function leagueCard(name,rows,sport,meta={}){const count=rows.filter(x=>x.sport===sport&&x.league===name).length;const calculating=meta.calculating===true&&count===0;const desc=sport==='football'&&name.includes('Professional Development')?'U21 academy competition · historical results + dedicated forward fixture model':sport==='tennis'?name+' tour · tournament-level fixtures and model signals':name+' · 22-day forward planning when fixtures are available';const badge=calculating?'Calculating':count===0?'Pending':count+' predictions';return '<article class="ms-league"><div class="ms-league-top"><h3>'+E(name)+'</h3><span class="ms-badge '+(calculating?'':'')+'">'+badge+'</span></div><p>'+E(desc)+'</p><a href="./league.html?sport='+encodeURIComponent(sport)+'&league='+encodeURIComponent(name)+'">Open league page →</a></article>'}function sportIcon(s){
  return ({football:"⚽",tennis:"🎾",basketball:"🏀",darts:"🏹",table_tennis:"🏓",virtual:"🧪"}[s]||"•");
}
function evidenceLabel(x){
  const d=String(x.evidence_depth||"").replaceAll("_"," ");
  if(d)return d;
  if(x.projection_tier==="deep_model")return "deep model";
  if(x.projection_tier==="research_model")return "research model";
  if(x.projection_tier==="testing_projection")return "testing projection";
  return "baseline projection";
}
function marketLabel(x){
  if(x.market==="over_under"){
    return "O/U "+(x.pick||"—")+" "+(x.line??"");
  }
  if(x.pick==="p1"||x.pick==="p2"||x.pick==="draw"){
    const pick=x.pick==="p1"?x.player_1:x.pick==="p2"?x.player_2:"Draw";
    return "Winner · "+(pick||x.pick);
  }
  return x.pick||x.markets?.over_under?.pick||"Model projection";
}
function probabilityValue(x){
  const p=x.probability;
  if(Number.isFinite(Number(p)))return Number(p);
  if(Number.isFinite(Number(x.confidence)))return Number(x.confidence);
  const pr=x.probabilities||{};
  if(x.pick&&Number.isFinite(Number(pr[x.pick])))return Number(pr[x.pick]);
  return null;
}
function unifiedRow(x){
  const p=probabilityValue(x);
  const when=DT(x.start_time);
  const status=x.prediction_status||(
    x.projection_tier==="deep_model"?"DEEP MODEL":
    x.projection_tier==="deep_research_projection"?"DEEP RESEARCH":
    x.projection_tier==="research_model"?"RESEARCH":
    x.projection_tier==="testing_projection"?"TESTING":"BASELINE");
  const tier=evidenceLabel(x);
  const odds=Number.isFinite(Number(x.model_fair_odds))?Number(x.model_fair_odds).toFixed(2):"—";
  const edge=Number.isFinite(Number(x.model_edge_vs_market))?((Number(x.model_edge_vs_market)>=0?"+":"")+(Number(x.model_edge_vs_market)*100).toFixed(1)+"%"):"—";
  return '<article class="ms-up-row">'+
    '<div class="ms-up-time"><b>'+E(when)+'</b><span>'+E(String(x.start_time||"").slice(0,10))+'</span></div>'+
    '<div class="ms-up-event"><div class="ms-up-meta"><span class="ms-sport-pill">'+sportIcon(x.sport)+' '+E(x.sport==="table_tennis"?"Table Tennis":(x.sport||"Sport"))+'</span><span>'+E(x.league||x.competition||"Unclassified")+'</span></div>'+
    '<div class="ms-up-match">'+E(x.player_1||x.home||"Participant 1")+' <span>vs</span> '+E(x.player_2||x.away||"Participant 2")+'</div>'+
    '<div class="ms-up-details"><span>'+E(marketLabel(x))+'</span><span>Probability <b>'+ (p==null?"—":P(p))+'</b></span><span>Fair <b>'+E(odds)+'</b></span><span>Edge <b>'+E(edge)+'</b></span></div></div>'+
    '<div class="ms-up-status"><span class="ms-up-status-badge '+(status.includes("DEEP")||status.includes("QUALIFIED")?"deep":status==="TESTING"?"testing":"research")+'">'+E(status)+'</span><small>'+E(tier)+'</small></div>'+
  '</article>';
}
async function renderUnifiedBoard(){
  const root=Q('#unifiedBoard');
  if(!root)return;
  try{
    const payload=await get('./data/unified_upcoming.json');
    const all=Array.isArray(payload?.events)?payload.events:[];
    const sport=Q('#upSport'), date=Q('#upDate'), search=Q('#upSearch');
    const setOptions=(el,vals)=>{if(!el||el.dataset.ready)return;el.innerHTML=vals.map(v=>'<option value="'+E(v.value)+'">'+E(v.label)+'</option>').join('');el.dataset.ready="1";};
    setOptions(sport,[{value:"all",label:"All sports"},{value:"football",label:"⚽ Football"},{value:"tennis",label:"🎾 Tennis"},{value:"basketball",label:"🏀 Basketball"},{value:"darts",label:"🏹 Darts"},{value:"table_tennis",label:"🏓 Table Tennis"},{value:"virtual",label:"🧪 Virtual / eFootball"}]);
    setOptions(date,[{value:"7",label:"Next 7 days"},{value:"today",label:"Today"},{value:"tomorrow",label:"Tomorrow"},{value:"3",label:"Next 3 days"}]);
    const draw=()=>{
      const now=new Date(), today=now.toISOString().slice(0,10);
      const tomorrow=new Date(now.getTime()+86400000).toISOString().slice(0,10);
      const horizon=Number(date?.value||7);
      const q=String(search?.value||"").trim().toLowerCase();
      const filtered=all.filter(x=>{
        if(sport?.value && sport.value!=="all" && x.sport!==sport.value)return false;
        const day=String(x.start_time||"").slice(0,10);
        if(date?.value==="today" && day!==today)return false;
        if(date?.value==="tomorrow" && day!==tomorrow)return false;
        if(date?.value==="3"){
          const d=dt(x.start_time); if(!d||d>new Date(now.getTime()+3*86400000))return false;
        }
        if(q){
          const hay=[x.sport,x.league,x.competition,x.player_1,x.player_2,x.home,x.away,x.pick,marketLabel(x)].join(" ").toLowerCase();
          if(!hay.includes(q))return false;
        }
        return true;
      }).sort((a,b)=>new Date(a.start_time)-new Date(b.start_time));
      const byDay=new Map();
      for(const row of filtered){const day=String(row.start_time).slice(0,10);if(!byDay.has(day))byDay.set(day,[]);byDay.get(day).push(row);}
      root.innerHTML=filtered.length?[...byDay.entries()].map(([day,rows])=>{
        const label=new Date(day+"T00:00:00Z").toLocaleDateString([], {weekday:"long",month:"short",day:"numeric"});
        return '<section class="ms-up-day"><div class="ms-up-day-head"><h3>'+E(label)+'</h3><span>'+rows.length+' fixtures</span></div>'+rows.map(unifiedRow).join("")+'</section>';
      }).join(""):'<div class="ms-empty">No future fixtures match these filters. The engines remain active and the board will refresh with the next generated window.</div>';
      Q('#upCount').textContent=filtered.length;
      Q('#upLast').textContent=payload.generated_at?DT(payload.generated_at):"—";
    };
    sport.addEventListener('change',draw);date.addEventListener('change',draw);search.addEventListener('input',draw);
    draw();
  }catch(e){
    root.innerHTML='<div class="ms-empty">Unified upcoming feed unavailable: '+E(e.message)+'</div>';
  }
}
async function renderHub(){const sport=document.body.dataset.sport;const [base,pdl,status,readiness]=await Promise.all([get('./data/predictions.json'),get('./data/pdl_predictions.json').catch(()=>[]),get('./data/pdl_status.json').catch(()=>null),get('./data/football_forward_readiness.json').catch(()=>null)]);const rows=mergeRows(base,pdl);const sportRows=rows.filter(x=>x.sport===sport);Q('#count').textContent=sportRows.length;Q('#upcoming').textContent=sportRows.filter(x=>{const d=new Date(x.start_time);return !isNaN(d)&&d>=new Date()}).length;Q('#leagues').textContent=[...new Set(sportRows.map(x=>x.league).filter(Boolean))].length;if(sport==='football'){const stateMap=new Map((readiness?.statuses||[]).map(x=>[x.league,x]));Q('#leagueGrid').innerHTML=footballLeagues(rows).map(x=>{const state=stateMap.get(x)||{};return leagueCard(x,rows,sport,{calculating:['CALCULATING','CALCULATING_PENDING_PUBLICATION','PROVISIONAL'].includes(state.status)});}).join('')}else if(sport==='tennis'){const tours=['ATP','WTA'];Q('#leagueGrid').innerHTML=tours.map(x=>leagueCard(x,rows,sport)).join('')}else{const leagues=['NBA','WNBA','NCAAM','NCAAW','Euroleague','ACB','BBL','BSL'];Q('#leagueGrid').innerHTML=leagues.map(x=>leagueCard(x,rows,sport)).join('')}}async function card(p){const pr=p.probabilities||{},isT=p.sport==='tennis',ou=isT?(p.analytics||{}).total_games:(p.markets||{}).over_under;const total=ou?('O/U '+(ou.line??'—')+' · '+(ou.pick||'—')+' '+P(ou[ou.pick==='under'?'under':'over'])):null;const wo=p.sportybet_winner_odds||{};const book=wo?.p1&&wo?.p2?'SportyBet 1X2: '+wo.p1+' / '+(wo.draw??'—')+' / '+wo.p2:'';const mi=p.market_insights||{};const edge=mi.winner_model_edge_vs_market;const ti=mi.total;let marketNote='';if(mi.available){marketNote='SportyBet live baseline'+(edge!=null?' · model vs market edge '+P(edge):'');if(ti?.line!=null&&ti.book_odds!=null)marketNote+=' · O/U '+ti.line+' '+String(ti.pick||'').toUpperCase()+' @ '+Number(ti.book_odds).toFixed(2)+(ti.model_edge_vs_market!=null?' · total edge '+P(ti.model_edge_vs_market):'');}else marketNote='SportyBet market snapshot unavailable this run';const absEdge=edge==null?0:Math.max(-.2,Math.min(.2,Number(edge)));const edgeWidth=Math.round(Math.abs(absEdge)*500);const edgeLabel=edge==null?'—':(edge>=0?'+':'')+P(edge);return '<article class="ms-pred"><div class="ms-pred-meta"><span>'+E(p.league||p.sport)+'</span><span>'+E(DT(p.start_time))+'</span></div><div class="ms-match">'+E(p.player_1)+' <span class="ms-muted">vs</span> '+E(p.player_2)+'</div><div class="ms-probs">'+(p.sport==='football'?'<div class="ms-prob"><small>Home</small><b>'+P(pr.p1)+'</b></div><div class="ms-prob"><small>Draw</small><b>'+P(pr.draw)+'</b></div><div class="ms-prob"><small>Away</small><b>'+P(pr.p2)+'</b></div>':'<div class="ms-prob"><small>P1</small><b>'+P(pr.p1)+'</b></div><div class="ms-prob"><small>P2</small><b>'+P(pr.p2)+'</b></div><div class="ms-prob"><small>Confidence</small><b>'+P(p.confidence)+'</b></div>')+'</div><div class="ms-signal">Model pick: <b>'+E(p.pick==='p1'?p.player_1:p.pick==='p2'?p.player_2:(p.pick||'—'))+'</b> · model fair '+E(OD(p.confidence))+(total?'<br><span class="ms-muted">'+E(total)+'</span>':'')+'</div><div class="ms-market-strip"><span class="ms-market-status '+(mi.available?'live':'stale')+'">'+(mi.available?'SPORTYBET LIVE':'MARKET FALLBACK')+'</span><span>'+E(marketNote)+'</span></div><div class="ms-edge"><div><span>Model ↔ market edge</span><b>'+edgeLabel+'</b></div><div class="ms-edge-track"><i style="width:'+edgeWidth+'%"></i></div></div>'+(book?'<div class="ms-note">'+E(book)+'</div>':'')+'<div class="ms-note">Model: '+E(p.model||p.model_version||'Match Signal')+' · '+E(p.decision||p.prediction_status||'PAPER ONLY')+'</div></article>'}async function renderLeague(){const params=new URLSearchParams(location.search),sport=params.get('sport')||'football',league=params.get('league')||'';Q('#leagueName').textContent=league||'League';Q('#leagueSport').textContent=sport.toUpperCase();const [base,pdl]=await Promise.all([get('./data/predictions.json'),get('./data/pdl_predictions.json').catch(()=>[])]);const rows=mergeRows(base,pdl).filter(p=>p.sport===sport&&p.league===league);Q('#count').textContent=rows.length;Q('#upcoming').textContent=rows.filter(x=>new Date(x.start_time)>=new Date()).length;const dates=[...new Set(rows.map(x=>String(x.start_time||'').slice(0,10)).filter(Boolean))];Q('#dateRange').textContent=dates.length?dates.slice(0,1)[0]+' → '+dates.slice(-1)[0]:'No current feed';const search=Q('#search'),sort=Q('#sort'),list=Q('#predictions');const draw=async()=>{let a=rows.filter(p=>{const q=(search.value||'').toLowerCase();return !q||String(p.player_1+' '+p.player_2+' '+(p.tournament||'')).toLowerCase().includes(q)});if(sort.value==='confidence')a.sort((x,y)=>(y.confidence||0)-(x.confidence||0));else a.sort((x,y)=>new Date(x.start_time)-new Date(y.start_time));list.innerHTML=a.length?(await Promise.all(a.map(card))).join(''):'<div class="ms-empty">No prediction rows are currently published for this league. The page remains active and will populate when the engine publishes the competition.</div>'};search.addEventListener('input',draw);sort.addEventListener('change',draw);await draw()}async function renderReports(){const [a,fp,tp,bp]=await Promise.allSettled([get('./data/accuracy.json'),get('./data/football_performance.json'),get('./data/tennis_performance.json'),get('./data/basketball_accuracy.json')]);const acc=a.status==='fulfilled'?a.value:null;const summary=acc?.summary||acc||{};Q('#settled').textContent=summary.settled??summary.total_settled??'—';Q('#accuracy').textContent=summary.accuracy!=null?P(summary.accuracy):'—';Q('#brier').textContent=summary.brier_score!=null?Number(summary.brier_score).toFixed(4):'—';const boxes=[['Football',fp],['Tennis',tp],['Basketball',bp],['Darts-X',await Promise.resolve(get('./data/darts_model.json')).catch(()=>null)],['Table Tennis-X',await Promise.resolve(get('./data/table_tennis_model.json')).catch(()=>null)]];const links={'Football':'./league.html?sport=football&league=EPL','Tennis':'./league.html?sport=tennis&league=ATP','Basketball':'./league.html?sport=basketball&league=NBA','Darts-X':'./darts.html','Table Tennis-X':'./table-tennis.html'};Q('#reportGrid').innerHTML=boxes.map(([name,x])=>{const d=x.status==='fulfilled'?x.value:null;return '<article class="ms-card"><h3>'+name+'</h3><p>'+E(JSON.stringify(d?.summary||d||{status:'No artifact'},null,2).slice(0,900))+'</p><a class="ms-link" href="'+links[name]+'">Open '+name+' desk →</a></article>'}).join('')}function boot(){injectNav();const page=document.body.dataset.page;if(page==='home'||page==='upcoming'||page==='unified')renderUnifiedBoard();if(page==='hub')renderHub().catch(e=>{Q('#leagueGrid').innerHTML='<div class="ms-empty">Feed error: '+E(e.message)+'</div>'});if(page==='league')renderLeague().catch(e=>{Q('#predictions').innerHTML='<div class="ms-empty">Feed error: '+E(e.message)+'</div>'});if(page==='reports')renderReports().catch(e=>{Q('#reportGrid').innerHTML='<div class="ms-empty">Report error: '+E(e.message)+'</div>'})}document.addEventListener('DOMContentLoaded',boot)})();