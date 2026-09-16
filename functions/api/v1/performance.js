import {requireApiKey,assetJson,ok} from './_lib.js';
export async function onRequestGet(context){
  const denied=await requireApiKey(context); if(denied)return denied;
  const data=await assetJson(context,'/data/verified_tip_ledger.json');
  if(!data)return new Response(JSON.stringify({error:'LEDGER_UNAVAILABLE'}),{status:503,headers:{'Content-Type':'application/json'}});
  return ok({version:'match-signal-api-v1',updated_at:data.updated_at,status:data.status,summary:data.summary,by_sport:data.by_sport,by_market:data.by_market,by_confidence:data.by_confidence});
}
