function corsHeaders(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*'}}
const ESPN_ORIGIN='https://site.api.espn.com';
const ALLOWED_PREFIX='/apis/site/v2/sports/';
export async function onRequestGet(context){
  const u=new URL(context.request.url);
  const path=u.searchParams.get('path')||'';
  let target;
  try { target=new URL(path,ESPN_ORIGIN); } catch { return new Response(JSON.stringify({ok:false,error:'INVALID_ESPN_PATH'}),{status:400,headers:corsHeaders()}); }
  if(target.origin!==ESPN_ORIGIN || !target.pathname.startsWith(ALLOWED_PREFIX) || target.pathname.includes('..') || target.pathname.includes('\\\\')) return new Response(JSON.stringify({ok:false,error:'INVALID_ESPN_PATH'}),{status:400,headers:corsHeaders()});
  // Accept the event ID whether the caller supplied it beside path or inside
  // the encoded ESPN path. Normalize to one canonical query value.
  const event=String(u.searchParams.get('event')||target.searchParams.get('event')||'');
  if(event && !/^\\d{6,12}$/.test(event)) return new Response(JSON.stringify({ok:false,error:'INVALID_ESPN_EVENT'}),{status:400,headers:corsHeaders()});
  if(event) target.searchParams.set('event',event);
  try{
    const upstream=await fetch(target.toString(),{headers:{Accept:'application/json','User-Agent':'MatchSignal/4.0 (+https://github.com/topboyasian-stack/match-signal)'},cache:'no-store',signal:AbortSignal.timeout(8000)});
    const body=await upstream.text();
    if(!upstream.ok){
      return new Response(JSON.stringify({ok:false,error:'ESPN_UPSTREAM_HTTP_'+upstream.status,body_prefix:body.slice(0,160)}),{status:upstream.status,headers:corsHeaders()});
    }
    return new Response(body,{status:200,headers:{...corsHeaders(),'X-Match-Signal-Proxy':'ESPN'}});
  }catch(e){
    return new Response(JSON.stringify({ok:false,error:'ESPN_PROXY_FAILED',detail:String(e?.message||e)}),{status:502,headers:corsHeaders()});
  }
}
// Production deployment retriggered after the Cloudflare promotion guard allowlist repair.
// Cloudflare promotion guard repair retrigger.
