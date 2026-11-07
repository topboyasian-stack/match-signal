import assert from 'node:assert/strict';
import { upstream, collectEvents, collectBasketballEvents, requestSportyBetShare, nbaTotalsReleaseQualified, onRequest } from '../functions/api/sportybet-booking.js';
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

  const basketballKickoff = Date.now() + 3600000;
  const sportPayload={bizCode:10000,data:[{
    eventId:'sr:match:booking-feed-test',tournamentId:'sr:tournament:132',homeTeamName:'Fixture Home',awayTeamName:'Fixture Away',estimateStartTime:basketballKickoff,matchStatus:'Not start',
    markets:[{id:'225',desc:'Full Game Total incl. OT',specifier:'total=220.5',status:'0',outcomes:[
      {id:'over',desc:'Over 220.5',odds:1.93,isActive:1},{id:'under',desc:'Under 220.5',odds:1.88,isActive:1}
    ]}]
  }]};
  const requested=[];
  globalThis.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url);requested.push(url);
    assert.ok(url.origin===SPORTYBET||url.origin===PROXY,'No self-fetch to Match Signal Pages is allowed');
    return jsonResponse(sportPayload);
  };
  const basketballTargetLeg = {
    event_id:'espn:source-basketball-fixture',
    sportybet_event_id:'sr:match:old-provider-basketball-id',
    player_1:'Fixture Home',
    player_2:'Fixture Away',
    start_time:new Date(basketballKickoff).toISOString()
  };
  const found=await collectBasketballEvents(
    {request:new Request('https://match-signal.pages.dev/api/sportybet-booking')},
    new Set([basketballTargetLeg.event_id,basketballTargetLeg.sportybet_event_id]),
    168,
    [basketballTargetLeg]
  );
  const event=found.get('sr:match:booking-feed-test');assert.ok(event,'basketball fixture must resolve by participants/time when provider ID changes');
  const market=event.markets.find(m=>String(m.id)==='225');assert.ok(market);
  assert.equal(market.specifier,'total=220.5');
  assert.deepEqual(market.outcomes.map(o=>Number(o.odds)).sort((a,b)=>a-b),[1.88,1.93]);
  assert.ok(requested.length>0&&requested.every(u=>u.origin===SPORTYBET||u.origin===PROXY));

  // The independent NBA gate must fail closed on absent/invalid release evidence.
  // Full NBA booking rejection is covered by nba-ticket-guard-tests.yml; this
  // generic catalogue resilience test does not mock the four remote evidence files.
  assert.equal(nbaTotalsReleaseQualified({}, {}), false,
    'missing independent NBA evidence must never qualify ticket booking');

  // Already-started selections are rejected explicitly and never trigger an
  // upcoming-catalogue lookup or a share-code request.
  const staleCatalogueRequests=[];
  globalThis.fetch=async input=>{
    staleCatalogueRequests.push(new URL(typeof input==='string'?input:input.url));
    throw new Error('A started fixture must not be queried as upcoming.');
  };
  const staleStart=new Date(Date.now()-60*60*1000).toISOString();
  const staleTicketResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {event_id:'stale-malaga',sportybet_event_id:'old-malaga',sport:'football',market:'winner',pick:'p1',start_time:staleStart,player_1:'Málaga',player_2:'Racing Santander',match:'Málaga vs Racing Santander'},
      {event_id:'stale-dortmund',sportybet_event_id:'old-dortmund',sport:'football',market:'winner',pick:'p1',start_time:staleStart,player_1:'Borussia Dortmund',player_2:'SV Elversberg',match:'Borussia Dortmund vs SV Elversberg'}
    ]})
  })});
  const staleTicketPayload=await staleTicketResponse.json();
  assert.equal(staleTicketResponse.status,409,JSON.stringify(staleTicketPayload));
  assert.equal(staleTicketPayload.booking_code_withheld,true);
  assert.ok(staleTicketPayload.validation.every(x=>/start time has passed/.test(x.reason)));
  assert.equal(staleCatalogueRequests.length,0,'already-started fixtures must not be looked up or sent to SportyBet share');

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

  // The scheduled football market collector scans up to 20 PC catalogue
  // pages, but manual booking previously stopped at page 5. Put both U21
  // fixtures on page 12 to prove the manual lookup reaches the same catalogue
  // depth before returning "Event is no longer present".
  const u21KickoffA = Date.now() + 4 * 60 * 60 * 1000;
  const u21KickoffB = Date.now() + 9.5 * 60 * 60 * 1000;
  const u21Legs = [
    {
      event_id: 'espn:millwall-cardiff-prediction',
      sportybet_event_id: 'sr:match:old-millwall-cardiff-id',
      player_1: 'Millwall U21',
      player_2: 'Cardiff City U21',
      market: 'total', pick: 'over', line: 2.5, market_id: '18',
      start_time: new Date(u21KickoffA).toISOString()
    },
    {
      event_id: 'espn:swansea-bristol-prediction',
      sportybet_event_id: 'sr:match:old-swansea-bristol-id',
      player_1: 'Swansea City U21',
      player_2: 'Bristol City U21',
      market: 'total', pick: 'over', line: 2.5, market_id: '18',
      start_time: new Date(u21KickoffB).toISOString()
    }
  ];
  const unrelatedFullPage = Array.from({length:100},(_,i)=>({
    eventId:'sr:match:unrelated-u21-'+i,
    homeTeamName:'Unrelated Home '+i,
    awayTeamName:'Unrelated Away '+i,
    estimateStartTime:Date.now()+3600000,
    matchStatus:'Not start',
    markets:[]
  }));
  const u21CatalogueCalls = [];
  const u21CurrentEvents = [
    {
      eventId:'sr:match:current-millwall-cardiff',
      homeTeamName:'Millwall U21',
      awayTeamName:'Cardiff City U21',
      estimateStartTime:u21KickoffA,
      matchStatus:'Not start',
      markets:[{id:'18',desc:'Total Goals Over/Under',specifier:'total=2.5',status:'0',outcomes:[
        {id:'millwall-over-2-5',desc:'Over 2.5',odds:1.91,isActive:1},
        {id:'millwall-under-2-5',desc:'Under 2.5',odds:1.87,isActive:1}
      ]}]
    },
    {
      eventId:'sr:match:current-swansea-bristol',
      homeTeamName:'Swansea City U21',
      awayTeamName:'Bristol City U21',
      estimateStartTime:u21KickoffB,
      matchStatus:'Not start',
      markets:[{id:'18',desc:'Total Goals Over/Under',specifier:'total=2.5',status:'0',outcomes:[
        {id:'swansea-over-2-5',desc:'Over 2.5',odds:1.88,isActive:1},
        {id:'swansea-under-2-5',desc:'Under 2.5',odds:1.92,isActive:1}
      ]}]
    }
  ];
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname==='/api/ng/orders/share') {
      return jsonResponse({bizCode:10000,data:{
        shareCode:'U21-CATALOGUE-FALLBACK-OK',
        outcomes:[{odds:1.91},{odds:1.88}]
      }});
    }
    if(url.pathname.endsWith('/pcUpcomingEvents')&&url.searchParams.get('sportId')==='sr:sport:1') {
      const page=Number(url.searchParams.get('pageNum'));
      u21CatalogueCalls.push({source:'pc',page});
      const events=page===12?u21CurrentEvents:unrelatedFullPage;
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'PC catalogue page',events}]}});
    }
    if(url.pathname.endsWith('/wapConfigurableUpcomingEvents')&&url.searchParams.get('sportId')==='sr:sport:1') {
      u21CatalogueCalls.push({source:'wap',page:Number(url.searchParams.get('pageNum'))});
      return jsonResponse({bizCode:10000,data:[]});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const u21TicketResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {
        event_id:u21Legs[0].event_id,sportybet_event_id:u21Legs[0].sportybet_event_id,
        sport:'football',market:'total',pick:'over',line:2.5,market_id:'18',
        start_time:u21Legs[0].start_time,player_1:u21Legs[0].player_1,player_2:u21Legs[0].player_2,
        match:'Millwall U21 vs Cardiff City U21'
      },
      {
        event_id:u21Legs[1].event_id,sportybet_event_id:u21Legs[1].sportybet_event_id,
        sport:'football',market:'total',pick:'over',line:2.5,market_id:'18',
        start_time:u21Legs[1].start_time,player_1:u21Legs[1].player_1,player_2:u21Legs[1].player_2,
        match:'Swansea City U21 vs Bristol City U21'
      }
    ]})
  })});
  const u21TicketPayload=await u21TicketResponse.json();
  assert.equal(u21TicketResponse.status,200,JSON.stringify(u21TicketPayload));
  assert.equal(u21TicketPayload.ok,true,JSON.stringify(u21TicketPayload));
  assert.equal(u21TicketPayload.booking_code,'U21-CATALOGUE-FALLBACK-OK');
  assert.equal(u21TicketPayload.selection_count,2);
  const scannedPcPages=u21CatalogueCalls.filter(x=>x.source==='pc').map(x=>x.page).sort((a,b)=>a-b);
  assert.ok(scannedPcPages.includes(12),
    'the manual booking lookup must reach page 12, matching the 20-page production football market collector');
  assert.ok(scannedPcPages.includes(1)&&scannedPcPages.includes(11));
  assert.equal(u21CatalogueCalls.filter(x=>x.source==='wap').length,0,
    'the exact U21 fixtures were found in the production PC catalogue before WAP fallback');
  assert.equal(u21TicketPayload.selections.length,2);
  assert.ok(u21TicketPayload.selections.every(row=>row.ok===true));
  assert.deepEqual(u21TicketPayload.selections.map(row=>row.resolved_by),[
    'fixture_participants_time','fixture_participants_time'
  ]);
  assert.deepEqual(u21TicketPayload.selections.map(row=>row.market_id),['18','18']);
  assert.deepEqual(u21TicketPayload.selections.map(row=>row.outcome_id),[
    'millwall-over-2-5','swansea-over-2-5'
  ]);

  // The configurable WAP catalogue remains a safe fallback when the PC
  // source is empty or unavailable.
  const wapFallbackCalls=[];
  globalThis.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname.endsWith('/pcUpcomingEvents')&&url.searchParams.get('sportId')==='sr:sport:1'){
      wapFallbackCalls.push('pc');
      return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    }
    if(url.pathname.endsWith('/wapConfigurableUpcomingEvents')&&url.searchParams.get('sportId')==='sr:sport:1'){
      wapFallbackCalls.push('wap');
      return jsonResponse({bizCode:10000,data:u21CurrentEvents});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const wapFallbackFound=await collectEvents({
    sportId:'sr:sport:1',marketId:'1,18',timeline:168,pageSize:100,
    maxPages:20,
    primaryPath:'/api/ng/factsCenter/pcUpcomingEvents',
    fallbackPath:'/api/ng/factsCenter/wapConfigurableUpcomingEvents'
  },new Set(u21Legs.map(leg=>leg.event_id)),u21Legs);
  assert.equal(wapFallbackFound.size,2,'WAP must recover both fixtures when the PC catalogue is empty');
  assert.deepEqual(wapFallbackCalls,['pc','wap'],'PC should be searched first and WAP used only as fallback');

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
  assert.ok(futureTicketPayload.selections.every(row => row.ok === true));


  // Regression on the four real football catalogue aliases which previously
  // all returned "Event is no longer present" despite current market evidence:
  // Malaga CF, SV 07 Elversberg, Paderborn, and Stuttgart are valid aliases for
  // the short names shown by the selected Match Signal legs.
  const staleIdKickoff = Date.now() + 6 * 60 * 60 * 1000;
  const staleIdKickoffIso = new Date(staleIdKickoff).toISOString();
  const staleIdLegs = [
    { event_id:'401882812', sportybet_event_id:'sr:match:stale-malaga-id', sport:'football', market:'total', pick:'over', line:1.5, market_id:'18', start_time:staleIdKickoffIso, player_1:'Málaga', player_2:'Racing Santander', match:'Málaga vs Racing Santander' },
    { event_id:'401884745', sportybet_event_id:'sr:match:stale-dortmund-id', sport:'football', market:'total', pick:'under', line:5.5, market_id:'18', start_time:staleIdKickoffIso, player_1:'Borussia Dortmund', player_2:'SV Elversberg', match:'Borussia Dortmund vs SV Elversberg' },
    { event_id:'401884737', sportybet_event_id:'sr:match:stale-paderborn-id', sport:'football', market:'total', pick:'under', line:5.5, market_id:'18', start_time:staleIdKickoffIso, player_1:'SC Paderborn 07', player_2:'Eintracht Frankfurt', match:'SC Paderborn 07 vs Eintracht Frankfurt' },
    { event_id:'401884743', sportybet_event_id:'sr:match:stale-stuttgart-id', sport:'football', market:'total', pick:'under', line:5.5, market_id:'18', start_time:staleIdKickoffIso, player_1:'VfB Stuttgart', player_2:'Werder Bremen', match:'VfB Stuttgart vs Werder Bremen' }
  ];
  const totalMarket = (line, prefix) => ({
    id:'18', desc:'Total Goals Over/Under', specifier:'total=' + line, status:'0',
    outcomes:[
      {id:prefix+'-over',desc:'Over ' + line,odds:1.21,isActive:1},
      {id:prefix+'-under',desc:'Under ' + line,odds:1.17,isActive:1}
    ]
  });
  const makeStaleIdFixture = (eventId, homeTeamName, awayTeamName, market) => ({
    eventId, homeTeamName, awayTeamName,
    estimateStartTime:staleIdKickoff,
    matchStatus:'Not start',
    markets:[market]
  });
  const staleProviderPage = staleIdLegs.map((leg,index) => makeStaleIdFixture(
    leg.sportybet_event_id,
    'Unrelated Home ' + index,
    'Unrelated Away ' + index,
    totalMarket(leg.line,'stale-'+index)
  ));
  while (staleProviderPage.length < 100) {
    const index = staleProviderPage.length;
    staleProviderPage.push(makeStaleIdFixture(
      'sr:match:stale-page-filler-' + index,
      'Catalogue Filler Home ' + index,
      'Catalogue Filler Away ' + index,
      {id:'1',desc:'3 Way',status:'0',outcomes:[]}
    ));
  }
  const currentFixturePage = [
    makeStaleIdFixture('sr:match:72478694','Malaga CF','Racing Santander',totalMarket(1.5,'malaga')),
    makeStaleIdFixture('sr:match:72513292','Borussia Dortmund','SV 07 Elversberg',totalMarket(5.5,'dortmund')),
    makeStaleIdFixture('sr:match:72513308','Paderborn','Eintracht Frankfurt',totalMarket(5.5,'paderborn')),
    makeStaleIdFixture('sr:match:72513296','Stuttgart','Werder Bremen',totalMarket(5.5,'stuttgart'))
  ];
  const staleIdPageRequests = [];
  const staleIdShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      staleIdShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'FOOTBALL-CLUB-ALIAS-RECOVERY-OK',
        outcomes:[{odds:1.21},{odds:1.17},{odds:1.13},{odds:1.19}]
      }});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') &&
        url.searchParams.get('sportId') === 'sr:sport:1') {
      const pageNum = Number(url.searchParams.get('pageNum') || 1);
      staleIdPageRequests.push(pageNum);
      const events = pageNum === 1 ? staleProviderPage : pageNum === 2 ? currentFixturePage : [];
      return jsonResponse({bizCode:10000,data:{
        tournaments:[{name:'Football club alias regression',events}]
      }});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const staleIdTicketResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:staleIdLegs})
  })});
  const staleIdTicketPayload = await staleIdTicketResponse.json();
  assert.equal(staleIdTicketResponse.status,200,JSON.stringify(staleIdTicketPayload));
  assert.equal(staleIdTicketPayload.booking_code,'FOOTBALL-CLUB-ALIAS-RECOVERY-OK');
  assert.ok(staleIdPageRequests.includes(2),'catalogue scan must continue past unrelated stale provider IDs to the current fixtures');
  assert.equal(staleIdShareRequests.length,1,'share generation happens only after all four current fixtures and markets validate');
  assert.equal(staleIdShareRequests[0].selections.length,4);
  assert.deepEqual(staleIdTicketPayload.selections.map(row=>row.resolved_event_id).sort(),[
    'sr:match:72478694','sr:match:72513292','sr:match:72513296','sr:match:72513308'
  ]);
  assert.ok(staleIdTicketPayload.selections.every(row=>row.ok===true));
  console.log('SportyBet booking resilience: PASS (bounded paging, stale-ID recovery, share fallback, exact market-225 pair, and Football/Tennis/eFootball mixed ticket).');
} finally { globalThis.fetch=originalFetch; }
