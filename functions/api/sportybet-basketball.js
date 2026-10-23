const ORIGIN='https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const MARKET_IDS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210,225';
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
  const started=Date.now();
  const requests=[
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:'1,18,10,29,11,26,36,14,60100,186,189,202,204,210'},
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:'225'},
    {path:'/api/ng/factsCenter/wapConfigurableUpcomingEvents',marketId:null}
  ];
  const attempts=await Promise.all(requests.map(async request=>{
    try{
      const url=new URL(ORIGIN+request.path);
      const params={sportId:'sr:sport:2',pageSize:String(pageSize),pageNum:String(pageNum),todayGames:'false',timeline:String(timeline),_t:String(Date.now())};
      if(request.marketId)params.marketId=request.marketId;
      Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
      const r=await fetch(url.toString(),{headers:{'Accept':'application/json, text/plain, */*'},cache:'no-store',signal:AbortSignal.timeout(12000)});
      const body=await r.text();
      if(!r.ok)throw new Error(request.path+' marketId='+(request.marketId||'default')+' HTTP '+r.status+' '+body.slice(0,120));
      let payload;try{payload=JSON.parse(body)}catch(_){throw new Error(request.path+' returned non-JSON data')}
      if(payload?.bizCode!==undefined&&payload.bizCode!==10000)throw new Error(request.path+' bizCode '+payload.bizCode);
      return {request,payload,error:null};
    }catch(error){return {request,payload:null,error:String(error?.message||error)}}
  }));
  const eventMap=new Map(),errors=attempts.filter(x=>x.error).map(x=>x.error);
  for(const attempt of attempts){
    if(!attempt.payload)continue;
    const tournaments=Array.isArray(attempt.payload?.data?.tournaments)?attempt.payload.data.tournaments:[];
    for(const t of tournaments)for(const e of (Array.isArray(t?.events)?t.events:[])){
      const id=String(e?.eventId??e?.id??'');
      const start=Number(e?.estimateStartTime??e?.startTime??e?.start_time_ms);
      if(!id||!Number.isFinite(start))continue;
      const existing=eventMap.get(id)||{event_id:id,home:String(e?.homeTeamName??e?.homeTeam?.name??''),away:String(e?.awayTeamName??e?.awayTeam?.name??''),start_time:new Date(start).toISOString(),tournament:String(t?.name??''),source:'SportyBet Nigeria',source_endpoints:[],fetched_at:new Date().toISOString(),markets:[]};
      const marketMap=new Map((existing.markets||[]).map(m=>[String(m.id)+'|'+String(m.specifier||''),m]));
      for(const market of (Array.isArray(e?.markets)?e.markets:[])){
        const normalized=normMarket(market);
        marketMap.set(String(normalized.id)+'|'+String(normalized.specifier||''),normalized);
      }
      existing.markets=Array.from(marketMap.values());
      if(!existing.source_endpoints.includes(attempt.request.path+(attempt.request.marketId?'?marketId='+attempt.request.marketId:'')))existing.source_endpoints.push(attempt.request.path+(attempt.request.marketId?'?marketId='+attempt.request.marketId:''));
      existing.fetched_at=new Date().toISOString();
      eventMap.set(id,existing);
    }
  }
  const events=Array.from(eventMap.values());
  const totalMarketEvents=events.filter(e=>e.markets.some(m=>String(m.id)==='225')).length;
  if(!events.length)throw new Error('SportyBet NBA feed returned no events. '+errors.join('; '));
  return new Response(JSON.stringify({ok:true,source:'SportyBet Nigeria',market_contract:{winner_including_overtime:'219',handicap_including_overtime:'223',total_including_overtime:'225',team_total_points:['227','228']},fetched_at:new Date().toISOString(),elapsed_ms:Date.now()-started,event_count:events.length,total_market_event_count:totalMarketEvents,source_errors:errors,events}),{status:200,headers:headers()});
  }catch(error){
        if(!firstError)firstError=String(error?.message||error);
      }
    }
    if(!payload)throw new Error('SportyBet NBA feed failed; first request: '+String(firstError||'unknown error')+'; fallback request also failed');
    const tournaments=Array.isArray(payload?.data?.tournaments)?payload.data.tournaments:[];
    const events=[];
    for(const t of tournaments)for(const e of (Array.isArray(t?.events)?t.events:[])){
      const id=String(e?.eventId??e?.id??'');
      const start=Number(e?.estimateStartTime??e?.startTime??e?.start_time_ms);
      const markets=(Array.isArray(e?.markets)?e.markets:[]).map(normMarket);
      if(!id||!Number.isFinite(start)||!markets.length)continue;
      events.push({event_id:id,home:String(e?.homeTeamName??e?.homeTeam?.name??''),away:String(e?.awayTeamName??e?.awayTeam?.name??''),start_time:new Date(start).toISOString(),tournament:String(t?.name??''),source:'SportyBet Nigeria',source_endpoint:endpointUsed,fetched_at:new Date().toISOString(),markets});
    }
    return new Response(JSON.stringify({ok:true,source:'SportyBet Nigeria',market_contract:{winner_including_overtime:'219',handicap_including_overtime:'223',total_including_overtime:'225',team_total_points:['227','228']},fetched_at:new Date().toISOString(),elapsed_ms:Date.now()-started,event_count:events.length,events}),{status:200,headers:headers()});
  }catch(error){
    return new Response(JSON.stringify({ok:false,source:'SportyBet Nigeria',error:String(error?.message||error),fetched_at:new Date().toISOString(),event_count:0,events:[]}),{status:200,headers:{...headers(),'Cache-Control':'no-store'}});
  }
}
