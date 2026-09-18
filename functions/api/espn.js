function corsHeaders(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*'}}
const ESPN_ORIGIN='https://site.api.espn.com';
const ALLOWED_PREFIX='/apis/site/v2/sports/';
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const path=u.searchParams.get('path')||'';
  if(!path.startsWith(ALLOWED_PREFIX) || path.includes('..') || path.includes('\\\\')) return new Response(JSON.stringify({ok:false,error:'INVALID_ESPN_PATH'}),{status:400,headers:corsHeaders()});
  try{
    const upstream=await fetch(ESPN_ORIGIN+path,{headers:{Accept:'application/json','User-Agent':'Match-Signal/1.0'},cache:'no-store'});
    const body=await upstream.text();
    return new Response(body,{status:upstream.status,headers:{...corsHeaders(),'X-Match-Signal-Proxy':'ESPN'}});
  }catch(e){
    return new Response(JSON.stringify({ok:false,error:'ESPN_PROXY_FAILED',detail:String(e?.message||e)}),{status:502,headers:corsHeaders()});
  }
}
