import { authorizeApi, json } from '../../_lib/api-auth.js';
function headers(){return {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','X-Content-Type-Options':'nosniff'}}
export async function onRequestGet(context){const denied=await authorizeApi(context,headers());if(denied)return denied;const u=new URL(context.request.url);u.pathname='/data/market_research.json';const r=await context.env.ASSETS.fetch(u);if(!r.ok)return json({error:'MARKET_RESEARCH_UNAVAILABLE'},503,headers());return json(await r.json(),200,headers())}
