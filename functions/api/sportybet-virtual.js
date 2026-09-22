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
    tournament_id:String(t?.id||t?.tournamentId||''),
    category_id:String(t?.categoryId||t?.category?.id||''),
    event_id:String(event?.eventId||''),
    team_1:String(event?.homeTeamName||''),
    team_2:String(event?.awayTeamName||''),
    participant_1:String(event?.homeParticipant||event?.homePlayer||event?.homeCompetitor||'').trim(),
    participant_2:String(event?.awayParticipant||event?.awayPlayer||event?.awayCompetitor||'').trim(),
    participant_identity_source:(event?.homeParticipant||event?.awayParticipant||event?.homePlayer||event?.awayPlayer||event?.homeCompetitor||event?.awayCompetitor)?'sportybet_explicit_event_metadata':null,
    start_time_ms:(()=>{const raw=Number(event?.estimateStartTime);if(!Number.isFinite(raw)||raw<=0)return null;return raw<100000000000?raw*1000:raw})(),
    match_status:event?.matchStatus ?? null,
    markets:(Array.isArray(event?.markets)?event.markets:[]).map(m=>({
      ...m,
      line:m?.line!=null?Number(m.line):((String(m?.specifier||'').match(/(?:total|line)=([0-9]+(?:\\.[0-9]+)?)/i)||[])[1]!=null?Number((String(m?.specifier||'').match(/(?:total|line)=([0-9]+(?:\\.[0-9]+)?)/i)||[])[1]):null),
      outcomes:Array.isArray(m?.outcomes)?m.outcomes.map(o=>({
        ...o,
        name:String(o?.name||o?.desc||o?.title||'')
      })):[]
    }))
  };
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  const requested=new Set((u.searchParams.get('sources')||'efootball,vfootball').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean));
  const out=[];
  const errors=[];
  const sourceStatus={};

  const pcTargets=[
    ['efootball','sr:sport:137']
  ];

  async function collectPc(label,sportId){
    if(!requested.has(label)) return;
    const t0=Date.now();
    try{
      const data=await upstream('/api/ng/factsCenter/pcUpcomingEvents',{
        sportId,marketId:'1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
        pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
      });
      let n=0;
      for(const t of tournaments(data)){
        for(const e of (t.events||[])){
          out.push(normalize(t,e,label,sportId)); n++;
        }
      }
      sourceStatus[label]={status:n?'LIVE':'EMPTY',events:n,latency_ms:Date.now()-t0};
    }catch(e){
      sourceStatus[label]={status:'ERROR',events:0,latency_ms:Date.now()-t0,error:String(e.message||e)};
      errors.push(label+': '+String(e.message||e));
    }
  }

  async function collectLive(label,sportId,path,extra={}){
    if(!requested.has(label)) return;
    const t0=Date.now();
    try{
      let data=await upstream(path,{sportId,pageSize,pageNum,todayGames:'false',timeline,_t:Date.now(),...extra});
      if(!tournaments(data).length && label==='vfootball'){
        data=await upstream(path,{sportId,pageSize,pageNum,todayGames:'true',_t:Date.now(),...extra});
      }
      let n=0;
      for(const t of tournaments(data)){
        for(const e of (t.events||[])){
          const row=normalize(t,e,label+'_live',sportId);
          row.live=true;
          row.match_status=e?.matchStatus ?? row.match_status;
          out.push(row); n++;
        }
      }
      sourceStatus[label+'_live']={status:n?'LIVE':'EMPTY',events:n,latency_ms:Date.now()-t0,endpoint:path};
    }catch(e){
      sourceStatus[label+'_live']={status:'ERROR',events:0,latency_ms:Date.now()-t0,error:String(e.message||e),endpoint:path};
      errors.push(label+'_live: '+String(e.message||e));
    }
  }

  async function collectVfootball(){
    if(!requested.has('vfootball')) return;
    const t0=Date.now();
    try{
      let data=await upstream('/api/ng/factsCenter/wapConfigurableUpcomingEvents',{
        sportId:'sr:sport:202120001',pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
      });
      if(!tournaments(data).length){
        data=await upstream('/api/ng/factsCenter/wapConfigurableUpcomingEvents',{
          sportId:'sr:sport:202120001',pageSize,pageNum,todayGames:'true',_t:Date.now()
        });
      }
      if(!tournaments(data).length){
        data=await upstream('/api/ng/factsCenter/pcUpcomingEvents',{
          sportId:'sr:sport:202120001',marketId:'1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
          pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
        });
      }
      let n=0;
      for(const t of tournaments(data)){
        for(const e of (t.events||[])){
          out.push(normalize(t,e,'vfootball','sr:sport:202120001')); n++;
        }
      }
      sourceStatus.vfootball={status:n?'LIVE':'EMPTY',events:n,latency_ms:Date.now()-t0};
    }catch(e){
      sourceStatus.vfootball={status:'ERROR',events:0,latency_ms:Date.now()-t0,error:String(e.message||e)};
      errors.push('vfootball: '+String(e.message||e));
    }
  }

  await Promise.all([
    collectPc('efootball','sr:sport:137'),
    collectVfootball(),
    collectLive('vfootball','sr:sport:202120001','/api/ng/factsCenter/wapConfigurableIndexLiveEvents'),
    collectLive('efootball','sr:sport:137','/api/ng/factsCenter/pcLiveEvents')
  ]);

  const cutoff=Date.now()-(2*60*1000);
  const dedup=new Map();
  for(const row of out){
    if(!row.event_id)continue;
    const start=Number(row.start_time_ms||0);
    if(start>0&&start<cutoff&&!row.live)continue;
    dedup.set(row.event_id,row);
  }
  const events=[...dedup.values()];
  const counts={};
  const filtered=[];
  for(const e of events){
    const blob=(e.tournament+' '+e.category+' '+e.team_1+' '+e.team_2+' '+e.participant_1+' '+e.participant_2).toLowerCase();
    let key=null;
    if(e.source==='efootball'){
      key=/eadriatic/.test(blob)?'efootball_adriatic':'efootball_gt';
    }else if(e.source==='vfootball' && /zoom|turbo/i.test(blob)){
      key='zoom';
    }else if(e.source==='vfootball'){
      key='vfootball';
    }
    if(!key) continue;
    e.product=key;
    filtered.push(e);
    counts[key]=(counts[key]||0)+1;
  }

  return new Response(JSON.stringify({
    ok:true,
    feed_contract:'virtual-lab-v2',
    excluded_products:['srl'],
    status:filtered.length?'LIVE':'UPSTREAM_EMPTY',
    updated_at:new Date().toISOString(),
    page_size:pageSize,
    page_num:pageNum,
    timeline_hours:timeline,
    events_count:filtered.length,
    upcoming_events_count:filtered.filter(e=>e.live||!e.start_time_ms||Number(e.start_time_ms)>=cutoff).length,
    server_time:new Date().toISOString(),
    product_counts:counts,
    source_status:sourceStatus,
    errors,
    events:filtered
  }),{status:200,headers:headers()});
}
