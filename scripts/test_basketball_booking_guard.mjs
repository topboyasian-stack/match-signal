import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { onRequestPost } from '../functions/api/sportybet-basketball-booking.js';
import { nbaTotalsReleaseQualified } from '../functions/api/sportybet-booking.js';

const oos = {
  paper_only: true,
  evaluation_type: 'NBA_TOTALS_FIXED_CUTOFF_V2',
  holdout_protocol: { fixed_cutoff_utc: '2026-11-02T02:00:00+00:00' },
  market_id: '225',
  market_definition: 'full_game_total_including_overtime',
  model_version: 'nba-total-v5.1-pace-efficiency-calibrated',
  release_decision: 'RESEARCH_ONLY',
  walk_forward: { holdout: { n: 4, mae: 26.7, baseline_mae: 24.75, bias: 6.4 } },
  market_holdout: { n: 0, roi: null, roi_ci95_lower: null, roi_vs_market_favorite: null }
};


const currentMainOos = JSON.parse(readFileSync(new URL('../data/nba_totals_oos_value_test.json', import.meta.url), 'utf8'));
const currentMainProbability = JSON.parse(readFileSync(new URL('../data/nba_totals_probability_value_experiment.json', import.meta.url), 'utf8'));

test('checked-in latest-main NBA reports agree with the strict release gate', () => {
  const gateQualified = nbaTotalsReleaseQualified(currentMainOos, currentMainProbability);
  const reportsDeclareQualified =
    currentMainOos.release_decision === 'QUALIFIED' &&
    currentMainProbability.release_decision === 'QUALIFIED';
  assert.equal(
    gateQualified,
    reportsDeclareQualified,
    'Current main evidence must not unlock the ticket gate unless both release reports and every independent gate predicate pass.'
  );
});

const probability = {
  paper_only: true,
  experiment: 'NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V3',
  model_version: 'nba-total-v5.1-pace-efficiency-calibrated',
  model_projection_market_blind: true,
  prospective_holdout_cutoff_utc: '2026-11-02T02:00:00+00:00',
  prospective_holdout_used_for_calibration: false,
  live_value_decisions_authorized: false,
  prospective_minimum_sample_reached: false,
  prospective_probability_validation_sample_met: false,
  prospective_clv_release_check_passed: false,
  prospective_pregame_snapshot_coverage: {
    cutoff_utc: '2026-11-02T02:00:00+00:00',
    prospective_settled_selections_with_exact_snapshot_match: 0,
    prospective_settled_selections_missing_or_mismatched_snapshot: 0,
    prospective_settled_unique_market_selections: 0
  },
  prospective_probability_score_summary: { n: 0, sufficient_for_probability_validation: false },
  prospective_clv_diagnostics: {
    positive_clv_release_check_passed: false,
    near_close_observations: 0,
    mean_probability_clv: 0,
    mean_line_clv_points: 0
  },
  calibration_protocol: { probability_edge_threshold: 0.04, expected_value_threshold: 0.03 }
};


test('the probability sample counts unique settled fixtures separately from 100 ROI-grade selections', () => {
  const qualifiedEvidence = {
    ...oos,
    release_decision: 'QUALIFIED',
    walk_forward: { holdout: { n: 100, mae: 20, baseline_mae: 21, bias: 0.5 } },
    market_holdout: { n: 100, roi: 0.08, roi_ci95_lower: 0.02, roi_vs_market_favorite: 0.01 }
  };
  const qualifiedProbability = {
    ...probability,
    prospective_minimum_sample_reached: true,
    prospective_probability_validation_sample_met: true,
    prospective_clv_release_check_passed: true,
    prospective_pregame_snapshot_coverage: {
      cutoff_utc: '2026-11-02T02:00:00+00:00',
      prospective_settled_selections_with_exact_snapshot_match: 100,
      prospective_settled_selections_missing_or_mismatched_snapshot: 0,
      prospective_settled_unique_market_selections: 100
    },
    prospective_probability_score_summary: { n: 30, sufficient_for_probability_validation: true },
    prospective_probability_fixture_coverage: {
      cutoff_utc: '2026-11-02T02:00:00+00:00',
      valid_unique_settled_fixtures: 30,
      binary_scored_unique_fixtures: 30,
      snapshot_linkage_failure_count: 0,
      sample_threshold_met: true
    },
    prospective_clv_diagnostics: {
      positive_clv_release_check_passed: true,
      near_close_observations: 1,
      mean_probability_clv: 0.01,
      mean_line_clv_points: 0.5
    }
  };
  assert.equal(nbaTotalsReleaseQualified(qualifiedEvidence, qualifiedProbability), true);
  const underSampled = {
    ...qualifiedProbability,
    prospective_probability_validation_sample_met: false,
    prospective_probability_score_summary: { n: 29, sufficient_for_probability_validation: false },
    prospective_probability_fixture_coverage: {
      ...qualifiedProbability.prospective_probability_fixture_coverage,
      valid_unique_settled_fixtures: 29,
      binary_scored_unique_fixtures: 29,
      sample_threshold_met: false
    }
  };
  assert.equal(nbaTotalsReleaseQualified(qualifiedEvidence, underSampled), false);
});

test('basketball-specific booking POST refuses to bypass the research-only NBA release gate', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const artifacts = {
    'nba_totals_oos_value_test.json': oos,
    'nba_totals_probability_value_experiment.json': probability,
    'nba_predictions.json': [],
    'nba_totals_publication_snapshots.json': []
  };

  globalThis.fetch = async input => {
    const url = String(input?.url || input);
    calls.push(url);
    if (url.startsWith('https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/data/')) {
      const filename = new URL(url).pathname.split('/').pop();
      assert.ok(Object.hasOwn(artifacts, filename), 'unexpected release artifact request: ' + filename);
      return new Response(JSON.stringify(artifacts[filename]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    if (url.includes('/api/sportybet-basketball?')) {
      throw new Error('A research-only release must be rejected before reading live markets.');
    }
    throw new Error('Unexpected outbound request: ' + url);
  };

  try {
    const request = new Request('https://match-signal.pages.dev/api/sportybet-basketball-booking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        builder_slot: 1,
        legs: [
          { event_id: 'sr:match:one', start_time: '2026-11-03T02:00:00+00:00', player_1: 'Team A', player_2: 'Team B', market_id: '225', line: 220.5, side: 'over' },
          { event_id: 'sr:match:two', start_time: '2026-11-03T02:30:00+00:00', player_1: 'Team C', player_2: 'Team D', market_id: '225', line: 221.5, side: 'under' }
        ]
      })
    });
    const response = await onRequestPost({ request });
    const result = await response.json();
    assert.equal(response.status, 423);
    assert.equal(result.error, 'NBA_RELEASE_GATE_LOCKED');
    assert.equal(result.booking_code_withheld, true);
    assert.match(result.message, /fixed-cutoff forecasting.*prospective market ROI/i);
    assert.equal(calls.filter(url => url.includes('/api/sportybet-basketball?')).length, 0);
    assert.equal(calls.some(url => /sportybet\.com/.test(url)), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
