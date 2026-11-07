import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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
    market_id: '225', model_qualified: true,
    start_time: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
    player_1: 'Match Signal Gate Probe Alpha', player_2: 'Match Signal Gate Probe Beta',
    match: 'Match Signal Gate Probe Alpha vs Match Signal Gate Probe Beta'
  },
  {
    event_id: 'nba-production-gate-probe-' + nonce + '-2',
    sportybet_event_id: 'sr:match:ms-gate-probe-' + nonce + '-2',
    sport: 'basketball', market: 'total', pick: 'under', line: 221.5,
    market_id: '225', model_qualified: true,
    start_time: new Date(now + 25 * 60 * 60 * 1000).toISOString(),
    player_1: 'Match Signal Gate Probe Gamma', player_2: 'Match Signal Gate Probe Delta',
    match: 'Match Signal Gate Probe Gamma vs Match Signal Gate Probe Delta'
  }
];

for (const base of bases) {
  const response = await fetch(base + '/api/sportybet-booking', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'Cache-Control': 'no-cache' },
    body: JSON.stringify({ mode: 'manual', manual_selections: legs }),
    cache: 'no-store',
    redirect: 'follow',
    signal: AbortSignal.timeout(30000)
  });
  const contentType = String(response.headers.get('content-type') || '').toLowerCase();
  const raw = await response.text();
  let body = null;
  try { body = JSON.parse(raw); } catch (_) {}
  assert.ok(contentType.includes('application/json'), base + ' must return JSON for the NBA gate probe');
  assert.ok(body && typeof body === 'object', base + ' returned non-JSON: ' + raw.slice(0, 180));
  assert.equal(body.ok, false, base + ' must not accept synthetic NBA probe legs');
  assert.equal(body.booking_code_withheld, true, base + ' must explicitly report that no code was returned');
  assert.equal(Object.hasOwn(body, 'booking_code'), false, base + ' must never return a code for synthetic NBA probe legs');

  if (!locallyQualified) {
    assert.equal(response.status, 423, base + ' must reject before catalogue lookup while current-main evidence is RESEARCH_ONLY');
    assert.equal(body.error, 'NBA_RELEASE_GATE_LOCKED');
  } else {
    assert.equal(response.status, 409, base + ' must reject synthetic legs after the global gate opens because they have no current SportyBet fixture/snapshot match');
    assert.equal(body.error, 'MANUAL_TICKET_REJECTED_PARTIAL');
    assert.equal(body.excluded_count, 2);
    assert.ok(Array.isArray(body.validation) && body.validation.length === 2);
    assert.ok(body.validation.every(item => item.ok === false));
  }
  console.log('PASS: production NBA manual-ticket fail-closed probe', JSON.stringify({
    base, http_status: response.status, error: body.error,
    current_main_release_qualified: locallyQualified, booking_code_withheld: body.booking_code_withheld
  }));
}
