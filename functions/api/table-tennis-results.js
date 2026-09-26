function headers(){
  return {
    'Content-Type':'application/json; charset=utf-8',
    'Cache-Control':'no-store',
    'Access-Control-Allow-Origin':'*',
    'Access-Control-Allow-Methods':'GET,OPTIONS'
  };
}

const HOSTS=[
  'https://www.sofascore.com/api/v1/sport/table-tennis/scheduled-events',
  'https://api.sofascore.com/api/v1/sport/table-tennis/scheduled-events'
];

async function fetchJson(url){
  const r=await fetch(url,{
    headers:{
      'Accept':'application/json, text/plain, */*',
      'Referer':'https://www.sofascore.com/table-tennis',
      'Origin':'https://www.sofascore.com',
      'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'
    },
    cache:'no-store',
    signal:AbortSignal.timeout(9000)
  });
  const body=await r.text();
  if(!r.ok)throw new Error(url+' HTTP '+r.status+' '+body.slice(0,160));
  return JSON.parse(body);
}

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const date=u.searchParams.get('date');
  if(!/^\\d{4}-\\d{2}-\\d{2}$/.test(String(date||''))){
    return new Response(JSON.stringify({ok:false,error:'date=YYYY-MM-DD is required'}),{status:400,headers:headers()});
  }
  const errors=[];
  for(const base of HOSTS){
    try{
      const payload=await fetchJson(base+'/'+date);
      return new Response(JSON.stringify({
        ok:true,
        provider:'Sofascore',
        date,
        fetched_at:new Date().toISOString(),
        events:Array.isArray(payload?.events)?payload.events:[],
        source_url:base+'/'+date
      }),{status:200,headers:headers()});
    }catch(e){
      errors.push(String(e?.message||e));
    }
  }
  return new Response(JSON.stringify({
    ok:false,
    provider:'Sofascore',
    date,
    fetched_at:new Date().toISOString(),
    events:[],
    errors
  }),{status:200,headers:headers()});
}
