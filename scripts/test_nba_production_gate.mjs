import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { nbaTotalsReleaseQualified } from '../functions/api/sportybet-booking.js';

const evidence = JSON.parse(readFileSync(new URL('../data/nba_totals_oos_value_test.json', import.meta.url), 'utf8'));
const probability = JSON.parse(readFileSync(new URL('../data/nba_totals_probability_value_experiment.json', import.meta.url), 'utf8'));
const locallyQualified = nbaTotalsReleaseQualified(evidence, probability);
const bases = [...new Set([
  'https://match-signal.pages.dev',
  process.env.CLOUDFLARE_DEPLOYMENT_URL || ''
].filter(Boolean).map(value => value.replace(/\/+$/, '')))];
const nonce = Date.now();
const now = Date.now();
const legs = [
  {
    event_id: 'nba-production-gate-probe-' + nonce + '-1',
    sportybet_event_id: 'sr:match:ms-gate-probe-' + nonce + '-1',
    sport: 'basketball', market: 'total', pick: 'over', line: 220.5,
    market_id: '225', model_qualified: false,
    start_time: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
    player_1: 'Match Signal Gate Probe Alpha', player_2: 'Match Signal Gate Probe Beta',
    match: 'Match Signal Gate Probe Alpha vs Match Signal Gate Probe Beta'
  },
  {
    event_id: 'nba-production-gate-probe-' + nonce + '-2',
    sportybet_event_id: 'sr:match:ms-gate-probe-' + nonce + '-2',
    sport: 'basketball', market: 'total', pick: 'under', line: 221.5,
    market_id: '225', model_qualified: false,
    start_time: new Date(now + 25 * 60 * 60 * 1000).toISOString(),
    player_1: 'Match Signal Gate Probe Gamma', player_2: 'Match Signal Gate Probe Delta',
    match: 'Match Signal Gate Probe Gamma vs Match Signal Gate Probe Delta'
  }
];

async function postJson(base, path, payload) {
  const response = await fetch(base + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'Cache-Control': 'no-cache' },
    body: JSON.stringify(payload),
    cache: 'no-store',
    redirect: 'follow',
    signal: AbortSignal.timeout(30000)
  });
  const contentType = String(response.headers.get('content-type') || '').toLowerCase();
  const raw = await response.text();
  let body = null;
  try { body = JSON.parse(raw); } catch (_) {}
  assert.ok(contentType.includes('application/json'), base + path + ' must return JSON');
  assert.ok(body && typeof body === 'object', base + path + ' returned non-JSON: ' + raw.slice(0, 180));
  return { response, body };
}

const probeResults = [];
for (const base of bases) {
  // Manual shared tickets are not model-qualified by this route. They must
  // reach live fixture/market validation and fail closed for fake fixtures.
  const manual = await postJson(base, '/api/sportybet-booking', {
    mode: 'manual',
    manual_selections: legs
  });
  assert.equal(manual.response.status, 409, base + ' must reject nonexistent manual NBA fixtures after live validation');
  assert.equal(manual.body.ok, false);
  assert.equal(manual.body.error, 'MANUAL_TICKET_REJECTED_PARTIAL');
  assert.equal(manual.body.booking_code_withheld, true);
  assert.equal(Object.hasOwn(manual.body, 'booking_code'), false);
  assert.equal(manual.body.excluded_count, 2);
  assert.ok(Array.isArray(manual.body.validation) && manual.body.validation.length === 2);
  assert.ok(manual.body.validation.every(item => item.ok === false));
  probeResults.push({
    base, endpoint_type: 'manual_shared_ticket',
    http_status: manual.response.status, error: manual.body.error,
    booking_code_withheld: manual.body.booking_code_withheld,
    booking_code_present: Object.hasOwn(manual.body, 'booking_code')
  });
  console.log('PASS: manual NBA ticket reaches live validation and rejects nonexistent fixtures', JSON.stringify(probeResults.at(-1)));

  // The dedicated Basketball-only booking endpoint retains the independent
  // NBA model-release gate. It must never mint a code for synthetic fixtures.
  const automatic = await postJson(base, '/api/sportybet-basketball-booking', {
    builder_slot: 1,
    legs: legs.map(leg => ({
      event_id: leg.event_id,
      sportybet_event_id: leg.sportybet_event_id,
      side: leg.pick,
      line: leg.line,
      market_id: leg.market_id,
      start_time: leg.start_time,
      player_1: leg.player_1,
      player_2: leg.player_2
    }))
  });
  assert.equal(automatic.body.ok, false, base + ' must not accept synthetic NBA Builder legs');
  assert.equal(automatic.body.booking_code_withheld, true, base + ' must report that no NBA Builder code was returned');
  assert.equal(Object.hasOwn(automatic.body, 'booking_code'), false, base + ' must never return a code for synthetic NBA Builder legs');
  if (!locallyQualified) {
    assert.equal(automatic.response.status, 423, base + ' must keep the automated NBA Builder locked while current-main evidence is RESEARCH_ONLY');
    assert.equal(automatic.body.error, 'NBA_RELEASE_GATE_LOCKED');
  } else {
    assert.equal(automatic.response.status, 409, base + ' must reject synthetic NBA Builder legs after the release gate opens');
    assert.equal(automatic.body.error, 'SELECTIONS_CHANGED');
    assert.ok(Array.isArray(automatic.body.validation) && automatic.body.validation.length === 2);
    assert.ok(automatic.body.validation.every(item => item.ok === false));
  }
  probeResults.push({
    base, endpoint_type: 'automated_basketball_builder',
    http_status: automatic.response.status, error: automatic.body.error,
    current_main_release_qualified: locallyQualified,
    booking_code_withheld: automatic.body.booking_code_withheld,
    booking_code_present: Object.hasOwn(automatic.body, 'booking_code')
  });
  console.log('PASS: automated NBA Builder keeps its independent release gate', JSON.stringify(probeResults.at(-1)));
}

writeFileSync('NBA-PRODUCTION-GATE-CHECK.json', JSON.stringify({
  verified_at: new Date().toISOString(),
  status: 'PASS',
  probe_type: 'manual_live_validation_plus_automated_nba_release_gate',
  current_main_release_qualified: locallyQualified,
  current_main_release_decision: evidence.release_decision || 'UNSPECIFIED',
  probes: probeResults
}, null, 2) + '\n');
