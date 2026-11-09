import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/sportybet-booking.js';

const originalFetch = globalThis.fetch;
const PROXY = 'https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const json = payload => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { 'content-type': 'application/json; charset=utf-8' }
});

function fixture(index, side = 'home', options = {}) {
  const start = Date.now() + 6 * 60 * 60 * 1000 + index * 60 * 1000;
  const providerId = 'sr:match:ptwas-' + index;
  const p1 = 'Alex Example ' + index;
  const p2 = 'Juan Example ' + index;
  const marketId = String(options.marketId || '203');
  const specifier = options.specifier ?? ('player=' + side);
  const yesId = String(options.yesId || ('ptwas-yes-' + index));
  const noId = 'ptwas-no-' + index;
  const yesOdds = Number(options.yesOdds || 1.24);
  const event = {
    eventId: providerId,
    homeTeamName: p1,
    awayTeamName: p2,
    estimateStartTime: start,
    matchStatus: 'Not start',
    markets: [{
      id: marketId,
      desc: 'Player to win at least one set',
      specifier,
      status: '0',
      outcomes: [
        { id: yesId, desc: 'Yes', odds: yesOdds, isActive: 1 },
        { id: noId, desc: 'No', odds: 3.60, isActive: 1 }
      ]
    }]
  };
  const selectedName = side === 'home' ? p1 : p2;
  const selectedPick = side === 'home' ? 'p1' : 'p2';
  const quoteAt = new Date(Date.now() - 30000).toISOString();
  return {
    event,
    leg: {
      event_id: 'espn:ptwas-' + index,
      sportybet_event_id: providerId,
      sport: 'tennis',
      market: 'player_to_win_set',
      pick: selectedPick,
      market_id: marketId,
      sportybet_specifier: specifier,
      sportybet_outcome_id: yesId,
      sportybet_outcome_name: 'Yes',
      market_quote_timestamp: quoteAt,
      odds: yesOdds,
      player_1: p1,
      player_2: p2,
      match: p1 + ' vs ' + p2,
      start_time: new Date(start).toISOString(),
      model_qualified: true,
      selection_label: selectedName + ' to win at least one set'
    }
  };
}

async function submit(legs, events, expectedShareCode = 'TENNIS-SET-MARKET-OK') {
  const shareRequests = [];
  const requests = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    requests.push(url);
    if (url.pathname === '/api/ng/factsCenter/event') {
      const providerId = url.searchParams.get('eventId');
      const event = events.get(providerId);
      return json(event ? { bizCode: 10000, data: { event } } : { bizCode: 10000, data: {} });
    }
    if (url.pathname === '/api/ng/orders/share') {
      shareRequests.push(JSON.parse(options.body || '{}'));
      return json({
        bizCode: 10000,
        data: {
          shareCode: expectedShareCode,
          outcomes: legs.map(leg => ({ odds: Number(leg.odds) }))
        }
      });
    }
    if (/\/(?:pcUpcomingEvents|wapConfigurableUpcomingEvents)$/.test(url.pathname)) {
      return json({ bizCode: 10000, data: { tournaments: [] } });
    }
    throw new Error('Unexpected SportyBet request: ' + url.toString());
  };
  const response = await onRequest({
    request: new Request('https://match-signal.pages.dev/api/sportybet-booking', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ mode: 'manual', manual_selections: legs })
    })
  });
  return { response, payload: await response.json(), shareRequests, requests };
}

try {
  const home = fixture(1, 'home');
  const away = fixture(2, 'away');
  const events = new Map([
    [home.event.eventId, home.event],
    [away.event.eventId, away.event]
  ]);
  const success = await submit([home.leg, away.leg], events);
  assert.equal(success.response.status, 200, JSON.stringify(success.payload));
  assert.equal(success.payload.ok, true);
  assert.equal(success.payload.booking_code, 'TENNIS-SET-MARKET-OK');
  assert.equal(success.payload.selection_count, 2);
  assert.deepEqual(
    success.shareRequests[0].selections.map(item => [item.eventId, item.marketId, item.specifier, item.outcomeId]),
    [
      [home.event.eventId, '203', 'player=home', 'ptwas-yes-1'],
      [away.event.eventId, '203', 'player=away', 'ptwas-yes-2']
    ]
  );
  assert.deepEqual(
    success.payload.selections.map(item => item.outcome_id),
    ['ptwas-yes-1', 'ptwas-yes-2']
  );

  // The same quote must fail closed when SportyBet changes the Yes price.
  const changedPrice = fixture(3, 'home');
  const changedPriceEvent = structuredClone(changedPrice.event);
  changedPriceEvent.markets[0].outcomes[0].odds = 1.30;
  const priceFailure = await submit(
    [changedPrice.leg, away.leg],
    new Map([[changedPriceEvent.eventId, changedPriceEvent], [away.event.eventId, away.event]])
  );
  assert.equal(priceFailure.response.status, 409);
  assert.equal(priceFailure.payload.booking_code_withheld, true);
  assert.equal(priceFailure.shareRequests.length, 0);

  // The exact market specifier is part of identity, not a fuzzy match.
  const changedSpecifier = fixture(4, 'home');
  const changedSpecifierEvent = structuredClone(changedSpecifier.event);
  changedSpecifierEvent.markets[0].specifier = 'player=away';
  const specifierFailure = await submit(
    [changedSpecifier.leg, away.leg],
    new Map([[changedSpecifierEvent.eventId, changedSpecifierEvent], [away.event.eventId, away.event]])
  );
  assert.equal(specifierFailure.response.status, 409);
  assert.equal(specifierFailure.payload.booking_code_withheld, true);
  assert.equal(specifierFailure.shareRequests.length, 0);

  // A disappeared exact Yes outcome ID must never silently switch selections.
  const changedOutcome = fixture(5, 'home');
  const changedOutcomeEvent = structuredClone(changedOutcome.event);
  changedOutcomeEvent.markets[0].outcomes[0].id = 'new-provider-outcome-id';
  const outcomeFailure = await submit(
    [changedOutcome.leg, away.leg],
    new Map([[changedOutcomeEvent.eventId, changedOutcomeEvent], [away.event.eventId, away.event]])
  );
  assert.equal(outcomeFailure.response.status, 409);
  assert.equal(outcomeFailure.payload.booking_code_withheld, true);
  assert.equal(outcomeFailure.shareRequests.length, 0);

  // A market that names no selected player or player-side must not be guessed.
  const ambiguous = fixture(6, 'home');
  const ambiguousEvent = structuredClone(ambiguous.event);
  ambiguousEvent.markets[0].specifier = '';
  const ambiguousFailure = await submit(
    [ambiguous.leg, away.leg],
    new Map([[ambiguousEvent.eventId, ambiguousEvent], [away.event.eventId, away.event]])
  );
  assert.equal(ambiguousFailure.response.status, 409);
  assert.equal(ambiguousFailure.payload.booking_code_withheld, true);
  assert.equal(ambiguousFailure.shareRequests.length, 0);

  console.log('Tennis Player-to-Win-a-Set booking: PASS (exact IDs, current Yes/No pair, live price lock, participant mapping and all-or-nothing rejection).');
} finally {
  globalThis.fetch = originalFetch;
}
