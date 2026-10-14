function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'public, max-age=15, s-maxage=15, stale-while-revalidate=15','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,OPTIONS'}}

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
  let data;
  try{
    data=JSON.parse(body);
  }catch(error){
    const contentType=r.headers.get('content-type')||'unknown content-type';
    const sample=body.replace(/\s+/g,' ').slice(0,120);
    const format=/text\/html/i.test(contentType)||/<(?:!doctype|html|head|body)\b/i.test(body.slice(0,300))?'HTML':'non-JSON';
    throw new Error(path+' returned '+format+' response ('+contentType+'): '+sample);
  }
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

function scoreValue(value){
  if(value==null) return null;
  if(typeof value==='number' && Number.isFinite(value)) return value;
  if(typeof value==='string' && value.trim()!=='' && Number.isFinite(Number(value))) return Number(value);
  if(typeof value==='object'){
    for(const key of ['display','value','score','current','points','games']){
      if(value[key]!=null){
        const n=scoreValue(value[key]);
        if(n!=null) return n;
      }
    }
  }
  return null;
}

function deepScore(root,side,depth=0){
  if(root==null||depth>3||typeof root!=='object') return null;
  const keys=Object.keys(root);
  for(const key of keys){
    const normalized=String(key).replace(/[^a-z0-9]/gi,'').toLowerCase();
    if((normalized.includes(side+'score')||normalized.includes('score'+side))||(side==='home'&&normalized==='hscore')||(side==='away'&&normalized==='ascore')){
      const n=scoreValue(root[key]);
      if(n!=null) return n;
    }
  }
  for(const key of keys){
    const value=root[key];
    if(value&&typeof value==='object'){
      const nested=deepScore(value,side,depth+1);
      if(nested!=null) return nested;
    }
  }
  return null;
}

function extractScore(event){
  const homeCandidates=[
    event?.homeScore,event?.home_score,event?.scoreHome,event?.homeTeamScore,
    event?.home?.score,event?.home?.currentScore,event?.scores?.home,event?.score?.home,
    event?.score?.homeScore,event?.homeTeam?.score,event?.competitors?.[0]?.score
  ];
  const awayCandidates=[
    event?.awayScore,event?.away_score,event?.scoreAway,event?.awayTeamScore,
    event?.away?.score,event?.away?.currentScore,event?.scores?.away,event?.score?.away,
    event?.score?.awayScore,event?.awayTeam?.score,event?.competitors?.[1]?.score
  ];
  let home=null,away=null;
  for(const value of homeCandidates){home=scoreValue(value);if(home!=null)break;}
  for(const value of awayCandidates){away=scoreValue(value);if(away!=null)break;}
  if(home==null) home=deepScore(event,'home');
  if(away==null) away=deepScore(event,'away');
  if(home==null && away==null) return null;
  return {home,away,text:(home!=null&&away!=null)?String(home)+' - '+String(away):null};
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
    tournament_id:String(t?.id||t?.tournamentId||t?.tournament_id||event?.tournamentId||event?.tournament?.id||event?.tournament?.tournamentId||''),
    category_id:String(t?.categoryId||t?.category?.id||t?.category?.categoryId||t?.category_id||event?.categoryId||event?.category?.id||event?.category_id||event?.tournament?.categoryId||''),
    event_id:String(event?.eventId||event?.event_id||''),
    team_1:team1,
    team_2:team2,
    participant_1:participant1,
    participant_2:participant2,
    participant_identity_source:identitySource,
    start_time_ms:(()=>{const raw=Number(event?.estimateStartTime);if(!Number.isFinite(raw)||raw<=0)return null;return raw<100000000000?raw*1000:raw})(),
    match_status:event?.matchStatus ?? null,
    live:Boolean(event?.live||event?.isLive||false),
    score:(source.endsWith('_live')||event?.live||event?.isLive)?extractScore(event):null,
    markets:(Array.isArray(event?.markets)?event.markets:[]).map(m=>({
      id:String(m?.id||''),
      name:String(m?.name||m?.desc||m?.title||''),
      specifier:String(m?.specifier||''),
      line:m?.line!=null?Number(m.line):((String(m?.specifier||'').match(/(?:total|line)=([0-9]+(?:\\.[0-9]+)?)/i)||[])[1]!=null?Number((String(m?.specifier||'').match(/(?:total|line)=([0-9]+(?:\\.[0-9]+)?)/i)||[])[1]):null),
      status:m?.status,
      lastOddsChangeTime:m?.lastOddsChangeTime,
      outcomes:Array.isArray(m?.outcomes)?m.outcomes.map(o=>({
        id:String(o?.id||''),
        name:String(o?.name||o?.desc||o?.title||''),
        odds:o?.odds!=null?Number(o.odds):null,
        active:o?.isActive!==false
      })).filter(o=>o.odds!=null):[]
    })).filter(m=>m.outcomes.length)
  };
}

