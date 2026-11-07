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

test("public endpoint returns only whitelisted qualified future alternatives", async () => {
  const response = await call([candidate()]);
  const payload = await response.json();
  assert.equal(response.status, 200);
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].probability, 0.71);
  assert.equal("private_model_detail" in payload.alternatives[0], false);
  assert.equal("raw_probability_vector" in payload.alternatives[0], false);
});

test("stale, weak, unqualified and already-started alternatives are withheld", async () => {
  const response = await call([
    candidate({ model_probability: 0.64 }),
    candidate({ passed_builder_gates: false }),
    candidate({ quote_timestamp: new Date(Date.now() - 16 * 60 * 1000).toISOString() }),
    candidate({ start_time: new Date(Date.now() - 1000).toISOString() })
  ]);
  const payload = await response.json();
  assert.equal(payload.alternatives.length, 0);
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
