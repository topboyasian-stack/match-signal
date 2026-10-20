import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/sportybet-booking.js';

const batches = [
  { batch_id: 'BATCH-01', legs: [] },
  { batch_id: 'DESK-BATCH-01', legs: [] }
];

async function post(batchId) {
  const request = new Request('https://match-signal.test/api/sportybet-booking', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch_id: batchId })
  });
  const response = await onRequest({
    request,
    env: {
      ASSETS: {
        fetch: async () => new Response(JSON.stringify({ mode: 'PAPER_ONLY', batches }), {
          headers: { 'Content-Type': 'application/json' }
        })
      }
    }
  });
  return { status: response.status, payload: await response.json() };
}

for (const batchId of ['BATCH-01', 'DESK-BATCH-01']) {
  const result = await post(batchId);
  assert.equal(result.status, 422, `${batchId} should resolve before empty-batch validation`);
  assert.equal(result.payload.error, 'EMPTY_BATCH', `${batchId} must not be rejected as an invalid ID`);
  assert.equal(result.payload.batch_id, batchId);
}

const invalid = await post('DESK-BATCH-001');
assert.equal(invalid.status, 400);
assert.equal(invalid.payload.error, 'INVALID_BATCH_ID');

const missing = await post('DESK-BATCH-02');
assert.equal(missing.status, 404);
assert.equal(missing.payload.error, 'BATCH_NOT_FOUND');

console.log('SportyBet booking batch-ID contract passed: standard, Desk, malformed, and missing IDs.');
