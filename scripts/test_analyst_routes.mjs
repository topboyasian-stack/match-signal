import assert from "node:assert/strict";
import { onRequestGet, onRequestPut, onRequestDelete } from "../functions/api/analyst/records.js";
import { validateDocument } from "../functions/api/analyst/market-evidence.js";
import { buildPublicAlternatives } from "../functions/api/public/market-alternatives.js";

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

const alternativesNow = Date.parse("2026-11-07T12:00:00.000Z");
function alternativeRecord(overrides = {}) {
  return {
    sport: "football",
    market: "total_goals",
    pick: "under",
    line: 3.5,
    event_id: "fixture-alt-1",
    sportybet_event_id: "sporty-event-1",
    sportybet_market_id: "18",
    start_time: new Date(alternativesNow + 3 * 60 * 60 * 1000).toISOString(),
    match: "Home FC vs Away FC",
    model_probability: 0.83,
    bookmaker_odds: 1.42,
    quote_timestamp: new Date(alternativesNow - 30 * 1000).toISOString(),
    fresh_exact_quote: true,
    passed_builder_gates: false,
    prediction_role: "ALTERNATIVE",
    alternative_source: "SYSTEM_RECOMMENDED",
    original_pick: "p1",
    ...overrides
  };
}

const independentAlternatives = buildPublicAlternatives({
  record_type: "cross_sport_market_reassessment",
  generated_at: new Date(alternativesNow).toISOString(),
  records: [
    // The primary winner pick must not be repeated as an "alternative".
    alternativeRecord({
      market: "1X2", pick: "p1", line: null, sportybet_market_id: "1",
      model_probability: 0.91, bookmaker_odds: 1.45, original_pick: "p1"
    }),
    alternativeRecord({ pick: "under", line: 3.5, model_probability: 0.83 }),
    // Different line on the same event: retained as a separate viable option.
    alternativeRecord({ pick: "over", line: 2.5, model_probability: 0.78, bookmaker_odds: 1.88 }),
    // Exact same market/line should not displace the two distinct best options.
    alternativeRecord({ pick: "over", line: 3.5, model_probability: 0.82, bookmaker_odds: 1.75 }),
    // Never publish a stale quote, a fixture about to start, or a sub-floor probability.
    alternativeRecord({
      event_id: "stale-fixture",
      quote_timestamp: new Date(alternativesNow - 901 * 1000).toISOString()
    }),
    alternativeRecord({
      event_id: "started-fixture",
      start_time: new Date(alternativesNow + 60 * 1000).toISOString()
    }),
    alternativeRecord({ event_id: "below-research-floor", model_probability: 0.54 })
  ]
}, alternativesNow);

assert.equal(independentAlternatives.status, "OK");
const fixtureOptions = independentAlternatives.alternatives.filter(row => row.event_id === "fixture-alt-1");
assert.equal(fixtureOptions.length, 2, "the publisher must limit each fixture to two distinct options");
assert.deepEqual(
  fixtureOptions.map(row => [row.pick, row.line]),
  [["under", 3.5], ["over", 3.5]],
  "the two highest-probability distinct options should be selected for the fixture"
);
const staleResearch = independentAlternatives.alternatives.find(row => row.event_id === "stale-fixture");
assert.ok(staleResearch, "stale quote candidates stay visible as research instead of disappearing");
assert.equal(staleResearch.quote_status, "STALE");
assert.equal(staleResearch.builder_qualified, false, "stale quotes cannot be Builder-qualified");
const belowBaselineResearch = independentAlternatives.alternatives.find(row => row.event_id === "below-research-floor");
assert.ok(belowBaselineResearch, "lower-probability alternatives stay visible for research");
assert.equal(belowBaselineResearch.below_research_baseline, true);
assert.equal(belowBaselineResearch.builder_qualified, false);
assert.equal(
  independentAlternatives.alternatives.some(row => row.event_id === "started-fixture"),
  false,
  "fixtures within two minutes of kickoff or already started must stay hidden"
);

