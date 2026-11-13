import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { nbaTotalsReleaseQualified as serverNbaTotalsReleaseQualified, nbaTotalTicketLegQualified as serverNbaTotalTicketLegQualified } from "../functions/api/sportybet-booking.js";

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
  market_id: 225, sportybet_event_id: "sr:match:test", quote_capture_basis: "SportyBet API response observed_at", pick: "over", result: "over"
};
assert.equal(api.verifiedTotalRecord(verified), true);
assert.equal(api.verifiedTotalRecord({ ...verified, publication_snapshot_verified: false }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, roi_eligible: false }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, quote_fresh_at_publication: false }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, sportybet_event_id: "" }), false);
assert.equal(api.verifiedTotalRecord({ ...verified, quote_capture_basis: "unknown" }), false);
const cutoff = "2026-11-02T02:00:00+00:00";
const modelVersion = "nba-total-v5.1-pace-efficiency-calibrated";
const now = Date.now();
const startTime = new Date(now + 2 * 60 * 60 * 1000).toISOString();
const quoteTimestamp = new Date(now - 2 * 60 * 1000).toISOString();
const publishedAt = new Date(now - 2 * 60 * 1000 + 3000).toISOString();
const reportAt = new Date(now - 60 * 1000).toISOString();
const qualifiedAudit = Array.from({ length: 120 }, (_, index) => {
  const eventId = `settled-${index + 1}`;
  return {
    event_id: eventId,
    publication_snapshot_id: `nba-total-pub:${eventId}`,
    selected_side: "OVER",
    sportybet_market_225_line: 220.5,
    over_odds: 1.91,
    under_odds: 1.89,
    selected_side_odds: 1.91
  };
});
const qualifiedTotalsEvidence = {
  generated_at: reportAt,
  paper_only: true, evaluation_type: "NBA_TOTALS_FIXED_CUTOFF_V2", market_id: "225",
  market_definition: "full_game_total_including_overtime", model_version: modelVersion,
  holdout_protocol: { fixed_cutoff_utc: cutoff }, release_decision: "QUALIFIED",
  walk_forward: { holdout: { n: 150, mae: 12.2, baseline_mae: 14.1, bias: 0.8 } },
  market_holdout: { n: 120, roi: 0.08, roi_ci95_lower: 0.02, roi_vs_market_favorite: 0.03 },
  market_record_audit: qualifiedAudit
};
const diagnostic = {
  event_id: "nba-1", start_time: startTime, quote_timestamp: quoteTimestamp,
  forecast_total: 224.5, sportybet_line: 220.5, over_odds: 1.91, under_odds: 1.89,
  calibration_check: "PASS", decision: "OVER VALUE",
  bootstrap_95_lower_bound: { over_probability_edge: 0.05, over_expected_value: 0.04 }
};
const qualifiedProbabilityEvidence = {
  paper_only: true, experiment: "NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V3",
  model_version: modelVersion, model_projection_market_blind: true,
  prospective_holdout_cutoff_utc: cutoff, prospective_holdout_used_for_calibration: false,
  live_value_decisions_authorized: false, generated_at: reportAt,
  calibration_protocol: { probability_edge_threshold: 0.04, expected_value_threshold: 0.03 },
  prospective_pregame_snapshot_coverage: {
    cutoff_utc: cutoff, prospective_settled_unique_market_selections: 120,
    prospective_settled_selections_with_exact_snapshot_match: 120,
    prospective_settled_selections_missing_or_mismatched_snapshot: 0,
    snapshot_linkage_complete_for_settled_selections: true
  },
  prospective_probability_fixture_coverage: {
    cutoff_utc: cutoff, valid_unique_settled_fixtures: 30, binary_scored_unique_fixtures: 30,
    snapshot_linkage_failure_count: 0, sample_threshold_met: true
  },
  prospective_probability_score_summary: { n: 30, sufficient_for_probability_validation: true },
  prospective_minimum_sample_reached: true, prospective_probability_validation_sample_met: true,
  prospective_clv_release_check_passed: true,
  prospective_clv_diagnostics: {
    near_close_observations: 10, mean_probability_clv: 0.01, mean_line_clv_points: 0.5,
    positive_clv_release_check_passed: true,
    fixtures: qualifiedAudit.map(row => ({
      event_id: row.event_id,
      selected_side: row.selected_side,
      opening: {
        snapshot_id: row.publication_snapshot_id,
        line: row.sportybet_market_225_line,
        over_odds: row.over_odds,
        under_odds: row.under_odds
      }
    }))
  },
  upcoming_exact_fresh_market_225_value_diagnostics: [diagnostic]
};
const prediction = {
  event_id: "nba-1", start_time: startTime, expected_total: 224.5, paper_only: true,
  totals_model_version: modelVersion,
  markets: { total_ou: {
    market_id: "225", source: "SportyBet Nigeria",
    quote_capture_basis: "SportyBet API response observed_at",
    sportybet_event_id: "sr:match:test", quote_timestamp: quoteTimestamp,
    line: 220.5, over_odds: 1.91, under_odds: 1.89, pick: "over"
  }}
};
const snapshot = {
  event_id: "nba-1", start_time: startTime, published_at: publishedAt,
  expected_total: 224.5, totals_model_version: modelVersion,
  publication_snapshot_id: "nba-total-pub:test", publication_snapshot_verified: true,
  publication_snapshot_kind: "immutable_sportybet_market_225_revision",
  markets: { total_ou: {
    market_id: "225", source: "SportyBet Nigeria",
    quote_capture_basis: "SportyBet API response observed_at",
    sportybet_event_id: "sr:match:test", quote_timestamp: quoteTimestamp,
    line: 220.5, over_odds: 1.91, under_odds: 1.89, pick: "over", expected_total: 224.5
  }}
};
const currentMarket = {
  line: 220.5, over: 1.91, under: 1.89, fetched: now - 30000, fresh: true,
  event: { event_id: "sr:match:test" }
};
assert.equal(api.nbaTotalsReleaseQualified({ release_decision: "APPROVED", holdout: { n: 161, roi: 0.03 } }, qualifiedProbabilityEvidence), false, "moneyline evidence cannot qualify totals");
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, qualifiedProbabilityEvidence), true);
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, {
  ...qualifiedProbabilityEvidence,
  prospective_clv_diagnostics: {
    ...qualifiedProbabilityEvidence.prospective_clv_diagnostics,
    fixtures: qualifiedProbabilityEvidence.prospective_clv_diagnostics.fixtures.map((row, index) =>
      index === 0 ? { ...row, opening: { ...row.opening, snapshot_id: "nba-total-pub:wrong-snapshot" } } : row
    )
  }
}), false, "the Basketball UI must reject mismatched ROI/CLV snapshot cohorts");
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, qualifiedProbabilityEvidence, {
  updated_at: new Date(now).toISOString()
}, {
  checked_at: new Date(now).toISOString()
}), false, "the Basketball UI must reject reports older than the latest ledger/capture state");
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence), false, "probability and CLV evidence are mandatory");
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, evaluation_type: "NBA_TOTALS_WALK_FORWARD_V1" }, qualifiedProbabilityEvidence), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, holdout_protocol: { fixed_cutoff_utc: "2026-11-03T02:00:00+00:00" } }, qualifiedProbabilityEvidence), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, release_decision: "RESEARCH_ONLY" }, qualifiedProbabilityEvidence), false);
assert.equal(api.nbaTotalsReleaseQualified({ ...qualifiedTotalsEvidence, walk_forward: { holdout: { n: 99, mae: 12, baseline_mae: 14, bias: 0 } } }, qualifiedProbabilityEvidence), false);
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, { ...qualifiedProbabilityEvidence, prospective_probability_score_summary: { n: 29, sufficient_for_probability_validation: false } }), false);
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, { ...qualifiedProbabilityEvidence, prospective_clv_release_check_passed: false }), false);
assert.equal(api.nbaTotalsReleaseQualified(qualifiedTotalsEvidence, { ...qualifiedProbabilityEvidence, prospective_clv_diagnostics: { ...qualifiedProbabilityEvidence.prospective_clv_diagnostics, mean_line_clv_points: -0.1 } }), false);
assert.equal(api.nbaTotalRowQualified(prediction, qualifiedTotalsEvidence, qualifiedProbabilityEvidence, [snapshot], currentMarket), true);
assert.equal(api.nbaTotalRowQualified(prediction, qualifiedTotalsEvidence, qualifiedProbabilityEvidence, [], currentMarket), false, "an immutable exact quote snapshot is required");
assert.equal(api.nbaTotalRowQualified(prediction, qualifiedTotalsEvidence, qualifiedProbabilityEvidence, [snapshot], { ...currentMarket, over: 1.90 }), false, "changed live prices must fail closed");
assert.equal(api.nbaTotalRowQualified(prediction, qualifiedTotalsEvidence, { ...qualifiedProbabilityEvidence, upcoming_exact_fresh_market_225_value_diagnostics: [{ ...diagnostic, decision: "UNDER VALUE" }] }, [snapshot], currentMarket), false, "the side must match the value decision");
const ticketLeg = { event_id: "nba-1", sportybet_event_id: "sr:match:test", sport: "basketball", market: "total", pick: "over", line: 220.5, market_id: "225", model_qualified: true, start_time: startTime };
const liveSelection = { eventId: "sr:match:test", marketId: "225", line: 220.5, overOdds: 1.91, underOdds: 1.89, odds: 1.91, fetchedAt: new Date(now - 30000).toISOString() };
const releaseContext = { evidence: qualifiedTotalsEvidence, probability: qualifiedProbabilityEvidence, predictions: [prediction], snapshots: [snapshot], sourceEvidenceFresh: true };
assert.equal(serverNbaTotalsReleaseQualified(qualifiedTotalsEvidence, qualifiedProbabilityEvidence, true), true);
assert.equal(serverNbaTotalsReleaseQualified(qualifiedTotalsEvidence, {
  ...qualifiedProbabilityEvidence,
  prospective_probability_fixture_coverage: {
    ...qualifiedProbabilityEvidence.prospective_probability_fixture_coverage,
    cutoff_utc: "2026-11-03T02:00:00+00:00"
  }
}, true), false, "probability fixtures from another cutoff must not qualify the frozen holdout");
assert.equal(serverNbaTotalTicketLegQualified(ticketLeg, liveSelection, releaseContext, now).ok, true);
assert.equal(serverNbaTotalTicketLegQualified({ ...ticketLeg, sportybet_event_id: "sr:match:wrong" }, liveSelection, releaseContext, now).ok, false, "the provider event ID must match the immutable SportyBet quote");
assert.equal(serverNbaTotalTicketLegQualified(ticketLeg, { ...liveSelection, overOdds: 1.90 }, releaseContext, now).ok, false, "the server must reject a changed current price pair");
assert.equal(serverNbaTotalTicketLegQualified(ticketLeg, liveSelection, { ...releaseContext, snapshots: [] }, now).ok, false, "the server must require an immutable snapshot");
assert.equal(serverNbaTotalTicketLegQualified({ ...ticketLeg, pick: "under" }, liveSelection, releaseContext, now).ok, false, "the server must reject a side that differs from the value-qualified side");
assert.equal(api.nbaTotalRowQualified({ ...prediction, totals_model_version: "old-model" }, qualifiedTotalsEvidence, qualifiedProbabilityEvidence, [snapshot], currentMarket), false);
assert.equal(api.nbaTotalRowQualified({ ...prediction, markets: { total_ou: { ...prediction.markets.total_ou, quote_timestamp: new Date(now - 16 * 60 * 1000).toISOString() } } }, qualifiedTotalsEvidence, qualifiedProbabilityEvidence, [snapshot], currentMarket), false, "stale quotes must fail closed");
assert.match(source, /RESEARCH ONLY · NO BETTING LEAN/);
assert.match(source, /Independent NBA release\/row gate has not passed/);
assert.match(source, /data-ticket-model-qualified/);
assert.match(source, /canGenerate=qualified&&releaseQualified/);
console.log("NBA live projection and verified totals tests passed.");
