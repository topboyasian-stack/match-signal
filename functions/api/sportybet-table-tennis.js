function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}
const ORIGIN='https://www.sportybet.com';
const BROWSER_HEADERS={'Accept':'application/json, text/plain, */*','Content-Type':'application/json','Current-Country':'NG','Origin':'https://www.sportybet.com','Referer':'https://www.sportybet.com/ng/','User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'};
async function upstream(params){
  const u=new URL(ORIGIN+'/api/ng/factsCenter/pcUpcomingEvents');
  for(const [k,v] of Object.entries(params))u.searchParams.set(k,String(v));
  const r=await fetch(u.toString(),{headers:BROWSER_HEADERS,cache:'no-store',signal:AbortSignal.timeout(10000)});
  const body=await r.text();
  if(!r.ok)throw new Error('SPORTYBET_UPSTREAM_HTTP_'+r.status);
  return JSON.parse(body);
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
  return {sport:'table_tennis',provider:'SportyBet NG',sport_id:'sr:sport:20',event_id:String(e?.eventId||''),competition:String(t?.name||''),category:String(t?.categoryName||''),start_time_ms:start,participant_1:p1,participant_2:p2,markets,winner_market:winner,source_url:'https://www.sportybet.com/ng/'};
}
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  try{
    const data=await upstream({sportId:'sr:sport:20',pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()});
    const events=[];
    for(const t of (data?.data?.tournaments||[]))for(const e of (t?.events||[])){
      const row=normalizeEvent(t,e);
      if(row.event_id&&row.participant_1&&row.participant_2)events.push(row);
    }
    return new Response(JSON.stringify({ok:true,status:events.length?'LIVE':'EMPTY',updated_at:new Date().toISOString(),events_count:events.length,events}),{headers:headers()});
  }catch(e){
    return new Response(JSON.stringify({ok:false,status:'UPSTREAM_ERROR',error:String(e?.message||e)}),{status:502,headers:headers()});
  }
}