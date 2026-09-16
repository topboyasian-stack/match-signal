export async function requireApiKey(context) {
  const expected = context.env.MATCH_SIGNAL_API_KEY;
  const supplied = context.request.headers.get('authorization') || '';
  if (!expected) return new Response(JSON.stringify({error:'API_NOT_CONFIGURED',message:'MATCH_SIGNAL_API_KEY is not configured on Cloudflare Pages.'}), {status:503,headers:jsonHeaders()});
  if (supplied !== `Bearer ${expected}`) return new Response(JSON.stringify({error:'UNAUTHORIZED'}), {status:401,headers:jsonHeaders()});
  return null;
}
export function jsonHeaders(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'Authorization, Content-Type'}}
export async function assetJson(context,path){
  const url=new URL(context.request.url); url.pathname=path;
  const r=await context.env.ASSETS.fetch(url);
  if(!r.ok) return null;
  return r.json();
}
export function ok(data){return new Response(JSON.stringify(data),{headers:jsonHeaders()})}
