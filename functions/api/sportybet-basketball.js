const ORIGIN='https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const MARKET_IDS='1,18,219,223,225,227,228';
function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'public, max-age=15, s-maxage=15, stale-while-revalidate=15','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}
function normMarket(m){
  const id=String(m?.id??m?.marketId??'');
  return {
    id, name:String(m?.desc??m?.name??''),
    specifier:String(m?.specifier??''),
    status:String(m?.status??''),
    outcomes:(Array.isArray(m?.outcomes)?m.outcomes:[]).map(o=>({
      id:String(o?.id??o?.outcomeId??''),
      name:String(o?.desc??o?.name??''),
      odds:Number(o?.odds),
      active:o?.isActive!==false
    })).filter(o=>Number.isFinite(o.odds)&&o.odds>1&&o.active)
  };
}
export async function onRequestOptions(){return new Response(null,{status:204,headers:headers()})}
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(100,Math.max(1,Number(u.searchParams.get('pageSize')||100)));
  const pageNum=Math.max(1,Number(u.searchParams.get('pageNum')||1));
  const timeline=Math.min(168,Math.max(12,Number(u.searchParams.get('timeline')||96)));
  const url=new URL(ORIGIN+'/api/ng/factsCenter/pcUpcomingEvents');
  const params={sportId:'sr:sport:2',marketId:MARKET_IDS,pageSize:String(pageSize),pageNum:String(pageNum),todayGames:'false',timeline:String(timeline),_t:String(Date.now())};
  Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
  const started=Date.now();
  try{
    const r=await fetch(url.toString(),{headers:{'Accept':'application/json, text/plain, */*'},cache:'no-store',signal:AbortSignal.timeout(12000)});
    const body=await r.text();
    if(!r.ok)throw new Error('SportyBet upstream HTTP '+r.status);
    let payload;try{payload=JSON.parse(body)}catch(_){throw new Error('SportyBet upstream returned non-JSON data')}
    if(payload?.bizCode!==undefined&&payload.bizCode!==10000)throw new Error('SportyBet upstream bizCode '+payload.bizCode);
    const tournaments=Array.isArray(payload?.data?.tournaments)?payload.data.tournaments:[];
    const events=[];
    for(const t of tournaments)for(const e of (Array.isArray(t?.events)?t.events:[])){
      const id=String(e?.eventId??e?.id??'');
      const start=Number(e?.estimateStartTime??e?.startTime??e?.start_time_ms);
      const markets=(Array.isArray(e?.markets)?e.markets:[]).map(normMarket);
      if(!id||!Number.isFinite(start)||!markets.length)continue;
      events.push({event_id:id,home:String(e?.homeTeamName??e?.homeTeam?.name??''),away:String(e?.awayTeamName??e?.awayTeam?.name??''),start_time:new Date(start).toISOString(),tournament:String(t?.name??''),source:'SportyBet Nigeria',source_endpoint:'/api/ng/factsCenter/pcUpcomingEvents',fetched_at:new Date().toISOString(),markets});
    }
    return new Response(JSON.stringify({ok:true,source:'SportyBet Nigeria',market_contract:{winner_including_overtime:'219',handicap_including_overtime:'223',total_including_overtime:'225',team_total_points:['227','228']},fetched_at:new Date().toISOString(),elapsed_ms:Date.now()-started,event_count:events.length,events}),{status:200,headers:headers()});
  }catch(error){
    return new Response(JSON.stringify({ok:false,source:'SportyBet Nigeria',error:String(error?.message||error),fetched_at:new Date().toISOString(),event_count:0,events:[]}),{status:200,headers:{...headers(),'Cache-Control':'no-store'}});
  }
}
