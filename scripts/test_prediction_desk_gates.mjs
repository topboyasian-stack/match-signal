import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../sport-hubs.js", import.meta.url), "utf8");
const start = source.indexOf("function isOverUnderPrediction(x){");
const end = source.indexOf("function ladderAnchor(rows){", start);
assert.ok(start >= 0 && end > start, "production desk gate functions are extractable");

const sandbox = { Date, Number, String, Math, Array, Boolean, Object, Map, Set, RegExp };
vm.createContext(sandbox);
vm.runInContext(
  source.slice(start, end) +
    "\n;globalThis.__deskTestApi={exactVirtualMarketLine,exactSportyBetQuote,exactMarketEdge,exactMarketExpectedReturn,qualificationState,primaryPrediction,qualifiedBestSelections,rawProbabilityValue,probabilityCalibrationInfo,probabilityValue,displayedFairOddsValue,isVirtualDeskCandidate};",
  sandbox,
  { filename: "sport-hubs.js#prediction-desk-gates" }
);
const { exactVirtualMarketLine, qualificationState, primaryPrediction, qualifiedBestSelections, rawProbabilityValue, probabilityCalibrationInfo, probabilityValue, displayedFairOddsValue, exactMarketExpectedReturn, isVirtualDeskCandidate } = sandbox.__deskTestApi;

function row(overrides = {}) {
  return {
    event_id: "fixture-1",
    start_time: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    sport: "football",
    league: "Regression Cup",
    player_1: "Alpha",
    player_2: "Beta",
    market: "over_under",
    line: 2.5,
    pick: "over",
    probability: 0.65,
    betting_qualified: true,
    qualified_for_builder: false,
    qualification_status: "BETTING_QUALIFIED_PAPER",
    bookmaker_odds: 1.9,
    sportybet_odds: 1.9,
    sportybet_odds_market: "total",
    sportybet_odds_line: 2.5,
    sportybet_odds_side: "over",
    sportybet_over_odds: 1.9,
    sportybet_under_odds: 2.0,
    market_odds_timestamp: new Date(Date.now() - 60 * 1000).toISOString(),
    ...overrides
  };
}

const valid = row();
assert.equal(qualificationState(valid).currentPricePass, true, "fresh exact-line value can pass");

// A positive model-vs-no-vig edge alone can still have negative expected return
// at the actual offered odds. Qualified Best must require BOTH checks.
const positiveMarketEdgeNegativeEV = row({
  probability: 0.65,
  bookmaker_odds: 1.42,
  sportybet_odds: 1.42,
  sportybet_over_odds: 1.42,
  sportybet_under_odds: 2.35,
  sportybet_odds_side: "over"
});
const quotedPrice = { odds: 1.42 };
assert.ok(exactMarketEdge(positiveMarketEdgeNegativeEV, quotedPrice) >= 0.02, "fixture demonstrates a >=2% edge versus de-vigged market");
assert.ok(exactMarketExpectedReturn(positiveMarketEdgeNegativeEV, quotedPrice) < 0, "same estimate has negative expected return at offered odds");
assert.equal(qualificationState(positiveMarketEdgeNegativeEV).currentPricePass, false, "a market edge cannot override negative price EV");
assert.equal(qualificationState(positiveMarketEdgeNegativeEV).reason, "CURRENT_PRICE_EV_BELOW_2_PERCENT");
assert.equal(qualifiedBestSelections([positiveMarketEdgeNegativeEV], Date.now()).rows.length, 0, "negative-EV selection must not enter Qualified Best");

const profitablePrice = row({
  probability: 0.65,
  bookmaker_odds: 1.9,
  sportybet_odds: 1.9,
  sportybet_over_odds: 1.9,
  sportybet_under_odds: 2.0,
  sportybet_odds_side: "over"
});
assert.ok(exactMarketExpectedReturn(profitablePrice, { odds: 1.9 }) >= 0.02, "positive expected-return example clears the economic threshold");
assert.equal(qualificationState(profitablePrice).currentPricePass, true, "selection must pass both value gates");

// A flag or candidate label must not override an explicit watch/not-qualified status.
const watchOnly = row({
  qualification_status: "TENNIS_FORWARD_WATCH_NOT_QUALIFIED",
  candidate_status: "BETTING_QUALIFIED_PAPER",
  betting_qualified: true,
  qualified_for_builder: true
});
assert.equal(qualificationState(watchOnly).modelQualified, false, "watch status vetoes model qualification");
assert.equal(qualificationState(watchOnly).currentPricePass, false, "watch status cannot enter the qualified list");
assert.equal(qualificationState(watchOnly).reason, "EXPLICIT_QUALIFICATION_VETO");

// Model estimate bands alone do not qualify a row.
const estimateOnly = row({
  qualification_status: "MODEL_90_PLUS",
  candidate_status: "MODEL_90_PLUS",
  betting_qualified: false,
  qualified_for_builder: false
});
assert.equal(qualificationState(estimateOnly).currentPricePass, false, "high probability is not the qualification gate");
assert.equal(qualificationState(estimateOnly).reason, "MODEL_GATE_NOT_PASSED");

// Quotes on a neighbouring line and stale quotes must fail closed.
const wrongLine = row({ sportybet_odds_line: 3.5 });
assert.equal(qualificationState(wrongLine).currentPricePass, false, "wrong totals line cannot qualify");
assert.equal(qualificationState(wrongLine).reason, "LINE_MISMATCH");
const stale = row({ market_odds_timestamp: new Date(Date.now() - 21 * 60 * 1000).toISOString() });
assert.equal(qualificationState(stale).currentPricePass, false, "stale SportyBet quote cannot qualify");
assert.equal(qualificationState(stale).reason, "QUOTE_STALE");

