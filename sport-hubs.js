(()=>{'use strict';const Q=s=>document.querySelector(s),E=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML},N=v=>Number.isFinite(Number(v))?Number(v):null,P=v=>N(v)==null?'—':Math.round(N(v)*100)+'%',OD=p=>N(p)>0?(1/N(p)).toFixed(2):'—',DT=v=>{const d=new Date(v);return isNaN(d)?'—':d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})};async function get(path){const sep=String(path).includes('?')?'&':'?';const r=await fetch(path+sep+'v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()}function mergeRows(base,pdl){const out=new Map();[...(Array.isArray(base)?base:[]),...(Array.isArray(pdl)?pdl:[])].forEach(row=>{if(!row||!row.event_id)return;out.set(String(row.event_id),row)});return [...out.values()]}const nav=()=>'<nav class="ms-nav"><a class="ms-brand ms-brand-link" href="./index.html" aria-label="Return to Match Signal main desk"><div class="ms-mark" aria-hidden="true"><svg viewBox="0 0 48 48" width="32" height="32" fill="none"><path d="M9 28.5a15 15 0 0 1 30 0" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/><path d="M14 29a10 10 0 0 1 20 0M19 29a5 5 0 0 1 10 0" stroke="#42e59a" stroke-width="2.4" stroke-linecap="round"/><path d="M24 29l9-11" stroke="#eef7fb" stroke-width="3" stroke-linecap="round"/><circle cx="24" cy="29" r="3.2" fill="#37e7ff"/><path d="M8 35h32" stroke="#7c6cff" stroke-width="1.8" stroke-linecap="round"/></svg></div><div><h1>Match Signal</h1><p>Real-data, market-calibrated sports prediction desk</p></div></a><div class="ms-tabs"><a class="ms-btn" href="./index.html">📅 Upcoming</a><a class="ms-btn" href="./football.html">⚽ Football</a><a class="ms-btn" href="./tennis.html">🎾 Tennis</a><a class="ms-btn" href="./live.html">🔴 Live</a><a class="ms-btn" href="./reports.html">📊 Reports</a><a class="ms-btn" href="./odds-builder.html">🧮 Odds Builder</a><a class="ms-btn" href="./virtual-lab/">🧪 Lab</a></div></nav>';function injectNav(){const n=Q('#msNav');if(n)n.innerHTML=nav()}function footballLeagues(rows){const base=['La Liga','Bundesliga','Ligue 1','Champions League'];return [...new Set([...base,...rows.filter(x=>x.sport==='football').map(x=>x.league).filter(Boolean)])]}function leagueCard(name,rows,sport,meta={}){const count=rows.filter(x=>x.sport===sport&&x.league===name).length;const calculating=meta.calculating===true&&count===0;const desc=sport==='football'&&name.includes('Professional Development')?'U21 academy competition · historical results + dedicated forward fixture model':sport==='tennis'?name+' tour · tournament-level fixtures and model signals':name+' · 22-day forward planning when fixtures are available';const badge=calculating?'Calculating':count===0?'Pending':count+' predictions';return '<article class="ms-league"><div class="ms-league-top"><h3>'+E(name)+'</h3><span class="ms-badge '+(calculating?'':'')+'">'+badge+'</span></div><p>'+E(desc)+'</p><a href="./league.html?sport='+encodeURIComponent(sport)+'&league='+encodeURIComponent(name)+'">Open league page →</a></article>'}function sportIcon(s){
  return ({football:"⚽",tennis:"🎾",basketball:"🏀",darts:"🏹",table_tennis:"🏓",virtual:"🧪"}[s]||"•");
}
function evidenceLabel(x){
  const d=String(x.evidence_depth||"").replaceAll("_"," ");
  let base=d;
  if(!base){
    if(x.projection_tier==="deep_model")base="deep model";
    else if(x.projection_tier==="research_model")base="research model";
    else if(x.projection_tier==="testing_projection")base="testing projection";
    else base="baseline projection";
  }
  const product=String(x.product||"").toLowerCase();
  if(product==="efootball_gt"||product==="vfootball"){
    const line=Number(x.line);
    const side=String(x.pick||x.selection||"").toLowerCase();
    const wfN=Number(x.walkforward_exact_line_n);
    const wfHit=Number(x.walkforward_exact_line_hit_rate);
    if(product==="vfootball"&&side==="under"&&Number.isFinite(line)&&line>=7.5){
      if(!Number.isFinite(wfN)||wfN<=0)return base+" · no exact-line walk-forward sample · NOT QUALIFIED";
      if(wfN<30||!Number.isFinite(wfHit)||wfHit<0.65)return base+" · exact-line walk-forward "+Math.round(wfN)+"/30 · insufficient evidence · NOT QUALIFIED";
      return base+" · exact-line walk-forward "+Math.round(wfN)+"/30 · "+Math.round(wfHit*100)+"% hit rate · separate value gates still apply";
    }
    const n=Number(x.desk_learning_exact_n);
    if(Number.isFinite(n)){
      const count=Math.max(0,Math.round(n));
      const accuracy=Number(x.desk_learning_exact_accuracy);
      const results=Number.isFinite(accuracy)
        ? count+" settled · "+Math.round(accuracy*100)+"% hit rate"
        : count+" settled";
      const source=String(x.desk_learning_adjustment_source||"NONE");
      if(base==="feed discovered base model")base="feed baseline · no participant-specific calibration";
      let state;
      if(source==="EXACT_LINE_DIRECTION")state="exact-line calibrated";
      else if(source==="PROBABILITY_BUCKET")state="bucket calibrated";
      else if(source==="SIDE_COMPARISON_ONLY")state="side comparison used; displayed side raw";
      else if(count<12)state="exact-line calibration only ("+count+"/12; qualification is separate)";
      else state="line history available; probability unadjusted";
      return base+" · "+results+" · "+state;
    }
  }
  return base;
}
function isOverUnderPrediction(x){
  const market=String(x?.market||"").toLowerCase().replace(/[\s-]+/g,"_");
  const sourceMarket=String(x?.sportybet_odds_market||"").toLowerCase();
  const side=String(x?.pick||x?.selection||"").toLowerCase();
  return sourceMarket==="total" ||
    ["over_under","total_goals_over_under","total_games","totals","total"].includes(market) ||
    ((side==="over"||side==="under")&&x?.line!=null);
}
function exactVirtualMarketLine(market){
  if(market?.line!=null){
    const direct=Number(market.line);
    if(Number.isFinite(direct))return direct;
  }
  const specifier=String(market?.specifier??market?.specifiers??market?.marketSpecifier??"");
  const match=specifier.match(/(?:^|[,\s;|&])(?:total|line)\s*=\s*(-?\d+(?:\.\d+)?)(?=$|[,\s;|&])/i);
  if(match){
    const parsed=Number(match[1]);
    if(Number.isFinite(parsed))return parsed;
  }
  return null;
}
function marketLabel(x){
  if(isOverUnderPrediction(x)){
    return "O/U "+(x.pick||x.selection||"—")+" "+(x.line??"");
  }
  if(x.pick==="p1"||x.pick==="p2"||x.pick==="draw"){
    const pick=x.pick==="p1"?x.player_1:x.pick==="p2"?x.player_2:"Draw";
    return "Winner · "+(pick||x.pick);
  }
  return x.pick||x.markets?.over_under?.pick||"Model projection";
}
function rawProbabilityValue(x){
  const valid=value=>{
    if(value===null||value===undefined||String(value).trim()==="")return null;
    const n=Number(value);
    return Number.isFinite(n)&&n>=0&&n<=1?n:null;
  };
  const direct=valid(x?.probability);
  if(direct!==null)return direct;
  const confidence=valid(x?.confidence);
  if(confidence!==null)return confidence;
  const model=valid(x?.model_probability);
  if(model!==null)return model;
  const pr=x?.probabilities||{};
  return valid(x?.pick?pr[x.pick]:null);
}
function probabilityCalibrationInfo(x){
  const raw=rawProbabilityValue(x);
  const product=String(x?.product||"").toLowerCase();
  const side=String(x?.pick||x?.selection||"").toLowerCase();
  const line=x?.line==null||String(x.line).trim()===""?NaN:Number(x.line);
  const rawN=x?.walkforward_exact_line_n;
  const rawHit=x?.walkforward_exact_line_hit_rate;
  const n=rawN==null||String(rawN).trim()===""?NaN:Number(rawN);
  const hit=rawHit==null||String(rawHit).trim()===""?NaN:Number(rawHit);
  if(raw===null||!["efootball_gt","efootball_adriatic"].includes(product)||
     !isOverUnderPrediction(x)||!Number.isFinite(line)||(side!=="over"&&side!=="under")||
     !Number.isFinite(n)||n<30||!Number.isFinite(hit)||hit<0||hit>1)return null;
  // Blend the model estimate toward its own exact-line chronological walk-forward
  // hit rate. n/(n+30) is the same evidence-weighting form used by the desk
  // learner; it reduces unsupported certainty without pretending the historical
  // rate is a guarantee. This adjustment affects Desk display/value evaluation only.
  const weight=n/(n+30);
  const probability=Math.max(0.01,Math.min(0.99,raw+(hit-raw)*weight));
  return {raw,probability,hitRate:hit,n,weight};
}
function probabilityValue(x){
  const calibrated=probabilityCalibrationInfo(x);
  return calibrated?calibrated.probability:rawProbabilityValue(x);
}
function displayedFairOddsValue(x){
  const calibration=probabilityCalibrationInfo(x);
  if(calibration&&calibration.probability>0)return 1/calibration.probability;
  const fair=Number(x?.model_fair_odds);
  return Number.isFinite(fair)&&fair>1?fair:null;
}
function isVirtualDeskCandidate(row){
  if(!row)return false;
  const product=String(row?.product||"").toLowerCase();
  const probability=rawProbabilityValue(row);
  const start=Date.parse(String(row?.start_time||""));
  const upstreamQualified=Boolean(row?.betting_qualified)||Boolean(row?.qualified_for_builder)||
    String(row?.qualification_status||"").startsWith("BETTING_QUALIFIED");
  return String(row?.sport||"").toLowerCase()==="virtual"&&
    isActiveVirtualProduct(product)&&Number.isFinite(probability)&&
    (probability>=0.80||upstreamQualified)&&Number.isFinite(start);
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
    const m=isOverUnderPrediction(row)?"over_under":"winner";
    const line=row.line==null?"":String(row.line);
    const pick=String(row.pick||row.selection||"");
    const dedupe=m+"|"+line+"|"+pick;
    if(!g.rows.some(x=>((isOverUnderPrediction(x)?"over_under":"winner")+"|"+(x.line==null?"":String(x.line))+"|"+String(x.pick||x.selection||""))===dedupe)){
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
function exactSportyBetQuote(x){
  const market=isOverUnderPrediction(x)?"over_under":"winner";
  const value=Number(x?.bookmaker_odds??x?.sportybet_odds??x?.book_odds);
  if(!Number.isFinite(value)||value<=1)return {odds:null,displayOdds:null,reason:"NO_QUOTE",fresh:false};
  const sourceMarket=String(x?.sportybet_odds_market||"").toLowerCase();
  if(market==="over_under"){
    if(sourceMarket!=="total")return {odds:null,displayOdds:null,reason:"MARKET_UNVERIFIED",fresh:false};
    const line=Number(x?.line),quotedLine=Number(x?.sportybet_odds_line);
    const side=String(x?.pick||x?.selection||"").toLowerCase();
    const quotedSide=String(x?.sportybet_odds_side||"").toLowerCase();
    if(!Number.isFinite(line)||!Number.isFinite(quotedLine)||Math.abs(line-quotedLine)>1e-9)return {odds:null,displayOdds:null,reason:"LINE_MISMATCH",fresh:false};
    if((side!=="over"&&side!=="under")||quotedSide!==side)return {odds:null,displayOdds:null,reason:"SIDE_MISMATCH",fresh:false};
  }else if(sourceMarket!=="winner"){
    return {odds:null,displayOdds:null,reason:"MARKET_UNVERIFIED",fresh:false};
  }else{
    const side=String(x?.pick||x?.selection||"").toLowerCase();
    if(!["p1","p2","draw"].includes(side)||String(x?.sportybet_odds_side||"").toLowerCase()!==side)return {odds:null,displayOdds:null,reason:"SIDE_MISMATCH",fresh:false};
  }
  // Identity matches the requested event-market-line-side. Preserve the last
  // recorded quote for transparency when its timestamp is missing/stale, but
  // never use that display-only value to calculate edge or qualify the pick.
  const timestamp=Date.parse(String(x?.market_odds_timestamp||x?.odds_timestamp||""));
  const now=Date.now();
  if(!Number.isFinite(timestamp))return {odds:null,displayOdds:value,reason:"TIMESTAMP_UNVERIFIED",fresh:false};
  if(timestamp>now+2*60*1000)return {odds:null,displayOdds:value,reason:"QUOTE_TIMESTAMP_IN_FUTURE",timestamp:timestamp,fresh:false};
  if(now-timestamp>15*60*1000)return {odds:null,displayOdds:value,reason:"QUOTE_STALE",timestamp:timestamp,fresh:false};
  return {odds:value,displayOdds:value,reason:"EXACT_MARKET_LINE_SIDE_FRESH",timestamp:timestamp,fresh:true};
}
function bookmakerOdds(x){
  return exactSportyBetQuote(x).odds;
}
function exactMarketEdge(x,quote){
  if(!quote||quote.odds==null)return null;
  const selected=String(x?.pick||x?.selection||"").toLowerCase();
  const probability=probabilityValue(x);
  const p=probability===null?NaN:Number(probability);
  if(!Number.isFinite(p)||p<0||p>1)return null;
  let selectedOdds=Number(quote.odds),oppositeOdds=null,marketProb=null;
  if(isOverUnderPrediction(x)){
    const line=Number(x?.line),quotedLine=Number(x?.sportybet_odds_line);
    if(!Number.isFinite(line)||!Number.isFinite(quotedLine)||Math.abs(line-quotedLine)>1e-9)return null;
    let over=Number(x?.sportybet_over_odds),under=Number(x?.sportybet_under_odds);
    if((!Number.isFinite(over)||over<=1||!Number.isFinite(under)||under<=1) && Array.isArray(x?.sportybet_total_games_odds)){
      over=under=null;
      x.sportybet_total_games_odds.forEach(item=>{
        const itemLine=Number(item?.line),side=String(item?.side||"").toLowerCase(),odds=Number(item?.odds);
        if(!Number.isFinite(itemLine)||Math.abs(itemLine-line)>1e-9||!Number.isFinite(odds)||odds<=1)return;
        if(side==="over")over=odds;if(side==="under")under=odds;
      });
    }
    if(!Number.isFinite(over)||over<=1||!Number.isFinite(under)||under<=1)return null;
    const sideOdds=selected==="over"?over:selected==="under"?under:null;
    if(sideOdds==null||Math.abs(sideOdds-selectedOdds)>1e-9)return null;
    const invOver=1/over,invUnder=1/under,sum=invOver+invUnder;
    marketProb=(1/selectedOdds)/sum;
  }else{
    const winner=x?.sportybet_winner_odds;
    if(!winner||typeof winner!=="object")return null;
    const sides=["p1","p2","draw"].map(key=>({key,odds:Number(winner[key])})).filter(item=>Number.isFinite(item.odds)&&item.odds>1);
    const picked=sides.find(item=>item.key===selected);
    if(!picked||Math.abs(picked.odds-selectedOdds)>1e-9||sides.length<2)return null;
    const sum=sides.reduce((total,item)=>total+1/item.odds,0);
    if(sum<=0)return null;
    marketProb=(1/selectedOdds)/sum;
  }
  return Number.isFinite(marketProb)?p-marketProb:null;
}
function qualificationVetoReason(x){
  const gate=x?.selection_gate||{};
  const fields=[
    x?.qualification_status,
    x?.candidate_status,
    x?.model_candidate_status,
    x?.prediction_status,
    gate?.status,
    ...(Array.isArray(gate?.reasons)?gate.reasons:[])
  ].filter(value=>value!=null&&String(value).trim()).map(value=>String(value).trim());
  if(x?.watch_projection===true||x?.forward_watch===true||x?.research_only===true)return "EXPLICIT_QUALIFICATION_VETO";
  return fields.some(value=>/(?:NOT[\s_-]*QUALIFIED|UNQUALIFIED|WATCH|RESEARCH|PROJECTION_ONLY|EVIDENCE[\s_-]*GATE[\s_-]*PENDING|PENDING[\s_-]*EVIDENCE)/i.test(value))
    ?"EXPLICIT_QUALIFICATION_VETO":null;
}
function qualificationState(x){
  const raw=String(x?.qualification_status||"").trim();
  const veto=qualificationVetoReason(x);
  const modelQualified=!veto&&(Boolean(x?.betting_qualified)||Boolean(x?.qualified_for_builder)||raw.startsWith("BETTING_QUALIFIED"));
  if(!modelQualified){
    const detail=veto
      ?String(raw||x?.candidate_status||x?.model_candidate_status||"explicit watch/research gate").replaceAll("_"," ")
      :(raw&&raw!=="MODEL_RESEARCH"&&raw!=="RESEARCH_PROJECTION"?raw.replaceAll("_"," "):"RESEARCH ONLY");
    const modelReason=raw.includes("DIRECTIONAL_LINE_VALIDATION_GATE_PENDING")?"DIRECTIONAL_LINE_VALIDATION_GATE_PENDING":
      raw.includes("MODEL_LINE_SCOPE_GATE_PENDING")?"MODEL_LINE_SCOPE_GATE_PENDING":
      raw.includes("HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING")?"HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING":"MODEL_GATE_NOT_PASSED";
    return {modelQualified:false,currentPricePass:false,label:"NOT QUALIFIED · "+detail,reason:veto||modelReason};
  }
  const quote=exactSportyBetQuote(x);
  if(quote.odds==null){
    const labels={
      QUOTE_STALE:"NOT ACTIONABLE · PRICE STALE",
      TIMESTAMP_UNVERIFIED:"NOT ACTIONABLE · QUOTE TIME UNVERIFIED",
      QUOTE_TIMESTAMP_IN_FUTURE:"NOT ACTIONABLE · QUOTE TIME INVALID",
    };
    return {modelQualified:true,currentPricePass:false,label:labels[quote.reason]||"NOT ACTIONABLE · PRICE UNVERIFIED",reason:quote.reason};
  }
  const edge=exactMarketEdge(x,quote);
  if(edge==null){
    return {modelQualified:true,currentPricePass:false,label:"NOT ACTIONABLE · VALUE UNVERIFIED",reason:"FRESH_TWO_SIDED_MARKET_REQUIRED"};
  }
  if(edge<0.02){
    return {modelQualified:true,currentPricePass:false,label:"NOT QUALIFIED · CURRENT EDGE BELOW 2%",reason:"CURRENT_EDGE_BELOW_2_PERCENT",edge:edge};
  }
  return {modelQualified:true,currentPricePass:true,label:"BETTING-QUALIFIED · PAPER",reason:"CURRENT_PRICE_GATE_PASSED",edge:edge};
}

function qualificationLabel(x){
  return qualificationState(x).label;
}
function unifiedMarketLine(x){
  const p=probabilityValue(x);
  const calibration=probabilityCalibrationInfo(x);
  const quote=exactSportyBetQuote(x);
  const book=quote.odds;
  const displayBook=quote.displayOdds==null?book:quote.displayOdds;
  const fair=displayedFairOddsValue(x);
  const edge=exactMarketEdge(x,quote);
  const pick=String(x.pick||x.selection||"").toUpperCase();
  const market=isOverUnderPrediction(x)?("O/U "+pick+" "+(x.line??"")):marketLabel(x);
  const fairLabel=Number.isFinite(fair)?fair.toFixed(2):"—";
  const marketReference=book!=null
    ?("SportyBet @ "+book.toFixed(2))
    :displayBook!=null
      ?("SportyBet last seen @ "+displayBook.toFixed(2)+" · "+String(quote.reason||"unverified").replaceAll("_"," ").toLowerCase())
      :("SportyBet exact quote "+String(quote.reason||"unavailable").replaceAll("_"," ").toLowerCase());
  const marketQuoteClass=book!=null?"ms-book-live":displayBook!=null?"ms-book-stale":"ms-book-missing";
  const edgeLabel=edge!=null?((edge>=0?"+":"")+(edge*100).toFixed(1)+"%"):"— (requires fresh two-sided exact market)";
  const evidence=evidenceLabel(x);
  return '<div class="ms-market-row">'+
    '<span class="ms-market-name"><b>'+E(market)+'</b></span>'+
    '<span>'+(calibration?'Desk-calibrated estimate':'Model estimate')+' <b>'+(p==null?"—":P(p))+'</b></span>'+
    (calibration?'<span>Raw model <b>'+P(calibration.raw)+'</b> · exact-line walk-forward '+P(calibration.hitRate)+' (n='+Math.round(calibration.n)+')</span>':'')+
    '<span>Model fair <b>'+E(fairLabel)+'</b></span>'+
    '<span>Evidence <b>'+E(String(evidence||"unavailable"))+'</b></span>'+
    '<span class="'+marketQuoteClass+'">'+E(marketReference)+'</span>'+
    '<span>Edge <b>'+E(edgeLabel)+'</b></span>'+
  '</div>';
}
function qualifiedBestRow(x){
  const when=DT(x.start_time);
  const status=qualificationState(x);
  const edge=Number.isFinite(status.edge)?(status.edge>=0?"+":"")+(status.edge*100).toFixed(1)+"%":"—";
  return '<article class="ms-up-row ms-fixture-card ms-qualified-best-row">'+
    '<div class="ms-up-time"><b>'+E(when)+'</b><span>'+E(String(x.start_time||"").slice(0,10))+'</span></div>'+
    '<div class="ms-up-event"><div class="ms-up-meta"><span class="ms-sport-pill">'+sportIcon(x.sport)+' '+E(x.sport==="table_tennis"?"Table Tennis":(x.sport||"Sport"))+'</span><span>'+E(x.league||x.competition||"Unclassified")+'</span><span class="ms-fixture-market-count">Qualified market</span></div>'+
    '<div class="ms-up-match">'+E(x.player_1||x.home||"Participant 1")+' <span>vs</span> '+E(x.player_2||x.away||"Participant 2")+'</div>'+
    '<div class="ms-market-stack">'+unifiedMarketLine(x)+'</div>'+
    '<div class="ms-fixture-foot"><span class="ms-qualified-gate-badge">QUALIFIED BEST · PAPER</span><span>Exact SportyBet market · edge '+E(edge)+' after margin removal</span></div></div>'+
    '<div class="ms-up-status"><span class="ms-up-status-badge deep">QUALIFIED BEST · PAPER</span></div>'+
  '</article>';
}
// VFOOTBALL_RESEARCH_ONLY: source feed, Virtual Lab and history remain intact;
 // active Virtual Desk and Builder selections are limited to eFootball products.
function isActiveVirtualProduct(product){
  const key=String(product||"").toLowerCase();
  return key==="efootball_gt"||key==="efootball_adriatic";
}
function primaryPrediction(rows){
  const rank=x=>{
    const gate=qualificationState(x);
    const p=Number(probabilityValue(x));
    const tier=String(x.projection_tier||"");
    const evidence=String(x.evidence_depth||"");
    const edge=Number(x.model_edge_vs_market);
    const pendingHighUnder=String(x.qualification_status||"")==="HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING";
    const exactN=Number(x.walkforward_exact_line_n);
    return [
      gate.currentPricePass?1:0,
      gate.modelQualified?1:0,
      pendingHighUnder?0:1,
      Number.isFinite(exactN)?Math.min(30,exactN):0,
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
function qualificationBlockerLabel(reason){
  const labels={
    EXPLICIT_QUALIFICATION_VETO:"Explicit watch/research/not-qualified status",
    MODEL_GATE_NOT_PASSED:"Model/evidence qualification not passed",
    DIRECTIONAL_LINE_VALIDATION_GATE_PENDING:"Directional line validation still pending",
    MODEL_LINE_SCOPE_GATE_PENDING:"Model line-scope validation still pending",
    HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING:"High-line Under evidence still insufficient",
    NO_QUOTE:"No exact SportyBet quote",
    MARKET_UNVERIFIED:"Market identity unverified",
    LINE_MISMATCH:"Quoted line does not match",
    SIDE_MISMATCH:"Quoted selection does not match",
    TIMESTAMP_UNVERIFIED:"Quote timestamp missing",
    QUOTE_TIMESTAMP_IN_FUTURE:"Quote timestamp invalid",
    QUOTE_STALE:"Quote older than 15 minutes",
    FRESH_TWO_SIDED_MARKET_REQUIRED:"Fresh two-sided exact market missing",
    CURRENT_EDGE_BELOW_2_PERCENT:"Current edge below +2%"
  };
  return labels[reason]||String(reason||"NOT_QUALIFIED").replaceAll("_"," ").toLowerCase();
}
function qualifiedBestSelections(rows,now=Date.now()){
  const horizon=now+7*24*60*60*1000;
  const exactMarkets=new Map();
  for(const row of Array.isArray(rows)?rows:[]){
    if(!row)continue;
    const kickoff=Date.parse(String(row?.start_time||""));
    if(!Number.isFinite(kickoff)||kickoff<=now||kickoff>horizon)continue;
    const state=String(row?.event_state||"").toUpperCase();
    if(["LIVE","SETTLED","FINAL","FINISHED","ENDED"].includes(state)||row?.live===true||row?.isLive===true)continue;
    const sport=String(row?.sport||"").toLowerCase();
    const product=String(row?.product||"").toLowerCase();
    const virtual=sport==="virtual"||["efootball_gt","efootball_adriatic","vfootball","zoom"].includes(product);
    if(virtual&&!isActiveVirtualProduct(product))continue;
    const market=isOverUnderPrediction(row)?"over_under":String(row?.market||"winner");
    const line=row?.line==null?"":String(row.line);
    const side=String(row?.pick||row?.selection||"").toLowerCase();
    const identity=[rowFixtureKey(row),market,line,side].join("|");
    const gate=qualificationState(row);
    const existing=exactMarkets.get(identity);
    const quality=x=>(x.gate.currentPricePass?3:0)+(x.gate.modelQualified?1:0);
    const candidate={row,gate};
    if(!existing||quality(candidate)>quality(existing)||
      (quality(candidate)===quality(existing)&&Number(probabilityValue(row)||0)>Number(probabilityValue(existing.row)||0))){
      exactMarkets.set(identity,candidate);
    }
  }
  const blockerCounts={};
  let modelQualifiedMarkets=0,freshExactQuoteMarkets=0,twoSidedValueMarkets=0,edgePassingMarkets=0;
  const bestByFixture=new Map();
  for(const candidate of exactMarkets.values()){
    const row=candidate.row,gate=qualificationState(row);
    if(gate.modelQualified)modelQualifiedMarkets++;
    const quote=exactSportyBetQuote(row);
    if(quote.odds!=null)freshExactQuoteMarkets++;
    const edge=exactMarketEdge(row,quote);
    if(edge!=null)twoSidedValueMarkets++;
    if(!gate.currentPricePass){
      const reason=gate.reason||"MODEL_GATE_NOT_PASSED";
      blockerCounts[reason]=(blockerCounts[reason]||0)+1;
      continue;
    }
    edgePassingMarkets++;
    const fixture=rowFixtureKey(row),previous=bestByFixture.get(fixture);
    const score=x=>{
      const state=qualificationState(x);
      return [Number.isFinite(state.edge)?state.edge:-999,Number(probabilityValue(x)||0),-Date.parse(String(x.start_time||""))];
    };
    if(!previous){
      bestByFixture.set(fixture,row);
    }else{
      const a=score(row),b=score(previous);
      if(a[0]>b[0]||(a[0]===b[0]&&(a[1]>b[1]||(a[1]===b[1]&&a[2]>b[2]))))bestByFixture.set(fixture,row);
    }
  }
  const selected=[...bestByFixture.values()].sort((a,b)=>{
    const ga=qualificationState(a),gb=qualificationState(b);
    const ea=Number.isFinite(ga.edge)?ga.edge:-999,eb=Number.isFinite(gb.edge)?gb.edge:-999;
    if(ea!==eb)return eb-ea;
    const pa=Number(probabilityValue(a)||0),pb=Number(probabilityValue(b)||0);
    if(pa!==pb)return pb-pa;
    return Date.parse(String(a.start_time||""))-Date.parse(String(b.start_time||""));
  });
  return {rows:selected,diagnostics:{
    futureCandidateMarkets:exactMarkets.size,
    modelQualifiedMarkets,
    freshExactQuoteMarkets,
    twoSidedValueMarkets,
    edgePassingMarkets,
    qualifiedFixtures:selected.length,
    blockerCounts
  }};
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
function unifiedRow(group){
  const rows=group.rows;
  const x=primaryPrediction(rows);
  if(!x)return "";
  const when=DT(x.start_time);
  const qualification=qualificationState(x);
  const qualified=qualification.currentPricePass;
  const modelQualified=qualification.modelQualified;
  const candidateBand=String(x.model_candidate_status||"");
  const live=String(x.event_state||"").toUpperCase()==="LIVE";
  const settled=String(x.event_state||"").toUpperCase()==="SETTLED";
  const quote=exactSportyBetQuote(x);
  const book=quote.odds;
  const displayBook=quote.displayOdds==null?book:quote.displayOdds;
  const result=String(x.settlement_result||"").toUpperCase();
  const won=settled && (x.settlement_result===x.pick || result==="WIN" || result==="WON" || x.win===true);
  const status=settled?(won?"SETTLED · ✓ WIN":"SETTLED · ✕ LOSS"):
    (qualified?"BETTING-QUALIFIED · PAPER":
    (modelQualified?qualification.label:
    (candidateBand==="MODEL_90_PLUS"?"MODEL ESTIMATE ≥90% · NOT QUALIFIED":
    candidateBand==="MODEL_80_PLUS"?"MODEL ESTIMATE ≥80% · NOT QUALIFIED":
    candidateBand==="MODEL_70_PLUS"?"MODEL ESTIMATE ≥70% · NOT QUALIFIED":
    (live?"LIVE RESEARCH · NOT QUALIFIED":"MODEL RESEARCH · NOT QUALIFIED"))));
  return '<article class="ms-up-row ms-fixture-card">'+
    '<div class="ms-up-time"><b>'+E(when)+'</b><span>'+E(String(x.start_time||"").slice(0,10))+'</span></div>'+
    '<div class="ms-up-event"><div class="ms-up-meta"><span class="ms-sport-pill">'+sportIcon(x.sport)+' '+E(x.sport==="table_tennis"?"Table Tennis":(x.sport||"Sport"))+'</span><span>'+E(x.league||x.competition||"Unclassified")+'</span><span class="ms-fixture-market-count">1 prediction</span></div>'+
    '<div class="ms-up-match">'+E(x.player_1||x.home||"Participant 1")+' <span>vs</span> '+E(x.player_2||x.away||"Participant 2")+'</div>'+
    '<div class="ms-market-stack">'+unifiedMarketLine(x)+'</div>'+
    (settled?'<div class="ms-fixture-foot"><span class="'+(won?"ms-settled-win":"ms-settled-loss")+'">'+E(won?"SETTLED · ✓ WIN":"SETTLED · ✕ LOSS")+'</span><span>'+E("Result "+(x.final_score||x.settlement_result||"recorded"))+'</span></div>':'')+'</div>'+
    '<div class="ms-up-status"><span class="ms-up-status-badge '+(settled?(won?"deep":"research"):(qualified?"deep":live?"testing":"research"))+'">'+E(status)+'</span></div>'+
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
    const generatedAt=Date.parse(String(payload?.generated_at||""));
    const generatedEl=Q('#upLast');
    if(generatedEl){
      if(Number.isFinite(generatedAt)){
        generatedEl.textContent=new Date(generatedAt).toLocaleString([], {month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
        generatedEl.title=new Date(generatedAt).toISOString();
      }else{
        generatedEl.textContent="Timestamp unavailable";
        generatedEl.title="The upstream board artifact did not include a valid generated_at timestamp.";
      }
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
    const virtualCandidates=selectedRows.filter(isVirtualDeskCandidate);

    function virtualParticipantIdentity(row,keys){
      let value="";
      for(const key of keys){
        if(row?.[key]!=null&&String(row[key]).trim()){value=String(row[key]).trim();break;}
      }
      const embedded=value.match(/\(([^()]*)\)\s*$/);
      if(embedded&&embedded[1].trim())value=embedded[1].trim();
      return value.toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
    }
    function virtualStartTimestamp(row){
      const raw=row?.start_time_ms??row?.startTimeMs??row?.start_time??row?.startTime??row?.timestamp??row?.date;
      if(typeof raw==="number"||(typeof raw==="string"&&/^\d{10,13}$/.test(raw.trim()))){
        const n=Number(raw);if(Number.isFinite(n))return n<1e11?n*1000:n;
      }
      const parsed=Date.parse(String(raw??""));
      return Number.isFinite(parsed)?parsed:null;
    }
    function sameVirtualEvent(row,live){
      const rowProduct=String(row?.product||"").toLowerCase();
      const liveProduct=String(live?.product||"").toLowerCase();
      if(rowProduct&&liveProduct&&rowProduct!==liveProduct)return false;
      const rowA=virtualParticipantIdentity(row,["participant_1","player_1","team_1","home","home_name","homeName","player1"]);
      const rowB=virtualParticipantIdentity(row,["participant_2","player_2","team_2","away","away_name","awayName","player2"]);
      const liveA=virtualParticipantIdentity(live,["participant_1","player_1","team_1","home","home_name","homeName","player1"]);
      const liveB=virtualParticipantIdentity(live,["participant_2","player_2","team_2","away","away_name","awayName","player2"]);
      if(!rowA||!rowB||!liveA||!liveB)return false;
      if([rowA,rowB].sort().join("|")!==[liveA,liveB].sort().join("|"))return false;
      const rowTime=virtualStartTimestamp(row),liveTime=virtualStartTimestamp(live);
      if(rowTime==null||liveTime==null||Math.abs(rowTime-liveTime)>90*1000)return false;
      return true;
    }
    async function freshVirtualQuoteMap(requiredRows=[]){
      const byEvent={};
      const quoteNow=Date.now();
      const required=(Array.isArray(requiredRows)?requiredRows:[]).filter(row=>{
        if(!row||String(row?.sport||"").toLowerCase()!=="virtual"||!isOverUnderPrediction(row)||!String(row?.event_id||""))return false;
        const start=virtualStartTimestamp(row);
        return start!=null&&start>=quoteNow;
      });
      if(!required.length)return byEvent;
      try{
        // The first 100-event page often omits fixtures further down the active
        // eFootball feed. Paginate only a bounded number of pages, stopping as
        // soon as each requested fixture has an exact ID + participant + kickoff
        // match. A reused provider ID by itself never validates a quote.
        for(let page=1;page<=5;page++){
          const feed=await get('./api/sportybet-virtual?sources=efootball,vfootball&pageSize=100&pageNum='+page+'&timeline=168');
          const events=Array.isArray(feed?.events)?feed.events:[];
          const fetchedAt=feed?.updated_at||feed?.server_time||null;
          events.forEach(e=>{
            const id=String(e?.event_id||"");
            if(id){
              if(!Array.isArray(byEvent[id]))byEvent[id]=[];
              byEvent[id].push({...e,__quote_fetched_at:fetchedAt});
            }
          });
          if(events.length<100)break;
          const allResolved=required.length>0&&required.every(row=>
            (byEvent[String(row?.event_id||"")]||[]).some(event=>sameVirtualEvent(row,event))
          );
          if(allResolved)break;
        }
      }catch(_){}
      return byEvent;
    }
    function freshVirtualQuoteFields(row,live){
      if(!row||!live||String(row?.market||"").toLowerCase()!=="over_under")return row;
      const line=Number(row?.line);
      const side=String(row?.pick||row?.selection||"").toLowerCase();
      if(!Number.isFinite(line)||(side!=="over"&&side!=="under"))return row;
      let over=null,under=null;
      for(const market of Array.isArray(live?.markets)?live.markets:[]){
        const marketLine=exactVirtualMarketLine(market);
        const marketId=String(market?.id||"");
        const marketName=String(market?.name||"").toLowerCase();
        if(!["18","189"].includes(marketId)&&!marketName.includes("total")&&!marketName.includes("over/under")&&!marketName.includes("over under"))continue;
        if(!Number.isFinite(marketLine)||Math.abs(marketLine-line)>1e-9)continue;
        let thisOver=null,thisUnder=null;
        for(const outcome of Array.isArray(market?.outcomes)?market.outcomes:[]){
          if(outcome?.active===false)continue;
          const name=String(outcome?.name||"").toLowerCase();
          const odds=Number(outcome?.odds);
          if(!Number.isFinite(odds)||odds<=1)continue;
          if(name.startsWith("over"))thisOver=odds;
          if(name.startsWith("under"))thisUnder=odds;
        }
        if(thisOver!=null||thisUnder!=null){over=thisOver;under=thisUnder;break;}
      }
      const selected=side==="over"?over:under;
      if(selected==null)return {
        ...row,
        market_odds_timestamp:null,
        odds_timestamp:null,
        desk_quote_refresh:"exact_line_or_side_not_found_in_live_snapshot"
      };
      return {
        ...row,
        bookmaker_odds:selected,
        sportybet_odds:selected,
        sportybet_odds_market:"total",
        sportybet_odds_line:line,
        sportybet_odds_side:side,
        sportybet_over_odds:over,
        sportybet_under_odds:under,
        bookmaker_available:Boolean(over&&under),
        bookmaker_source:"SportyBet NG",
        market_odds_timestamp:live?.__quote_fetched_at||null,
        desk_quote_refresh:"fresh_exact_event_line_side",
      };
    }
    function virtualCandidateDeskRows(rows,quoteMap){
      const now=Date.now();
      return rows.map(row=>{
        const eventId=String(row?.event_id||"");
        const live=(Array.isArray(quoteMap[eventId])?quoteMap[eventId]:[]).find(event=>sameVirtualEvent(row,event));
        const line=Number(row?.line);
        const side=String(row?.pick||row?.selection||"").toLowerCase();
        if(!live || !Number.isFinite(line) || (side!=="over" && side!=="under")) return null;
        const matchStart=Date.parse(String(row?.start_time||""));
        if(!Number.isFinite(matchStart) || matchStart < now) return null;

        let over=null,under=null,matchedMarket=null;
        for(const market of Array.isArray(live?.markets)?live.markets:[]){
          const ml=exactVirtualMarketLine(market);
          const marketId=String(market?.id||"");
          const marketName=String(market?.name||"").toLowerCase();
          if(!["18","189"].includes(marketId)&&!marketName.includes("total")&&!marketName.includes("over/under")&&!marketName.includes("over under"))continue;
          if(!Number.isFinite(ml) || Math.abs(ml-line)>1e-9)continue;
          let marketOver=null,marketUnder=null;
          for(const outcome of Array.isArray(market?.outcomes)?market.outcomes:[]){
            if(outcome?.active===false)continue;
            const name=String(outcome?.name||"").toLowerCase();
            const odds=Number(outcome?.odds);
            if(!Number.isFinite(odds) || odds<=1)continue;
            if(name.startsWith("over"))marketOver=odds;
            if(name.startsWith("under"))marketUnder=odds;
          }
          if(marketOver!=null||marketUnder!=null){
            over=marketOver;under=marketUnder;matchedMarket=market;break;
          }
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
          sportybet_odds_market:"total",
          sportybet_odds_line:line,
          sportybet_odds_side:side,
          sportybet_over_odds:over,
          sportybet_under_odds:under,
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
          market_odds_timestamp:live?.__quote_fetched_at||matchedMarket?.lastOddsChangeTime||null,
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
      if(qualificationVetoReason(x)){
        x.betting_qualified=false;
        x.qualified_for_builder=false;
      }else{
        x.betting_qualified=Boolean(x.betting_qualified)||Boolean(x.qualified_for_builder)||
          x.qualification_status==="BETTING_QUALIFIED_PAPER"||
          x.qualification_status==="BETTING_QUALIFIED_PAPER_BOOTSTRAP"||
          x.qualification_status==="BETTING_QUALIFIED_PAPER_DIRECTIONAL";
      }
      x.paper_only=true;
      x.live_money_eligible=Boolean(x.live_money_eligible) ||
        Boolean(riskGate?.gate?.[String(x?.sport||"").toLowerCase()]?.live_eligible);
      return x;
    };
    all=all.map(annotate);
    try{
      const requiredQuoteRows=[...all,...virtualCandidates].filter(row=>
        String(row?.sport||"").toLowerCase()==="virtual"&&isOverUnderPrediction(row)&&virtualStartTimestamp(row)>=Date.now()
      );
      const quoteMap=await freshVirtualQuoteMap(requiredQuoteRows);
      all=all.map(row=>{
        if(String(row?.sport||"").toLowerCase()!=="virtual"||!isOverUnderPrediction(row))return row;
        const candidates=quoteMap[String(row?.event_id||"")]||[];
        const current=Array.isArray(candidates)?candidates.find(event=>sameVirtualEvent(row,event)):null;
        if(current)return freshVirtualQuoteFields(row,current);
        // Keep a previously observed price visible, but strip its freshness
        // timestamps so the UI cannot treat a non-matched live fixture as a
        // current exact-event price or compute an actionable edge from it.
        return {
          ...row,
          market_odds_timestamp:null,
          odds_timestamp:null,
          desk_quote_refresh:"exact_event_not_found_in_live_snapshot"
        };
      });
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
        const kickoff=Date.parse(String(x?.start_time||""));
        if(!Number.isFinite(kickoff))return false;
        const state=String(x?.event_state||"").toUpperCase();
        const live=state==="LIVE" || x?.live===true || x?.isLive===true;
        const settled=state==="SETTLED";
        const sportKey=String(x?.sport||"").toLowerCase();
        const productKey=String(x?.product||"").toLowerCase();
        const isVirtual=sportKey==="virtual"||["efootball_gt","efootball_adriatic","vfootball","zoom"].includes(productKey);
        if (isVirtual && !isActiveVirtualProduct(productKey)) return false;
        const liveLimitMs=isVirtual?2*60*60*1000:(sportKey==="tennis"?8*60*60*1000:4*60*60*1000);
        // Client-side guard as well as the backend guard: even a cached JSON
        // record with a stale LIVE flag cannot remain on Upcoming indefinitely.
        // A removed fixture stays in the canonical archive/history.
        if(kickoff<=now.getTime() && !live && !settled)return false;
        if(kickoff<=now.getTime() && live && now.getTime()-kickoff>liveLimitMs)return false;
        if(settled){
          const settledAt=Date.parse(String(x?.settled_at||""));
          const settledAge=now.getTime()-settledAt;
          if(!Number.isFinite(settledAt) || settledAge<0 || settledAge>2*60*60*1000)return false;
        }
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
      const best=qualifiedBestSelections(filteredRows,now.getTime());
      const bestBoard=Q('#qualifiedBestBoard');
      if(bestBoard){
        bestBoard.innerHTML=best.rows.length
          ?best.rows.slice(0,12).map(qualifiedBestRow).join("")
          :'<div class="ms-qualified-best-empty">'+(best.diagnostics.futureCandidateMarkets===0
            ?"No future candidate markets in this filtered view."
            :"Zero qualified picks from "+best.diagnostics.futureCandidateMarkets+" future market candidates. No pick was forced.")+'</div>';
      }
      const bestSummary=Q('#qualifiedBestSummary');
      if(bestSummary){
        const blockerText=Object.entries(best.diagnostics.blockerCounts)
          .sort((a,b)=>b[1]-a[1]).slice(0,3)
          .map(([reason,count])=>qualificationBlockerLabel(reason)+" ("+count+")").join(" · ");
        bestSummary.innerHTML=best.rows.length
          ?'<span><b>'+best.rows.length+'</b> qualified fixture'+(best.rows.length===1?'':'s')+' · exact SportyBet market/line/side · quote ≤15 min · edge ≥+2% after margin removal'+(best.rows.length>12?' · showing top 12 by current edge':'')+'</span>'
          :'<span><b>0 qualified picks.</b> '+(best.diagnostics.futureCandidateMarkets===0
            ?"No future candidates in this filtered view."
            :"Blockers: "+E(blockerText||"No current candidate passed every gate.")+". No selections were relaxed to fill the list.")+'</span>';
      }
      const byDay=new Map();
      for(const group of groups){const day=String(group.rows[0].start_time).slice(0,10);if(!byDay.has(day))byDay.set(day,[]);byDay.get(day).push(group);}
      root.innerHTML=groups.length?[...byDay.entries()].map(([day,groupsForDay])=>{
        const label=new Date(day+"T00:00:00Z").toLocaleDateString([], {weekday:"long",month:"short",day:"numeric"});
        return '<section class="ms-up-day"><div class="ms-up-day-head"><h3>'+E(label)+'</h3><span>'+groupsForDay.length+' fixtures</span></div>'+groupsForDay.map(unifiedRow).join("")+'</section>';
      }).join(""):'<div class="ms-empty">No future fixtures match these filters. The engines remain active and the board will refresh with the next generated window.</div>';
      // Count only the primary prediction displayed per fixture, and only if
      // the current exact-line price/value gate passes for that displayed row.
      const qualified=best.rows.length;
      const strong=groups.filter(group=>{
        const row=primaryPrediction(group.rows);
        return Boolean(row&&Number(probabilityValue(row))>=0.80);
      }).length;
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