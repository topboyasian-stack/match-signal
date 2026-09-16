import {requireApiKey,assetJson,ok} from './_lib.js';
export async function onRequestGet(context){
  const denied=await requireApiKey(context); if(denied)return denied;
  const data=await assetJson(context,'/data/odds_builder.json');
  if(!data)return new Response(JSON.stringify({error:'ACCUMULATOR_UNAVAILABLE'}),{status:503,headers:{'Content-Type':'application/json'}});
  return ok({version:'match-signal-api-v1',updated_at:data.updated_at,status:data.status,reference_combined_odds:data.reference_combined_odds,qualified_legs:data.qualified_legs||[],bookmaker_odds:data.bookmaker_odds||{}});
}
