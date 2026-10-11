import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('expansion-odds-builder.js', 'utf8');
const start = source.indexOf('function qualificationMonitorHtml(data,visibleBatchCount) {');
const end = source.indexOf('function render(data, tracker) {', start);
assert.notEqual(start, -1, 'qualification monitor helper must exist');
assert.notEqual(end, -1, 'qualification monitor helper must end before render');
const helper = source.slice(start, end);

assert.match(helper, /Array\.isArray\(data\.best_available_legs\)/, 'monitor must read leg-level candidates');
assert.match(helper, /INDIVIDUAL GATES PASS/, 'monitor must distinguish an individually eligible leg from an eligible batch');
assert.match(helper, /NOT QUALIFIED/, 'monitor must retain an unqualified state for candidates that fail leg gates');
assert.match(helper, /Why it is not a qualified batch/, 'monitor must show per-candidate batch blockers');
assert.match(helper, /individual_leg_diagnostics/, 'monitor must display counts for individual gate results');
assert.match(helper, /65% per-leg and average floor/, 'monitor must explain the exact-evidence value lane floor');
assert.match(helper, /No booking code is created from this panel/, 'monitor must disclose no-booking behavior');
assert.match(helper, /if\(Number\(visibleBatchCount\|\|0\)>0\)return ''/, 'monitor must appear when no visible batch remains');
assert.doesNotMatch(helper, /requestBookingCode|ensureBookingCodes|GenUI|fetch\(/, 'monitor must not perform booking or network actions');

assert.match(source, /EFOOTBALL_EXACT_EVIDENCE_MIN_PROBABILITY = 0\.65/, 'exact-evidence batch guard must use the 65% lane floor');
assert.match(source, /function activeVirtualProbabilityFloor\(leg,batchLane\)/, 'front end must apply a lane-specific probability floor');
assert.match(source, /qualificationMonitorHtml\(data,batches\.length\)/, 'monitor visibility must use actually visible batches');
assert.match(source, /var ACTIVE_VIRTUAL_MIN_PROBABILITY = 0\.80/, 'standard/high-confidence lane must retain its 80% floor');
assert.match(source, /var PHASE2_CYCLICAL_MIN_PROBABILITY = 0\.78/, 'Phase 2 must retain its separate 78% confidence floor');

console.log('Qualification monitor and lane-specific floor contract tests passed.');
