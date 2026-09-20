function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*'}}
const ORIGIN='https://www.sportybet.com';
const BROWSER_HEADERS={'Accept':'application/json, text/plain, */*','Content-Type':'application/json','Current-Country':'NG','Origin':'https://www.sportybet.com','Referer':'https://www.sportybet.com/ng/','User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'};

export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const sportId=u.searchParams.get('sportId')||'sr:sport:5';
  const marketId=u.searchParams.get('marketId')||'';
  const pageSize=Math.min(Math.max(Number(u.searchParams.get('pageSize')||100),1),100);
  const pageNum=Math.max(Number(u.searchParams.get('pageNum')||1),1);
  const timeline=Math.min(Math.max(Number(u.searchParams.get('timeline')||168),12),720);
  const params=new URLSearchParams({sportId,marketId,pageSize:String(pageSize),pageNum:String(pageNum),todayGames:'false',timeline:String(timeline),_t:String(Date.now())});
  try{
    const upstream=await fetch(ORIGIN+'/api/ng/factsCenter/pcUpcomingEvents?'+params.toString(),{
      headers:BROWSER_HEADERS,
      cache:'no-store',
      signal:AbortSignal.timeout(10000)
    });
    const body=await upstream.text();
    if(!upstream.ok)return new Response(JSON.stringify({ok:false,error:'SPORTYBET_UPSTREAM_HTTP_'+upstream.status,body_prefix:body.slice(0,200)}),{status:upstream.status,headers:headers()});
    if(!body.trim())return new Response(JSON.stringify({ok:false,error:'SPORTYBET_EMPTY_RESPONSE'}),{status:502,headers:headers()});
    return new Response(body,{status:200,headers:{...headers(),'X-Match-Signal-Proxy':'SportyBet'}});
  }catch(e){
    return new Response(JSON.stringify({ok:false,error:'SPORTYBET_PROXY_FAILED',detail:String(e?.message||e)}),{status:502,headers:headers()});
  }
}
