import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/sportybet-booking.js';

function futureStart() {
  return new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
}

function manualLeg(eventId, home, away, startTime) {
  return {
    event_id: eventId,
    sport: 'basketball',
    market: 'total',
    pick: 'over',
    line: 220.5,
    market_id: '225',
    model_qualified: true,
    start_time: startTime,
    player_1: home,
    player_2: away,
    match: home + ' vs ' + away
  };
}

function sportBetEvent(eventId, home, away, startTime) {
  return {
    event_id: eventId,
    home,
    away,
    start_time: startTime,
    tournament: 'NBA',
    markets: [{
      id: '225',
      name: 'Game Total',
      specifier: 'total=220.5',
      status: '0',
      outcomes: [
        { id: eventId + '-over', name: 'Over', odds: 1.91, active: true },
        { id: eventId + '-under', name: 'Under', odds: 1.89, active: true }
      ]
    }]
  };
}

function requestFor(manualSelections) {
  return {
    method: 'POST',
    url: 'https://match-signal.pages.dev/api/sportybet-booking',
    json: async () => ({ mode: 'manual', manual_selections: manualSelections })
  };
}

test('an NBA-containing ticket is rejected before sharing if any leg fails current validation', async () => {
  const originalFetch = globalThis.fetch;
  const start = futureStart();
  const feedCalls = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    feedCalls.push(url);
    assert.equal(url.pathname, '/api/sportybet-basketball');
    return new Response(JSON.stringify({
      ok: true,
      events: [sportBetEvent('nba-valid', 'Boston Celtics', 'New York Knicks', start)]
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  try {
    const response = await onRequest({
      request: requestFor([
        manualLeg('nba-valid', 'Boston Celtics', 'New York Knicks', start),
        manualLeg('nba-missing', 'Cleveland Cavaliers', 'Chicago Bulls', start)
      ])
    });
    const body = await response.json();
    assert.equal(response.status, 409);
    assert.equal(body.error, 'BASKETBALL_SLIP_REJECTED_PARTIAL');
    assert.equal(body.booking_code_withheld, true);
    assert.equal(body.excluded_count, 1);
    assert.equal(feedCalls.length, 1, 'must not call SportyBet share endpoint after any NBA leg fails validation');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an NBA-containing ticket with a partially accepted SportyBet response withholds the code', async () => {
  const originalFetch = globalThis.fetch;
  const start = futureStart();
  const shareCalls = [];
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(String(input));
    if (url.pathname === '/api/sportybet-basketball') {
      return new Response(JSON.stringify({
        ok: true,
        events: [
          sportBetEvent('nba-one', 'Boston Celtics', 'New York Knicks', start),
          sportBetEvent('nba-two', 'Cleveland Cavaliers', 'Chicago Bulls', start)
        ]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url.origin === 'https://www.sportybet.com' && url.pathname === '/api/ng/orders/share') {
      shareCalls.push({ url, options });
      return new Response(JSON.stringify({
        bizCode: 10000,
        data: {
          shareCode: 'PARTIAL99',
          outcomes: [{ eventId: 'nba-one', odds: 1.91 }],
          unavailableOutcomes: [{ eventId: 'nba-two', reason: 'market closed' }]
        }
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    throw new Error('Unexpected network call: ' + url.toString());
  };

  try {
    const response = await onRequest({
      request: requestFor([
        manualLeg('nba-one', 'Boston Celtics', 'New York Knicks', start),
        manualLeg('nba-two', 'Cleveland Cavaliers', 'Chicago Bulls', start)
      ])
    });
    const body = await response.json();
    assert.equal(shareCalls.length, 1, 'validated ticket should be submitted once for share-code preparation');
    assert.equal(response.status, 409);
    assert.equal(body.error, 'BASKETBALL_SLIP_REJECTED_PARTIAL');
    assert.equal(body.booking_code_withheld, true);
    assert.equal(body.accepted_selection_count, 1);
    assert.equal(body.unavailable_count, 1);
    assert.equal(Object.hasOwn(body, 'booking_code'), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
