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

// The selected artifact may have no explicit market property on winner rows;
// the candidate pool does. Both must resolve to the same exact winner key.
const selectedWinner = {
  sport: "tennis",
  event_id: "186477",
  pick: "p1"
};
const candidateWinner = {
  sport: "tennis",
  event_id: "186477",
  market: "winner",
  sportybet_odds_market: "winner",
  sportybet_odds_side: "p1",
  pick: "p1"
};
assert.equal(key(selectedWinner), key(candidateWinner));

// A total market must include its exact line. Adjacent lines and opposite
// selections are deliberately different keys.
const selectedTotal = {
  sport: "tennis",
  event_id: "tennis-1",
  pick: "over",
  analytics: { total_games: { line: 21.5 } }
};
const candidateTotal = {
  sport: "tennis",
  event_id: "tennis-1",
  market: "over_under",
  line: 21.5,
  pick: "over",
  sportybet_odds_market: "total"
};
assert.equal(key(selectedTotal), key(candidateTotal));
assert.notEqual(key(selectedTotal), key({ ...candidateTotal, line: 22.5 }));
assert.notEqual(key(selectedTotal), key({ ...candidateTotal, pick: "under" }));
assert.notEqual(key(candidateWinner), key({ ...candidateWinner, sport: "basketball" }));
assert.notEqual(key(candidateWinner), key({ ...candidateWinner, event_id: "186478" }));

// The UI must read the selected artifact through the independent gate, require
// a fresh gate report, and never translate that flag into Builder eligibility.
assert.match(source, /get\('\.\/data\/selection_gate_selected\.json'\)/);
assert.match(source, /qualifiedBestSourceIsFresh\(singleSelectionGateStatus\?\.generated_at\)/);
assert.match(source, /singleSelectionGateMap\.get\(singleSelectionGateKey\(x\)\)/);
assert.match(source, /singleSelectionGatePassed=x\?\.single_selection_gate\?\.status==="passed"/);
assert.match(source, /const singleSelectionGatePassed=x\?\.single_selection_gate\?\.status==="passed"&&x\?\.single_selection_gate\?\.mode==="PAPER_ONLY"/);

console.log("Independent single-selection gate exact-identity and isolation tests passed.");
