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

  // End-to-end manual slip regression: ordinary Football + Tennis must still work
  // when a qualified product-scoped eFootball O/U leg is included.
  const kickoff = Date.now() + 3 * 60 * 60 * 1000;
  const kickoffIso = new Date(kickoff).toISOString();
  const makeFixture = (eventId, homeTeamName, awayTeamName, market) => ({
    eventId, homeTeamName, awayTeamName, estimateStartTime: kickoff,
    matchStatus: 'Not start', markets: [market]
  });
  const mixedCatalog = {
    'sr:sport:1': [makeFixture('sr:match:fb-ticket-test', 'Home FC', 'Away FC', {
      id:'1', desc:'3 Way', status:'0', outcomes:[
        {id:'fb-home',desc:'Home FC',odds:1.82,isActive:1},
        {id:'fb-draw',desc:'Draw',odds:3.4,isActive:1},
        {id:'fb-away',desc:'Away FC',odds:4.4,isActive:1}
      ]
    })],
    'sr:sport:5': [makeFixture('sr:match:tennis-ticket-test', 'Player One', 'Player Two', {
      id:'186', desc:'Match Winner', status:'0', outcomes:[
        {id:'tennis-home',desc:'Player One',odds:1.71,isActive:1},
        {id:'tennis-away',desc:'Player Two',odds:2.1,isActive:1}
      ]
    })],
    'sr:sport:137': [makeFixture('sr:match:efootball-ticket-test', 'GT Home (Alpha)', 'GT Away (Beta)', {
      id:'18', desc:'Total Goals Over/Under', specifier:'total=2.5', status:'0',
      outcomes:[
        {id:'ef-over',desc:'Over 2.5',odds:1.9,isActive:1},
        {id:'ef-under',desc:'Under 2.5',odds:1.85,isActive:1}
      ]
    })]
  };
  const mixedShareRequests=[];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname==='/api/sportybet-virtual') return jsonResponse({ok:true,events:[]});
    if(url.pathname==='/api/ng/orders/share'){
      mixedShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'MIXED-EFOOTBALL-OK',
        shareURL:'https://www.sportybet.com/ng/?shareCode=MIXED-EFOOTBALL-OK',
        outcomes:[{odds:1.82},{odds:1.71},{odds:1.9}]
      }});
    }
    const sportId=url.searchParams.get('sportId');
    if(url.pathname.includes('UpcomingEvents')&&mixedCatalog[sportId]){
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Booking regression',events:mixedCatalog[sportId]}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const mixedResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {event_id:'prediction-fb-ticket-test',sportybet_event_id:'sr:match:fb-ticket-test',sport:'football',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Home FC',player_2:'Away FC',match:'Home FC vs Away FC'},
      {event_id:'prediction-tennis-ticket-test',sportybet_event_id:'sr:match:tennis-ticket-test',sport:'tennis',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Player One',player_2:'Player Two',match:'Player One vs Player Two'},
      {event_id:'sr:match:efootball-ticket-test',sportybet_event_id:'sr:match:efootball-ticket-test',sport:'efootball',product:'efootball_gt',market:'total',pick:'over',line:2.5,market_id:'18',model_qualified:false,start_time:kickoffIso,player_1:'GT Home (Alpha)',player_2:'GT Away (Beta)',match:'GT Home (Alpha) vs GT Away (Beta)'}
    ]})
  })});
  const mixedPayload=await mixedResponse.json();
  assert.equal(mixedResponse.status,200,JSON.stringify(mixedPayload));
  assert.equal(mixedPayload.ok,true,JSON.stringify(mixedPayload));
  assert.equal(mixedPayload.booking_code,'MIXED-EFOOTBALL-OK');
  assert.equal(mixedPayload.selection_count,3);
  assert.equal(mixedPayload.pre_excluded_count,0);
  assert.equal(mixedPayload.partial,false);
  assert.equal(mixedShareRequests.length,1);
  assert.equal(mixedShareRequests[0].selections.length,3,'the generated SportyBet request must contain all three sports');
  assert.ok(mixedPayload.selections.every(row=>row.ok===true),'each current fixture/market must be revalidated');
  // Manual Football/Tennis slips are also all-or-nothing. A missing leg must
  // prevent the share endpoint from being called at all.
  const savedTennisCatalogue = mixedCatalog['sr:sport:5'];
  mixedCatalog['sr:sport:5'] = [];
  const missingLegShareCalls=[];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname==='/api/ng/orders/share'){
      missingLegShareCalls.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{shareCode:'MUST-NOT-BE-REQUESTED'}});
    }
    const sportId=url.searchParams.get('sportId');
    if(url.pathname.includes('UpcomingEvents')&&mixedCatalog[sportId]){
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Booking regression',events:mixedCatalog[sportId]}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const missingLegResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {event_id:'prediction-fb-ticket-test',sportybet_event_id:'sr:match:fb-ticket-test',sport:'football',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Home FC',player_2:'Away FC',match:'Home FC vs Away FC'},
      {event_id:'prediction-tennis-missing',sportybet_event_id:'sr:match:tennis-missing',sport:'tennis',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Player One',player_2:'Player Two',match:'Player One vs Player Two'}
    ]})
  })});
  const missingLegPayload=await missingLegResponse.json();
  assert.equal(missingLegResponse.status,409,JSON.stringify(missingLegPayload));
  assert.equal(missingLegPayload.error,'MANUAL_TICKET_REJECTED_PARTIAL');
  assert.equal(missingLegPayload.booking_code_withheld,true);
  assert.equal(Boolean(missingLegPayload.booking_code),false);
  assert.equal(missingLegShareCalls.length,0,'a manual slip with any failed leg must not reach the share endpoint');
  mixedCatalog['sr:sport:5'] = savedTennisCatalogue;

  // Even when all legs revalidate, a provider response accepting only part of a
  // plain Football/Tennis ticket must not leak a reduced share code.
  const partialProviderCalls=[];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname==='/api/ng/orders/share'){
      partialProviderCalls.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'PARTIAL-FOOTBALL-TENNIS-MUST-BE-WITHHELD',
        outcomes:[{odds:1.82}]
      }});
    }
    const sportId=url.searchParams.get('sportId');
    if(url.pathname.includes('UpcomingEvents')&&mixedCatalog[sportId]){
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Booking regression',events:mixedCatalog[sportId]}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const providerPartialResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {event_id:'prediction-fb-ticket-test',sportybet_event_id:'sr:match:fb-ticket-test',sport:'football',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Home FC',player_2:'Away FC',match:'Home FC vs Away FC'},
      {event_id:'prediction-tennis-ticket-test',sportybet_event_id:'sr:match:tennis-ticket-test',sport:'tennis',market:'winner',pick:'p1',start_time:kickoffIso,player_1:'Player One',player_2:'Player Two',match:'Player One vs Player Two'}
    ]})
  })});
  const providerPartialPayload=await providerPartialResponse.json();
  assert.equal(providerPartialResponse.status,409,JSON.stringify(providerPartialPayload));
  assert.equal(providerPartialPayload.error,'MANUAL_TICKET_REJECTED_PARTIAL');
  assert.equal(providerPartialPayload.booking_code_withheld,true);
  assert.equal(Boolean(providerPartialPayload.booking_code),false);
  assert.equal(partialProviderCalls.length,1);
  assert.equal(partialProviderCalls[0].selections.length,2);

  // Manual tickets must search beyond the seven-day default when their
  // selected fixtures are further ahead (the 19-day production regression).
  const futureNow = Date.now();
  const futureKickoff = futureNow + 19 * 24 * 60 * 60 * 1000 + 60 * 60 * 1000;
  const futureKickoffIso = new Date(futureKickoff).toISOString();
  const futureTimelineObserved = [];
  const futureShareRequests = [];
  const futureCatalog = [
    {
      eventId: 'sr:match:future-19d-home',
      homeTeamName: 'Future Home FC',
      awayTeamName: 'Future Away FC',
      estimateStartTime: futureKickoff,
      matchStatus: 'Not start',
      markets: [{ id: '1', desc: '3 Way', status: '0', outcomes: [
        { id: 'future-home', desc: 'Future Home FC', odds: 1.84, isActive: 1 },
        { id: 'future-draw', desc: 'Draw', odds: 3.4, isActive: 1 },
        { id: 'future-away', desc: 'Future Away FC', odds: 4.2, isActive: 1 }
      ] }]
    },
    {
      eventId: 'sr:match:future-19d-second',
      homeTeamName: 'Second Home FC',
      awayTeamName: 'Second Away FC',
      estimateStartTime: futureKickoff + 90 * 60 * 1000,
      matchStatus: 'Not start',
      markets: [{ id: '1', desc: '3 Way', status: '0', outcomes: [
        { id: 'second-home', desc: 'Second Home FC', odds: 1.92, isActive: 1 },
        { id: 'second-draw', desc: 'Draw', odds: 3.3, isActive: 1 },
        { id: 'second-away', desc: 'Second Away FC', odds: 3.9, isActive: 1 }
      ] }]
    }
  ];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      futureShareRequests.push(JSON.parse(options.body));
      return jsonResponse({ bizCode: 10000, data: {
        shareCode: 'FUTURE-19-DAY-LOOKAHEAD-OK',
        outcomes: [{ odds: 1.84 }, { odds: 1.92 }]
      } });
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') &&
        url.searchParams.get('sportId') === 'sr:sport:1') {
      futureTimelineObserved.push(Number(url.searchParams.get('timeline')));
      return jsonResponse({ bizCode: 10000, data: {
        tournaments: [{ name: 'Future booking regression', events: futureCatalog }]
      } });
    }
    return jsonResponse({ bizCode: 10000, data: { tournaments: [] } });
  };
  const futureTicketResponse = await onRequest({ request: new Request('https://match-signal.pages.dev/api/sportybet-booking', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'manual', manual_selections: [
      { event_id: 'prediction-future-19d-home', sportybet_event_id: 'sr:match:future-19d-home', sport: 'football', market: 'winner', pick: 'p1', start_time: futureKickoffIso, player_1: 'Future Home FC', player_2: 'Future Away FC', match: 'Future Home FC vs Future Away FC' },
      { event_id: 'prediction-future-19d-second', sportybet_event_id: 'sr:match:future-19d-second', sport: 'football', market: 'winner', pick: 'p1', start_time: new Date(futureKickoff + 90 * 60 * 1000).toISOString(), player_1: 'Second Home FC', player_2: 'Second Away FC', match: 'Second Home FC vs Second Away FC' }
    ] })
  }) });
  const futureTicketPayload = await futureTicketResponse.json();
  assert.equal(futureTicketResponse.status, 200, JSON.stringify(futureTicketPayload));
  assert.equal(futureTicketPayload.booking_code, 'FUTURE-19-DAY-LOOKAHEAD-OK');
  assert.ok(futureTimelineObserved.length > 0, 'future football catalogue must be queried');
  assert.ok(futureTimelineObserved.every(hours => hours >= 19 * 24 && hours <= 720),
    'manual football catalogue lookahead must cover the 19-day fixture horizon and stay within 30 days');
  assert.equal(futureShareRequests.length, 1, 'the share endpoint is called only after both future legs validate');
  assert.equal(futureShareRequests[0].selections.length, 2);
  assert.ok(futureTicketPayload.validation.every(row => row.ok === true));

  console.log('SportyBet booking resilience: PASS (bounded paging, share fallback, exact market-225 pair, and Football/Tennis/eFootball mixed ticket).');
} finally { globalThis.fetch=originalFetch; }
