function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}

const ORIGIN='https://www.sportybet.com';
const BROWSER_HEADERS={
  'Accept':'application/json, text/plain, */*',
  'Content-Type':'application/json',
  'Current-Country':'NG',
  'Origin':'https://www.sportybet.com',
  'Referer':'https://www.sportybet.com/ng/',
  'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'
};

async function upstream(path, params){
  const url=new URL(ORIGIN+path);
  for(const [k,v] of Object.entries(params)) url.searchParams.set(k,String(v));
  const r=await fetch(url.toString(),{headers:BROWSER_HEADERS,cache:'no-store',signal:AbortSignal.timeout(10000)});
  const body=await r.text();
  if(!r.ok) throw new Error(path+' HTTP '+r.status+' '+body.slice(0,180));
  if(!body.trim()) throw new Error(path+' empty response');
  const data=JSON.parse(body);
  if(data?.bizCode!==undefined && data.bizCode!==10000) throw new Error(path+' bizCode '+data.bizCode);
  return data;
}

function tournaments(body){
  return Array.isArray(body?.data?.tournaments)?body.data.tournaments:[];
}

function normalize(t, event, source, sportId){
  return {
    provider:'SportyBet NG',
    source,
    sport_id:sportId,
    tournament:String(t?.name||''),
    category:String(t?.categoryName||''),
    event_id:String(event?.eventId||''),
    participant_1:String(event?.homeTeamName||''),
    participant_2:String(event?.awayTeamName||''),
    start_time_ms:event?.estimateStartTime ?? null,
    match_status:event?.matchStatus ?? null,
    markets:Array.isArray(event?.markets)?event.markets:[]
  };
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  const requested=new Set((u.searchParams.get('sources')||'efootball,srl,vfootball').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean));
  const out=[];
  const errors=[];

  const pcTargets=[
    ['srl','sr:sport:1'],
    ['efootball','sr:sport:97']
  ];
  for(const [label,sportId] of pcTargets){
    if(!requested.has(label)) continue;
    try{
      const data=await upstream('/api/ng/factsCenter/pcUpcomingEvents',{
        sportId,marketId:'1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
        pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
      });
      for(const t of tournaments(data)){
        for(const e of (t.events||[])) out.push(normalize(t,e,label,sportId));
      }
    }catch(e){errors.push(label+': '+String(e.message||e))}
  }

  if(requested.has('vfootball')){
    try{
      const data=await upstream('/api/ng/factsCenter/wapConfigurableUpcomingEvents',{
        sportId:'sr:sport:202120001',
        pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
      });
      for(const t of tournaments(data)){
        for(const e of (t.events||[])) out.push(normalize(t,e,'vfootball','sr:sport:202120001'));
      }
    }catch(e){errors.push('vfootball: '+String(e.message||e))}
  }

  const dedup=new Map();
  for(const row of out) if(row.event_id) dedup.set(row.event_id,row);
  const events=[...dedup.values()];
  const counts={};
  const filtered=[];
  for(const e of events){
    const blob=(e.tournament+' '+e.category+' '+e.participant_1+' '+e.participant_2).toLowerCase();
    let key=null;
    if(e.source==='efootball'){
      key=/eadriatic/.test(blob)?'efootball_adriatic':'efootball_gt';
    }else if(e.source==='vfootball'){
      key='vfootball';
    }else if(e.source==='srl' && (/simulated reality/.test(blob)||/\bsrl\b/i.test(blob)||/simulated/.test(blob))){
      key='srl';
    }else if(/zoom|turbo/i.test(blob)){
      key='zoom';
    }
    if(!key) continue;
    e.product=key;
    filtered.push(e);
    counts[key]=(counts[key]||0)+1;
  }

  return new Response(JSON.stringify({
    ok:true,
    status:events.length?'LIVE':'UPSTREAM_EMPTY',
    updated_at:new Date().toISOString(),
    events_count:filtered.length,
    product_counts:counts,
    errors,
    events:filtered
  }),{status:200,headers:headers()});
}
