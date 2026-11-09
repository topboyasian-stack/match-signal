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
  assert.equal(payload.alternatives[0].ticket_selectable, true);
  assert.equal(payload.alternatives[0].quote_status, "FRESH_EXACT");
  assert.equal(payload.alternatives[0].qualification_status, "BUILDER_QUALIFIED");
  assert.equal(payload.alternatives[0].primary_comparison_status, "PRIMARY_PROBABILITY_UNAVAILABLE");
  assert.equal(payload.diagnostics.records_seen, 1);
  assert.equal(payload.diagnostics.role_source_match, 1);
  assert.equal(payload.diagnostics.marked_fresh_exact_quote, 1);
  assert.equal(payload.diagnostics.quote_fresh_within_15_minutes, 1);
  assert.equal(payload.diagnostics.public_schema_valid, 1);
  assert.equal(payload.diagnostics.selected_alternatives, 1);
  assert.equal("private_model_detail" in payload.alternatives[0], false);
  assert.equal("raw_probability_vector" in payload.alternatives[0], false);
});

test("empty private evidence declares display baseline separately from qualification", async () => {
  const response = await onRequestGet({
    request: new Request("https://example.test/api/public/market-alternatives"),
    env: { MATCH_SIGNAL_ANALYST_STORE: { get: async () => null } }
  });
  const payload = await response.json();
  assert.equal(response.status, 200);
  assert.equal(payload.status, "EMPTY");
  assert.equal(payload.min_probability, 0);
  assert.equal(payload.research_display_baseline, 0.55);
  assert.equal(payload.builder_min_probability, 0.65);
  assert.deepEqual(payload.alternatives, []);
});

test("fixture participants are split correctly for selectable winner alternatives", async () => {
  const response = await call([candidate({
    market: "winner", pick: "p2", line: null, sportybet_market_id: "1"
  })]);
  const payload = await response.json();
  assert.equal(payload.alternatives[0].player_1, "Home FC");
  assert.equal(payload.alternatives[0].player_2, "Away FC");
  assert.equal(payload.alternatives[0].ticket_selectable, true);
});

test("lower-probability research candidates remain visible below the display baseline", async () => {
  const response = await call([candidate({
    passed_builder_gates: false,
    model_probability: 0.42,
    original_pick: "p1",
    primary_prediction_id: "fixture-primary"
  })]);
  const payload = await response.json();
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].probability, 0.42);
  assert.equal(payload.alternatives[0].below_research_baseline, true);
  assert.equal(payload.alternatives[0].builder_qualified, false);
  assert.equal(payload.alternatives[0].qualification_status, "RESEARCH_ONLY_BELOW_BASELINE");
});

test("stale and unverified quotes remain visible but cannot be Builder-qualified", async () => {
  const stale = candidate({
    event_id: "stale-fixture",
    quote_timestamp: new Date(Date.now() - 16 * 60 * 1000).toISOString(),
    passed_builder_gates: true
  });
  const unverified = candidate({
    event_id: "unverified-fixture",
    fresh_exact_quote: false,
    passed_builder_gates: true
  });
  const payload = await (await call([stale, unverified])).json();
  assert.equal(payload.alternatives.length, 2);
  const staleRow = payload.alternatives.find(x => x.event_id === "stale-fixture");
  const unverifiedRow = payload.alternatives.find(x => x.event_id === "unverified-fixture");
  assert.equal(staleRow.quote_status, "STALE");
  assert.equal(staleRow.builder_qualified, false);
  assert.equal(staleRow.qualification_status, "RESEARCH_ONLY_QUOTE_NOT_CURRENT");
  assert.equal(unverifiedRow.quote_status, "NOT_MARKED_EXACT");
  assert.equal(unverifiedRow.builder_qualified, false);
  assert.equal(unverifiedRow.ticket_selectable, true);
});

