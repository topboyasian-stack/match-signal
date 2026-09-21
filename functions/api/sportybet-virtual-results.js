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
    throw new Error(path+' bizCode '+payload.bizCode);
  }
  return payload;
}

function tournaments(body){
  return Array.isArray(body?.data?.tournaments)?body.data.tournaments:[];
}

function scopeFromTournament(t){
  const categoryId=String(t?.categoryId||t?.category?.id||'');
  const tournamentId=String(t?.id||t?.tournamentId||'');
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
  for(const scope of scopes){
    for(let page=pageNum;page<pageNum+8;page++){
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

  const dedup=new Map();
  for(const event of events){
    const eventId=String(event?.eventId||event?.event_id||'');
    if(eventId) dedup.set(eventId,event);
  }

  return new Response(JSON.stringify({
    ok:true,
    source,
    fetched_at:new Date().toISOString(),
    scopes,
    events:[...dedup.values()],
    errors:[...discoveryErrors,...resultErrors]
  }),{status:200,headers:headers()});
}
