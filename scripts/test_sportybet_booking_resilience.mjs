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

  // Manual shared tickets may include unqualified NBA legs when every leg passes
  // exact, current SportyBet market checks. This must not call model-release artifacts.
  const mixedBase = Date.now() + 6 * 60 * 60 * 1000;
  const mixedFixtures = [
    {id:'elche-betis',event_id:'espn:manual-elche-betis',provider_id:'sr:match:manual-elche-betis',sport:'football',market:'total',pick:'under',line:5.5,market_id:'18',player_1:'Elche',player_2:'Real Betis',match:'Elche vs Real Betis',start_ms:mixedBase,odds:1.09,over_odds:7.5,under_odds:1.09},
    {id:'sociedad-rayo',event_id:'espn:manual-sociedad-rayo',provider_id:'sr:match:manual-sociedad-rayo',sport:'football',market:'total',pick:'under',line:5.5,market_id:'18',player_1:'Real Sociedad',player_2:'Rayo Vallecano',match:'Real Sociedad vs Rayo Vallecano',start_ms:mixedBase+60*60*1000,odds:1.10,over_odds:7.2,under_odds:1.10},
    {id:'atletico-barcelona',event_id:'espn:manual-atletico-barcelona',provider_id:'sr:match:manual-atletico-barcelona',sport:'football',market:'total',pick:'under',line:5.5,market_id:'18',player_1:'Atlético Madrid',player_2:'Barcelona',match:'Atlético Madrid vs Barcelona',start_ms:mixedBase+2*60*60*1000,odds:1.21,over_odds:5.8,under_odds:1.21},
    {id:'warriors-magic',event_id:'espn:manual-warriors-magic',provider_id:'sr:match:manual-warriors-magic',sport:'basketball',market:'total',pick:'over',line:207.5,market_id:'225',player_1:'Golden State Warriors',player_2:'Orlando Magic',match:'Golden State Warriors vs Orlando Magic',start_ms:mixedBase+3*60*60*1000,odds:1.25,over_odds:1.25,under_odds:3.7},
    {id:'suns-rockets',event_id:'espn:manual-suns-rockets',provider_id:'sr:match:manual-suns-rockets',sport:'basketball',market:'total',pick:'over',line:215.5,market_id:'225',player_1:'Phoenix Suns',player_2:'Houston Rockets',match:'Phoenix Suns vs Houston Rockets',start_ms:mixedBase+4*60*60*1000,odds:1.42,over_odds:1.42,under_odds:2.8},
    {id:'trailblazers-spurs',event_id:'espn:manual-trailblazers-spurs',provider_id:'sr:match:manual-trailblazers-spurs',sport:'basketball',market:'total',pick:'over',line:216.5,market_id:'225',player_1:'Portland Trail Blazers',player_2:'San Antonio Spurs',match:'Portland Trail Blazers vs San Antonio Spurs',start_ms:mixedBase+5*60*60*1000,odds:1.26,over_odds:1.26,under_odds:3.2}
  ];
  function mixedEvent(fixture) {
    const basketball = fixture.sport === 'basketball';
    return {
      eventId:fixture.provider_id,
      tournamentId:basketball?'sr:tournament:132':'sr:tournament:manual-test',
      homeTeamName:fixture.player_1,
      awayTeamName:fixture.player_2,
      estimateStartTime:fixture.start_ms,
      matchStatus:'Not start',
      markets:[{
        id:fixture.market_id,
        desc:basketball?'Full Game Total incl. OT':'Total Goals Over/Under',
        specifier:'total='+fixture.line,
        status:'0',
        outcomes:[
          {id:'over-'+fixture.id,desc:'Over '+fixture.line,odds:fixture.over_odds,isActive:1},
          {id:'under-'+fixture.id,desc:'Under '+fixture.line,odds:fixture.under_odds,isActive:1}
        ]
      }]
    };
  }
  const mixedCalls = [];
  globalThis.fetch = async input => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    mixedCalls.push(url);
    if (url.hostname === 'raw.githubusercontent.com') {
      throw new Error('Manual booking must not load NBA model-release artifacts.');
    }
    if (url.pathname === '/api/ng/orders/share') {
      return jsonResponse({bizCode:10000,data:{
        shareCode:'MANUAL-MIXED-TICKET-OK',
        outcomes:mixedFixtures.map(fixture=>({odds:fixture.pick==='over'?fixture.over_odds:fixture.under_odds}))
      }});
    }
    if (/\/(?:pcUpcomingEvents|wapConfigurableUpcomingEvents)$/.test(url.pathname)) {
      const sportId = url.searchParams.get('sportId');
      const fixtures = sportId === 'sr:sport:1'
        ? mixedFixtures.filter(fixture=>fixture.sport==='football')
        : sportId === 'sr:sport:2'
          ? mixedFixtures.filter(fixture=>fixture.sport==='basketball')
          : [];
      return jsonResponse({bizCode:10000,data:fixtures.map(mixedEvent)});
    }
    throw new Error('Unexpected manual-ticket request: '+url.toString());
  };
  const mixedRequest = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:mixedFixtures.map(fixture=>({
      event_id:fixture.event_id,sportybet_event_id:fixture.provider_id,sport:fixture.sport,
      market:fixture.market,pick:fixture.pick,line:fixture.line,market_id:fixture.market_id,
      player_1:fixture.player_1,player_2:fixture.player_2,match:fixture.match,
      start_time:new Date(fixture.start_ms).toISOString(),model_qualified:false
    }))})
  })});
  const manualSixPayload = await mixedRequest.json();
  assert.equal(mixedRequest.status,200,JSON.stringify(manualSixPayload));
  assert.equal(manualSixPayload.ok,true,JSON.stringify(manualSixPayload));
  assert.equal(manualSixPayload.booking_code,'MANUAL-MIXED-TICKET-OK');
  assert.equal(manualSixPayload.initial_selection_count,6);
  assert.equal(manualSixPayload.selection_count,6);
  assert.equal(manualSixPayload.selections.length,6);
  assert.ok(manualSixPayload.selections.every(selection=>selection.ok===true));
  assert.equal(mixedCalls.some(url=>url.hostname==='raw.githubusercontent.com'),false,
    'Manual mixed-sport tickets must not require NBA model-release evidence.');
  assert.equal(mixedCalls.filter(url=>url.pathname==='/api/ng/orders/share').length,1,
    'A successful mixed ticket must request exactly one SportyBet share code.');

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

  // Direct current-event lookup: an existing SportyBet provider ID should
  // return the live event and exact markets in one request. Alias display names
  // must still pass participant, kickoff, line, active-side and price checks.
  const directKickoff = Date.now() + 6 * 60 * 60 * 1000;
  const directStart = new Date(directKickoff).toISOString();
  const directLegs = [
    {
      event_id:'prediction-direct-man-utd-psg',
      sportybet_event_id:'sr:match:direct-man-utd-psg',
      sport:'football',market:'total',pick:'over',line:3.5,market_id:'18',
      start_time:directStart,player_1:'Man Utd',player_2:'PSG',match:'Man Utd vs PSG'
    },
    {
      event_id:'prediction-direct-west-ham-wolves',
      sportybet_event_id:'sr:match:direct-west-ham-wolves',
      sport:'football',market:'total',pick:'under',line:2.5,market_id:'18',
      start_time:directStart,player_1:'West Ham',player_2:'Wolves',match:'West Ham vs Wolves'
    }
  ];
  const directEventDetails = new Map([
    ['sr:match:direct-man-utd-psg',{
      eventId:'sr:match:direct-man-utd-psg',
      estimateStartTime:directKickoff,
      matchStatus:'Not start',
      homeTeamName:'Manchester United',
      awayTeamName:'Paris Saint Germain',
      sport:{id:'sr:sport:1',category:{tournament:{name:'Direct Event Alias Regression'}}},
      markets:[{id:'18',desc:'Over/Under',specifier:'total=3.5',status:0,outcomes:[
        {id:'direct-man-over',desc:'Over 3.5',odds:1.88,isActive:1},
        {id:'direct-man-under',desc:'Under 3.5',odds:1.96,isActive:1}
      ]}]
    }],
    ['sr:match:direct-west-ham-wolves',{
      eventId:'sr:match:direct-west-ham-wolves',
      estimateStartTime:directKickoff,
      matchStatus:'Not start',
      homeTeamName:'West Ham United',
      awayTeamName:'Wolverhampton Wanderers',
      sport:{id:'sr:sport:1',category:{tournament:{name:'Direct Event Alias Regression'}}},
      markets:[{id:'18',desc:'Over/Under',specifier:'total=2.5',status:0,outcomes:[
        {id:'direct-west-over',desc:'Over 2.5',odds:2.05,isActive:1},
        {id:'direct-west-under',desc:'Under 2.5',odds:1.72,isActive:1}
      ]}]
    }]
  ]);
  const directLookups = [];
  const directCatalogueLookups = [];
  const directShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname.endsWith('/factsCenter/event')) {
      directLookups.push(url.searchParams.get('eventId'));
      const event = directEventDetails.get(String(url.searchParams.get('eventId')));
      return jsonResponse({bizCode:10000,data:event||{}});
    }
    if (/\/(?:pcUpcomingEvents|wapConfigurableUpcomingEvents)$/.test(url.pathname) || url.pathname==='/api/sportybet-virtual') {
      directCatalogueLookups.push(url.pathname);
      return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    }
    if (url.pathname==='/api/ng/orders/share') {
      directShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'DIRECT-EVENT-ALIAS-LOOKUP-OK',
        outcomes:[{odds:1.88},{odds:1.72}]
      }});
    }
    throw new Error('Unexpected direct-event lookup request: '+url.toString());
  };
  const directResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:directLegs})
  })});
  const directPayload = await directResponse.json();
  assert.equal(directResponse.status,200,JSON.stringify(directPayload));
  assert.equal(directPayload.booking_code,'DIRECT-EVENT-ALIAS-LOOKUP-OK');
  assert.equal(directPayload.fixture_matcher_version,'sportybet-alias-v1');
  assert.equal(directPayload.selection_count,2);
  assert.deepEqual(directLookups.sort(),[
    'sr:match:direct-man-utd-psg','sr:match:direct-west-ham-wolves'
  ]);
  assert.equal(directCatalogueLookups.length,0,'exact single-event matches must not trigger full catalogue paging');
  assert.equal(directShareRequests.length,1);
  assert.equal(directShareRequests[0].selections.length,2);
  assert.deepEqual(directPayload.selections.map(row=>row.resolved_by),[
    'sportybet_event_id','sportybet_event_id'
  ]);
  assert.deepEqual(directPayload.selections.map(row=>row.resolved_event_id),[
    'sr:match:direct-man-utd-psg','sr:match:direct-west-ham-wolves'
  ]);

  // Production Builder shape regression: eFootball GT totals are serialized
  // as sport=virtual + product=efootball_gt + market=virtual_total. The direct
  // event verifier must treat them as exact totals, not winner selections,
  // or it falls back to slow 20-page scans and times out the booking POST.
  const directVirtualKickoff = Date.now() + 6 * 60 * 60 * 1000;
  const directVirtualStart = new Date(directVirtualKickoff).toISOString();
  const directVirtualLegs = [
    {
      event_id:'sr:match:direct-gt-bayern-inter',
      sportybet_event_id:'sr:match:direct-gt-bayern-inter',
      sport:'virtual',product:'efootball_gt',market:'virtual_total',pick:'over',line:2.5,market_id:'18',
      start_time:directVirtualStart,player_1:'Bayern Munchen (Virtual_10)',player_2:'Inter Milan (Virtual_12)',
      match:'Bayern Munchen (Virtual_10) vs Inter Milan (Virtual_12)'
    },
    {
      event_id:'sr:match:direct-gt-psg-real',
      sportybet_event_id:'sr:match:direct-gt-psg-real',
      sport:'virtual',product:'efootball_gt',market:'virtual_total',pick:'under',line:3.5,market_id:'18',
      start_time:directVirtualStart,player_1:'Paris SG (Virtual_09)',player_2:'Real Madrid (Virtual_10)',
      match:'Paris SG (Virtual_09) vs Real Madrid (Virtual_10)'
    }
  ];
  const directVirtualDetails = new Map([
    ['sr:match:direct-gt-bayern-inter',{
      eventId:'sr:match:direct-gt-bayern-inter',estimateStartTime:directVirtualKickoff,matchStatus:'Not start',
      homeTeamName:'FC Bayern Munchen (Virtual_10)',awayTeamName:'Internazionale (Virtual_12)',
      sport:{id:'sr:sport:137',category:{tournament:{name:'eFootball GT'}}},
      markets:[{id:'18',desc:'Over/Under',specifier:'total=2.5',status:0,outcomes:[
        {id:'gt-bayern-over',desc:'Over 2.5',odds:1.91,isActive:1},
        {id:'gt-bayern-under',desc:'Under 2.5',odds:1.88,isActive:1}
      ]}]
    }],
    ['sr:match:direct-gt-psg-real',{
      eventId:'sr:match:direct-gt-psg-real',estimateStartTime:directVirtualKickoff,matchStatus:'Not start',
      homeTeamName:'Paris Saint-Germain (Virtual_09)',awayTeamName:'Real Madrid (Virtual_10)',
      sport:{id:'sr:sport:137',category:{tournament:{name:'eFootball GT'}}},
      markets:[{id:'18',desc:'Over/Under',specifier:'total=3.5',status:0,outcomes:[
        {id:'gt-psg-over',desc:'Over 3.5',odds:1.97,isActive:1},
        {id:'gt-psg-under',desc:'Under 3.5',odds:1.81,isActive:1}
      ]}]
    }]
  ]);
  const directVirtualCalls = [];
  const directVirtualShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname.endsWith('/factsCenter/event')) {
      directVirtualCalls.push({eventId:url.searchParams.get('eventId'),origin:url.origin});
      const event = directVirtualDetails.get(String(url.searchParams.get('eventId')));
      return jsonResponse({bizCode:10000,data:event||{}});
    }
    if (/\/(?:pcUpcomingEvents|wapConfigurableUpcomingEvents)$/.test(url.pathname) || url.pathname==='/api/sportybet-virtual') {
      directCatalogueLookups.push('virtual_total:'+url.pathname);
      return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    }
    if (url.pathname==='/api/ng/orders/share') {
      directVirtualShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'EFOOTBALL-VIRTUAL-TOTAL-DIRECT-LOOKUP-OK',
        outcomes:[{odds:1.91},{odds:1.81}]
      }});
    }
    throw new Error('Unexpected virtual-total direct lookup request: '+url.toString());
  };
  const directVirtualResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:directVirtualLegs})
  })});
  const directVirtualPayload = await directVirtualResponse.json();
  assert.equal(directVirtualResponse.status,200,JSON.stringify(directVirtualPayload));
  assert.equal(directVirtualPayload.booking_code,'EFOOTBALL-VIRTUAL-TOTAL-DIRECT-LOOKUP-OK');
  assert.equal(directVirtualPayload.fixture_matcher_version,'sportybet-alias-v1');
  assert.equal(directVirtualPayload.selection_count,2);
  assert.deepEqual(directVirtualCalls.map(item=>item.eventId).sort(),[
    'sr:match:direct-gt-bayern-inter','sr:match:direct-gt-psg-real'
  ]);
  assert.equal(directCatalogueLookups.length,0,'valid virtual_total direct matches must not fall back to broad catalogue scans');
  assert.equal(directVirtualShareRequests.length,1);
  assert.deepEqual(directVirtualShareRequests[0].selections.map(s=>s.marketId),['18','18']);
  assert.deepEqual(directVirtualPayload.selections.map(row=>row.resolved_by),[
    'sportybet_event_id','sportybet_event_id'
  ]);

  // Permanent display-name alias regression: current SportyBet IDs and labels
  // differ from the slip, but the fixture pair + kickoff + exact live total must
  // resolve before a share request is allowed.
  const aliasKickoff = Date.now() + 6 * 60 * 60 * 1000;
  const aliasStart = new Date(aliasKickoff).toISOString();
  const aliasFixtures = [
    {
      event_id:'prediction-man-utd-psg',
      sportybet_event_id:'sr:match:old-man-utd-psg',
      sport:'football',market:'total',pick:'over',line:3.5,market_id:'18',
      start_time:aliasStart,player_1:'Man Utd',player_2:'PSG',match:'Man Utd vs PSG'
    },
    {
      event_id:'prediction-west-ham-wolves',
      sportybet_event_id:'sr:match:old-west-ham-wolves',
      sport:'football',market:'total',pick:'under',line:2.5,market_id:'18',
      start_time:aliasStart,player_1:'West Ham',player_2:'Wolves',match:'West Ham vs Wolves'
    }
  ];
  const staleIdWrongMarket = makeStaleIdFixture(
    'sr:match:old-man-utd-psg','Manchester United','Paris Saint Germain',{
      id:'1',desc:'3 Way',status:'0',outcomes:[
        {id:'old-home',desc:'Manchester United',odds:1.8,isActive:1},
        {id:'old-draw',desc:'Draw',odds:3.4,isActive:1},
        {id:'old-away',desc:'Paris Saint Germain',odds:4.1,isActive:1}
      ]
    }
  );
  const aliasCatalogue = [
    staleIdWrongMarket,
    makeStaleIdFixture('sr:match:current-man-utd-psg','Manchester United','Paris Saint Germain',totalMarket(3.5,'alias-man-utd')),
    makeStaleIdFixture('sr:match:current-west-ham-wolves','West Ham United','Wolverhampton Wanderers',totalMarket(2.5,'alias-west-ham'))
  ];
  const aliasShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      aliasShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'FOOTBALL-DISPLAY-ALIAS-RECOVERY-OK',
        outcomes:[{odds:1.22},{odds:1.28}]
      }});
    }
    if (url.pathname.endsWith('/factsCenter/event')) {
      // The old provider ID still exists, but its details response exposes
      // only a winner market. The current exact total must be found by alias.
      const eventId = String(url.searchParams.get('eventId')||'');
      return jsonResponse({bizCode:10000,data:eventId==='sr:match:old-man-utd-psg'
        ? aliasCatalogue[0]
        : {}});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') && url.searchParams.get('sportId') === 'sr:sport:1') {
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Club alias regression',events:aliasCatalogue}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const aliasResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:aliasFixtures})
  })});
  const aliasPayload = await aliasResponse.json();
  assert.equal(aliasResponse.status,200,JSON.stringify(aliasPayload));
  assert.equal(aliasPayload.booking_code,'FOOTBALL-DISPLAY-ALIAS-RECOVERY-OK');
  assert.equal(aliasPayload.selection_count,2);
  assert.equal(aliasPayload.fixture_matcher_version,'sportybet-alias-v1');
  assert.deepEqual(aliasPayload.selections.map(row=>row.resolved_event_id),[
    'sr:match:current-man-utd-psg','sr:match:current-west-ham-wolves'
  ]);
  assert.deepEqual(aliasPayload.selections.map(row=>row.resolved_by),[
    'fixture_participants_time','fixture_participants_time'
  ]);
  assert.equal(aliasShareRequests.length,1);
  assert.equal(aliasShareRequests[0].selections.length,2);

  // Tennis player formatting regression: SportyBet can display surname-first
  // names with initials while the prediction stores full first+last names.
  const tennisAliasLegs = [
    {
      event_id:'prediction-djokovic-sinner',sportybet_event_id:'sr:match:old-djokovic-sinner',
      sport:'tennis',market:'winner',pick:'p1',market_id:'186',
      start_time:aliasStart,player_1:'Novak Djokovic',player_2:'Jannik Sinner',
      match:'Novak Djokovic vs Jannik Sinner'
    },
    {
      event_id:'prediction-sabalenka-gauff',sportybet_event_id:'sr:match:old-sabalenka-gauff',
      sport:'tennis',market:'winner',pick:'p2',market_id:'186',
      start_time:aliasStart,player_1:'Aryna Sabalenka',player_2:'Coco Gauff',
      match:'Aryna Sabalenka vs Coco Gauff'
    }
  ];
  const tennisAliasCatalogue = [
    makeStaleIdFixture('sr:match:current-djokovic-sinner','Djokovic N.','Sinner J.',{
      id:'186',desc:'Match Winner',status:'0',outcomes:[
        {id:'djokovic-home',desc:'Djokovic N.',odds:1.73,isActive:1},
        {id:'sinner-away',desc:'Sinner J.',odds:2.12,isActive:1}
      ]
    }),
    makeStaleIdFixture('sr:match:current-sabalenka-gauff','Sabalenka A.','Gauff C.',{
      id:'186',desc:'Match Winner',status:'0',outcomes:[
        {id:'sabalenka-home',desc:'Sabalenka A.',odds:1.66,isActive:1},
        {id:'gauff-away',desc:'Gauff C.',odds:2.25,isActive:1}
      ]
    })
  ];
  const tennisAliasShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      tennisAliasShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'TENNIS-SURNAME-FIRST-ALIAS-OK',
        outcomes:[{odds:1.73},{odds:2.25}]
      }});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') && url.searchParams.get('sportId') === 'sr:sport:5') {
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Tennis name-order regression',events:tennisAliasCatalogue}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const tennisAliasResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:tennisAliasLegs})
  })});
  const tennisAliasPayload = await tennisAliasResponse.json();
  assert.equal(tennisAliasResponse.status,200,JSON.stringify(tennisAliasPayload));
  assert.equal(tennisAliasPayload.booking_code,'TENNIS-SURNAME-FIRST-ALIAS-OK');
  assert.equal(tennisAliasPayload.selection_count,2);
  assert.equal(tennisAliasPayload.fixture_matcher_version,'sportybet-alias-v1');
  assert.deepEqual(tennisAliasPayload.selections.map(row=>row.resolved_event_id),[
    'sr:match:current-djokovic-sinner','sr:match:current-sabalenka-gauff'
  ]);
  assert.deepEqual(tennisAliasPayload.selections.map(row=>row.outcome_id),[
    'djokovic-home','gauff-away'
  ]);
  assert.equal(tennisAliasShareRequests.length,1);
  assert.equal(tennisAliasShareRequests[0].selections.length,2);

  // eFootball must also resolve a new provider event ID through the normalized
  // live feed, using club aliases while preserving the Virtual player slot.
  const virtualAliasLeg = {
    event_id:'sr:match:old-gt-bayern-inter',
    sportybet_event_id:'sr:match:old-gt-bayern-inter',
    sport:'efootball',product:'efootball_gt',market:'total',pick:'over',line:2.5,market_id:'18',
    start_time:aliasStart,player_1:'Bayern Munich (Virtual_10)',player_2:'Inter Milan (Virtual_12)',
    match:'Bayern Munich (Virtual_10) vs Inter Milan (Virtual_12)',model_qualified:false
  };
  const virtualAliasEvent = {
    event_id:'sr:match:current-gt-bayern-inter',
    team_1:'FC Bayern Munchen (Virtual_10)',
    team_2:'Internazionale (Virtual_12)',
    start_time_ms:aliasKickoff,
    match_status:'Not start',
    competition:'eFootball GT',
    markets:[{
      id:'18',name:'Total Goals Over/Under',specifier:'total=2.5',line:2.5,status:'0',
      outcomes:[
        {id:'gt-bayern-over',name:'Over 2.5',odds:1.91,active:true},
        {id:'gt-bayern-under',name:'Under 2.5',odds:1.85,active:true}
      ]
    }]
  };
  const virtualAliasShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      virtualAliasShareRequests.push(JSON.parse(options.body));
      return jsonResponse({bizCode:10000,data:{
        shareCode:'EFOOTBALL-ALIAS-AND-NEW-ID-OK',
        outcomes:[{odds:1.91},{odds:1.22}]
      }});
    }
    if (url.pathname === '/api/sportybet-virtual') {
      return jsonResponse({ok:true,events:[virtualAliasEvent]});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') && url.searchParams.get('sportId') === 'sr:sport:137') {
      // The catalogue has no event under the old ID; the normalized feed has
      // the same open fixture under its current provider ID.
      return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') && url.searchParams.get('sportId') === 'sr:sport:1') {
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Club alias regression',events:[aliasCatalogue[1]]}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const virtualAliasResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      aliasFixtures[0],
      virtualAliasLeg
    ]})
  })});
  const virtualAliasPayload = await virtualAliasResponse.json();
  assert.equal(virtualAliasResponse.status,200,JSON.stringify(virtualAliasPayload));
  assert.equal(virtualAliasPayload.booking_code,'EFOOTBALL-ALIAS-AND-NEW-ID-OK');
  assert.equal(virtualAliasPayload.selection_count,2);
  assert.equal(virtualAliasPayload.fixture_matcher_version,'sportybet-alias-v1');
  const virtualAliasValidation = virtualAliasPayload.selections.find(
    row=>row.event_id===virtualAliasLeg.event_id
  );
  assert.equal(virtualAliasValidation?.resolved_event_id,'sr:match:current-gt-bayern-inter');
  assert.equal(virtualAliasValidation?.resolved_by,'fixture_participants_time');
  assert.equal(virtualAliasShareRequests.length,1);
  assert.ok(virtualAliasShareRequests[0].selections.some(row=>row.eventId==='sr:match:current-gt-bayern-inter'));

  // Age-group identity must never be collapsed into the first team by an alias.
  const ageGroupDoesNotMatch = [];
  globalThis.fetch = async input => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      ageGroupDoesNotMatch.push('share');
      return jsonResponse({bizCode:10000,data:{shareCode:'MUST-NOT-BE-CREATED'}});
    }
    if (url.pathname.endsWith('/pcUpcomingEvents') && url.searchParams.get('sportId') === 'sr:sport:1') {
      return jsonResponse({bizCode:10000,data:{tournaments:[{name:'Age group safeguard',events:[
        makeStaleIdFixture('sr:match:first-team-man-utd','Manchester United','Paris Saint Germain',totalMarket(2.5,'first-team')),
        aliasCatalogue[1]
      ]}]}});
    }
    return jsonResponse({bizCode:10000,data:{tournaments:[]}});
  };
  const ageGroupResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {
        event_id:'prediction-man-utd-u21',sportybet_event_id:'sr:match:old-man-utd-u21',
        sport:'football',market:'total',pick:'over',line:2.5,market_id:'18',
        start_time:aliasStart,player_1:'Man Utd U21',player_2:'PSG U21',match:'Man Utd U21 vs PSG U21'
      },
      aliasFixtures[0]
    ]})
  })});
  const ageGroupPayload = await ageGroupResponse.json();
  assert.equal(ageGroupResponse.status,409,JSON.stringify(ageGroupPayload));
  assert.equal(ageGroupPayload.booking_code_withheld,true);
  assert.ok(ageGroupPayload.validation.some(row=>row.event_id==='prediction-man-utd-u21'&&row.ok===false));
  assert.equal(ageGroupDoesNotMatch.length,0,'a first-team alias must never satisfy an U21 ticket leg');

  // Tennis Set 1 and Set 2 must resolve to distinct market-202 setnr
  // specifiers and exact player outcome IDs on the current provider event.
  const tennisSetStart = Date.now() + 5 * 60 * 60 * 1000;
  const tennisSetFixtures = [
    {
      event_id: 'tennis-source-set-one',
      sportybet_event_id: 'sr:match:tennis-set-one',
      sport: 'tennis', market: 'set_winner', set_number: 1, market_id: '202', pick: 'p1',
      player_1: 'Alice Alpha', player_2: 'Bruno Beta',
      match: 'Alice Alpha vs Bruno Beta', start_time: new Date(tennisSetStart).toISOString()
    },
    {
      event_id: 'tennis-source-set-two',
      sportybet_event_id: 'sr:match:tennis-set-two',
      sport: 'tennis', market: 'set_winner', set_number: 2, market_id: '202', pick: 'p2',
      player_1: 'Carla Gamma', player_2: 'Diego Delta',
      match: 'Carla Gamma vs Diego Delta', start_time: new Date(tennisSetStart + 60 * 60 * 1000).toISOString()
    }
  ];
  const tennisCurrentEvents = new Map([
    ['sr:match:tennis-set-one', {
      eventId: 'sr:match:tennis-set-one', homeTeamName: 'Alice Alpha', awayTeamName: 'Bruno Beta',
      estimateStartTime: tennisSetStart, matchStatus: 'Not start',
      markets: [{id:'202',desc:'1st Set Winner',specifier:'setnr=1',status:'0',outcomes:[
        {id:'tennis-s1-alice',desc:'Alice Alpha',odds:1.82,isActive:1},
        {id:'tennis-s1-bruno',desc:'Bruno Beta',odds:2.02,isActive:1}
      ]}]
    }],
    ['sr:match:tennis-set-two', {
      eventId: 'sr:match:tennis-set-two', homeTeamName: 'Carla Gamma', awayTeamName: 'Diego Delta',
      estimateStartTime: tennisSetStart + 60 * 60 * 1000, matchStatus: 'Not start',
      markets: [{id:'202',desc:'2nd Set Winner',specifier:'setnr=2',status:'0',outcomes:[
        {id:'tennis-s2-carla',desc:'Carla Gamma',odds:1.86,isActive:1},
        {id:'tennis-s2-diego',desc:'Diego Delta',odds:1.98,isActive:1}
      ]}]
    }]
  ]);
  const tennisShareRequests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      tennisShareRequests.push(JSON.parse(String(options.body || '{}')));
      return jsonResponse({bizCode:10000,data:{shareCode:'TENNIS-SET-SCOPES-EXACT',outcomes:[{odds:1.82},{odds:1.98}]}});
    }
    if (url.pathname === '/api/ng/factsCenter/event') {
      const eventId = String(url.searchParams.get('eventId') || '');
      const event = tennisCurrentEvents.get(eventId);
      assert.ok(event, 'Only the two known current tennis events should be requested');
      return jsonResponse({bizCode:10000,data:{event}});
    }
    throw new Error('Unexpected tennis set-winner booking request: ' + url.toString());
  };
  const tennisSetResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:tennisSetFixtures})
  })});
  const tennisSetPayload = await tennisSetResponse.json();
  assert.equal(tennisSetResponse.status,200,JSON.stringify(tennisSetPayload));
  assert.equal(tennisSetPayload.ok,true,JSON.stringify(tennisSetPayload));
  assert.equal(tennisSetPayload.booking_code,'TENNIS-SET-SCOPES-EXACT');
  assert.equal(tennisSetPayload.selection_count,2);
  assert.equal(tennisShareRequests.length,1,'both tennis set winners must be shared in one all-or-nothing ticket');
  assert.deepEqual(tennisShareRequests[0].selections.map(x=>({
    eventId:x.eventId,marketId:x.marketId,specifier:x.specifier,outcomeId:x.outcomeId
  })),[
    {eventId:'sr:match:tennis-set-one',marketId:'202',specifier:'setnr=1',outcomeId:'tennis-s1-alice'},
    {eventId:'sr:match:tennis-set-two',marketId:'202',specifier:'setnr=2',outcomeId:'tennis-s2-diego'}
  ]);

  // A Set 2 request must not fall back to an otherwise open Set 1 market.
  const mismatchedSetStart = Date.now() + 4 * 60 * 60 * 1000;
  let mismatchedSetShareCalls = 0;
  globalThis.fetch = async input => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    if (url.pathname === '/api/ng/orders/share') {
      mismatchedSetShareCalls++;
      return jsonResponse({bizCode:10000,data:{shareCode:'MUST-NOT-BE-CREATED'}});
    }
    if (url.pathname === '/api/ng/factsCenter/event') {
      const eventId = String(url.searchParams.get('eventId') || '');
      const second = eventId === 'sr:match:tennis-other-fixture';
      return jsonResponse({bizCode:10000,data:{event:{
        eventId,
        homeTeamName:second?'George Golf':'Eva Echo',
        awayTeamName:second?'Helen Hotel':'Finn Foxtrot',
        estimateStartTime:mismatchedSetStart + (second ? 3600000 : 0),matchStatus:'Not start',
        markets:[{id:'202',desc:'1st Set Winner',specifier:'setnr=1',status:'0',outcomes:[
          {id:second?'other-s1-george':'only-s1-eva',desc:second?'George Golf':'Eva Echo',odds:1.9,isActive:1},
          {id:second?'other-s1-helen':'only-s1-finn',desc:second?'Helen Hotel':'Finn Foxtrot',odds:1.9,isActive:1}
        ]}]
      }}});
    }
    throw new Error('Unexpected mismatched tennis set request: ' + url.toString());
  };
  const mismatchedSetResponse = await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'manual',manual_selections:[
      {event_id:'tennis-wrong-set-scope',sportybet_event_id:'sr:match:tennis-only-set-one',sport:'tennis',
       market:'set_winner',set_number:2,market_id:'202',pick:'p1',player_1:'Eva Echo',player_2:'Finn Foxtrot',
       match:'Eva Echo vs Finn Foxtrot',start_time:new Date(mismatchedSetStart).toISOString()},
      {event_id:'tennis-other-fixture',sportybet_event_id:'sr:match:tennis-other-fixture',sport:'tennis',
       market:'set_winner',set_number:1,pick:'p1',market_id:'202',player_1:'George Golf',player_2:'Helen Hotel',
       match:'George Golf vs Helen Hotel',start_time:new Date(mismatchedSetStart + 3600000).toISOString()}
    ]})
  })});
  const mismatchedSetPayload = await mismatchedSetResponse.json();
  assert.equal(mismatchedSetResponse.status,409,JSON.stringify(mismatchedSetPayload));
  assert.equal(mismatchedSetPayload.booking_code_withheld,true);
  assert.equal(mismatchedSetPayload.validation.some(x=>x.event_id==='tennis-wrong-set-scope'&&x.ok===true),false,
    'the Set 2 leg must not validate against a Set 1-only catalogue; actual validation: ' + JSON.stringify(mismatchedSetPayload.validation));
  assert.equal(mismatchedSetShareCalls,0,'a missing exact Set 2 market must withhold the entire ticket without a share request');

  // When the exact live virtual feed resolves every eFootball leg, do not
  // launch a duplicate broad catalogue crawl that can exceed Pages Worker CPU.
  const feedFirstStart = Date.now() + 6 * 60 * 60 * 1000;
  const feedFirstLegs = [
    {
      event_id:'sr:match:efootball-feed-alpha', sportybet_event_id:'sr:match:efootball-feed-alpha',
      sport:'virtual', product:'efootball_gt', market:'virtual_total', pick:'over', line:1.5, market_id:'18',
      player_1:'Alpha FC', player_2:'Beta FC', match:'Alpha FC vs Beta FC',
      start_time:new Date(feedFirstStart).toISOString(), odds:1.82, odds_fresh:true
    },
    {
      event_id:'sr:match:efootball-feed-gamma', sportybet_event_id:'sr:match:efootball-feed-gamma',
      sport:'virtual', product:'efootball_gt', market:'virtual_total', pick:'under', line:2.5, market_id:'18',
      player_1:'Gamma FC', player_2:'Delta FC', match:'Gamma FC vs Delta FC',
      start_time:new Date(feedFirstStart + 60 * 60 * 1000).toISOString(), odds:1.89, odds_fresh:true
    }
  ];
  const feedFirstBuilder = {mode:'PAPER_ONLY',batches:[{batch_id:'DESK-BATCH-01',legs:feedFirstLegs}]};
  const feedFirstEvents = feedFirstLegs.map((leg,index)=>({
    event_id:leg.sportybet_event_id,
    team_1:leg.player_1,
    team_2:leg.player_2,
    start_time_ms:Date.parse(leg.start_time),
    match_status:'Not start',
    markets:[{
      id:'18',desc:'Total Goals Over/Under',specifier:'total='+leg.line,status:'0',
      outcomes:[
        {id:'feed-over-'+index,desc:'Over '+leg.line,odds:index===0?1.82:1.88,isActive:1},
        {id:'feed-under-'+index,desc:'Under '+leg.line,odds:index===0?1.92:1.89,isActive:1}
      ]
    }]
  }));
  let feedFirstCatalogueRequests=0;
  let feedFirstShareRequests=0;
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url);
    if(url.pathname==='/data/odds_builder.json') return jsonResponse(feedFirstBuilder);
    if(url.pathname==='/api/ng/factsCenter/event') return jsonResponse({bizCode:10000,data:{}});
    if(url.pathname==='/api/sportybet-virtual') return jsonResponse({ok:true,events:feedFirstEvents,upcoming_events_count:feedFirstEvents.length});
    if(/\/(?:pcUpcomingEvents|wapConfigurableUpcomingEvents)$/.test(url.pathname)){
      feedFirstCatalogueRequests++;
      return jsonResponse({bizCode:10000,data:{tournaments:[]}});
    }
    if(url.pathname==='/api/ng/orders/share'){
      feedFirstShareRequests++;
      return jsonResponse({bizCode:10000,data:{shareCode:'EFOOTBALL-FEED-FIRST',outcomes:[{odds:1.82},{odds:1.89}]}});
    }
    throw new Error('Unexpected feed-first booking request: '+url.toString());
  };
  const feedFirstResponse=await onRequest({request:new Request('https://match-signal.pages.dev/api/sportybet-booking',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:'DESK-BATCH-01'})
  })});
  const feedFirstPayload=await feedFirstResponse.json();
  assert.equal(feedFirstResponse.status,200,JSON.stringify(feedFirstPayload));
  assert.equal(feedFirstPayload.ok,true,JSON.stringify(feedFirstPayload));
  assert.equal(feedFirstPayload.booking_code,'EFOOTBALL-FEED-FIRST');
  assert.equal(feedFirstPayload.selection_count,2);
  assert.equal(feedFirstCatalogueRequests,0,'exact live-feed matches must bypass the broad catalogue crawl');
  assert.equal(feedFirstShareRequests,1,'the resolved two-leg paper batch must request exactly one share code');

  console.log('SportyBet booking resilience: PASS (bounded paging, stale-ID recovery, football and basketball aliases, exact Tennis Set 1/Set 2 market-202 scopes, virtual eFootball aliases, and full-ticket safeguards).');
} finally { globalThis.fetch=originalFetch; }
