import assert from "node:assert/strict";
import { onRequestGet, onRequestPut, onRequestDelete } from "../functions/api/analyst/records.js";

const token = "analyst-test-token-" + "a".repeat(48);
const origin = "https://match-signal.test";
class MemoryKV {
  constructor() { this.items = new Map(); }
  async get(key) { return this.items.has(key) ? this.items.get(key) : null; }
  async put(key, value) { this.items.set(key, value); }
  async delete(key) { this.items.delete(key); }
}
function context(method, body, headers, store) {
  return {
    request: new Request(origin + "/api/analyst/records", {
      method: method,
      headers: Object.assign({
        "Authorization": "Bearer " + token,
        "Origin": origin
      }, headers || {}),
      body: body === undefined ? undefined : JSON.stringify(body)
    }),
    env: { MATCH_SIGNAL_ANALYST_TOKEN: token, MATCH_SIGNAL_ANALYST_STORE: store }
  };
}
async function payload(response) { return await response.json(); }
function documentWithTicket() {
  return {
    schema_version: 1,
    record_type: "private_user_ticket_review",
    mode: "PRIVATE_USER_EVIDENCE",
    updated_at: "1970-01-01T00:00:00.000Z",
    tickets: [{
      ticket_ref: "ticket_internal_1",
      captured_at: "2026-10-09T10:00:00Z",
      reported_ticket_outcome: "LOST",
      legs: [{
        leg_ref: "leg_1",
        product: "vfootball",
        match: "Sample FC vs Example FC",
        actual_selection: { market: "total_goals_over_under", pick: "over", line: 1.5, odds: 1.5 },
        final_score: { home: 1, away: 1 },
        settled_at: "2026-10-09T10:10:00Z"
      }]
    }]
  };
}

const store = new MemoryKV();
let response = await onRequestGet(context("GET", undefined, { "Authorization": "Bearer wrong-token" }, store));
assert.equal(response.status, 401, "private records require the correct token");

response = await onRequestGet({
  request: new Request(origin + "/api/analyst/records", { headers: { "Authorization": "Bearer " + token, "Origin": "https://attacker.test" } }),
  env: { MATCH_SIGNAL_ANALYST_TOKEN: token, MATCH_SIGNAL_ANALYST_STORE: store }
});
assert.equal(response.status, 403, "cross-origin requests are rejected");

response = await onRequestGet(context("GET", undefined, {}, store));
assert.equal(response.status, 200);
const empty = await payload(response);
assert.equal(empty.document.tickets.length, 0);
const initialRevision = empty.document.updated_at;
assert.equal(initialRevision, "1970-01-01T00:00:00.000Z", "empty ledger revision is stable");

const draft = documentWithTicket();
response = await onRequestPut(context("PUT", draft, {}, store));
assert.equal(response.status, 428, "writes require revision precondition");

response = await onRequestPut(context("PUT", draft, { "If-Match": initialRevision }, store));
assert.equal(response.status, 200, "first reviewed write should succeed");
const saved = await payload(response);
assert.equal(saved.status, "SAVED");
assert.equal(saved.summary.ticket_count, 1);
assert.equal(saved.summary.actual_selection_outcomes.WON, 1);

response = await onRequestPut(context("PUT", draft, { "If-Match": initialRevision }, store));
assert.equal(response.status, 409, "stale revision should not overwrite an updated ledger");

response = await onRequestGet(context("GET", undefined, {}, store));
assert.equal(response.status, 200);
const persisted = await payload(response);
assert.equal(persisted.document.tickets.length, 1);
assert.equal(persisted.document.tickets[0].ticket_ref, "ticket_internal_1");

const invalid = documentWithTicket();
invalid.tickets[0].unrecognised_verification_code = "MUST_NOT_STORE";
response = await onRequestPut(context("PUT", invalid, { "If-Match": persisted.document.updated_at }, store));
assert.equal(response.status, 400, "unknown fields must be rejected");

response = await onRequestDelete(context("DELETE", undefined, {}, store));
assert.equal(response.status, 200);
assert.equal((await payload(response)).status, "DELETED");
response = await onRequestGet(context("GET", undefined, {}, store));
assert.equal((await payload(response)).document.tickets.length, 0);

console.log("Analyst route tests passed: auth, origin check, private persistence, validation, revision guard and delete.");
