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

function participantFromName(value){
  const text=String(value||'').trim();
  const m=text.match(/\\(([^()]+)\\)\\s*$/);
  return m&&m[1]?m[1].trim():'';
}
function normalize(t, event, source, sportId){
  const team1=String(event?.homeTeamName||'').trim();
  const team2=String(event?.awayTeamName||'').trim();
  const explicit1=String(event?.homeParticipant||event?.homePlayer||event?.homeCompetitor||'').trim();
  const explicit2=String(event?.awayParticipant||event?.awayPlayer||event?.awayCompetitor||'').trim();
  const participant1=explicit1||participantFromName(team1);
  const participant2=explicit2||participantFromName(team2);
  const identitySource=(explicit1||explicit2)?'sportybet_explicit_event_metadata':((participant1||participant2)?'derived_from_team_name_suffix':null);
  return {
    provider:'SportyBet NG',
    source,
    sport_id:sportId,
    tournament:String(t?.name||''),
    category:String(t?.categoryName||''),
    tournament_id:String(t?.id||t?.tournamentId||''),
    category_id:String(t?.categoryId||t?.category?.id||''),
    event_id:String(event?.eventId||''),
    team_1:team1,
    team_2:team2,
    participant_1:participant1,
    participant_2:participant2,
    participant_identity_source:identitySource,
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
  const nowMs=Date.now();
  const events=[...dedup.values()].filter(e=>{
    if(e.live)return true;
    const start=Number(e.start_time_ms||0);
    // Upcoming non-live records must have a real timestamp and still be
    // current. This prevents stale/partial upstream records from reaching
    // the Lab and being mistaken for predictions.
    return start>0&&start>=nowMs-(30*60*1000);
  });
  const counts={};
  const filtered=[];
  for(const e of events){
    const blob=(e.tournament+' '+e.category+' '+e.team_1+' '+e.team_2+' '+e.participant_1+' '+e.participant_2).toLowerCase();
    let key=null;
    const sourceBase=String(e.source||'').replace(/_live$/,'');
    if(sourceBase==='efootball'){
      key=/eadriatic/.test(blob)?'efootball_adriatic':'efootball_gt';
    }else if(sourceBase==='vfootball' && /zoom|turbo/i.test(blob)){
      key='zoom';
    }else if(sourceBase==='vfootball'){
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
    upcoming_events_count:filtered.filter(e=>e.live||(!e.live&&Number(e.start_time_ms||0)>=Date.now()-(30*60*1000))).length,
    server_time:new Date().toISOString(),
    product_counts:counts,
    source_status:sourceStatus,
    errors,
    events:filtered
  }),{status:200,headers:headers()});
}
