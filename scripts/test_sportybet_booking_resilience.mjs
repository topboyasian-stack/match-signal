import assert from 'node:assert/strict';
import { upstream, collectBasketballEvents, onRequest } from '../functions/api/sportybet-booking.js';
const originalFetch=globalThis.fetch;
const SPORTYBET='https://www.sportybet.com';
const PROXY='https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const jsonResponse=payload=>new Response(JSON.stringify(payload),{status:200,headers:{'content-type':'application/json; charset=utf-8'}});
const htmlResponse=()=>new Response('<!doctype html><html><body>edge challenge</body></html>',{status:200,headers:{'content-type':'text/html; charset=utf-8'}});
try {
  const emptyTicketResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[]})
  })});
  assert.equal(emptyTicketResponse.status,422);
  assert.match(String(emptyTicketResponse.headers.get('content-type')||''),/application\/json/i);
  const emptyTicketPayload=await emptyTicketResponse.json();
  assert.equal(emptyTicketPayload.error,'INVALID_MANUAL_LEG_COUNT');
  assert.equal(Boolean(emptyTicketPayload.booking_code),false);

  const observed=[];
  globalThis.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url);observed.push(url);
    if(url.origin===SPORTYBET)return htmlResponse();
    if(url.origin===PROXY)return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    throw new Error('Unexpected test URL '+url.href);
  };
  const recovered=await upstream('/api/ng/factsCenter/pcUpcomingEvents',{sportId:'sr:sport:1',marketId:'225'});
  assert.equal(recovered.bizCode,10000);assert.equal(observed.length,2);
  assert.equal(observed[0].origin,SPORTYBET);assert.equal(observed[1].origin,PROXY);
  assert.equal(observed[0].pathname,observed[1].pathname);
  assert.equal(observed[0].searchParams.get('marketId'),'225');assert.equal(observed[1].searchParams.get('marketId'),'225');
  globalThis.fetch=async()=>htmlResponse();
  await assert.rejects(()=>upstream('/api/ng/factsCenter/pcUpcomingEvents',{marketId:'225'}),
    error=>/returned HTML instead of JSON/.test(error.message)&&!/Unexpected token/.test(error.message));

  const sportPayload={bizCode:10000,data:{tournaments:[{id:'sr:tournament:132',name:'NBA',events:[{
    eventId:'sr:match:booking-feed-test',homeTeamName:'Fixture Home',awayTeamName:'Fixture Away',estimateStartTime:Date.now()+3600000,matchStatus:'Not start',
    markets:[{id:'225',desc:'Full Game Total incl. OT',specifier:'total=220.5',status:'0',outcomes:[
      {id:'over',desc:'Over 220.5',odds:1.93,isActive:1},{id:'under',desc:'Under 220.5',odds:1.88,isActive:1}
    ]}]
  }]}]}};
  const requested=[];
  globalThis.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url);requested.push(url);
    assert.ok(url.origin===SPORTYBET||url.origin===PROXY,'No self-fetch to Match Signal Pages is allowed');
    return jsonResponse(sportPayload);
  };
  const found=await collectBasketballEvents({request:new Request('https://match-signal.pages.dev/api/sportybet-booking')},new Set(['sr:match:booking-feed-test']));
  const event=found.get('sr:match:booking-feed-test');assert.ok(event);
  const market=event.markets.find(m=>String(m.id)==='225');assert.ok(market);
  assert.equal(market.specifier,'total=220.5');
  assert.deepEqual(market.outcomes.map(o=>Number(o.odds)).sort((a,b)=>a-b),[1.88,1.93]);
  assert.ok(requested.length>0&&requested.every(u=>u.origin===SPORTYBET||u.origin===PROXY));
  console.log('SportyBet booking resilience: PASS (HTML fallback, error diagnostics, direct NBA feed invocation, exact market-225 pair).');
} finally { globalThis.fetch=originalFetch; }
