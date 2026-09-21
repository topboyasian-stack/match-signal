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

const SOURCE_SPORTS={
  srl:'sr:sport:1',
  efootball:'sr:sport:137',
  vfootball:'sr:sport:202120001'
};

export async function onRequestOptions(){
  return new Response('',{status:204,headers:headers()});
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const source=(u.searchParams.get('source')||'').trim().toLowerCase();
  const sportId=SOURCE_SPORTS[source];
  if(!sportId){
    return new Response(JSON.stringify({
      ok:false,
      error:'source must be srl, efootball, or vfootball'
    }),{status:400,headers:headers()});
  }

  const params={
    sportId,
    pageSize:String(Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100)),
    pageNum:String(Math.max(Number(u.searchParams.get('pageNum')||1),1)),
    startTime:String(u.searchParams.get('startTime')||''),
    endTime:String(u.searchParams.get('endTime')||''),
  };

  const upstreamUrl=new URL(ORIGIN+'/api/ng/factsCenter/eventResultList');
  for(const [key,value] of Object.entries(params)){
    if(value) upstreamUrl.searchParams.set(key,value);
  }

  try{
    const response=await fetch(upstreamUrl.toString(),{
      headers:BROWSER_HEADERS,
      cache:'no-store',
      signal:AbortSignal.timeout(10000)
    });
    const body=await response.text();
    if(!response.ok){
      return new Response(JSON.stringify({
        ok:false,
        source,
        error:'Upstream HTTP '+response.status,
        detail:body.slice(0,240)
      }),{status:502,headers:headers()});
    }
    if(!body.trim()){
      return new Response(JSON.stringify({
        ok:false,
        source,
        error:'Upstream returned an empty response'
      }),{status:502,headers:headers()});
    }
    let payload;
    try{ payload=JSON.parse(body); }catch{
      return new Response(JSON.stringify({
        ok:false,
        source,
        error:'Upstream returned non-JSON content'
      }),{status:502,headers:headers()});
    }
    if(payload?.bizCode!==undefined && payload.bizCode!==10000){
      return new Response(JSON.stringify({
        ok:false,
        source,
        error:'Upstream bizCode '+payload.bizCode
      }),{status:502,headers:headers()});
    }
    return new Response(JSON.stringify({
      ok:true,
      source,
      fetched_at:new Date().toISOString(),
      payload
    }),{status:200,headers:headers()});
  }catch(error){
    return new Response(JSON.stringify({
      ok:false,
      source,
      error:String(error&&error.message?error.message:error)
    }),{status:502,headers:headers()});
  }
}
