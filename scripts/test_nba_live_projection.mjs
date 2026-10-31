import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("basketball-live.js", "utf8");
const start = source.indexOf("function statNumber(");
const end = source.indexOf("function liveHtml(){", start);
assert.ok(start >= 0 && end > start, "Live projection helpers must exist before the live desk renderer.");
const helperSource = source.slice(start, end);
const api = new Function("teamKey", helperSource + "\nreturn { liveTotalProjection, nbaPredictionFresh, teamPossessions, verifiedTotalRecord, nbaTotalsReleaseQualified, nbaTotalRowQualified };")(
  value => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
);
const stat = (name, displayValue, abbreviation) => ({ name, displayValue, abbreviation });
const record = {
  period: 2,
  clock: "06:00",
  home: { name: "Home", score: 45 },
  away: { name: "Away", score: 42 },
  team_statistics: [
    { team: { displayName: "Home" }, statistics: [
      stat("fieldGoalsMade-fieldGoalsAttempted", "18-40", "FG"),
      stat("freeThrowsMade-freeThrowsAttempted", "7-10", "FT"),
      stat("offensiveRebounds", "5", "OREB"),
      stat("totalTurnovers", "8", "TO")
    ] },
    { team: { displayName: "Away" }, statistics: [
      stat("fieldGoalsMade-fieldGoalsAttempted", "17-39", "FG"),
      stat("freeThrowsMade-freeThrowsAttempted", "6-8", "FT"),
      stat("offensiveRebounds", "4", "OREB"),
      stat("totalTurnovers", "7", "TO")
    ] }
  ]
};
const freshPrediction = { expected_total: 224.5, generated_at: new Date(Date.now() - 30 * 60 * 1000).toISOString() };
assert.equal(api.nbaPredictionFresh(freshPrediction).fresh, true);
assert.equal(api.nbaPredictionFresh({ expected_total: 224.5 }).fresh, false);
const stalePrediction = { expected_total: 224.5, generated_at: new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString() };
assert.equal(api.nbaPredictionFresh(stalePrediction).reason, "OLDER_THAN_SIX_HOURS");
assert.equal(api.liveTotalProjection(record, stalePrediction).status, "STALE_PREGAME_BASELINE");
const projection = api.liveTotalProjection(record, freshPrediction);
assert.equal(projection.status, "AVAILABLE");
assert.ok(projection.pregame_baseline_age_minutes >= 0 && projection.pregame_baseline_age_minutes <= 60);
assert.equal(projection.uses_live_boxscore_stats, true);
assert.equal(projection.projection_source, "ESPN_LIVE_BOXSCORE_POSSESSIONS_AND_SCORE_PACE");
assert.ok(projection.stats_summary.fields_used.includes("FGA"));
assert.ok(projection.stats_summary.fields_used.includes("turnovers"));
assert.ok(projection.live_total_estimate >= 206.5 && projection.live_total_estimate <= 242.5);
assert.equal(projection.qualification, "PAPER_RESEARCH_ONLY_NOT_BETTING_QUALIFIED");
assert.equal(api.liveTotalProjection({ ...record, period: 1, clock: "09:00" }, freshPrediction).status, "COLLECTING");
assert.equal(api.liveTotalProjection({ ...record, period: 5, clock: "04:00" }, freshPrediction).status, "OVERTIME_CONTEXT_ONLY");
const verified = {
  settled: true, publication_snapshot_verified: true, roi_eligible: true,
  quote_fresh_at_publication: true, price_pair_valid: true, price_source_verified: true,
  market_id: 225, pick: "over", result: "over"
};
assert.equal(api.verifiedTotalRecord(verified), true);
assert.equal(api.verifiedTotalRecord({ ...verified, publication_snapshot_verified: false }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, roi_eligible: false }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, quote_fresh_at_publication: false }), false);
const qualifiedTotalsEvidence = {
  evaluation_type: "NBA_TOTALS_WALK_FORWARD_V1", market_id: "225",
  market_definition: "full_game_total_including_overtime",
  model_version: "nba-total-v2-balanced-home-margin", release_decision: "QUALIFIED",
  walk_forward: { holdout: { n: 150, mae: 12.2, baseline_mae: 14.1, bias: 0.8 } },
  market_holdout: { n: 120, roi: 0.08, roi_ci95_lower: 0.02, roi_vs_market_favorite: 0.03 }
};
assert.equal(api.nbaTotalsReleaseQualified({ release_decision: "APPROVED", holdout: { n: 161, roi: 0.03, accuracy_delta: 0.01 } }), false, "moneyline evidence cannot qualify totals");
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, release_decision: "RESEARCH_ONLY" }), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, walk_forward: { holdout: { n: 99, mae: 12, baseline_mae: 14, bias: 0 } } }), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, market_holdout: { n: 99, roi: 0.08, roi_ci95_lower: 0.02, roi_vs_market_favorite: 0.03 } }), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, market_holdout: { n: 120, roi: 0.08, roi_ci95_lower: -0.01, roi_vs_market_favorite: 0.03 } }), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, market_holdout: { n: 120, roi: 0.08, roi_ci95_lower: 0.02, roi_vs_market_favorite: -0.01 } }), false);
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence), true);
assert.equal(api.nbaTotalRowQualified({ totals_model_version: "old-model", prediction_status: "BETTING_QUALIFIED", markets: { total_ou: { market_id: "225", prediction_status: "BETTING_QUALIFIED" } } }, qualifiedTotalsEvidence), false);
assert.equal(api.nbaTotalRowQualified({ totals_model_version: "nba-total-v2-balanced-home-margin", prediction_status: "live_experimental", markets: { total_ou: { market_id: "225", prediction_status: "LIVE_EXPERIMENTAL_NOT_QUALIFIED" } } }, qualifiedTotalsEvidence), false);
assert.equal(api.nbaTotalRowQualified({ totals_model_version: "nba-total-v2-balanced-home-margin", prediction_status: "BETTING_QUALIFIED", markets: { total_ou: { market_id: "225", prediction_status: "BETTING_QUALIFIED" } } }, { ...qualifiedTotalsEvidence, release_decision: "RESEARCH_ONLY" }), false);
assert.equal(api.nbaTotalRowQualified({ totals_model_version: "nba-total-v2-balanced-home-margin", prediction_status: "BETTING_QUALIFIED", markets: { total_ou: { market_id: "225", prediction_status: "BETTING_QUALIFIED" } } }, qualifiedTotalsEvidence), true);
assert.match(source, /RESEARCH ONLY · NO BETTING LEAN/);
assert.match(source, /Research-only model: no betting lean or builder action/);
assert.match(source, /NBA totals are research-only; this builder stays locked until the model passes strict out-of-sample validation\./);
console.log("NBA live projection and verified totals tests passed.");
