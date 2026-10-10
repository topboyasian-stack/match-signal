import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('expansion-odds-builder.js', 'utf8');
const start = source.indexOf('function qualificationMonitorHtml(data) {');
const end = source.indexOf('function render(data, tracker) {', start);
assert.notEqual(start, -1, 'qualification monitor helper must exist');
assert.notEqual(end, -1, 'qualification monitor helper must end before render');
const helper = source.slice(start, end);

assert.match(helper, /Array\.isArray\(data\.best_available_legs\)/, 'monitor must read informational near-miss rows');
assert.match(helper, /NOT QUALIFIED/, 'near-misses must be labeled unqualified');
assert.match(helper, /Why it is not a ticket/, 'monitor must show per-candidate reasons');
assert.match(helper, /Model probability is below the active 80% per-leg construction floor/, 'monitor must explain the probability floor');
assert.match(helper, /No independently proven profitable settled-ticket shape/, 'monitor must explain construction evidence blockers');
assert.match(helper, /No booking code is created from this panel/, 'monitor must disclose no-booking behavior');
assert.match(helper, /if\(activeBatches\.length\|\|Number\(data\.batch_count\|\|0\)>0\)return ''/, 'monitor must appear only when no batch exists');
assert.doesNotMatch(helper, /requestBookingCode|ensureBookingCodes|GenUI|fetch\(/, 'monitor must not perform booking or network actions');

console.log('Qualification monitor contract tests passed.');