// Primary fixture display prioritizes a genuinely price-qualified exact line over a high but stale estimate.
const staleHigh = row({
  pick: "under",
  probability: 0.97,
  bookmaker_odds: 1.9,
  sportybet_odds: 1.9,
  sportybet_odds_side: "under",
  sportybet_over_odds: 2.0,
  sportybet_under_odds: 1.9,
  market_odds_timestamp: new Date(Date.now() - 21 * 60 * 1000).toISOString()
});
const passingLowerEstimate = row({ probability: 0.70 });
assert.equal(primaryPrediction([staleHigh, passingLowerEstimate]).pick, "over", "a stale high model rating must not hide a passing exact-price line");

// The shortlist contains one passing selection per fixture, uses upcoming rows only, and excludes research-only VFootball.
const best = qualifiedBestSelections([staleHigh, passingLowerEstimate], Date.now());
assert.equal(best.rows.length, 1, "one best qualified selection per fixture");
assert.equal(best.rows[0].pick, "over", "qualified shortlist selects the current-price pass");
const past = row({ start_time: new Date(Date.now() - 60 * 1000).toISOString() });
assert.equal(qualifiedBestSelections([past], Date.now()).rows.length, 0, "past-kickoff rows never enter Qualified Best");
const vfootball = row({ sport: "virtual", product: "vfootball", event_id: "vfb-1" });
assert.equal(qualifiedBestSelections([vfootball], Date.now()).rows.length, 0, "VFootball remains outside active qualified Desk scope");
 
// Upstream-qualified eFootball rows below the 80% discovery threshold must still
// reach the exact-price gate. Model-only rows below 80% stay out of that lane.
const qualifiedSeventy = {
  ...row({
    sport: "virtual", product: "efootball_gt", probability: 0.7117,
    line: 7.5, pick: "under", event_id: "efootball-qualified-71",
    sportybet_odds_line: 7.5, sportybet_odds_side: "under",
    bookmaker_odds: 1.9, sportybet_odds: 1.9,
    sportybet_over_odds: 2.0, sportybet_under_odds: 1.9
  }),
  betting_qualified: true,
  qualified_for_builder: true,
  qualification_status: "BETTING_QUALIFIED_PAPER_DIRECTIONAL"
};
assert.equal(isVirtualDeskCandidate(qualifiedSeventy), true, "an upstream-qualified 71% eFootball candidate must reach the exact-price gate");
assert.equal(qualificationState(qualifiedSeventy).currentPricePass, true, "the sub-80% row still has to pass an exact fresh-price gate");
assert.equal(qualifiedBestSelections([qualifiedSeventy], Date.now()).rows.length, 1, "a fully price-validated sub-80% paper-qualified candidate can enter Qualified Best");
assert.equal(isVirtualDeskCandidate({ ...qualifiedSeventy, betting_qualified: false, qualified_for_builder: false, qualification_status: "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING" }), false, "a sub-80% pending research candidate is not promoted");

const overconfidentUnder = {
  ...row({ sport: "virtual", product: "efootball_gt", probability: 0.9614, line: 10.5, pick: "under", event_id: "efootball-under-105" }),
  walkforward_exact_line_n: 69,
  walkforward_exact_line_hit_rate: 0.5652173913043478
};
const calibration = probabilityCalibrationInfo(overconfidentUnder);
assert.ok(calibration, "adequately sampled exact-line walk-forward evidence enables conservative Desk blending");
assert.ok(probabilityValue(overconfidentUnder) < 0.70, "a 96% raw estimate with a 56.5% historical hit rate must not remain near-certain");
assert.ok(probabilityValue(overconfidentUnder) < rawProbabilityValue(overconfidentUnder), "poor exact-line outcomes must pull the Desk estimate down");
assert.equal(calibration.n, 69, "calibration labels retain their evidence sample size");
assert.ok(Math.abs(displayedFairOddsValue(overconfidentUnder)-(1/probabilityValue(overconfidentUnder)))<1e-9, "fair odds must agree with the calibrated Desk estimate");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, walkforward_exact_line_hit_rate: null }), null, "a null hit rate is not treated as 0% evidence");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, walkforward_exact_line_n: null }), null, "a null sample count cannot unlock calibration");

const pendingDirectional = {
  ...overconfidentUnder,
  betting_qualified: false,
  qualified_for_builder: false,
  qualification_status: "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING"
};
assert.equal(qualificationState(pendingDirectional).currentPricePass, false, "calibration never bypasses an upstream directional validation gate");
assert.equal(qualificationState(pendingDirectional).reason, "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING", "the Desk should explain the actual blocker instead of a generic model gate");

// Parse only an explicit total/line provider specifier when market.line is absent.
assert.equal(exactVirtualMarketLine({ specifier: "total=7.5" }), 7.5, "provider total specifier is recognized");
assert.equal(exactVirtualMarketLine({ specifier: "total=7.5", line: 8.5 }), 8.5, "explicit market.line takes precedence");
assert.equal(exactVirtualMarketLine({ specifier: "period=1" }), null, "unrelated specifier is not treated as a totals line");

console.log("Prediction Desk gate regressions passed: explicit status veto, probability-band separation, exact line/side, 15-minute freshness, qualified-first ranking, future-only shortlist, active virtual scope, and provider specifier normalization.");
