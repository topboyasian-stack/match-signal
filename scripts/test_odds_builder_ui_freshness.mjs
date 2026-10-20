import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const sourcePath = new URL('../expansion-odds-builder.js', import.meta.url);
const source = readFileSync(fileURLToPath(sourcePath), 'utf8');
const window = { __MATCH_SIGNAL_ODDS_BUILDER_TEST_MODE__: true };
const document = { readyState: 'loading', addEventListener() {} };
vm.runInNewContext(source, { window, document, console });

const hooks = window.__MATCH_SIGNAL_ODDS_BUILDER_TEST_HOOKS__;
assert.ok(hooks, 'Builder freshness regression hooks must be exposed in test mode');

const now = Date.parse('2026-10-20T03:00:00.000Z');
const iso = (offsetMs) => new Date(now + offsetMs).toISOString();

function deskLeg(overrides = {}) {
  return {
    product: 'efootball_gt',
    sport: 'virtual',
    qualification_lane: 'upcoming_desk_research_only',
    model_probability: 0.677,
    raw_model_probability: 0.7281,
    start_time: iso(5 * 60 * 1000),
    odds_fresh: true,
    market_odds_age_seconds: 12,
    event_id: 'evt-desk-1',
    ...overrides
  };
}

function deskBatch(legs = [deskLeg()], overrides = {}) {
  return {
    batch_id: 'DESK-BATCH-01',
    products: ['efootball_gt'],
    primary_lane: 'upcoming_desk_research',
    legs,
    ...overrides
  };
}

function snapshot(generatedOffsetMs = -60_000, batches = [deskBatch()], qualified = []) {
  return {
    generated_at: iso(generatedOffsetMs),
    status: 'VALUE_RESEARCH_SET',
    batches,
    qualified_legs: qualified
  };
}

// Allow a short future timestamp skew between GitHub runners and user browsers; the 15-minute maximum age remains inclusive.
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(-15 * 60_000) }, now).fresh, true);
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(-15 * 60_000 - 1) }, now).fresh, false);
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(30_000) }, now).fresh, true);
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(2 * 60_000) }, now).fresh, true);
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(5 * 60_000) }, now).fresh, true);
assert.equal(hooks.builderArtifactFreshness({ generated_at: iso(5 * 60_000 + 1) }, now).fresh, false);
assert.equal(hooks.builderArtifactFreshness({}, now).fresh, false);

// The intended 60%+ Desk lane is visible within its dedicated research lane, but the ordinary
// eFootball lane keeps its 80% floor.
assert.equal(hooks.activeVirtualProbabilityFloor(deskLeg(), 'upcoming_desk_research'), 0.60);
assert.equal(hooks.isActiveVirtualBatchAt(deskBatch(), now), true);
const ordinary = deskBatch([deskLeg({ qualification_lane: 'standard_efootball', model_probability: 0.79 })], {
  batch_id: 'BATCH-01',
  primary_lane: 'standard_efootball'
});
assert.equal(hooks.isActiveVirtualBatchAt(ordinary, now), false);

// Started and near-kickoff fixtures, invalid start times, stale quotes, and non-fresh prices
// must remove the whole accumulator rather than displaying its stale odds.
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ start_time: iso(-1) }), now), false);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ start_time: iso(119_999) }), now), false);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ start_time: iso(120_001) }), now), true);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ start_time: 'not-a-date' }), now), false);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ market_odds_age_seconds: 900 }), now), true);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ market_odds_age_seconds: 901 }), now), false);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ odds_fresh: false }), now), false);
assert.equal(hooks.isActiveVirtualBatchAt(deskBatch([
  deskLeg(),
  deskLeg({ event_id: 'evt-desk-2', start_time: iso(-10) })
]), now), false);

// Stale artifact: no batches or fallback individual legs are exposed to the UI/book-code worker.
const staleFiltered = hooks.filterCurrentBuilderSnapshot(
  snapshot(-16 * 60_000, [deskBatch()], [deskLeg()]),
  now
);
assert.equal(staleFiltered.freshness.fresh, false);
assert.equal(staleFiltered.batches.length, 0);
assert.equal(staleFiltered.qualified_legs.length, 0);

// Fresh artifact: only live, entirely future, fresh-price Desk batches survive.
const filtered = hooks.filterCurrentBuilderSnapshot(
  snapshot(-60_000, [
    deskBatch(),
    deskBatch([deskLeg({ start_time: iso(-60_000) })], { batch_id: 'DESK-BATCH-02' }),
    deskBatch([deskLeg({ market_odds_age_seconds: 901 })], { batch_id: 'DESK-BATCH-03' })
  ]),
  now
);
assert.equal(filtered.freshness.fresh, true);
assert.equal(filtered.batches.length, 1);
assert.equal(filtered.batches[0].batch_id, 'DESK-BATCH-01');

// Effective quote age is the original quote age plus the time elapsed since the
// Builder snapshot was generated; separate "fresh" flags must not hide an old price.
const combinedAgeFiltered = hooks.filterCurrentBuilderSnapshot(
  snapshot(-10 * 60_000, [
    deskBatch([deskLeg({ market_odds_age_seconds: 6 * 60 })], { batch_id: 'DESK-BATCH-OLD-QUOTE' })
  ]),
  now
);
assert.equal(combinedAgeFiltered.freshness.fresh, true);
assert.equal(combinedAgeFiltered.batches.length, 0);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ market_odds_age_seconds: 6 * 60 }), now, 10 * 60_000), false);
assert.equal(hooks.isCurrentBuilderLeg(deskLeg({ market_odds_age_seconds: 5 * 60 }), now, 10 * 60_000), true);

console.log('Odds Builder UI freshness passed: desk-only 60% gate, artifact expiry, future kickoffs, and combined snapshot-plus-quote age.');

assert.ok(source.includes('Exact-line walk-forward holdout'), 'Desk candidates must display the walk-forward evidence basis');
assert.ok(source.includes('recent_settled_line_side_loss_streak'), 'No-batch explanation must reveal recent settled-loss holds');
assert.ok(source.includes('data-builder-refresh'), 'Builder must include a usable manual refresh action');
assert.ok(source.includes('function checkBuilderBuildVersion'), 'Open Builder tabs must detect changed production build markers');
assert.ok(source.includes('window.setInterval(checkBuilderBuildVersion,60000)'), 'Open Builder tabs must poll for renderer deployments automatically');
