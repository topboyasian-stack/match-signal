const ORIGIN='https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const STANDARD_MARKET_IDS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
// Scope the bounded feed to NBA so NCAA events cannot crowd out market-225 fixtures.
const NBA_TOURNAMENT_ID='sr:tournament:132';
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
      active:o?.isActive==null ? true : (o.isActive===true || Number(o.isActive)===1)
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
  const tournamentId=String(u.searchParams.get('tournamentId')||NBA_TOURNAMENT_ID).trim();
  if(tournamentId!==NBA_TOURNAMENT_ID){
    return new Response(JSON.stringify({ok:false,error:'UNSUPPORTED_TOURNAMENT_ID'}),{status:400,headers:headers()});
  }
  const started=Date.now();
  const requests=[
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:STANDARD_MARKET_IDS},
    {path:'/api/ng/factsCenter/pcUpcomingEvents',marketId:'225'},
    {path:'/api/ng/factsCenter/wapConfigurableUpcomingEvents',marketId:null}
  ];
  let attempts=[];
  try{
    const origins=[ORIGIN,'https://www.sportybet.com'];
    attempts=await Promise.all(requests.map(async request=>{
      const errors=[];
      const diagnostics=[];
      for(const origin of origins){
        let diagnostic=null;
        try{
          const url=new URL(origin+request.path);
          const params={sportId:'sr:sport:2',pageSize:String(pageSize),pageNum:String(pageNum),todayGames:'false',timeline:String(timeline),_t:String(Date.now())};
          if(request.marketId)params.marketId=request.marketId;
          // SportyBet's tournamentId filter truncates the NBA result to five rows.
          // Pull the paged basketball feed unfiltered, then keep exact NBA IDs below.
          Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
          const r=await fetch(url.toString(),{
            headers:{'Accept':'application/json, text/plain, */*','Current-Country':'NG'},
            cache:'no-store',signal:AbortSignal.timeout(12000)
          });
          const body=await r.text();
          if(!r.ok)throw new Error('HTTP '+r.status+' '+body.slice(0,160));
          let payload;try{payload=JSON.parse(body)}catch(_){throw new Error('returned non-JSON data')}
          const tournaments=getTournaments(payload);
          const tournamentArrayPresent=Array.isArray(payload?.data?.tournaments);
          const data=payload?.data&&typeof payload.data==='object'?payload.data:{};
          const rawTotal=data.totalNum??data.totalEvents??data.totalCount??payload?.totalNum??null;
          const parsedTotal=rawTotal===null?null:Number(rawTotal);
          const count=tournaments.reduce((n,t)=>n+(Array.isArray(t?.events)?t.events.length:0),0);
          diagnostic={
            endpoint:request.path,
            market_id:request.marketId||null,
            page_num:pageNum,
            page_size:pageSize,
            timeline_hours:timeline,
            source_origin:origin,
            http_status:r.status,
            biz_code:payload?.bizCode??null,
            top_level_keys:Object.keys(payload||{}).slice(0,12),
            data_keys:Object.keys(data).slice(0,12),
            upstream_total_events:Number.isFinite(parsedTotal)?parsedTotal:null,
            tournament_count:tournaments.length,
            event_count:count,
            response_shape:!tournamentArrayPresent?'TOURNAMENTS_FIELD_MISSING':tournaments.length?'TOURNAMENTS_PRESENT':'TOURNAMENTS_ARRAY_EMPTY'
          };
          const emptyPaginationPage=request.path==='/api/ng/factsCenter/pcUpcomingEvents'&&pageNum>1&&payload?.bizCode===10000&&payload?.data&&typeof payload.data==='object'&&!Array.isArray(payload.data)&&Object.keys(payload.data).length===0;
          if(emptyPaginationPage)diagnostic.response_shape='PAGINATION_END_EMPTY_DATA';
          diagnostics.push(diagnostic);
          if(payload?.bizCode!==undefined&&payload.bizCode!==10000)throw new Error('bizCode '+payload.bizCode);
          if(payload?.ok===false)throw new Error(String(payload?.detail||payload?.error||'source rejected query'));
          if(!tournamentArrayPresent&&!emptyPaginationPage)throw new Error('response omitted data.tournaments; metadata='+JSON.stringify(diagnostic));
          const usablePayload=emptyPaginationPage?{...payload,data:{tournaments:[]}}:payload;
          return {request,payload:usablePayload,error:null,event_count:count,source_origin:origin,diagnostics};
        }catch(error){
          const message=String(error?.message||error);
          if(!diagnostic)diagnostics.push({
            endpoint:request.path,
            market_id:request.marketId||null,
            page_num:pageNum,
            page_size:pageSize,
            timeline_hours:timeline,
            source_origin:origin,
            request_error:message
          });
          errors.push(origin+': '+message);
        }
      }
      return {request,payload:null,error:errors.join(' || '),event_count:0,diagnostics};
    }));
    const eventMap=new Map();
    for(const attempt of attempts){
      if(!attempt.payload)continue;
      for(const t of getTournaments(attempt.payload))for(const e of (Array.isArray(t?.events)?t.events:[])){
        const eventTournamentId=String(t?.id??t?.tournamentId??e?.tournamentId??'');
        if(eventTournamentId!==NBA_TOURNAMENT_ID)continue;
        const id=String(e?.eventId??e?.id??'');
        const start=Number(e?.estimateStartTime??e?.startTime??e?.start_time_ms);
        if(!id||!Number.isFinite(start))continue;
        const existing=eventMap.get(id)||{
          event_id:id,home:String(e?.homeTeamName??e?.homeTeam?.name??''),
          away:String(e?.awayTeamName??e?.awayTeam?.name??''),
          start_time:new Date(start).toISOString(),tournament:String(t?.name??''),
          tournament_id:String(t?.id??t?.tournamentId??e?.tournamentId??''),
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
    const hasValidTournamentArray=attempts.some(a=>a.payload&&Array.isArray(a.payload?.data?.tournaments));
    if(!events.length&&!hasValidTournamentArray){
      const attemptsSummary=attempts.map(a=>a.request.path+' marketId='+(a.request.marketId||'default')+': '+(a.error||('events='+a.event_count))).join('; ');
      throw new Error('SportyBet NBA feed returned no usable event-list response. '+attemptsSummary);
    }
    return new Response(JSON.stringify({
      ok:true,source:'SportyBet Nigeria',
      source_origins:Array.from(new Set(attempts.filter(a=>a.payload).map(a=>a.source_origin))),
      market_contract:{winner_including_overtime:'219',handicap_including_overtime:'223',total_including_overtime:'225',team_total_points:['227','228']},
      fetched_at:new Date().toISOString(),elapsed_ms:Date.now()-started,event_count:events.length,
      total_market_event_count:totalMarketEvents,source_errors:sourceErrors,
      source_diagnostics:attempts.flatMap(a=>a.diagnostics||[]),events
    }),{status:200,headers:headers()});
  }catch(error){
    return new Response(JSON.stringify({ok:false,source:'SportyBet Nigeria',error:String(error?.message||error),fetched_at:new Date().toISOString(),event_count:0,total_market_event_count:0,source_diagnostics:attempts.flatMap(a=>a.diagnostics||[]),events:[]}),{status:200,headers:{...headers(),'Cache-Control':'no-store'}});
  }
}
