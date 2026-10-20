function headers(){
  return {
    'Content-Type':'application/json; charset=utf-8',
    'Cache-Control':'no-store',
    'Access-Control-Allow-Origin':'*',
    'Access-Control-Allow-Methods':'GET,OPTIONS'
  };
}

const ORIGIN='https://www.sportybet.com';
const BROWSER_HEADERS={
  'Accept':'application/json, text/plain, */*',
  'Content-Type':'application/json',
  'Current-Country':'NG',
  'Origin':ORIGIN,
  'Referer':ORIGIN+'/ng/',
  'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0 Safari/537.36'
};
const MARKET_IDS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210';
const VFOOTBALL_FIXED_SCOPES=[
  {categoryId:'sv:category:202120001',tournamentId:'sv:league:1'},
  {categoryId:'sv:category:202120002',tournamentId:'sv:league:2'},
  {categoryId:'sv:category:202120003',tournamentId:'sv:league:3'},
  {categoryId:'sv:category:202120004',tournamentId:'sv:league:4'},
  {categoryId:'sv:category:202120005',tournamentId:'sv:league:5'}
];
const SOURCES={
  srl:{sportId:'sr:sport:1',upcoming:'/api/ng/factsCenter/pcUpcomingEvents'},
  efootball:{sportId:'sr:sport:137',upcoming:'/api/ng/factsCenter/pcUpcomingEvents'},
  vfootball:{sportId:'sr:sport:202120001',upcoming:'/api/ng/factsCenter/wapConfigurableUpcomingEvents'}
};

async function upstream(path,params){
  const url=new URL(ORIGIN+path);
  for(const [key,value] of Object.entries(params)){
    if(value!==undefined&&value!==null&&String(value)!=='') url.searchParams.set(key,String(value));
  }
  const response=await fetch(url.toString(),{
    headers:BROWSER_HEADERS,
    cache:'no-store',
    signal:AbortSignal.timeout(10000)
  });
  const body=await response.text();
  if(!response.ok) throw new Error(path+' HTTP '+response.status+' '+body.slice(0,180));
  if(!body.trim()) throw new Error(path+' empty response');
  let payload;
  try{payload=JSON.parse(body);}catch{
    throw new Error(path+' returned non-JSON content');
  }
  if(payload?.bizCode!==undefined && payload.bizCode!==10000){
    // Preserve bounded upstream diagnostics. SportyBet's business errors can
    // arrive as HTTP 200 JSON, so status alone is insufficient to isolate
    // a rejected result query. Never include the full payload in public logs.
    const detailKeys=['message','msg','error','errMsg','errorMsg','bizMessage','bizMsg','description','desc'];
    let detail='';
    for(const key of detailKeys){
      const value=payload[key];
      if(typeof value==='string' && value.trim()){
        detail=value.trim().slice(0,240);
        break;
      }
    }
    const shape=Object.keys(payload).slice(0,16).join(',');
    throw new Error(path+' bizCode '+payload.bizCode+(detail?' detail='+detail:' fields='+shape));
  }
  return payload;
}

function tournaments(body){
  return Array.isArray(body?.data?.tournaments)?body.data.tournaments:[];
}

function scopeFromTournament(t){
  const e=Array.isArray(t?.events)?t.events[0]:null;
  const categoryId=String(t?.categoryId||t?.category?.id||t?.category?.categoryId||t?.category_id||e?.categoryId||e?.category?.id||e?.category_id||'');
  const tournamentId=String(t?.id||t?.tournamentId||t?.tournament_id||e?.tournamentId||e?.tournament?.id||e?.tournament_id||'');
  return categoryId&&tournamentId?{categoryId,tournamentId}:null;
}

