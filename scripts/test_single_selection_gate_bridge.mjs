#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("sport-hubs.js", "utf8");
function extractFunction(name) {
  const match = source.match(new RegExp(
    `function ${name}\\(x\\)\\{[\\s\\S]*?\\n\\}`
  ));
  assert.ok(match, `Missing ${name} in sport-hubs.js`);
  return match[0];
}

const context = {};
vm.runInNewContext(
  [
    extractFunction("isOverUnderPrediction"),
    extractFunction("singleSelectionGateKey"),
    "this.singleSelectionGateKey = singleSelectionGateKey;"
  ].join("\n"),
  context
);
const key = context.singleSelectionGateKey;

const selectedWinner = { sport: "tennis", event_id: "186477", pick: "p1" };
const candidateWinner = {
  sport: "tennis", event_id: "186477", market: "winner",
  sportybet_odds_market: "winner", sportybet_odds_side: "p1", pick: "p1"
};
assert.equal(key(selectedWinner), key(candidateWinner));

const selectedTotal = {
  sport: "tennis", event_id: "tennis-1", pick: "over",
  analytics: { total_games: { line: 21.5 } }
};
const candidateTotal = {
  sport: "tennis", event_id: "tennis-1", market: "over_under",
  line: 21.5, pick: "over", sportybet_odds_market: "total"
};
assert.equal(key(selectedTotal), key(candidateTotal));
assert.notEqual(key(selectedTotal), key({ ...candidateTotal, line: 22.5 }));
assert.notEqual(key(selectedTotal), key({ ...candidateTotal, pick: "under" }));
assert.notEqual(key(candidateWinner), key({ ...candidateWinner, sport: "basketball" }));
assert.notEqual(key(candidateWinner), key({ ...candidateWinner, event_id: "186478" }));

assert.match(source, /get\('\.\/data\/selection_gate_selected\.json'\)/);
assert.match(source, /qualifiedBestSourceIsFresh\(singleSelectionGateStatus\?\.generated_at\)/);
assert.match(source, /const selectionKey=singleSelectionGateKey\(x\);/);
assert.match(source, /singleSelectionGateMap\.get\(selectionKey\)/);
assert.match(source, /const singleSelectionGatePassed=x\?\.single_selection_gate\?\.status==="passed"&&x\?\.single_selection_gate\?\.mode==="PAPER_ONLY"/);

// The candidate quote must be copied onto the Unified Upcoming row before
// Qualified Best runs its exact SportyBet freshness check.
const evidenceMatch = source.match(/function attachSingleSelectionMarketEvidence\(row, gate, candidate\)\{[\s\S]*?\n\}/);
assert.ok(evidenceMatch, "Missing selected market-evidence bridge");
const quoteMatch = source.match(/function exactSportyBetQuote\(x\)\{[\s\S]*?\n\}/);
assert.ok(quoteMatch, "Missing exact SportyBet quote gate");
const evidenceContext = {};
vm.runInNewContext(
  [
    extractFunction("isOverUnderPrediction"),
    evidenceMatch[0],
    quoteMatch[0],
    "this.attachSingleSelectionMarketEvidence = attachSingleSelectionMarketEvidence;",
    "this.exactSportyBetQuote = exactSportyBetQuote;"
  ].join("\n"),
  evidenceContext
);
const freshTimestamp = new Date().toISOString();
const displayRow = {
  sport: "tennis",
  event_id: "186477",
  market: "winner",
  pick: "p1",
  bookmaker_odds: null
};
const selectedGateRow = {
  confidence: 0.736,
  market_odds_timestamp: freshTimestamp,
  sportybet_winner_odds: { p1: 1.39, p2: 3.15, market_id: "186" },
  market_insights: {
    snapshot_at: freshTimestamp,
    winner_book_odds: 1.39,
    winner_model_edge_vs_market: 0.099467,
    winner_expected_value: 0.102687,
    winner_value_signal: true
  }
};
const staleTimestamp = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
const exactCandidate = {
  sport: "tennis",
  event_id: "186477",
  market: "winner",
  pick: "p1",
  bookmaker_odds: 1.11,
  sportybet_odds_market: "winner",
  sportybet_odds_side: "p1",
  sportybet_winner_odds: { p1: 1.11, p2: 8.0 },
  market_odds_timestamp: staleTimestamp,
  odds_timestamp: staleTimestamp,
  model_edge_vs_market: -0.2,
  expected_value: -0.3,
  value_signal: false
};
evidenceContext.attachSingleSelectionMarketEvidence(displayRow, selectedGateRow, exactCandidate);
assert.equal(displayRow.bookmaker_odds, 1.39);
assert.equal(displayRow.sportybet_odds_market, "winner");
assert.equal(displayRow.sportybet_odds_side, "p1");
assert.equal(displayRow.market_odds_timestamp, freshTimestamp);
assert.equal(displayRow.odds_timestamp, freshTimestamp);
assert.equal(displayRow.sportybet_winner_odds.p2, 3.15);
assert.equal(displayRow.value_signal, true);
assert.ok(displayRow.model_edge_vs_market > 0);
assert.ok(displayRow.expected_value > 0);
const exactQuote = evidenceContext.exactSportyBetQuote(displayRow);
assert.equal(exactQuote.reason, "EXACT_MARKET_LINE_SIDE_FRESH");
assert.equal(exactQuote.fresh, true);
assert.equal(exactQuote.odds, 1.39);

console.log("Independent single-selection gate exact-identity and isolation tests passed.");
