import {requireApiKey,assetJson,ok} from './_lib.js';
export async function onRequestGet(context){
  const denied=await requireApiKey(context); if(denied)return denied;
  const data=await assetJson(context,'/data/predictions.json');
  if(!data)return new Response(JSON.stringify({error:'DATA_UNAVAILABLE'}),{status:503,headers:{'Content-Type':'application/json'}});
  const url=new URL(context.request.url), sport=url.searchParams.get('sport');
  const rows=(Array.isArray(data)?data:[]).filter(x=>!sport||String(x.sport).toLowerCase()===sport.toLowerCase());
  return ok({version:'match-signal-api-v1',updated_at:new Date().toISOString(),count:rows.length,sport:sport||'all',predictions:rows});
}
