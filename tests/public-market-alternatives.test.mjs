import test from "node:test";
import assert from "node:assert/strict";
import { onRequestGet } from "../functions/api/public/market-alternatives.js";

const future = new Date(Date.now() + 60 * 60 * 1000).toISOString();
const fresh = new Date(Date.now() - 60 * 1000).toISOString();
function candidate(overrides = {}) {
  return {
    sport: "football", event_id: "fixture-1", start_time: future,
    match: "Home FC vs Away FC", market: "total_goals", line: 2.5, pick: "over",
    model_probability: 0.71, bookmaker_odds: 1.82, quote_timestamp: fresh,
    sportybet_event_id: "sr:match:123", sportybet_market_id: "18",
    prediction_role: "ALTERNATIVE", alternative_source: "SYSTEM_RECOMMENDED",
    passed_builder_gates: true, fresh_exact_quote: true,
    private_model_detail: "must never escape", raw_probability_vector: { p1: 0.2 },
    ...overrides
  };
}
async function call(records) {
  return onRequestGet({
    request: new Request("https://example.test/api/public/market-alternatives"),
    env: { MATCH_SIGNAL_ANALYST_STORE: { get: async () => JSON.stringify({
      record_type: "cross_sport_market_reassessment", updated_at: fresh, records
    }) } }
  });
}

test("public endpoint returns whitelisted Builder-qualified future alternatives", async () => {
  const response = await call([candidate()]);
  const payload = await response.json();
  assert.equal(response.status, 200);
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].probability, 0.71);
  assert.equal(payload.alternatives[0].builder_qualified, true);
  assert.equal(payload.alternatives[0].qualification_status, "BUILDER_QUALIFIED");
  assert.equal(payload.diagnostics.records_seen, 1);
  assert.equal(payload.diagnostics.role_source_match, 1);
  assert.equal(payload.diagnostics.marked_fresh_exact_quote, 1);
  assert.equal(payload.diagnostics.quote_fresh_within_15_minutes, 1);
  assert.equal(payload.diagnostics.public_schema_valid, 1);
  assert.equal(payload.diagnostics.selected_alternatives, 1);
  assert.equal("private_model_detail" in payload.alternatives[0], false);
  assert.equal("raw_probability_vector" in payload.alternatives[0], false);
});

test("empty private evidence keeps the same public probability contract", async () => {
  const response = await onRequestGet({
    request: new Request("https://example.test/api/public/market-alternatives"),
    env: { MATCH_SIGNAL_ANALYST_STORE: { get: async () => null } }
  });
  const payload = await response.json();
  assert.equal(response.status, 200);
  assert.equal(payload.status, "EMPTY");
  assert.equal(payload.min_probability, 0.55);
  assert.equal(payload.builder_min_probability, 0.65);
  assert.deepEqual(payload.alternatives, []);
});

test("fixture participants are split correctly for selectable winner alternatives", async () => {
  const response = await call([candidate({ market: "winner", market_label: "Winner", pick: "p2", line: null })]);
  const payload = await response.json();
  assert.equal(payload.alternatives[0].player_1, "Home FC");
  assert.equal(payload.alternatives[0].player_2, "Away FC");
});

test("Builder qualification keeps the 65% floor while linked research alternatives use 55%", async () => {
  const base = candidate({
    passed_builder_gates: false,
    model_probability: 0.60,
    original_pick: "p1",
    primary_prediction_id: "fixture-primary",
    candidate_status: "RESEARCH_ONLY"
  });
  const response = await call([base]);
  const payload = await response.json();
  assert.equal(payload.min_probability, 0.55);
  assert.equal(payload.builder_min_probability, 0.65);
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].builder_qualified, false);
  assert.equal(payload.alternatives[0].qualification_status, "RESEARCH_ONLY");

  const rejected = await call([
    candidate({ model_probability: 0.64 }),
    { ...base, original_pick: "", primary_prediction_id: "" },
    { ...base, model_probability: 0.54 },
    { ...base, quote_timestamp: new Date(Date.now() - 16 * 60 * 1000).toISOString() },
    { ...base, start_time: new Date(Date.now() - 1000).toISOString() },
    candidate({ passed_builder_gates: true, model_probability: 0.64 })
  ]);
  const rejectedPayload = await rejected.json();
  assert.equal(rejectedPayload.alternatives.length, 0);
  assert.equal(rejectedPayload.status, "EMPTY");
  assert.equal(rejectedPayload.diagnostics.records_seen, 6);
  assert.equal(rejectedPayload.diagnostics.rejected_by_reason.below_probability_floor_or_invalid_probability, 3);
  assert.equal(rejectedPayload.diagnostics.rejected_by_reason.missing_primary_link, 1);
  assert.equal(rejectedPayload.diagnostics.rejected_by_reason.quote_older_than_15_minutes, 1);
  assert.equal(rejectedPayload.diagnostics.rejected_by_reason.kickoff_within_two_minutes_or_started, 1);
});

test("at most two distinct market alternatives are returned per fixture", async () => {
  const response = await call([
    candidate(),
    candidate({ pick: "under", model_probability: 0.73 }),
    candidate({ market: "1X2", line: null, pick: "p1", model_probability: 0.69, sportybet_market_id: "1" }),
    candidate({ event_id: "fixture-2", pick: "under", model_probability: 0.68 })
  ]);
  const payload = await response.json();
  const first = payload.alternatives.filter(x => x.event_id === "fixture-1");
  assert.equal(first.length, 2);
  assert.equal(first.some(x => x.market === "total" && x.pick === "over" && x.line === 2.5) &&
    first.some(x => x.market === "total" && x.pick === "under" && x.line === 2.5), false);
  assert.equal(payload.alternatives.filter(x => x.event_id === "fixture-2").length, 1);
});


test("eFootball virtual_total audit records are published using exact product and ticket identity", async () => {
  const response = await call([candidate({
    sport: "virtual", product: "efootball_gt", market: "virtual_total", line: 8.5,
    pick: "over", sportybet_event_id: "sporty-virtual-77", sportybet_market_id: "18",
    match: "GT Home vs GT Away"
  })]);
  const payload = await response.json();
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].sport, "efootball");
  assert.equal(payload.alternatives[0].market, "total");
  assert.equal(payload.alternatives[0].market_id, "18");
  assert.equal(payload.alternatives[0].sportybet_event_id, "sporty-virtual-77");
  assert.equal(payload.alternatives[0].product, "efootball_gt");
});

test("qualified eFootball alternatives retain the exact product and ticket identity", async () => {
  const response = await call([candidate({
    sport: "virtual", product: "efootball_gt", market: "total_ou", line: 8.5,
    pick: "under", sportybet_event_id: undefined, sportybet_market_id: "18",
    match: "GT Home vs GT Away"
  })]);
  const payload = await response.json();
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].sport, "efootball");
  assert.equal(payload.alternatives[0].product, "efootball_gt");
  assert.equal(payload.alternatives[0].sportybet_event_id, "fixture-1");
});