test("alternatives must beat a known primary probability and must not echo the same market pick", async () => {
  const better = candidate({
    event_id: "better",
    model_probability: 0.64,
    passed_builder_gates: false,
    original_primary_pick: "p1",
    original_primary_market: "winner",
    original_primary_probability: 0.60
  });
  const worse = candidate({
    event_id: "worse",
    model_probability: 0.59,
    passed_builder_gates: false,
    original_primary_pick: "p1",
    original_primary_market: "winner",
    original_primary_probability: 0.60
  });
  const samePick = candidate({
    event_id: "same-pick",
    model_probability: 0.80,
    passed_builder_gates: false,
    original_primary_pick: "over",
    original_primary_market: "total_goals",
    original_primary_line: 2.5,
    original_primary_probability: 0.60
  });
  const payload = await (await call([better, worse, samePick])).json();
  assert.deepEqual(payload.alternatives.map(x => x.event_id), ["better"]);
  assert.equal(payload.alternatives[0].primary_comparison_status, "MORE_LIKELY_THAN_PRIMARY");
  assert.equal(payload.diagnostics.rejected_by_reason.not_more_likely_than_primary, 1);
  assert.equal(payload.diagnostics.rejected_by_reason.repeats_primary_pick, 1);
});

test("a missing exact side price remains visible but cannot claim a fresh quote", async () => {
  const payload = await (await call([candidate({
    event_id: "no-price",
    bookmaker_odds: null,
    passed_builder_gates: true
  })])).json();
  assert.equal(payload.alternatives.length, 1);
  assert.equal(payload.alternatives[0].odds, null);
  assert.equal(payload.alternatives[0].quote_status, "PRICE_UNAVAILABLE");
  assert.equal(payload.alternatives[0].ticket_selectable, true);
  assert.equal(payload.alternatives[0].builder_qualified, false);
});

test("BTTS and double-chance remain visible but are not offered as unsupported ticket buttons", async () => {
  const btts = candidate({
    event_id: "btts-fixture", market: "btts", line: null, pick: "yes",
    sportybet_market_id: "55", model_probability: 0.68
  });
  const doubleChance = candidate({
    event_id: "dc-fixture", market: "double_chance", line: null, pick: "1x",
    sportybet_market_id: "13", model_probability: 0.67
  });
  const payload = await (await call([btts, doubleChance])).json();
  assert.equal(payload.alternatives.length, 2);
  const bttsRow = payload.alternatives.find(x => x.event_id === "btts-fixture");
  const dcRow = payload.alternatives.find(x => x.event_id === "dc-fixture");
  assert.equal(bttsRow.market, "btts");
  assert.equal(bttsRow.ticket_selectable, false);
  assert.equal(dcRow.market, "double_chance");
  assert.equal(dcRow.ticket_selectable, false);
});

test("opposite Over and Under alternatives on one exact line are not collapsed", async () => {
  const over = candidate({
    pick: "over", model_probability: 0.71, original_primary_pick: "p1",
    original_primary_market: "winner", original_primary_probability: 0.60
  });
  const under = candidate({
    pick: "under", model_probability: 0.73, original_primary_pick: "p1",
    original_primary_market: "winner", original_primary_probability: 0.60
  });
  const response = await call([over, under]);
  const payload = await response.json();
  const first = payload.alternatives.filter(x => x.event_id === "fixture-1");
  assert.equal(first.length, 2);
  assert.ok(first.some(x => x.market === "total" && x.pick === "over" && x.line === 2.5));
  assert.ok(first.some(x => x.market === "total" && x.pick === "under" && x.line === 2.5));
});

test("publisher returns at most two options per fixture while retaining other fixtures", async () => {
  const response = await call([
    candidate({ pick: "over", model_probability: 0.71, original_primary_pick: "p1", original_primary_market: "winner", original_primary_probability: 0.60 }),
    candidate({ pick: "under", model_probability: 0.73, original_primary_pick: "p1", original_primary_market: "winner", original_primary_probability: 0.60 }),
    candidate({ market: "1X2", line: null, pick: "p1", model_probability: 0.69, sportybet_market_id: "1", original_primary_pick: "p2", original_primary_market: "winner", original_primary_probability: 0.60 }),
    candidate({ event_id: "fixture-2", pick: "under", model_probability: 0.68 })
  ]);
  const payload = await response.json();
  assert.equal(payload.alternatives.filter(x => x.event_id === "fixture-1").length, 2);
  assert.equal(payload.alternatives.filter(x => x.event_id === "fixture-2").length, 1);
});

test("eFootball virtual_total audit records retain exact product and ticket identity", async () => {
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
  assert.equal(payload.alternatives[0].ticket_selectable, true);
});

test("eFootball alternatives keep exact product and fallback event identity", async () => {
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
