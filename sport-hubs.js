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
  const fairLabel=Number.isFinite(fair)?fair.toFixed(2):"—";
  const qualified=Boolean(x.betting_qualified) || String(x.qualification_status||"").startsWith("BETTING_QUALIFIED");
  const marketReference=book!=null?("SportyBet @ "+book.toFixed(2)):"SportyBet quote unavailable";
  const edgeLabel=Number.isFinite(edge)?((edge>=0?"+":"")+(edge*100).toFixed(1)+"%"):"—";
  const band=String(x.model_candidate_status||"").replaceAll("_"," ");
  const q=qualified?"BETTING-QUALIFIED":(band||x.qualification_status||"MODEL RESEARCH");
  return '<div class="ms-market-row">'+
    '<span class="ms-market-name"><b>'+E(market)+'</b></span>'+
    '<span>Model rating <b>'+(p==null?"—":P(p))+'</b></span>'+
    '<span>Fair <b>'+E(fairLabel)+'</b></span>'+
    '<span>Evidence <b>'+E(String(x.evidence_depth||"model").replaceAll("_"," "))+'</b></span>'+
    '<span class="'+(qualified&&book!=null?"ms-book-live":"ms-book-missing")+'">'+E(marketReference)+'</span>'+
    '<span>Edge <b>'+E(edgeLabel)+'</b></span>'+
    '<span class="ms-market-q '+(qualified?"qualified":"paper")+'">'+E(q)+'</span>'+
  '</div>';
}
function primaryPrediction(rows){
  const rank=x=>{
    const p=Number(probabilityValue(x));
    const q=Boolean(x.betting_qualified)||String(x.qualification_status||"").startsWith("BETTING_QUALIFIED");
    const tier=String(x.projection_tier||"");
    const evidence=String(x.evidence_depth||"");
    const edge=Number(x.model_edge_vs_market);
    return [
      q?1:0,
      Number.isFinite(p)?p*100:0,
      evidence.includes("participant")?3:evidence.includes("historical")?2:1,
      tier.includes("deep")?2:tier.includes("research")?1:0,
      Number.isFinite(edge)?Math.max(-5,Math.min(5,edge*100)):0
    ];
  };
  return [...rows].sort((a,b)=>{
    const ra=rank(a),rb=rank(b);
    for(let i=0;i<ra.length;i++)if(ra[i]!==rb[i])return rb[i]-ra[i];
    return String(a.market||"").localeCompare(String(b.market||""));
  })[0]||null;
}
function ladderAnchor(rows){
  const candidates=(rows||[]).filter(x=>x&&x.market==="over_under"&&Number.isFinite(Number(x.line))&&Number.isFinite(Number(probabilityValue(x)))&&Number(probabilityValue(x))>=0.80);
  return [...candidates].sort((a,b)=>{
    const aq=Boolean(a.betting_qualified||a.qualified_for_builder), bq=Boolean(b.betting_qualified||b.qualified_for_builder);
    if(aq!==bq)return bq-aq;
    const ae=Number(a.model_edge_vs_market),be=Number(b.model_edge_vs_market);
    if(Number.isFinite(ae)||Number.isFinite(be))return (Number.isFinite(be)?be:-999)-(Number.isFinite(ae)?ae:-999);
    return Number(probabilityValue(b))-Number(probabilityValue(a));
  })[0]||null;
}
function ladderRows(rows,anchor){
  if(!anchor||anchor.market!=="over_under")return [];
  const side=String(anchor.pick||anchor.selection||"").toLowerCase();
  const line=Number(anchor.line);
  if(!Number.isFinite(line)||!side)return [];
  const same=(rows||[]).filter(x=>x&&x.market==="over_under"&&String(x.pick||x.selection||"").toLowerCase()===side&&Number.isFinite(Number(x.line)));
  const safe=same.filter(x=>side==="over"?Number(x.line)<line:Number(x.line)>line);
  safe.sort((a,b)=>side==="over"?Number(b.line)-Number(a.line):Number(a.line)-Number(b.line));
  return safe.slice(0,3);
}
function shadowLadderMarkup(group){
  const rows=group?.rows||[];
  if(!rows.some(x=>x&&x.sport==="virtual"&&x.market==="over_under"))return "";
  const anchor=ladderAnchor(rows.filter(x=>x.sport==="virtual"));
  if(!anchor)return "";
  const safe=ladderRows(rows,anchor);
  if(!safe.length)return "";
  const anchorP=probabilityValue(anchor);
  const anchorOdds=bookmakerOdds(anchor);
  const anchorText=(String(anchor.pick||"").toUpperCase()+" "+(anchor.line??""));
  const safeHtml=safe.map(x=>{
    const p=probabilityValue(x), odds=bookmakerOdds(x), edge=Number(x.model_edge_vs_market);
    const edgeText=Number.isFinite(edge)?((edge>=0?"+":"")+((edge*100).toFixed(1))+"%"):"—";
    return '<div class="ms-ladder-option"><span class="ms-ladder-line">'+E(String(x.pick||"").toUpperCase()+" "+(x.line??""))+'</span><span>Model <b>'+E(p==null?"—":P(p))+'</b></span><span class="'+(odds!=null?"ms-book-live":"ms-book-missing")+'">SportyBet '+E(odds!=null?("@ "+odds.toFixed(2)):"—")+'</span><span>Edge <b>'+E(edgeText)+'</b></span><span class="ms-ladder-tag">SAFER RUNG</span></div>';
  }).join("");
  return '<div class="ms-line-ladder"><div class="ms-line-ladder-head"><div><b>Shadow O/U line ladder</b><span>Same directional signal · safer thresholds shown separately</span></div><span class="ms-ladder-badge">PAPER RESEARCH</span></div><div class="ms-line-ladder-anchor"><span>Anchor · '+E(anchorText)+'</span><span>Model <b>'+E(anchorP==null?"—":P(anchorP))+'</b></span><span class="'+(anchorOdds!=null?"ms-book-live":"ms-book-missing")+'">SportyBet '+E(anchorOdds!=null?("@ "+anchorOdds.toFixed(2)):"—")+'</span></div><div class="ms-line-ladder-options">'+safeHtml+'</div><div class="ms-line-ladder-note">The safer rung is not assigned the anchor probability automatically. This display exposes the current desk ladder; promotion remains blocked until the shadow research passes its chronological evidence gate.</div></div>';
}
function unifiedRow(group){
  const rows=group.rows;
  const x=primaryPrediction(rows);
  if(!x)return "";
  const when=DT(x.start_time);
  const qualified=Boolean(x.betting_qualified)||String(x.qualification_status||"").startsWith("BETTING_QUALIFIED");
  const candidateBand=String(x.model_candidate_status||"");
  const live=String(x.event_state||"").toUpperCase()==="LIVE";
  const settled=String(x.event_state||"").toUpperCase()==="SETTLED";
  const book=bookmakerOdds(x);
  const result=String(x.settlement_result||"").toUpperCase();
  const won=settled && (x.settlement_result===x.pick || result==="WIN" || result==="WON" || x.win===true);
  const status=settled?(won?"SETTLED · ✓ WIN":"SETTLED · ✕ LOSS"):
    (qualified?"BETTING QUALIFIED · PAPER":
    (candidateBand==="MODEL_90_PLUS"?"MODEL 90%+":
    candidateBand==="MODEL_80_PLUS"?"MODEL 80%+":
    candidateBand==="MODEL_70_PLUS"?"MODEL 70%+":
    (live?"LIVE RESEARCH":"MODEL RESEARCH")));
  const q=settled?(won?"SETTLED · ✓":"SETTLED · ✕"):(x.betting_qualified?"BETTING-QUALIFIED":(candidateBand||x.qualification_status||"MODEL RESEARCH"));
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
    let riskGate=null; let ladderResearch=null;
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
    try{ ladderResearch=await get('./data/line_ladder_research.json'); }catch(_){ ladderResearch=null; }
    const ladderDesk=Q('#lineLadderDesk');
    if(ladderDesk){
      const state=ladderResearch?.promotion_gate?.status||'SHADOW';
      const anchors=Number(ladderResearch?.current_anchor_count||0);
      const validated=Array.isArray(ladderResearch?.chronological_validation)?ladderResearch.chronological_validation.length:0;
      ladderDesk.innerHTML='<div class="ms-line-ladder-desk-head"><div><b>Directional O/U Line Ladder</b><span>Shadow research layer on the Upcoming Prediction Desk · exact-line qualification is unchanged.</span></div><div class="ms-ladder-desk-stats"><span>'+E(state)+'</span><span>'+E(String(anchors))+' live anchors</span><span>'+E(String(validated))+' validated pairs</span></div></div>';
    }
    let all=Array.isArray(payload?.events)?payload.events:[];
    if(!all.length){
      const sources=[
        './data/predictions.json',
        './data/pdl_predictions.json',
        './data/ere_divisie_predictions.json'
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
      const labels=['football_tennis','football','football'];
      all=chunks.flatMap((rows,i)=>rows.map(r=>normalize(r,labels[i]))).filter(x=>x.start_time);
      payload.generated_at=new Date().toISOString();
    }
    const candidateMap=new Map(selectedRows.map(x=>{
      const event=String(x?.event_id||x?.id||"");
      const pick=String(x?.pick||x?.selection||"");
      const line=x?.line==null?"":String(x.line);
      return [event+"|"+pick+"|"+line,x];
    }));

    // The core prediction feed intentionally does not contain Virtual/eFootball.
    // Bring the existing evidence-backed eFootball candidate lane onto the
    // Upcoming Desk without turning it into a Builder qualification bypass.
    const virtualCandidates=selectedRows.filter(x=>{
      const product=String(x?.product||"").toLowerCase();
      const group=String(x?.candidate_group||"").toLowerCase();
      const p=Number(x?.model_probability);
      const start=Date.parse(String(x?.start_time||""));
      return (
        x &&
        String(x?.sport||"").toLowerCase()==="virtual" &&
        (product==="efootball_gt" || product==="efootball_adriatic" || group==="efootball") &&
        Number.isFinite(p) &&
        p>=0.80 &&
        Number.isFinite(start)
      );
    });

    async function freshVirtualQuoteMap(){
      const byEvent={};
      try{
        const feed=await get('./api/sportybet-virtual?sources=efootball&pageSize=100&pageNum=1&timeline=168');
        const events=Array.isArray(feed?.events)?feed.events:[];
        events.forEach(e=>{
          const id=String(e?.event_id||"");
          if(id)byEvent[id]=e;
        });
      }catch(_){}
      return byEvent;
    }

    function virtualCandidateDeskRows(rows,quoteMap){
      const now=Date.now();
      return rows.map(row=>{
        const eventId=String(row?.event_id||"");
        const live=quoteMap[eventId];
        const line=Number(row?.line);
        const side=String(row?.pick||row?.selection||"").toLowerCase();
        if(!live || !Number.isFinite(line) || (side!=="over" && side!=="under")) return null;
        const matchStart=Date.parse(String(row?.start_time||""));
        if(!Number.isFinite(matchStart) || matchStart < now) return null;

        let over=null,under=null;
        for(const market of Array.isArray(live?.markets)?live.markets:[]){
          const ml=Number(market?.line);
          if(!Number.isFinite(ml) || Math.abs(ml-line)>1e-9)continue;
          for(const outcome of Array.isArray(market?.outcomes)?market.outcomes:[]){
            const name=String(outcome?.name||"").toLowerCase();
            const odds=Number(outcome?.odds);
            if(!Number.isFinite(odds) || odds<=1)continue;
            if(name.startsWith("over"))over=odds;
            if(name.startsWith("under"))under=odds;
          }
          if(over!=null || under!=null)break;
        }
        const selectedOdds=side==="over"?over:under;
        if(selectedOdds==null)return null;

        const p=Number(row?.model_probability);
        const fair=Number(row?.model_fair_odds);
        const edge=Number(row?.model_edge_vs_market);
        const candidateStatus=String(row?.candidate_status||row?.candidate_group||"MODEL_RESEARCH");
        const qual=Boolean(row?.betting_qualified)||Boolean(row?.qualified_for_builder)||
          String(row?.qualification_status||"").startsWith("BETTING_QUALIFIED");

        return {
          ...row,
          sport:"virtual",
          event_id:eventId,
          start_time:row.start_time,
          player_1:row.player_1||live?.participant_1,
          player_2:row.player_2||live?.participant_2,
          league:row.league||live?.competition||"eFootball",
          competition:row.competition||live?.competition,
          market:"over_under",
          selection:"O/U "+side+" "+line,
          pick:side,
          probability:p,
          confidence:p,
          model_fair_odds:Number.isFinite(fair)?fair:(p>0?1/p:null),
          bookmaker_odds:selectedOdds,
          sportybet_odds:selectedOdds,
          model_edge_vs_market:Number.isFinite(edge)?edge:null,
          candidate_status:candidateStatus,
          model_candidate_status:candidateStatus,
          projection_tier:row.projection_tier||"deep_research_projection",
          evidence_depth:row.evidence_depth||"exact_line_research",
          qualification_status:row.qualification_status||"MODEL_RESEARCH",
          betting_qualified:qual,
          qualified_for_builder:Boolean(row?.qualified_for_builder),
          paper_only:true,
          live_money_eligible:false,
          market_odds_timestamp:new Date().toISOString(),
          source_engine:"Virtual Lab",
          desk_source:"selection_candidates + fresh SportyBet virtual quote"
        };
      }).filter(Boolean);
    }
    const annotate=(x)=>{
      const event=String(x?.event_id||"");
      const pick=String(x?.pick||x?.selection||"");
      const line=x?.line==null?"":String(x.line);
      const exact=event+"|"+pick+"|"+line;
      const broad=event+"|"+pick+"|";
      const candidate=candidateMap.get(exact)||[...candidateMap.entries()].find(([k])=>k.startsWith(broad))?.[1];
      if(candidate){
        x.model_candidate_status=candidate.candidate_status||"MODEL_RESEARCH";
        x.model_rating=candidate.model_rating??null;
        x.candidate_group=candidate.candidate_group||null;
        x.candidate_source="selection_candidates";
      }
      x.betting_qualified=Boolean(x.betting_qualified)||Boolean(x.qualified_for_builder)||
        x.qualification_status==="BETTING_QUALIFIED_PAPER"||
        x.qualification_status==="BETTING_QUALIFIED_PAPER_BOOTSTRAP"||
        x.qualification_status==="BETTING_QUALIFIED_PAPER_DIRECTIONAL";
      x.paper_only=true;
      x.live_money_eligible=Boolean(x.live_money_eligible) ||
        Boolean(riskGate?.gate?.[String(x?.sport||"").toLowerCase()]?.live_eligible);
      return x;
    };
    all=all.map(annotate);
    try{
      const quoteMap=await freshVirtualQuoteMap();
      const virtualDeskRows=virtualCandidateDeskRows(virtualCandidates,quoteMap);
      if(virtualDeskRows.length){
        const existingKeys=new Set(all.map(row=>rowFixtureKey(row)));
        for(const row of virtualDeskRows){
          const key=rowFixtureKey(row);
          if(!existingKeys.has(key)){
            all.push(annotate(row));
            existingKeys.add(key);
          }else{
            // Keep any existing unified event row, but add the richer eFootball
            // candidate into its fixture group when it represents a distinct
            // O/U line/side. This preserves the canonical event while exposing
            // the evidence-backed market prediction.
            all.push(row);
          }
        }
      }
    }catch(_){}
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
      const strong=filteredRows.filter(x=>Number(probabilityValue(x))>=0.80).length;
      Q('#upCount').textContent=groups.length;
      const sEl=Q('#upStrong'); if(sEl)sEl.textContent=strong;
      const qEl=Q('#upQualified'); if(qEl)qEl.textContent=qualified;
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