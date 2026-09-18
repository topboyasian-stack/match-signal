function corsHeaders(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*'}}
const ESPN_ORIGIN='https://site.api.espn.com';
const ALLOWED_PREFIX='/apis/site/v2/sports/';
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const path=u.searchParams.get('path')||'';
  if(!path.startsWith(ALLOWED_PREFIX) || path.includes('..') || path.includes('\\\\')) return new Response(JSON.stringify({ok:false,error:'INVALID_ESPN_PATH'}),{status:400,headers:corsHeaders()});
  try{
    const upstream=await fetch(ESPN_ORIGIN+path,{headers:{Accept:'*/*','User-Agent':'curl/8.16.0'},cache:'no-store'});
    const body=await upstream.text();
    if(!upstream.ok){
      return new Response(JSON.stringify({ok:false,error:'ESPN_UPSTREAM_HTTP_'+upstream.status,body_prefix:body.slice(0,160)}),{status:upstream.status,headers:corsHeaders()});
    }
    return new Response(body,{status:200,headers:{...corsHeaders(),'X-Match-Signal-Proxy':'ESPN'}});
  }catch(e){
    return new Response(JSON.stringify({ok:false,error:'ESPN_PROXY_FAILED',detail:String(e?.message||e)}),{status:502,headers:corsHeaders()});
  }
}
