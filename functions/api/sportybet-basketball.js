const ORIGIN='https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const STANDARD_MARKET_IDS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'public, max-age=15, s-maxage=15, stale-while-revalidate=15','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}
function normMarket(m){
  const id=String(m?.id??m?.marketId??'');
  return {
    id, name:String(m?.desc??m?.name??m?.title??''),
    specifier:String(m?.specifier??''),
    status:String(m?.status??''),
    outcomes:(Array.isArray(m?.outcomes)?m.outcomes:[]).map(o=>({
      id:String(o?.id??o?.outcomeId??''),
      name:String(o?.desc??o?.name??o?.title??''),
      odds:Number(o?.odds),
      active:o?.isActive!==false
    })).filter(o=>Number.isFinite(o.odds)&&o.odds>1&&o.active)
  };
}
function getTournaments(payload){return Array.isArray(payload?.data?.tournaments)?payload.data.tournaments:[]}
export async function onRequestOptions(){return new Response(null,{status:204,headers:headers()})}
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(100,Math.max(1,Number(u.searchParams.get('pageSize')||100)));
  const pageNum=Math.max(1,Number(u.searchParams.get('pageNum')||1));
  const timeline=Math.min(168,Math.max(12,Number(u.searchParams.get('timeline')||96)));
  const started=Date.now();
  const requests=[
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:STANDARD_MARKET_IDS},
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:'225'},
    {path:'/api/ng/factsCenter/wapConfigurableUpcomingEvents',marketId:null}
  ];
  try{
    const origins=[ORIGIN,'https://www.sportybet.com'];
    const attempts=await Promise.all(requests.map(async request=>{
      const errors=[];
      for(const origin of origins){
        try{
          const url=new URL(origin+request.path);
          const params={sportId:'sr:sport:2',pageSize:String(pageSize),pageNum:String(pageNum),todayGames:'false',timeline:String(timeline),_t:String(Date.now())};
          if(request.marketId)params.marketId=request.marketId;
          Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
          const r=await fetch(url.toString(),{
            headers:{'Accept':'application/json, text/plain, */*','Current-Country':'NG'},
            cache:'no-store',signal:AbortSignal.timeout(12000)
          });
          const body=await r.text();
          if(!r.ok)throw new Error('HTTP '+r.status+' '+body.slice(0,160));
          let payload;try{payload=JSON.parse(body)}catch(_){throw new Error('returned non-JSON data')}
          if(payload?.bizCode!==undefined&&payload.bizCode!==10000)throw new Error('bizCode '+payload.bizCode);
          if(payload?.ok===false)throw new Error(String(payload?.detail||payload?.error||'source rejected query'));
          const count=getTournaments(payload).reduce((n,t)=>n+(Array.isArray(t?.events)?t.events.length:0),0);
          if(!getTournaments(payload).length)throw new Error('response omitted data.tournaments');
          return {request,payload,error:null,event_count:count,source_origin:origin};
        }catch(error){
          errors.push(origin+': '+String(error?.message||error));
        }
      }
      return {request,payload:null,error:errors.join(' || '),event_count:0};
    }));
    const eventMap=new Map();
    for(const attempt of attempts){
      if(!attempt.payload)continue;
      for(const t of getTournaments(attempt.payload))for(const e of (Array.isArray(t?.events)?t.events:[])){
        const id=String(e?.eventId??e?.id??'');
        const start=Number(e?.estimateStartTime??e?.startTime??e?.start_time_ms);
        if(!id||!Number.isFinite(start))continue;
        const existing=eventMap.get(id)||{
          event_id:id,home:String(e?.homeTeamName??e?.homeTeam?.name??''),
          away:String(e?.awayTeamName??e?.awayTeam?.name??''),
          start_time:new Date(start).toISOString(),tournament:String(t?.name??''),
          source:'SportyBet Nigeria',source_endpoints:[],fetched_at:new Date().toISOString(),markets:[]
        };
        const marketMap=new Map((existing.markets||[]).map(m=>[String(m.id)+'|'+String(m.specifier||''),m]));
        for(const market of (Array.isArray(e?.markets)?e.markets:[])){
          const normalized=normMarket(market);
          marketMap.set(String(normalized.id)+'|'+String(normalized.specifier||''),normalized);
        }
        existing.markets=Array.from(marketMap.values());
        const endpoint=(attempt.source_origin||ORIGIN)+attempt.request.path+(attempt.request.marketId?'?marketId='+attempt.request.marketId:'');
        if(!existing.source_endpoints.includes(endpoint))existing.source_endpoints.push(endpoint);
        existing.fetched_at=new Date().toISOString();
        eventMap.set(id,existing);
      }
    }
    const events=Array.from(eventMap.values());
    const totalMarketEvents=events.filter(e=>e.markets.some(m=>String(m.id)==='225')).length;
    const sourceErrors=attempts.filter(a=>a.error).map(a=>a.error);
    if(!events.length){
      const attemptsSummary=attempts.map(a=>a.request.path+' marketId='+(a.request.marketId||'default')+': '+(a.error||('events='+a.event_count))).join('; ');
      throw new Error('SportyBet NBA feed returned no events. '+attemptsSummary);
    }
    return new Response(JSON.stringify({
      ok:true,source:'SportyBet Nigeria',
      source_origins:Array.from(new Set(attempts.filter(a=>a.payload).map(a=>a.source_origin))),
      market_contract:{winner_including_overtime:'219',handicap_including_overtime:'223',total_including_overtime:'225',team_total_points:['227','228']},
      fetched_at:new Date().toISOString(),elapsed_ms:Date.now()-started,event_count:events.length,
      total_market_event_count:totalMarketEvents,source_errors:sourceErrors,events
    }),{status:200,headers:headers()});
  }catch(error){
    return new Response(JSON.stringify({ok:false,source:'SportyBet Nigeria',error:String(error?.message||error),fetched_at:new Date().toISOString(),event_count:0,total_market_event_count:0,events:[]}),{status:200,headers:{...headers(),'Cache-Control':'no-store'}});
  }
}