const primaryIdLinked = buildPublicAlternatives({
  record_type: "cross_sport_market_reassessment",
  generated_at: new Date(alternativesNow).toISOString(),
  records: [
    alternativeRecord({
      event_id: "football-alt-with-primary-id",
      market: "1X2",
      pick: "p2",
      line: null,
      sportybet_market_id: "1",
      original_pick: "",
      primary_prediction_id: "primary-football-fixture-id",
      model_probability: 0.71,
      passed_builder_gates: false
    })
  ]
}, alternativesNow);
assert.equal(
  primaryIdLinked.alternatives.length,
  1,
  "a market alternative linked to the primary prediction ID must appear even when original_pick is absent and the accumulator gate failed"
);
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
        match_observations: [
          { observed_at: "2026-10-09T10:02:00Z", phase: "PRE_MATCH", home: 0, away: 0, source: "user_reported" },
          { observed_at: "2026-10-09T10:05:00Z", phase: "IN_PLAY", home: 1, away: 0, source: "user_reported" },
          { observed_at: "2026-10-09T10:07:00Z", phase: "HALF_TIME", home: 1, away: 1, source: "user_reported" }
        ],
        final_score: { home: 1, away: 1 },
        settled_at: "2026-10-09T10:10:00Z"
      }, {
        leg_ref: "leg_2",
        product: "tennis",
        match: "Wallin vs Sonego",
        actual_selection: { market: "total_games_over_under", pick: "over", line: 18.5, odds: 1.46 },
        final_score: { sets: [{ home: 6, away: 4 }, { home: 6, away: 2 }] },
        qualification_state: "NOT_QUALIFIED"
      }]
    }]
  };
}


const validAlternativeDoc = {
  record_type: "cross_sport_market_reassessment",
  mode: "PAPER_ONLY",
  records: [{
    snapshot_id: "a".repeat(24),
    sport: "football",
    event_id: "football-event-1",
    market: "1X2",
    pick: "p2",
    quote_timestamp: "2026-11-07T23:40:00Z",
    start_time: "2026-11-08T12:00:00Z",
    model_probability: 0.71,
    bookmaker_odds: 1.72,
    settlement_status: "PENDING",
    prediction_role: "ALTERNATIVE",
    alternative_source: "SYSTEM_RECOMMENDED",
    primary_prediction_id: "b".repeat(24)
  }]
};
assert.deepEqual(validateDocument(validAlternativeDoc), [], "a same-fixture alternative linked by primary prediction ID is valid");
const invalidPrimaryLink = structuredClone(validAlternativeDoc);
invalidPrimaryLink.records[0].primary_prediction_id = "not-a-primary-id";
assert.ok(
  validateDocument(invalidPrimaryLink).includes("records[0].primary_prediction_id is invalid"),
  "malformed primary prediction links must not be persisted"
);
const invalidRole = structuredClone(validAlternativeDoc);
invalidRole.records[0].prediction_role = "PRIMARY";
assert.ok(
  validateDocument(invalidRole).includes("records[0].prediction_role is invalid"),
  "only alternative records may be published in the alternatives evidence stream"
);

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
assert.equal(saved.summary.leg_count, 2, "private storage preserves every leg from a lost accumulator");
assert.equal(saved.summary.actual_selection_outcomes.LOST, 1, "the second tennis leg is independently scored");
assert.equal(saved.summary.outcome_by_qualification_state.NOT_QUALIFIED.LOST, 1, "qualification label stays separate from the leg result");

response = await onRequestPut(context("PUT", draft, { "If-Match": initialRevision }, store));
assert.equal(response.status, 409, "stale revision should not overwrite an updated ledger");

response = await onRequestGet(context("GET", undefined, {}, store));
assert.equal(response.status, 200);
const persisted = await payload(response);
assert.equal(persisted.document.tickets.length, 1);
assert.equal(persisted.document.tickets[0].ticket_ref, "ticket_internal_1");
assert.equal(persisted.document.tickets[0].legs.length, 2, "all mixed-sport legs are persisted independently");
const persistedTimeline = persisted.document.tickets[0].legs[0].match_observations;
assert.equal(persistedTimeline.length, 3, "timestamped match-state observations survive KV write/read");
assert.deepEqual(persistedTimeline.map(item => item.phase), ["PRE_MATCH", "IN_PLAY", "HALF_TIME"]);
assert.deepEqual(persisted.document.tickets[0].legs[0].final_score, { home: 1, away: 1 }, "final settlement remains separate from in-play observations");

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
