import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/sportybet-booking.js';

const MODEL = 'nba-total-v5.1-pace-efficiency-calibrated';
const CUTOFF = '2026-11-02T02:00:00+00:00';

function buildEvidence(fixtures) {
  const now = Date.now();
  const quoteTime = new Date(now - 45_000).toISOString();
  const publishedAt = new Date(now - 40_000).toISOString();
  const predictions = [];
  const snapshots = [];
  const diagnostics = [];

  for (const fixture of fixtures) {
    const market = {
      line: 220.5,
      over_odds: 1.91,
      under_odds: 1.89,
      market_id: '225',
      source: 'SportyBet Nigeria',
      sportybet_event_id: fixture.sportybetId,
      quote_timestamp: quoteTime,
      quote_capture_basis: 'SportyBet API response observed_at',
      pick: 'over',
      expected_total: 225.5
    };
    const prediction = {
      sport: 'basketball',
      league: 'NBA',
      event_id: fixture.espnId,
      start_time: fixture.startTime,
      player_1: fixture.home,
      player_2: fixture.away,
      expected_total: 225.5,
      totals_model_version: MODEL,
      paper_only: true,
      markets: { total_ou: { ...market } }
    };
    predictions.push(prediction);
    snapshots.push({
      ...prediction,
      publication_snapshot_verified: true,
      publication_snapshot_kind: 'immutable_sportybet_market_225_revision',
      publication_snapshot_id: 'nba-total-pub:' + fixture.espnId,
      published_at: publishedAt,
      markets: { total_ou: { ...market } }
    });
    diagnostics.push({
      event_id: fixture.espnId,
      start_time: fixture.startTime,
      quote_timestamp: quoteTime,
      forecast_total: 225.5,
      sportybet_line: 220.5,
      over_odds: 1.91,
      under_odds: 1.89,
      decision: 'OVER VALUE',
      calibration_check: 'PASS',
      bootstrap_95_lower_bound: {
        over_probability_edge: 0.05,
        over_expected_value: 0.04
      }
    });
  }

  const evidence = {
    paper_only: true,
    evaluation_type: 'NBA_TOTALS_FIXED_CUTOFF_V2',
    holdout_protocol: { fixed_cutoff_utc: CUTOFF },
    market_id: '225',
    market_definition: 'full_game_total_including_overtime',
    model_version: MODEL,
    release_decision: 'QUALIFIED',
    walk_forward: {
      holdout: { n: 100, mae: 10, baseline_mae: 11, bias: 0.2 }
    },
    market_holdout: {
      n: 100, roi: 0.12, roi_ci95_lower: 0.01, roi_vs_market_favorite: 0.02
    }
  };
  const probability = {
    paper_only: true,
    experiment: 'NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V3',
    model_version: MODEL,
    model_projection_market_blind: true,
    prospective_holdout_cutoff_utc: CUTOFF,
    prospective_holdout_used_for_calibration: false,
    live_value_decisions_authorized: false,
    generated_at: new Date(now - 10_000).toISOString(),
    calibration_protocol: {
      probability_edge_threshold: 0.04,
      expected_value_threshold: 0.03
    },
    prospective_pregame_snapshot_coverage: {
      cutoff_utc: CUTOFF,
      prospective_settled_selections_with_exact_snapshot_match: 100,
      prospective_settled_selections_missing_or_mismatched_snapshot: 0,
      prospective_settled_unique_market_selections: 100
    },
    prospective_probability_score_summary: {
      n: 30, sufficient_for_probability_validation: true
    },
    prospective_probability_fixture_coverage: {
      cutoff_utc: CUTOFF,
      valid_unique_settled_fixtures: 30,
      binary_scored_unique_fixtures: 30,
      snapshot_linkage_failure_count: 0,
      sample_threshold_met: true
    },
    prospective_minimum_sample_reached: true,
    prospective_probability_validation_sample_met: true,
    prospective_clv_release_check_passed: true,
    prospective_clv_diagnostics: {
      positive_clv_release_check_passed: true,
      near_close_observations: 2,
      mean_probability_clv: 0.01,
      mean_line_clv_points: 0.5
    },
    upcoming_exact_fresh_market_225_value_diagnostics: diagnostics
  };
  return { evidence, probability, predictions, snapshots };
}

function fixture(espnId, sportybetId, home, away, offsetMinutes = 0) {
  return {
    espnId,
    sportybetId,
    home,
    away,
    startTime: new Date(Date.now() + (120 + offsetMinutes) * 60_000).toISOString()
  };
}