const LAST_GOOD_EFOOTBALL_CACHE_TTL_MS = 15 * 60 * 1000;

function lastGoodEfootballCacheKey(requestUrl, pageSize, pageNum, timeline) {
  const key = new URL('/__match-signal-internal-cache__/sportybet-virtual', requestUrl.origin);
  key.searchParams.set('sources', 'efootball');
  key.searchParams.set('pageSize', String(pageSize));
  key.searchParams.set('pageNum', String(pageNum));
  key.searchParams.set('timeline', String(timeline));
  key.searchParams.set('includeLive', 'false');
  return new Request(key.toString(), { method: 'GET' });
}

function lastGoodEfootballCacheStore() {
  try { return globalThis.caches?.default || null; } catch (_) { return null; }
}

async function storeLastGoodEfootballSnapshot(requestUrl, pageSize, pageNum, timeline, payload) {
  try {
    const cache = lastGoodEfootballCacheStore();
    if (!cache) return;
    await cache.put(lastGoodEfootballCacheKey(requestUrl, pageSize, pageNum, timeline), new Response(JSON.stringify(payload), {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=900, s-maxage=900'
      }
    }));
  } catch (_) {
    // Best-effort resilience only; cache failures must never block a live response.
  }
}

async function readLastGoodEfootballSnapshot(requestUrl, pageSize, pageNum, timeline) {
  try {
    const cache = lastGoodEfootballCacheStore();
    if (!cache) return null;
    const response = await cache.match(lastGoodEfootballCacheKey(requestUrl, pageSize, pageNum, timeline));
    if (!response) return null;
    const payload = await response.json();
    const observedAt = Date.parse(String(payload?.updated_at || payload?.server_time || ''));
    const ageMs = Date.now() - observedAt;
    if (payload?.status !== 'LIVE' ||
        !Array.isArray(payload?.events) || payload.events.length === 0 ||
        payload?.source_status?.efootball?.status !== 'LIVE' ||
        !Number.isFinite(ageMs) || ageMs < -120000 ||
        ageMs >= LAST_GOOD_EFOOTBALL_CACHE_TTL_MS) return null;
    return { payload, ageMs: Math.max(0, ageMs) };
  } catch (_) {
    return null;
  }
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  // Upcoming qualification checks can opt out of the separate live-event source;
  // its transient errors must not make an otherwise usable upcoming snapshot incomplete.
  const includeLive=u.searchParams.get('includeLive')!=='false';
  const requested=new Set((u.searchParams.get('sources')||'efootball,vfootball').split(',').map(s=>s.trim().toLowerCase()).filter(Boolean));
  const edgeCacheEligible=!includeLive&&requested.size===1&&requested.has('efootball');
  const out=[];
  const errors=[];
  const sourceStatus={};

  const pcTargets=[
    ['efootball','sr:sport:137']
  ];

  async function collectPc(label,sportId){
    if(!requested.has(label)) return;
    const t0=Date.now();
    const endpoint='/api/ng/factsCenter/pcUpcomingEvents';
    let data=null,lastError=null,attempts=0;
    // SportyBet can return an HTML error/challenge page with HTTP 200, or a
    // temporarily empty JSON page. Retry the normal upcoming endpoint first.
    for(let attempt=1;attempt<=2;attempt++){
      attempts=attempt;
      try{
        const candidate=await upstream(endpoint,{
          sportId,marketId:'1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
          pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
        });
        const count=tournaments(candidate).reduce((sum,t)=>sum+(Array.isArray(t?.events)?t.events.length:0),0);
        data=candidate;
        if(count>0){lastError=null;break;}
        lastError='upstream upcoming feed returned no tournaments/events';
      }catch(e){
        lastError=String(e.message||e||'upstream upcoming feed failed');
      }
      if(attempt<2)await new Promise(resolve=>setTimeout(resolve,250));
    }

    const primaryError=lastError;
    const primaryCount=tournaments(data).reduce((sum,t)=>sum+(Array.isArray(t?.events)?t.events.length:0),0);
    let fallbackAttempted=false;
    let fallbackUsed=false;
    const fallbackEndpoint='/api/ng/factsCenter/wapConfigurableUpcomingEvents';
    let selectedEndpoint=endpoint;
    // Separate official SportyBet upcoming endpoint: use it only if the primary
    // endpoint produced no events. No synthetic fixtures or cached odds are inserted.
    if(primaryCount===0){
      fallbackAttempted=true;
      try{
        const fallback=await upstream(fallbackEndpoint,{
          sportId,pageSize,pageNum,todayGames:'false',timeline,_t:Date.now()
        });
        data=fallback;
        const fallbackCount=tournaments(fallback).reduce((sum,t)=>sum+(Array.isArray(t?.events)?t.events.length:0),0);
        if(fallbackCount>0){
          fallbackUsed=true;
          selectedEndpoint=fallbackEndpoint;
          lastError=null;
        }else{
          lastError=[primaryError?'primary '+endpoint+' failed or was empty: '+primaryError:null,
            'fallback '+fallbackEndpoint+' returned no tournaments/events'].filter(Boolean).join('; ');
        }
      }catch(e){
        const fallbackError=String(e.message||e||'fallback upcoming feed failed');
        lastError=[primaryError?'primary '+endpoint+' failed or was empty: '+primaryError:null,
          'fallback '+fallbackEndpoint+' failed: '+fallbackError].filter(Boolean).join('; ');
      }
    }

    let n=0;
    for(const t of tournaments(data)){
      for(const e of (t.events||[])){
        out.push(normalize(t,e,label,sportId)); n++;
      }
    }
    const status=n?'LIVE':(data?'EMPTY':'ERROR');
    sourceStatus[label]={
      status,events:n,attempts,retried:attempts>1,latency_ms:Date.now()-t0,
      endpoint:selectedEndpoint,primary_endpoint:endpoint,
      ...(fallbackAttempted?{fallback_attempted:true,fallback_used:fallbackUsed,fallback_endpoint:fallbackEndpoint}:{}),
      ...(n?{}:{error:String(lastError||'upstream upcoming feed returned no events')})
    };
    if(!n)errors.push(label+': '+String(lastError||'upstream upcoming feed returned no events'));
  }
  async function collectLive(label,sportId,path,extra={}){
    if(!requested.has(label)||!includeLive) return;
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
    collectLive('efootball','sr:sport:137','/api/ng/factsCenter/wapConfigurableIndexLiveEvents')
  ]);

  const cutoff=Date.now()-(2*60*1000);
  const dedup=new Map();
  for(const row of out){
    if(!row.event_id)continue;
    const status=String(row.match_status||'').toLowerCase();
    const inferredLive=row.live===true || /live|running|playing|in.?play|started|1st half|2nd half|half time/.test(status);
    if(inferredLive) row.live=true;
    const start=Number(row.start_time_ms||0);
    const finished=/finish|ended|final|completed|settled|closed/.test(status);
    if(start>0&&start<cutoff&&!row.live){
      const recentlyStarted=start>=Date.now()-(4*60*60*1000)&&start<=Date.now()&&!finished;
      if(!recentlyStarted)continue;
    }
    const previous=dedup.get(row.event_id);
    // Live records must always win over the corresponding upcoming snapshot.
    if(!previous || row.live===true || previous.live!==true) dedup.set(row.event_id,row);
  }
  const nowMs=Date.now();
  const events=[...dedup.values()].filter(e=>{
    if(e.live)return true;
    const start=Number(e.start_time_ms||0);
    const status=String(e.match_status||'').toLowerCase();
    const finished=/finish|ended|final|completed|settled|closed/.test(status);
    if(!start||finished)return false;
    // Keep near-start and recently-started records visible even when SportyBet
    // has not exposed a live flag yet, so the UI can show STARTED / awaiting feed.
    return start>=nowMs-(4*60*60*1000);
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

  const payload={
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
  };

  if(edgeCacheEligible){
    const source=payload.source_status?.efootball;
    const liveSuccess=source?.status==='LIVE'&&payload.status==='LIVE'&&payload.events.length>0&&payload.errors.length===0;
    if(liveSuccess){
      await storeLastGoodEfootballSnapshot(u,pageSize,pageNum,timeline,payload);
    }else if(source?.status==='ERROR'){
      // Reuse only an actual recent provider success after an upstream failure.
      // Keep its original timestamp; an empty provider response never resurrects old events.
      const cached=await readLastGoodEfootballSnapshot(u,pageSize,pageNum,timeline);
      if(cached){
        const ageSeconds=Math.floor(cached.ageMs/1000);
        const failure=String(source?.error||'SportyBet upstream request failed');
        return new Response(JSON.stringify({
          ...cached.payload,
          cache_fallback_used:true,
          cache_age_seconds:ageSeconds,
          cache_fallback_reason:failure,
          source_status:{
            ...cached.payload.source_status,
            efootball:{
              ...cached.payload.source_status.efootball,
              status:'CACHED',
              cache_fallback_used:true,
              cache_age_seconds:ageSeconds,
              last_refresh_error:failure
            }
          },
          errors:[]
        }),{status:200,headers:{...headers(),'Cache-Control':'no-store','X-Match-Signal-Quote-Cache':'STALE-IF-ERROR'}});
      }
    }
  }

  return new Response(JSON.stringify(payload),{status:200,headers:headers()});
}
