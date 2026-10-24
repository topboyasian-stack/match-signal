const ORIGIN = 'https://www.sportybet.com';
const HEADERS = {
  'Accept': 'application/json, text/plain, */*',
  'Content-Type': 'application/json',
  'Current-Country': 'NG',
  'Origin': ORIGIN,
  'Referer': ORIGIN + '/ng/',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'
};
const OUT_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};
function json(body, status=200){ return new Response(JSON.stringify(body), {status, headers:OUT_HEADERS}); }
function lineOf(m){
  const direct=Number(m?.line);
  if(Number.isFinite(direct) && m?.line!==null && m?.line!=='') return direct;
  const text=[m?.specifier,m?.name,m?.desc,m?.title].map(x=>String(x||'')).join(' ');
  const hit=text.match(/(?:total|line|over|under)[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)/i) || text.match(/\b([0-9]{3}(?:\.[0-9]+)?)\b/);
  return hit?Number(hit[1]):null;
}
function active(x){return x?.active!==false && (x?.isActive==null || x.isActive===true || Number(x.isActive)===1);}
function sameTeam(a,b){return String(a||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()===String(b||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();}
async function liveEvents(request){
  const url=new URL('/api/sportybet-basketball?pageSize=100&timeline=96&_t='+Date.now(), request.url);
  const response=await fetch(url.toString(),{headers:{'Accept':'application/json','Cache-Control':'no-cache'},cache:'no-store',signal:AbortSignal.timeout(18000)});
  if(!response.ok) throw new Error('Current SportyBet feed HTTP '+response.status);
  const data=await response.json();
  if(data?.ok!==true || !Array.isArray(data.events)) throw new Error(data?.error||'Current SportyBet basketball feed unavailable');
  const fetched=Date.parse(data.fetched_at||'');
  if(!Number.isFinite(fetched)||Date.now()-fetched>15*60*1000||fetched>Date.now()+120000) throw new Error('SportyBet market feed is stale; refresh before generating a code.');
  return data.events;
}
function mapLeg(leg,event){
  const requestedLine=Number(leg.line), side=String(leg.side||'').toLowerCase();
  if(!Number.isFinite(requestedLine)||requestedLine<100||requestedLine>300||!['over','under'].includes(side)) return {error:'Invalid totals line or side.'};
  if(String(leg.market_id||'225')!=='225') return {error:'Only SportyBet full-game total market 225 is supported.'};
  const start=Date.parse(event.start_time||'');
  if(!Number.isFinite(start)||start<=Date.now()+2*60*1000) return {error:'The event has started or is too close to start for a pre-match code.'};
  if(leg.start_time && Math.abs(Date.parse(leg.start_time)-start)>45*60*1000) return {error:'Event start time changed; refresh this selection.'};
  if(leg.player_1 && !(sameTeam(leg.player_1,event.home)||sameTeam(leg.player_1,event.away))) return {error:'Participant names no longer match the current event.'};
  if(leg.player_2 && !(sameTeam(leg.player_2,event.home)||sameTeam(leg.player_2,event.away))) return {error:'Participant names no longer match the current event.'};
  const markets=(event.markets||[]).filter(m=>String(m.id)==='225' && !/suspend|closed|inactive|settled|unavailable|stop/i.test(String(m.status||'')));
  let found=null;
  for(const m of markets){
    const line=lineOf(m);
    if(!Number.isFinite(line)||Math.abs(line-requestedLine)>1e-9) continue;
    const outcome=(m.outcomes||[]).find(o=>active(o) && (side==='over'?/\bover\b/i.test(String(o.name||'')):/\bunder\b/i.test(String(o.name||''))) && Number(o.odds)>1 && String(o.id||''));
    if(outcome){found={eventId:String(event.event_id),marketId:'225',specifier:m.specifier??null,outcomeId:String(outcome.id),outcomeName:String(outcome.name||side),odds:Number(outcome.odds),line,side,fixture:event.home+' vs '+event.away};break;}
  }
  return found||{error:'Exact SportyBet market 225, line and side are no longer available.'};
}
async function createShare(selections){
  const requestBody=JSON.stringify({selections:selections.map(s=>({eventId:s.eventId,marketId:s.marketId,specifier:s.specifier,outcomeId:s.outcomeId}))});
  let lastDiagnostic='No response from SportyBet.';
  for(let attempt=1;attempt<=3;attempt++){
    let response=null,body='',contentType='not supplied';
    try{
      response=await fetch(ORIGIN+'/api/ng/orders/share?_t='+Date.now(),{method:'POST',headers:{...HEADERS,'Accept-Language':'en-NG,en;q=0.9','Cache-Control':'no-cache','Pragma':'no-cache','Sec-Fetch-Dest':'empty','Sec-Fetch-Mode':'cors','Sec-Fetch-Site':'same-origin'},body:requestBody,cache:'no-store',redirect:'follow',signal:AbortSignal.timeout(15000)});
      contentType=response.headers.get('content-type')||contentType;
      body=await response.text();
      if(!response.ok) lastDiagnostic='HTTP '+response.status+'; content-type '+contentType+'; response '+body.slice(0,180).replace(/\\s+/g,' ');
      else {
        let payload=null;
        try{payload=JSON.parse(body)}catch(_){lastDiagnostic='HTTP '+response.status+' but response was not JSON (content-type '+contentType+'): '+(body.slice(0,180).replace(/\\s+/g,' ')||'[empty response]');}
        if(payload){
          if(payload?.bizCode!=null&&Number(payload.bizCode)!==10000) throw new Error('SportyBet rejected this slip (code '+payload.bizCode+'). Refresh markets and try again.');
          const data=payload?.data||{},code=String(data.shareCode||'').trim().toUpperCase();
          if(code){
            const accepted=Array.isArray(data.outcomes)?data.outcomes:[],unavailable=Array.isArray(data.unavailableOutcomes)?data.unavailableOutcomes.length:0;
            const odds=accepted.length?accepted.reduce((p,x)=>p*(Number(x.odds)>0?Number(x.odds):1),1):selections.reduce((p,x)=>p*x.odds,1);
            return {code,url:String(data.shareURL||('https://www.sportybet.com/ng/?c=ng&shareCode='+encodeURIComponent(code))),accepted_count:accepted.length||Math.max(0,selections.length-unavailable),combined_odds:odds,unavailable_count:unavailable};
          }
          lastDiagnostic='SportyBet returned JSON but no shareCode (bizCode '+String(payload?.bizCode??'missing')+'); response '+body.slice(0,180).replace(/\\s+/g,' ');
        }
      }
    }catch(error){
      if(error instanceof Error && /rejected this slip/.test(error.message)) throw error;
      lastDiagnostic=String(error?.message||error);
    }
    if(attempt<3) await new Promise(resolve=>setTimeout(resolve,500*Math.pow(2,attempt-1)));
  }
  throw new Error('SportyBet did not create a share code after 3 attempts. '+lastDiagnostic);
}
export async function onRequestOptions(){return new Response(null,{status:204,headers:OUT_HEADERS});}
export async function onRequestPost(context){
  try{
    const body=await context.request.json();
    const slot=Number(body?.builder_slot);
    const legs=Array.isArray(body?.legs)?body.legs:[];
    if(!Number.isInteger(slot)||slot<1||slot>4) return json({ok:false,error:'INVALID_BUILDER_SLOT',message:'Choose one of the four basketball builders.'},400);
    if(legs.length<2||legs.length>4) return json({ok:false,error:'INVALID_LEG_COUNT',message:'Each slip needs 2–4 selections.'},422);
    const ids=legs.map(l=>String(l.event_id||''));
    if(ids.some(id=>!id)||new Set(ids).size!==ids.length) return json({ok:false,error:'DUPLICATE_OR_MISSING_EVENT',message:'Each builder must contain different, identified events.'},422);
    const events=await liveEvents(context.request);
    const validation=[],selections=[];
    for(const leg of legs){
      const event=events.find(e=>String(e.event_id)===String(leg.event_id));
      if(!event){validation.push({event_id:leg.event_id,ok:false,reason:'Fixture no longer exists in current SportyBet feed.'});continue;}
      const selection=mapLeg(leg,event);
      if(selection.error){validation.push({event_id:leg.event_id,ok:false,reason:selection.error});continue;}
      selections.push(selection);validation.push({event_id:leg.event_id,ok:true,fixture:selection.fixture,side:selection.side,line:selection.line,odds:selection.odds});
    }
    if(selections.length!==legs.length) return json({ok:false,error:'SELECTIONS_CHANGED',message:'One or more legs failed live revalidation. No booking code was created; remove or refresh the flagged selection.',validation},409);
    const share=await createShare(selections);
    return json({ok:true,mode:'NON_STAKING_BETSLIP_PREPARATION',builder_slot:slot,booking_code:share.code,share_url:share.url,accepted_count:share.accepted_count,initial_selection_count:legs.length,combined_odds:share.combined_odds,unavailable_count:share.unavailable_count,validation,message:'SportyBet returned a share/booking code only. No stake, payment or wager was placed.'});
  }catch(error){return json({ok:false,error:'SPORTYBET_BASKETBALL_BOOKING_FAILED',message:String(error?.message||error)},502);}
}
