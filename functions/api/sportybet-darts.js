function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}
const ORIGIN='https://www.sportybet.com';
const BROWSER_HEADERS={'Accept':'application/json, text/plain, */*','Content-Type':'application/json','Current-Country':'NG','Origin':'https://www.sportybet.com','Referer':'https://www.sportybet.com/ng/','User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'};
async function upstream(path,params){
  const u=new URL(ORIGIN+path);
  for(const [k,v] of Object.entries(params))u.searchParams.set(k,String(v));
  const r=await fetch(u.toString(),{headers:BROWSER_HEADERS,cache:'no-store',signal:AbortSignal.timeout(10000)});
  const body=await r.text();
  if(!r.ok)throw new Error(path+' HTTP '+r.status+' '+body.slice(0,180));
  if(!body.trim())throw new Error(path+' empty response');
  return JSON.parse(body);
}
async function fetchSportFeed(params){
  const attempts=[
    ['/api/ng/factsCenter/pcUpcomingEvents',{...params,marketId:'1,10,14,18,29,186,189,202,204,210'}],
    ['/api/ng/factsCenter/wapConfigurableUpcomingEvents',params]
  ];
  const errors=[];
  for(const [path,p] of attempts){
    try{
      const data=await upstream(path,p);
      const tournaments=Array.isArray(data?.data?.tournaments)?data.data.tournaments:[];
      return {data,tournaments};
    }catch(e){errors.push(String(e?.message||e));}
  }
  throw new Error(errors.join(' | '));
}

function nameOf(v){return String(v?.name||v?.desc||v?.title||'').trim()}
function normalizeEvent(t,e){
  const p1=String(e?.homeTeamName||e?.homePlayerName||e?.homeParticipant||e?.homePlayer||e?.homeCompetitor||'').trim();
  const p2=String(e?.awayTeamName||e?.awayPlayerName||e?.awayParticipant||e?.awayPlayer||e?.awayCompetitor||'').trim();
  const markets=(Array.isArray(e?.markets)?e.markets:[]).map(m=>({
    id:String(m?.id||''),
    name:nameOf(m),
    specifier:String(m?.specifier||''),
    outcomes:(Array.isArray(m?.outcomes)?m.outcomes:[]).map(o=>({id:String(o?.id||''),name:nameOf(o),odds:Number(o?.odds??o?.displayOdds??0)})).filter(o=>Number.isFinite(o.odds)&&o.odds>0)
  })).filter(m=>m.outcomes.length);
  const winner=markets.find(m=>['1','186'].includes(m.id)||/winner|match result|1x2/i.test(m.name))||null;
  const startRaw=Number(e?.estimateStartTime);
  const start=startRaw>0?(startRaw<100000000000?startRaw*1000:startRaw):null;
  return {sport:'darts',provider:'SportyBet NG',sport_id:'sr:sport:22',event_id:String(e?.eventId||''),competition:String(t?.name||''),category:String(t?.categoryName||''),start_time_ms:start,participant_1:p1,participant_2:p2,markets,winner_market:winner,source_url:'https://www.sportybet.com/ng/'};
}
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  try{
    const feed=await fetchSportFeed({sportId:'sr:sport:22',pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()});
    const events=[];
    for(const t of feed.tournaments)for(const e of (t?.events||[])){
      const row=normalizeEvent(t,e);
      if(row.event_id&&row.participant_1&&row.participant_2)events.push(row);
    }
    return new Response(JSON.stringify({ok:true,status:events.length?'LIVE':'EMPTY',updated_at:new Date().toISOString(),events_count:events.length,events}),{headers:headers()});
  }catch(e){
    return new Response(JSON.stringify({ok:true,status:'UPSTREAM_UNAVAILABLE',updated_at:new Date().toISOString(),events_count:0,events:[],error:String(e?.message||e),provider:'SportyBet NG',sport_id:'sr:sport:22'}),{status:200,headers:headers()});
  }
}