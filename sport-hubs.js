(()=>{'use strict';const Q=s=>document.querySelector(s),E=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML},N=v=>Number.isFinite(Number(v))?Number(v):null,P=v=>N(v)==null?'—':Math.round(N(v)*100)+'%',OD=p=>N(p)>0?(1/N(p)).toFixed(2):'—',DT=v=>{const d=new Date(v);return isNaN(d)?'—':d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})};async function get(path){const r=await fetch(path+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()}function mergeRows(base,pdl){const out=new Map();[...(Array.isArray(base)?base:[]),...(Array.isArray(pdl)?pdl:[])].forEach(row=>{if(!row||!row.event_id)return;out.set(String(row.event_id),row)});return [...out.values()]}const nav=()=>'<nav class="ms-nav"><a class="ms-brand ms-brand-link" href="./index.html" aria-label="Return to Match Signal main desk"><div class="ms-mark" aria-hidden="true"><svg viewBox="0 0 48 48" width="32" height="32" fill="none"><path d="M9 28.5a15 15 0 0 1 30 0" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/><path d="M14 29a10 10 0 0 1 20 0M19 29a5 5 0 0 1 10 0" stroke="#42e59a" stroke-width="2.4" stroke-linecap="round"/><path d="M24 29l9-11" stroke="#eef7fb" stroke-width="3" stroke-linecap="round"/><circle cx="24" cy="29" r="3.2" fill="#37e7ff"/><path d="M8 35h32" stroke="#7c6cff" stroke-width="1.8" stroke-linecap="round"/></svg></div><div><h1>Match Signal</h1><p>Real-data, market-calibrated sports prediction desk</p></div></a><div class="ms-tabs"><a class="ms-btn" href="./index.html">📅 Upcoming</a><a class="ms-btn" href="./football.html">⚽ Football</a><a class="ms-btn" href="./tennis.html">🎾 Tennis</a><a class="ms-btn" href="./live.html">🔴 Live</a><a class="ms-btn" href="./reports.html">📊 Reports</a><a class="ms-btn" href="./odds-builder.html">🧮 Odds Builder</a><a class="ms-btn" href="./virtual-lab/">🧪 Lab</a></div></nav>';function injectNav(){const n=Q('#msNav');if(n)n.innerHTML=nav()}function footballLeagues(rows){const base=['La Liga','Bundesliga','Ligue 1','Champions League'];return [...new Set([...base,...rows.filter(x=>x.sport==='football').map(x=>x.league).filter(Boolean)])]}function leagueCard(name,rows,sport,meta={}){const count=rows.filter(x=>x.sport===sport&&x.league===name).length;const calculating=meta.calculating===true&&count===0;const desc=sport==='football'&&name.includes('Professional Development')?'U21 academy competition · historical results + dedicated forward fixture model':sport==='tennis'?name+' tour · tournament-level fixtures and model signals':name+' · 22-day forward planning when fixtures are available';const badge=calculating?'Calculating':count===0?'Pending':count+' predictions';return '<article class="ms-league"><div class="ms-league-top"><h3>'+E(name)+'</h3><span class="ms-badge '+(calculating?'':'')+'">'+badge+'</span></div><p>'+E(desc)+'</p><a href="./league.html?sport='+encodeURIComponent(sport)+'&league='+encodeURIComponent(name)+'">Open league page →</a></article>'}function sportIcon(s){
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
function rowFixtureKey(x){
  const norm=s=>String(s||"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
  const sport=String(x.sport||"").toLowerCase();
  const date=String(x.start_time||"").slice(0,10);
  const p1=norm(x.player_1||x.home),p2=norm(x.player_2||x.away);
  return String(x.event_id||"")+"|"+sport+"|"+date+"|"+[p1,p2].sort().join("|");
}
function fixtureGroups(rows){
  const map=new Map();
  for(const row of rows){
    const key=rowFixtureKey(row);
    if(!map.has(key))map.set(key,{key,rows:[]});
    const g=map.get(key);
    const m=String(row.market||"winner");
    const line=row.line==null?"":String(row.line);
    const pick=String(row.pick||row.selection||"");
    const dedupe=m+"|"+line+"|"+pick;
    if(!g.rows.some(x=>(String(x.market||"winner")+"|"+(x.line==null?"":String(x.line))+"|"+String(x.pick||x.selection||""))===dedupe)){
      g.rows.push(row);
    }
  }
  return [...map.values()].map(g=>{
    g.rows.sort((a,b)=>{
      const la=Number.isFinite(Number(a.line))?Number(a.line):999;
      const lb=Number.isFinite(Number(b.line))?Number(b.line):999;
      return la-lb;
    });
    return g;
  }).sort((a,b)=>new Date(a.rows[0].start_time)-new Date(b.rows[0].start_time));
}
function bookmakerOdds(x){
  const v=Number(x.bookmaker_odds??x.sportybet_odds??x.book_odds);
  return Number.isFinite(v)&&v>1?v:null;
}
function unifiedMarketLine(x){
  const p=probabilityValue(x);
  const fair=Number(x.model_fair_odds);
  const book=bookmakerOdds(x);
  const edge=Number(x.model_edge_vs_market);
  const pick=String(x.pick||x.selection||"").toUpperCase();
  const market=x.market==="over_under"?("O/U "+pick+" "+(x.line??"")):marketLabel(x);
  const sportLabel=book!=null?("SportyBet LIVE @ "+book.toFixed(2)):"SportyBet —";
  const fairLabel=Number.isFinite(fair)?fair.toFixed(2):"—";
  const edgeLabel=Number.isFinite(edge)?((edge>=0?"+":"")+(edge*100).toFixed(1)+"%"):"—";
  const q=x.betting_qualified?"QUALIFIED":(x.qualification_status||"PAPER");
  return '<div class="ms-market-row">'+
    '<span class="ms-market-name">'+E(market)+'</span>'+
    '<span>Model <b>'+(p==null?"—":P(p))+'</b></span>'+
    '<span>Fair <b>'+E(fairLabel)+'</b></span>'+
    '<span class="'+(book!=null?"ms-book-live":"ms-book-missing")+'">'+E(sportLabel)+'</span>'+
    '<span>Edge <b>'+E(edgeLabel)+'</b></span>'+
    '<span class="ms-market-q '+(x.betting_qualified?"qualified":"paper")+'">'+E(q)+'</span>'+
  '</div>';
}
function primaryPrediction(rows){
  const rank=x=>{
    const q=x.betting_qualified||x.qualification_status==="BETTING_QUALIFIED_PAPER"||x.qualification_status==="BETTING_QUALIFIED_PAPER_BOOTSTRAP";
    const tier=String(x.projection_tier||"");
    const p=Number(probabilityValue(x));
    const edge=Number(x.model_edge_vs_market);
    return [
      q?100:0,
      tier.includes("deep")?30:tier.includes("research")?20:10,
      Number.isFinite(edge)?Math.max(-10,Math.min(20,edge*100)):0,
      Number.isFinite(p)?p*10:0,
      bookmakerOdds(x)!=null?1:0
    ];
  };
  return [...rows].sort((a,b)=>{
    const ra=rank(a),rb=rank(b);
    for(let i=0;i<ra.length;i++)if(ra[i]!==rb[i])return rb[i]-ra[i];
    return String(a.market||"").localeCompare(String(b.market||""));
  })[0]||null;
}
function unifiedRow(group){
  const rows=group.rows;
  const x=primaryPrediction(rows);
  if(!x)return "";
  const when=DT(x.start_time);
  const qualified=Boolean(x.betting_qualified);
  const live=String(x.event_state||"").toUpperCase()==="LIVE";
  const settled=String(x.event_state||"").toUpperCase()==="SETTLED";
  const book=bookmakerOdds(x);
  const result=String(x.settlement_result||"").toUpperCase();
  const won=settled && (x.settlement_result===x.pick || result==="WIN" || result==="WON" || x.win===true);
  const status=settled?(won?"SETTLED · ✓ WIN":"SETTLED · ✕ LOSS"):
    (qualified?"BETTING QUALIFIED · PAPER":
    (live?"LIVE RESEARCH":
    (String(x.projection_tier||"").includes("deep")?"DEEP MODEL":"RESEARCH PROJECTION")));
  const q=settled?(won?"SETTLED · ✓":"SETTLED · ✕"):(x.betting_qualified?"BETTING-QUALIFIED":(x.qualification_status||"PAPER · NOT QUALIFIED"));
  return '<article class="ms-up-row ms-fixture-card">'+
    '<div class="ms-up-time"><b>'+E(when)+'</b><span>'+E(String(x.start_time||"").slice(0,10))+'</span></div>'+
    '<div class="ms-up-event"><div class="ms-up-meta"><span class="ms-sport-pill">'+sportIcon(x.sport)+' '+E(x.sport==="table_tennis"?"Table Tennis":(x.sport||"Sport"))+'</span><span>'+E(x.league||x.competition||"Unclassified")+'</span><span class="ms-fixture-market-count">1 prediction</span></div>'+
    '<div class="ms-up-match">'+E(x.player_1||x.home||"Participant 1")+' <span>vs</span> '+E(x.player_2||x.away||"Participant 2")+'</div>'+
    '<div class="ms-market-stack">'+unifiedMarketLine(x)+'</div>'+
    '<div class="ms-fixture-foot"><span class="'+(settled?(won?"ms-settled-win":"ms-settled-loss"):"")+'">'+E(q)+'</span><span>'+E(settled?("Result "+(x.final_score||x.settlement_result||"recorded")):(book!=null?"SportyBet quote matched to this prediction":"SportyBet quote not matched"))+'</span></div></div>'+
    '<div class="ms-up-status"><span class="ms-up-status-badge '+(settled?(won?"deep":"research"):(qualified?"deep":live?"testing":"research"))+'">'+E(status)+'</span><span class="ms-up-qual '+(qualified?"qualified":"paper")+'">'+E(qualified?"BETTING-QUALIFIED":"PAPER · NOT QUALIFIED")+'</span><small>'+E(evidenceLabel(x))+'</small></div>'+
  '</article>';
}
async function renderUnifiedBoard(){
  const root=Q('#unifiedBoard');
  if(!root)return;
  try{
    let payload={events:[],generated_at:null};
    let selectedRows=[];
    let riskGate=null;
    try{
      const [sel,rg]=await Promise.all([
        get('./data/selection_candidates.json'),
        get('./data/risk_gate.json')
      ]);
      selectedRows=Array.isArray(sel)?sel:[];
      riskGate=rg;
    }catch(_){}
    try{
      payload=await get('./data/unified_upcoming.json');
    }catch(_){
      payload={events:[],generated_at:null};
    }
    let all=Array.isArray(payload?.events)?payload.events:[];
    if(!all.length){
      const sources=[
        './data/predictions.json',
        './data/pdl_predictions.json',
        './data/ere_divisie_predictions.json',
        './data/saudi_pro_league_predictions.json',
        './data/nba_predictions.json'
      ];
      const chunks=await Promise.all(sources.map(async url=>{
        try{
          const data=await get(url);
          return Array.isArray(data)?data:[];
        }catch(_){return [];}
      }));
      const normalize=(row,source)=>{
        const x={...row};
        if(!x.start_time && x.start_time_ms){
          const d=new Date(Number(x.start_time_ms));
          if(!Number.isNaN(d.getTime()))x.start_time=d.toISOString();
        }
        x.sport=x.sport||source;
        x.league=x.league||x.competition||x.tournament||'Unclassified';
        x.player_1=x.player_1||x.home||x.team_1||'Participant 1';
        x.player_2=x.player_2||x.away||x.team_2||'Participant 2';
        x.projection_tier=x.projection_tier||(
          source==='darts'||source==='table_tennis'?'testing_projection':'deep_model'
        );
        x.prediction_status=x.prediction_status||(
          x.qualified?'qualified_candidate':
          x.projection_tier==='deep_model'?'deep_model':'research_projection'
        );
        x.evidence_depth=x.evidence_depth||(
          x.qualified?'validated_gate':
          x.projection_tier==='deep_model'?'published_core_model':'baseline_plus_current_feed'
        );
        x.probability=x.probability??x.confidence??null;
        x.model_fair_odds=x.model_fair_odds??x.fair_odds??null;
        x.model_edge_vs_market=x.model_edge_vs_market??x.edge??null;
        return x;
      };
      const labels=['football_tennis','football','football','football','football'];
      all=chunks.flatMap((rows,i)=>rows.map(r=>normalize(r,labels[i]))).filter(x=>x.start_time);
      payload.generated_at=new Date().toISOString();
    }
    const selectedKeys=new Set(selectedRows.map(x=>{
      const event=String(x?.event_id||x?.id||"");
      const pick=String(x?.pick||x?.selection||"");
      const line=x?.line==null?"":String(x.line);
      return event+"|"+pick+"|"+line;
    }));
    const annotate=(x)=>{
      const event=String(x?.event_id||"");
      const pick=String(x?.pick||x?.selection||"");
      const line=x?.line==null?"":String(x.line);
      const exact=event+"|"+pick+"|"+line;
      const broad=event+"|"+pick+"|";
      x.betting_qualified=Boolean(x.betting_qualified)||Boolean(x.qualified_for_builder)||
        selectedKeys.has(exact)||selectedKeys.has(broad)||
        x.qualification_status==="qualified"||
        x.qualification_status==="BETTING_QUALIFIED_PAPER";
      x.paper_only=true;
      x.live_money_eligible=Boolean(x.live_money_eligible) ||
        Boolean(riskGate?.gate?.[String(x?.sport||"").toLowerCase()]?.live_eligible);
      return x;
    };
    all=all.map(annotate);
    const sport=Q('#upSport'), date=Q('#upDate'), search=Q('#upSearch');
    const setOptions=(el,vals)=>{if(!el||el.dataset.ready)return;el.innerHTML=vals.map(v=>'<option value="'+E(v.value)+'">'+E(v.label)+'</option>').join('');el.dataset.ready="1";};
    setOptions(sport,[{value:"all",label:"All active sports"},{value:"football",label:"⚽ Football"},{value:"tennis",label:"🎾 Tennis"},{value:"virtual",label:"🧪 Virtual / eFootball"}]);
    setOptions(date,[{value:"7",label:"Next 7 days"},{value:"today",label:"Today"},{value:"tomorrow",label:"Tomorrow"},{value:"3",label:"Next 3 days"}]);
    const draw=()=>{
      const now=new Date(), today=now.toISOString().slice(0,10);
      const tomorrow=new Date(now.getTime()+86400000).toISOString().slice(0,10);
      const horizon=Number(date?.value||7); const horizonEnd=new Date(now.getTime()+horizon*86400000);
      const q=String(search?.value||"").trim().toLowerCase();
      const filteredRows=all.filter(x=>{
        if(sport?.value && sport.value!=="all" && x.sport!==sport.value)return false;
        const day=String(x.start_time||"").slice(0,10);
        if(date?.value==="today" && day!==today)return false;
        if(date?.value==="tomorrow" && day!==tomorrow)return false;
        if(date?.value==="3"||date?.value==="7"){
          const d=new Date(x.start_time); if(Number.isNaN(d.getTime())||d>horizonEnd)return false;
        }
        if(q){
          const hay=[x.sport,x.league,x.competition,x.player_1,x.player_2,x.home,x.away,x.pick,x.selection,marketLabel(x)].join(" ").toLowerCase();
          if(!hay.includes(q))return false;
        }
        return true;
      });
      const groups=fixtureGroups(filteredRows);
      const byDay=new Map();
      for(const group of groups){const day=String(group.rows[0].start_time).slice(0,10);if(!byDay.has(day))byDay.set(day,[]);byDay.get(day).push(group);}
      root.innerHTML=groups.length?[...byDay.entries()].map(([day,groupsForDay])=>{
        const label=new Date(day+"T00:00:00Z").toLocaleDateString([], {weekday:"long",month:"short",day:"numeric"});
        return '<section class="ms-up-day"><div class="ms-up-day-head"><h3>'+E(label)+'</h3><span>'+groupsForDay.length+' fixtures</span></div>'+groupsForDay.map(unifiedRow).join("")+'</section>';
      }).join(""):'<div class="ms-empty">No future fixtures match these filters. The engines remain active and the board will refresh with the next generated window.</div>';
      const qualified=filteredRows.filter(x=>x.betting_qualified).length;
      Q('#upCount').textContent=groups.length;
      const qEl=Q('#upQualified'); if(qEl)qEl.textContent=qualified;
      Q('#upLast').textContent=payload.generated_at?DT(payload.generated_at):"—";
    };
    if(!root.dataset.bound){
      sport.addEventListener('change',draw);
      date.addEventListener('change',draw);
      search.addEventListener('input',draw);
      root.dataset.bound='1';
    }
    draw();
  }catch(e){
    root.innerHTML='<div class="ms-empty">Unified upcoming feed unavailable: '+E(e.message)+'</div>';
  }
}
async function renderHub(){const sport=document.body.dataset.sport;const [base,pdl,status,readiness]=await Promise.all([get('./data/predictions.json'),get('./data/pdl_predictions.json').catch(()=>[]),get('./data/pdl_status.json').catch(()=>null),get('./data/football_forward_readiness.json').catch(()=>null)]);const rows=mergeRows(base,pdl);const sportRows=rows.filter(x=>x.sport===sport);Q('#count').textContent=sportRows.length;Q('#upcoming').textContent=sportRows.filter(x=>{const d=new Date(x.start_time);return !isNaN(d)&&d>=new Date()}).length;Q('#leagues').textContent=[...new Set(sportRows.map(x=>x.league).filter(Boolean))].length;if(sport==='football'){const stateMap=new Map((readiness?.statuses||[]).map(x=>[x.league,x]));Q('#leagueGrid').innerHTML=footballLeagues(rows).map(x=>{const state=stateMap.get(x)||{};return leagueCard(x,rows,sport,{calculating:['CALCULATING','CALCULATING_PENDING_PUBLICATION','PROVISIONAL'].includes(state.status)});}).join('')}else if(sport==='tennis'){const tours=['ATP','WTA'];Q('#leagueGrid').innerHTML=tours.map(x=>leagueCard(x,rows,sport)).join('')}else{const leagues=['NBA','WNBA','NCAAM','NCAAW','Euroleague','ACB','BBL','BSL'];Q('#leagueGrid').innerHTML=leagues.map(x=>leagueCard(x,rows,sport)).join('')}}async function card(p){const pr=p.probabilities||{},isT=p.sport==='tennis',ou=isT?(p.analytics||{}).total_games:(p.markets||{}).over_under;const total=ou?('O/U '+(ou.line??'—')+' · '+(ou.pick||'—')+' '+P(ou[ou.pick==='under'?'under':'over'])):null;const wo=p.sportybet_winner_odds||{};const book=wo?.p1&&wo?.p2?'SportyBet 1X2: '+wo.p1+' / '+(wo.draw??'—')+' / '+wo.p2:'';const mi=p.market_insights||{};const edge=mi.winner_model_edge_vs_market;const ti=mi.total;let marketNote='';if(mi.available){marketNote='SportyBet live baseline'+(edge!=null?' · model vs market edge '+P(edge):'');if(ti?.line!=null&&ti.book_odds!=null)marketNote+=' · O/U '+ti.line+' '+String(ti.pick||'').toUpperCase()+' @ '+Number(ti.book_odds).toFixed(2)+(ti.model_edge_vs_market!=null?' · total edge '+P(ti.model_edge_vs_market):'');}else marketNote='SportyBet market snapshot unavailable this run';const absEdge=edge==null?0:Math.max(-.2,Math.min(.2,Number(edge)));const edgeWidth=Math.round(Math.abs(absEdge)*500);const edgeLabel=edge==null?'—':(edge>=0?'+':'')+P(edge);return '<article class="ms-pred"><div class="ms-pred-meta"><span>'+E(p.league||p.sport)+'</span><span>'+E(DT(p.start_time))+'</span></div><div class="ms-match">'+E(p.player_1)+' <span class="ms-muted">vs</span> '+E(p.player_2)+'</div><div class="ms-probs">'+(p.sport==='football'?'<div class="ms-prob"><small>Home</small><b>'+P(pr.p1)+'</b></div><div class="ms-prob"><small>Draw</small><b>'+P(pr.draw)+'</b></div><div class="ms-prob"><small>Away</small><b>'+P(pr.p2)+'</b></div>':'<div class="ms-prob"><small>P1</small><b>'+P(pr.p1)+'</b></div><div class="ms-prob"><small>P2</small><b>'+P(pr.p2)+'</b></div><div class="ms-prob"><small>Confidence</small><b>'+P(p.confidence)+'</b></div>')+'</div><div class="ms-signal">Model pick: <b>'+E(p.pick==='p1'?p.player_1:p.pick==='p2'?p.player_2:(p.pick||'—'))+'</b> · model fair '+E(OD(p.confidence))+(total?'<br><span class="ms-muted">'+E(total)+'</span>':'')+'</div><div class="ms-market-strip"><span class="ms-market-status '+(mi.available?'live':'stale')+'">'+(mi.available?'SPORTYBET LIVE':'MARKET FALLBACK')+'</span><span>'+E(marketNote)+'</span></div><div class="ms-edge"><div><span>Model ↔ market edge</span><b>'+edgeLabel+'</b></div><div class="ms-edge-track"><i style="width:'+edgeWidth+'%"></i></div></div>'+(book?'<div class="ms-note">'+E(book)+'</div>':'')+'<div class="ms-note">Model: '+E(p.model||p.model_version||'Match Signal')+' · '+E(p.decision||p.prediction_status||'PAPER ONLY')+'</div></article>'}async function renderLeague(){const params=new URLSearchParams(location.search),sport=params.get('sport')||'football',league=params.get('league')||'';Q('#leagueName').textContent=league||'League';Q('#leagueSport').textContent=sport.toUpperCase();const [base,pdl]=await Promise.all([get('./data/predictions.json'),get('./data/pdl_predictions.json').catch(()=>[])]);const rows=mergeRows(base,pdl).filter(p=>p.sport===sport&&p.league===league);Q('#count').textContent=rows.length;Q('#upcoming').textContent=rows.filter(x=>new Date(x.start_time)>=new Date()).length;const dates=[...new Set(rows.map(x=>String(x.start_time||'').slice(0,10)).filter(Boolean))];Q('#dateRange').textContent=dates.length?dates.slice(0,1)[0]+' → '+dates.slice(-1)[0]:'No current feed';const search=Q('#search'),sort=Q('#sort'),list=Q('#predictions');const draw=async()=>{let a=rows.filter(p=>{const q=(search.value||'').toLowerCase();return !q||String(p.player_1+' '+p.player_2+' '+(p.tournament||'')).toLowerCase().includes(q)});if(sort.value==='confidence')a.sort((x,y)=>(y.confidence||0)-(x.confidence||0));else a.sort((x,y)=>new Date(x.start_time)-new Date(y.start_time));list.innerHTML=a.length?(await Promise.all(a.map(card))).join(''):'<div class="ms-empty">No prediction rows are currently published for this league. The page remains active and will populate when the engine publishes the competition.</div>'};search.addEventListener('input',draw);sort.addEventListener('change',draw);await draw()}async function renderReports(){const [a,fp,tp,bp]=await Promise.allSettled([get('./data/accuracy.json'),get('./data/football_performance.json'),get('./data/tennis_performance.json'),get('./data/basketball_accuracy.json')]);const acc=a.status==='fulfilled'?a.value:null;const summary=acc?.summary||acc||{};Q('#settled').textContent=summary.settled??summary.total_settled??'—';Q('#accuracy').textContent=summary.accuracy!=null?P(summary.accuracy):'—';Q('#brier').textContent=summary.brier_score!=null?Number(summary.brier_score).toFixed(4):'—';const boxes=[['Football',fp],['Tennis',tp]];const links={'Football':'./league.html?sport=football&league=La%20Liga','Tennis':'./league.html?sport=tennis&league=ATP'};Q('#reportGrid').innerHTML=boxes.map(([name,x])=>{const d=x.status==='fulfilled'?x.value:null;return '<article class="ms-card"><h3>'+name+'</h3><p>'+E(JSON.stringify(d?.summary||d||{status:'No artifact'},null,2).slice(0,900))+'</p><a class="ms-link" href="'+links[name]+'">Open '+name+' desk →</a></article>'}).join('')}function boot(){injectNav();const page=document.body.dataset.page;if(page==='home'||page==='upcoming'||page==='unified'){renderUnifiedBoard();window.setInterval(renderUnifiedBoard,120000);}if(page==='hub')renderHub().catch(e=>{Q('#leagueGrid').innerHTML='<div class="ms-empty">Feed error: '+E(e.message)+'</div>'});if(page==='league')renderLeague().catch(e=>{Q('#predictions').innerHTML='<div class="ms-empty">Feed error: '+E(e.message)+'</div>'});if(page==='reports')renderReports().catch(e=>{Q('#reportGrid').innerHTML='<div class="ms-empty">Report error: '+E(e.message)+'</div>'})}document.addEventListener('DOMContentLoaded',boot)})();