export async function onRequestOptions(){
  return new Response('',{status:204,headers:headers()});
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const source=(u.searchParams.get('source')||'').trim().toLowerCase();
  const config=SOURCES[source];
  if(!config){
    return new Response(JSON.stringify({ok:false,error:'source must be srl, efootball, or vfootball'}),{
      status:400,headers:headers()
    });
  }

  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const startTime=String(u.searchParams.get('startTime')||'');
  const endTime=String(u.searchParams.get('endTime')||'');
  const explicitCategory=String(u.searchParams.get('categoryId')||'');
  const explicitTournament=String(u.searchParams.get('tournamentId')||'');

  let scopes=[];
  const discoveryErrors=[];

  if(explicitCategory&&explicitTournament){
    scopes=[{categoryId:explicitCategory,tournamentId:explicitTournament}];
  }else{
    // vFootball result history must not depend on the current upcoming feed.
    // Completed VFL tournaments disappear from upcoming, so retain the stable
    // five category/tournament result scopes as a bounded fallback.
    if(source==='vfootball'){
      VFOOTBALL_FIXED_SCOPES.forEach(function(scope){
        if(!scopes.some(function(x){return x.categoryId===scope.categoryId&&x.tournamentId===scope.tournamentId;})) scopes.push(scope);
      });
    }
    try{
      for(const page of [1,2]){
        const body=await upstream(config.upcoming,{
          sportId:config.sportId,
          marketId:MARKET_IDS,
          pageSize:100,
          pageNum:page,
          todayGames:'false',
          timeline:168,
          _t:Date.now()
        });
        for(const tournament of tournaments(body)){
          const scope=scopeFromTournament(tournament);
          if(scope&&!scopes.some(x=>x.categoryId===scope.categoryId&&x.tournamentId===scope.tournamentId)){
            scopes.push(scope);
          }
        }
        if(tournaments(body).length<1) break;
      }
    }catch(error){
      discoveryErrors.push(String(error?.message||error));
    }
  }

  if(!scopes.length){
    return new Response(JSON.stringify({
      ok:true,
      source,
      fetched_at:new Date().toISOString(),
      scopes:[],
      events:[],
      errors:discoveryErrors.length ? discoveryErrors : ['No active result scope is currently available for this source.']
    }),{status:200,headers:headers()});
  }

  const events=[];
  const resultErrors=[];
  const maxPages=source==='vfootball'?8:8;
  for(const scope of scopes){
    for(let page=pageNum;page<pageNum+maxPages;page++){
      try{
        const body=await upstream('/api/ng/factsCenter/eventResultList',{
          sportId:config.sportId,
          categoryId:scope.categoryId,
          tournamentId:scope.tournamentId,
          pageSize,
          pageNum:page,
          ...(startTime?{startTime}:{}),
          ...(endTime?{endTime}:{}),
        });
        const rows=Array.isArray(body?.data?.tournaments)
          ?body.data.tournaments.flatMap(t=>Array.isArray(t?.events)?t.events:[])
          :(Array.isArray(body?.data)?body.data:(Array.isArray(body?.events)?body.events:[]));
        for(const row of rows){
          if(row&&typeof row==='object'){
            events.push({
              ...row,
              __scope:{categoryId:scope.categoryId,tournamentId:scope.tournamentId}
            });
          }
        }
        if(rows.length<pageSize) break;
      }catch(error){
        resultErrors.push({
          categoryId:scope.categoryId,
          tournamentId:scope.tournamentId,
          page,
          error:String(error?.message||error)
        });
        break;
      }
    }
  }

  function identityPart(value){
    return String(value||'').normalize('NFKC').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ');
  }
  function eventStartIdentity(event){
    for(const key of ['startTime','estimateStartTime','start_time_ms','start_time','kickoff_time']){
      const raw=event?.[key];
      if(raw===undefined||raw===null||raw==='') continue;
      const numeric=Number(raw);
      if(Number.isFinite(numeric)&&numeric>0) return String(Math.round(numeric<100000000000?numeric*1000:numeric));
      const parsed=Date.parse(String(raw));
      if(Number.isFinite(parsed)) return String(parsed);
    }
    return '';
  }
  function eventParticipantIdentity(event){
    const home=identityPart(event?.homeTeamName||event?.homeTeam||event?.team_1||event?.participant_1);
    const away=identityPart(event?.awayTeamName||event?.awayTeam||event?.team_2||event?.participant_2);
    return home&&away?home+'|'+away:'';
  }
  function eventIdentityKey(event,index){
    const eventId=String(event?.eventId||event?.event_id||'').trim();
    const scope=event?.__scope||{};
    const scopeKey=String(scope.categoryId||'')+'|'+String(scope.tournamentId||'');
    const kickoff=eventStartIdentity(event);
    const participants=eventParticipantIdentity(event);
    if(!eventId) return 'unidentified|'+scopeKey+'|'+kickoff+'|'+participants+'|row:'+index;
    // Never collapse two rows on provider ID alone. If kickoff is missing,
    // preserve the row individually so the tracker can reject missing identity.
    if(!kickoff) return scopeKey+'|'+eventId+'|unverified-row:'+index;
    return [scopeKey,eventId,kickoff,participants||'participants-unavailable'].join('|');
  }
  const dedup=new Map();
  events.forEach((event,index)=>dedup.set(eventIdentityKey(event,index),event));

  return new Response(JSON.stringify({
    ok:true,
    source,
    fetched_at:new Date().toISOString(),
    scopes,
    events:[...dedup.values()],
    errors:[...discoveryErrors,...resultErrors]
  }),{status:200,headers:headers()});
}
