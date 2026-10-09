#!/usr/bin/env node
"use strict";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("sport-hubs.js", "utf8");
const css = fs.readFileSync("sport-hubs.css", "utf8");
const start = source.indexOf("function isOverUnderPrediction(x)");
const end = source.indexOf("function qualificationState(x)", start);
assert.ok(start >= 0 && end > start, "quote contract helpers must remain in the public Desk bundle");
const helperSource = source.slice(start, end);
const context = {};
vm.runInNewContext(helperSource + "\nthis.quoteContract={isOverUnderPrediction,exactSportyBetQuote};", context);
const quote = context.quoteContract.exactSportyBetQuote;
const now = Date.now();
function row(overrides = {}) {
  return {
    market: "over_under",
    pick: "under",
    line: 7.5,
    bookmaker_odds: 1.72,
    sportybet_odds: 1.72,
    sportybet_odds_market: "total",
    sportybet_odds_line: 7.5,
    sportybet_odds_side: "under",
    sportybet_over_odds: 2.10,
    sportybet_under_odds: 1.72,
    market_odds_timestamp: new Date(now - 20 * 60 * 1000).toISOString(),
    ...overrides,
  };
}

// A stale but exact market/line/side match remains visible as a last-seen
// reference; it is deliberately not returned as a current odds value.
const stale = quote(row());
assert.equal(stale.odds, null);
assert.equal(stale.displayOdds, 1.72);
assert.equal(stale.reason, "QUOTE_STALE");
assert.equal(stale.fresh, false);

// A missing timestamp does not erase a precisely matched price, but cannot
// be promoted to a current quote.
const unverifiedTimestamp = quote(row({ market_odds_timestamp: null, odds_timestamp: null }));
assert.equal(unverifiedTimestamp.odds, null);
assert.equal(unverifiedTimestamp.displayOdds, 1.72);
assert.equal(unverifiedTimestamp.reason, "TIMESTAMP_UNVERIFIED");

// A recent exact quote can be considered for the current price gate.
const fresh = quote(row({ market_odds_timestamp: new Date(now - 3 * 60 * 1000).toISOString() }));
assert.equal(fresh.odds, 1.72);
assert.equal(fresh.displayOdds, 1.72);
assert.equal(fresh.reason, "EXACT_MARKET_LINE_SIDE_FRESH");
assert.equal(fresh.fresh, true);

// A neighbouring line or opposite side is not the selected quote and must
// never be shown as if it priced the prediction.
const wrongLine = quote(row({ sportybet_odds_line: 8.5 }));
assert.equal(wrongLine.displayOdds, null);
assert.equal(wrongLine.reason, "LINE_MISMATCH");
const wrongSide = quote(row({ sportybet_odds_side: "over" }));
assert.equal(wrongSide.displayOdds, null);
assert.equal(wrongSide.reason, "SIDE_MISMATCH");

// Display-only reference odds must remain separate from current-edge logic.
assert.match(source, /const displayBook=quote\.displayOdds==null\?book:quote\.displayOdds;/);
assert.match(source, /const edge=exactMarketEdge\(x,quote\);/);
assert.match(source, /SportyBet last seen @/);
assert.match(source, /NOT ACTIONABLE · PRICE STALE/);
assert.doesNotMatch(source, /MODEL GATE PASSED · PRICE STALE/);
assert.match(source, /generatedEl\.textContent=new Date\(generatedAt\)\.toLocaleString/);
assert.match(source, /qualificationState\(row\)\.currentPricePass/);
assert.doesNotMatch(source, /class="ms-up-qual /);
assert.doesNotMatch(source, /class="ms-market-q /);
assert.match(css, /\.ms-book-stale\{[^}]*var\(--ms-amber\)/);
console.log("Prediction Desk exact-line quote contract and de-duplicated status assertions passed.");