function manualLeg(row) {
  return {
    event_id: row.espnId,
    sportybet_event_id: row.sportybetId,
    sport: 'basketball',
    market: 'total',
    pick: 'over',
    line: 220.5,
    market_id: '225',
    model_qualified: false,
    start_time: row.startTime,
    player_1: row.home,
    player_2: row.away,
    match: row.home + ' vs ' + row.away
  };
}

function sportBetEvent(row) {
  const line = Number(row.line == null ? 220.5 : row.line);
  return {
    event_id: row.sportybetId,
    home: row.home,
    away: row.away,
    start_time: row.startTime,
    fetched_at: new Date().toISOString(),
    tournament: 'NBA',
    markets: [{
      id: '225',
      name: 'Game Total',
      specifier: 'total=' + line,
      status: '0',
      outcomes: [
        { id: row.sportybetId + '-over', name: 'Over', odds: 1.91, active: true },
        { id: row.sportybetId + '-under', name: 'Under', odds: 1.89, active: true }
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

function installFetchMock({ bundle, events, shareResponse }) {
  const originalFetch = globalThis.fetch;
  const calls = { feed: 0, share: 0, raw: 0 };
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(String(input));
    if (url.hostname === 'raw.githubusercontent.com') {
      calls.raw++;
      const name = url.pathname.split('/').pop();
      const files = {
        'nba_totals_oos_value_test.json': bundle.evidence,
        'nba_totals_probability_value_experiment.json': bundle.probability,
        'nba_predictions.json': bundle.predictions,
        'nba_totals_publication_snapshots.json': bundle.snapshots
      };
      assert.ok(Object.hasOwn(files, name), 'unexpected release evidence request: ' + name);
      return new Response(JSON.stringify(files[name]), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      });
    }
    if (url.hostname === 'match-signal-sportybet-proxy.topboyasian.workers.dev' &&
        url.pathname.startsWith('/api/ng/factsCenter/')) {
      calls.feed++;
      const providerEvents = events.map(row => {
        const normalized = sportBetEvent(row);
        return {
          eventId: normalized.event_id,
          homeTeamName: normalized.home,
          awayTeamName: normalized.away,
          estimateStartTime: Date.parse(normalized.start_time),
          matchStatus: 'Not start',
          markets: normalized.markets.map(m => ({
            id: m.id,
            desc: m.name,
            specifier: m.specifier,
            status: m.status,
            outcomes: m.outcomes.map(o => ({
              id: o.id,
              desc: o.name,
              odds: o.odds,
              isActive: o.active ? 1 : 0
            }))
          }))
        };
      });
      return new Response(JSON.stringify({
        bizCode: 10000,
        data: { tournaments: [{ id: 'sr:tournament:132', name: 'NBA', events: providerEvents }] }
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url.origin === 'https://www.sportybet.com' && url.pathname === '/api/ng/orders/share') {
      calls.share++;
      return new Response(JSON.stringify(shareResponse), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      });
    }
    throw new Error('Unexpected network call: ' + url.toString());
  };
  return { calls, restore: () => { globalThis.fetch = originalFetch; } };
}

test('NBA ticket resolves SportyBet event ID separately from ESPN prediction ID and rejects a missing leg whole', async () => {
  const one = fixture('espn-one', 'sr:match:one', 'Boston Celtics', 'New York Knicks');
  const two = fixture('espn-two', 'sr:match:two', 'Cleveland Cavaliers', 'Chicago Bulls', 30);
  const bundle = buildEvidence([one, two]);
  const mock = installFetchMock({ bundle, events: [one] });

  try {
    const response = await onRequest({
      request: requestFor([manualLeg(one), manualLeg(two)])
    });
    const body = await response.json();
    assert.equal(mock.calls.raw, 0, 'manual NBA picks must not require model-release artifacts');
    assert.equal(mock.calls.feed, 3, 'the three bounded NBA catalog queries must use the proxy source');
    assert.equal(mock.calls.share, 0, 'must not request a share code when any NBA leg is missing');
    assert.equal(response.status, 409);
    assert.equal(body.error, 'MANUAL_TICKET_REJECTED_PARTIAL');
    assert.equal(body.booking_code_withheld, true);
    assert.equal(body.excluded_count, 1);
    const valid = body.validation.find(row => row.event_id === one.espnId);
    assert.equal(valid.ok, true);
    assert.equal(valid.resolved_by, 'sportybet_event_id');
    assert.equal(valid.resolved_event_id, one.sportybetId);
    const missing = body.validation.find(row => row.event_id === two.espnId);
    assert.equal(missing.ok, false);
  } finally {
    mock.restore();
  }
});

test('NBA ticket with a partial SportyBet acceptance withholds the provider share code', async () => {
  const one = fixture('espn-one', 'sr:match:one', 'Boston Celtics', 'New York Knicks');
  const two = fixture('espn-two', 'sr:match:two', 'Cleveland Cavaliers', 'Chicago Bulls', 30);
  const bundle = buildEvidence([one, two]);
  const mock = installFetchMock({
    bundle,
    events: [one, two],
    shareResponse: {
      bizCode: 10000,
      data: {
        shareCode: 'PARTIAL99',
        outcomes: [{ eventId: one.sportybetId, odds: 1.91 }],
        unavailableOutcomes: [{ eventId: two.sportybetId, reason: 'market closed' }]
      }
    }
  });

  try {
    const response = await onRequest({
      request: requestFor([manualLeg(one), manualLeg(two)])
    });
    const body = await response.json();
    assert.equal(mock.calls.raw, 0, 'manual NBA picks must not require model-release artifacts');
    assert.equal(mock.calls.feed, 3, 'the three bounded NBA catalog queries must use the proxy source');
    assert.equal(mock.calls.share, 1);
    assert.equal(response.status, 409);
    assert.equal(body.error, 'MANUAL_TICKET_REJECTED_PARTIAL');
    assert.equal(body.booking_code_withheld, true);
    assert.equal(body.accepted_selection_count, 1);
    assert.equal(body.unavailable_count, 1);
    assert.equal(Object.hasOwn(body, 'booking_code'), false);
    assert.ok(body.validation.every(row => row.ok === true), 'both ESPN predictions must map to their SportyBet fixtures');
  } finally {
    mock.restore();
  }
});

test('manual NBA share-code preparation remains available when model evidence is research-only', async () => {
  const one = fixture('espn-one', 'sr:match:one', 'Boston Celtics', 'New York Knicks');
  const two = fixture('espn-two', 'sr:match:two', 'Cleveland Cavaliers', 'Chicago Bulls', 30);
  const bundle = buildEvidence([one, two]);
  bundle.evidence.release_decision = 'RESEARCH_ONLY';
  const mock = installFetchMock({
    bundle,
    events: [one, two],
    shareResponse: {
      bizCode: 10000,
      data: {
        shareCode: 'MANUALUNQUALIFIED',
        outcomes: [{ eventId: one.sportybetId, odds: 1.91 }, { eventId: two.sportybetId, odds: 1.91 }]
      }
    }
  });

  try {
    const response = await onRequest({ request: requestFor([manualLeg(one), manualLeg(two)]) });
    const body = await response.json();
    assert.equal(response.status, 200, JSON.stringify(body));
    assert.equal(body.ok, true);
    assert.equal(body.booking_code, 'MANUALUNQUALIFIED');
    assert.equal(body.selection_count, 2);
    assert.equal(mock.calls.raw, 0, 'manual NBA picks must not depend on the model release decision');
    assert.equal(mock.calls.feed, 3, 'manual NBA picks must still look up current SportyBet markets');
    assert.equal(mock.calls.share, 1, 'the full manually selected ticket should be sent for share-code preparation');
    assert.ok(body.selections.every(row => row.ok === true));
  } finally {
    mock.restore();
  }
});

test('manual NBA leg with a mismatched current market-225 line is rejected before share-code creation', async () => {
  const one = fixture('espn-one', 'sr:match:one', 'Boston Celtics', 'New York Knicks');
  const two = fixture('espn-two', 'sr:match:two', 'Cleveland Cavaliers', 'Chicago Bulls', 30);
  const bundle = buildEvidence([one, two]);
  const mock = installFetchMock({
    bundle,
    events: [{ ...one, line: 221.5 }, two],
    shareResponse: {
      bizCode: 10000,
      data: {
        shareCode: 'MUSTNOTEXIST',
        outcomes: [{ eventId: one.sportybetId, odds: 1.91 }, { eventId: two.sportybetId, odds: 1.91 }]
      }
    }
  });

  try {
    const response = await onRequest({ request: requestFor([manualLeg(one), manualLeg(two)]) });
    const body = await response.json();
    assert.equal(response.status, 409);
    assert.equal(body.error, 'MANUAL_TICKET_REJECTED_PARTIAL');
    assert.equal(body.booking_code_withheld, true);
    assert.equal(mock.calls.raw, 0, 'manual NBA picks must not require model-release artifacts');
    assert.equal(mock.calls.feed, 3);
    assert.equal(mock.calls.share, 0, 'a leg with a stale SportyBet line must not reach the share endpoint');
    assert.equal(Object.hasOwn(body, 'booking_code'), false);
    assert.ok(body.validation.some(row => row.event_id === one.espnId && row.ok === false));
  } finally {
    mock.restore();
  }
});
