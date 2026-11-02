import assert from 'node:assert/strict';
import { upstream, collectEvents, collectBasketballEvents, requestSportyBetShare, onRequest } from '../functions/api/sportybet-booking.js';
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
    // whichever source is tried first returns a 200 HTML edge response; the
    // alternate configured source must recover with the JSON payload.
    if(observed.length===1)return htmlResponse();
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const recovered=await upstream('/api/ng/factsCenter/pcUpcomingEvents',{sportId:'sr:sport:1',marketId:'225'});
  assert.equal(recovered.bizCode,10000);assert.equal(observed.length,2);
  assert.notEqual(observed[0].origin,observed[1].origin,'the alternate source must be tried after an HTML response');
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

  // Catalogue scans must honor the Worker’s strict pageNum 1..5 contract.
  requested.length=0;
  const oneFullPage=Array.from({length:100},(_,i)=>({
    eventId:'sr:match:page-test-'+i,
    homeTeamName:'Home '+i,awayTeamName:'Away '+i,
    estimateStartTime:Date.now()+7200000,matchStatus:'Not start',markets:[]
  }));
  globalThis.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url);requested.push(url);
    return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Regression',events:oneFullPage}]}});
  };
  await collectEvents({sportId:'sr:sport:1',marketId:'1,18',pageSize:100},new Set(['sr:match:not-on-these-pages']));
  assert.deepEqual(requested.map(u=>Number(u.searchParams.get('pageNum'))),[1,2,3,4,5]);
  assert.ok(requested.every(u=>Number(u.searchParams.get('pageNum'))<=5));

  // A regional share POST should recover via direct origin only when the Worker
  // cannot produce JSON; the selection body is unchanged between attempts.
  const shareSelections=[
    {eventId:'sr:match:football-test',marketId:'18',specifier:'total=2.5',outcomeId:'under'},
    {eventId:'sr:match:tennis-test',marketId:'186',specifier:null,outcomeId:'home'}
  ];
  const shareRequests=[];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);shareRequests.push({url,options});
    if(url.origin===PROXY)return new Response(JSON.stringify({
      ok:false,error:'SPORTYBET_SHARE_NON_JSON',detail:'SportyBet share endpoint returned HTML'
    }),{status:502,headers:{'content-type':'application/json; charset=utf-8'}});
    return jsonResponse({bizCode:10000,data:{shareCode:'TESTSHARE'}});
  };
  const shared=await requestSportyBetShare([
    {eventId:'sr:match:football-test',marketId:'18',specifier:'total=2.5',outcomeId:'under'},
    {eventId:'sr:match:tennis-test',marketId:'186',specifier:null,outcomeId:'home'}
  ]);
  assert.equal(shared.payload.data.shareCode,'TESTSHARE');
  assert.equal(shared.origin,SPORTYBET);
  assert.deepEqual(shareRequests.map(x=>x.url.origin),[PROXY,SPORTYBET]);
  assert.ok(shareRequests.every(x=>x.options.method==='POST'));
  assert.deepEqual(JSON.parse(shareRequests[0].options.body),{selections:shareSelections});
  assert.deepEqual(JSON.parse(shareRequests[1].options.body),{selections:shareSelections});

  const failedShareRequests=[];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);failedShareRequests.push(url);
    return htmlResponse();
  };
  const failedShare=await requestSportyBetShare([
    {eventId:'sr:match:football-test',marketId:'18',specifier:'total=2.5',outcomeId:'under'},
    {eventId:'sr:match:tennis-test',marketId:'186',specifier:null,outcomeId:'home'}
  ]);
  assert.equal(failedShare.error,'SPORTYBET_SHARE_UPSTREAM_UNAVAILABLE');
  assert.match(failedShare.message,/regional proxy or direct endpoint/);
  assert.deepEqual(failedShareRequests.map(u=>u.origin),[PROXY,SPORTYBET]);

  console.log('SportyBet booking resilience: PASS (bounded catalog paging, regional share POST fallback, JSON-safe failures, and exact market-225 pair).');
} finally { globalThis.fetch=originalFetch; }
