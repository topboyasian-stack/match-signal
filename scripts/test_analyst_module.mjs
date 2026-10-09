import assert from "node:assert/strict";
import {
  analyzeLeg,
  classifyLineAdjustment,
  emptyReviewDocument,
  evaluatePick,
  extractJsonObject,
  summarizeReviewDocument,
  summarizeDiagnosticFacts,
  sanitizeAnalystAnswer,
  validateReviewDocument
} from "../functions/_shared/analyst.mjs";

const stamp = "2026-10-09T10:00:00Z";
function makeLeg(actualPick, actualLine, deskPick, deskLine, home = 1, away = 1) {
  return {
    leg_ref: "leg_1",
    product: "vfootball",
    match: "Sample FC vs Example FC",
    actual_selection: { market: "total_goals_over_under", pick: actualPick, line: actualLine, odds: 1.5 },
    desk_snapshot: { market: "total_goals_over_under", provenance: "user_reported", pick: deskPick, line: deskLine, odds: 1.8, model_probability: 0.72, captured_at: stamp },
    final_score: { home: home, away: away },
    settled_at: stamp
  };
}
function makeDocument(oneLeg) {
  const document = emptyReviewDocument(stamp);
  document.tickets = [{
    ticket_ref: "private_ticket_1", captured_at: stamp, reported_ticket_outcome: "LOST",
    stake: 300, total_odds: 3.17, total_return: 0, currency: "NGN", legs: [oneLeg]
  }];
  return document;
}
let result = analyzeLeg(makeLeg("over", 1.5, "over", 2.5, 1, 1));
assert.equal(result.line_adjustment, "user_line_easier");
assert.equal(result.actual_result, "WON");
assert.equal(result.desk_result, "LOST");
assert.equal(result.counterfactual, "actual_selection_won_desk_did_not");
assert.equal(result.desk_snapshot_timing, "kickoff_time_missing");
const beforeKickoff = makeLeg("over", 2.5, "over", 1.5, 2, 1);
beforeKickoff.kickoff_at = "2026-10-09T10:30:00Z";
beforeKickoff.desk_snapshot.captured_at = "2026-10-09T10:00:00Z";
assert.equal(analyzeLeg(beforeKickoff).desk_snapshot_timing, "user_reported_pre_kickoff_time_unverified");
beforeKickoff.desk_snapshot.captured_at = "2026-10-09T10:45:00Z";
assert.equal(analyzeLeg(beforeKickoff).desk_snapshot_timing, "captured_after_kickoff");
result = analyzeLeg(makeLeg("under", 9.5, "under", 8.5, 7, 6));
assert.equal(result.line_adjustment, "user_line_easier");
assert.equal(result.actual_result, "LOST");
assert.equal(result.desk_result, "LOST");
assert.equal(classifyLineAdjustment({ pick: "under", line: 8.5 }, { pick: "under", line: 7.5 }), "user_line_harder");
assert.equal(classifyLineAdjustment({ pick: "over", line: 2.5 }, { pick: "under", line: 2.5 }), "side_changed");
assert.equal(evaluatePick("over", 2, { home: 1, away: 1 }), "PUSH");
assert.equal(evaluatePick("under", 2, { home: 1, away: 1 }), "PUSH");
const missingDesk = makeLeg("over", 1.5, "over", 2.5, 1, 1);
delete missingDesk.desk_snapshot;
assert.equal(analyzeLeg(missingDesk).line_adjustment, "desk_snapshot_missing");
assert.equal(analyzeLeg(missingDesk).counterfactual, "not_comparable");
const document = makeDocument(makeLeg("over", 1.5, "over", 2.5, 1, 1));
assert.deepEqual(validateReviewDocument(document), []);
const summary = summarizeReviewDocument(document);
assert.equal(summary.ticket_count, 1);
assert.equal(summary.actual_selection_outcomes.WON, 1);
assert.equal(summary.actual_leg_hit_rate_excluding_pushes, 1);
assert.equal(summary.desk_snapshot_timing.kickoff_time_missing, 1);
assert.equal(document.tickets[0].reported_ticket_outcome, "LOST");
const invalid = makeDocument(makeLeg("over", 1.5, "over", 2.5));
invalid.tickets[0].legs[0].actual_selection.odds = 1;
assert.ok(validateReviewDocument(invalid).some(function(error) { return error.includes("actual_selection.odds"); }));
const unexpectedField = makeDocument(makeLeg("over", 1.5, "over", 2.5));
unexpectedField.tickets[0].sportsbook_verification_code = "DO_NOT_ACCEPT";
assert.ok(validateReviewDocument(unexpectedField).some(function(error) { return error.includes("unsupported properties"); }));
const unsupportedProvenance = makeDocument(makeLeg("over", 1.5, "over", 2.5));
unsupportedProvenance.tickets[0].legs[0].desk_snapshot.provenance = "captured_live";
assert.ok(validateReviewDocument(unsupportedProvenance).some(function(error) { return error.includes("provenance"); }));
assert.equal(extractJsonObject('{"legs":[1]}').legs[0], 1);
assert.equal(extractJsonObject("there is no JSON here"), null);

const facts = summarizeDiagnosticFacts({
  collected_at: "2026-10-09T17:39:48.000Z",
  system_health: {
    generated_at: "2026-10-09T17:13:24.000Z", status: "DEGRADED",
    critical_issues: 0, warning_issues: 1, info_issues: 1,
    issue_count_by_severity: { critical: 0, warning: 1, info: 1, other: 0 },
    issues: [{ code: "TENNIS_FEED_EMPTY", severity: "warning" }, { code: "SELECTION_GATE_EMPTY", severity: "info" }]
  },
  core_pipeline: {
    updated_at: "2026-10-09T15:16:15.000Z", prediction_count: 120, football_count: 120, tennis_count: 0,
    error_count: 3, errors: ["source one", "source two", "tennis empty"],
    market_data: { matched: 58, unmatched: 62, football_events: 2000, tennis_events: 130, coverage: 0.4833 }
  },
  automation: { updated_at: "2026-10-09T16:36:08.000Z" },
  results_first_report: {
    generated_at: "2026-10-09T17:15:08.000Z",
    tracker_summary: { tracked_tickets: 100, pending: 68, won: 5, lost: 27, settled_tickets: 32, legs_won: 84, legs_lost: 36, legs_pending: 134 },
    settled_ou_legs: 98, settled_tickets_with_ou_legs: 32,
    ticket_shape_records: [
      { ticket_shape: "ou_legs_2", settled_tickets: 13, ticket_history: { n: 13, wins: 1, losses: 12, accuracy: 0.076923 } },
      { ticket_shape: "ou_legs_3", settled_tickets: 4, ticket_history: { n: 4, wins: 1, losses: 3, accuracy: 0.25 } }
    ],
    product_records: []
  },
  odds_builder: { generated_at: "2026-10-09T17:13:49.000Z", status: "VALUE_RESEARCH_SET", batch_count: 1, candidate_diagnostics: { evaluated: 1547, rejections: { LIVE_VALUE: 818, REJECTED: 729 } } },
  tennis_forward_status: {
    updated_at: "2026-10-09T06:33:27.000Z", window_days: 14, scope: "ATP/WTA singles only",
    tours: { ATP: { events_seen: 236, valid_singles: 0, new_predictions: 0, rejected: { "missing athlete id": 157, "non-singles draw": 79 }, error: null } }
  },
  prediction_desk: {
    generated_at: "2026-10-09T17:35:00.000Z", horizon_days: 7, event_count: 80, live_count: 4, pending_settlement_count: 0,
    publication_filters: { past_kickoff_rows_hidden: 13, stale_live_flags_hidden: 2, expired_settled_rows_hidden: 5 },
    high_line_under_evidence: [
      { product: "vfootball", line: 7.5, side: "under", event_rows: 4, walkforward_n: 10, walkforward_hit_rate: 1, walkforward_brier: 0.0006, walkforward_model_variant: "participant_model", qualification_status: "HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING", betting_qualified: false },
      { product: "vfootball", line: 8.5, side: "under", event_rows: 2, walkforward_n: 0, walkforward_hit_rate: null, walkforward_brier: null, walkforward_model_variant: null, qualification_status: "HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING", betting_qualified: false }
    ]
  }
}, new Date("2026-10-09T17:39:48.000Z"));
assert.equal(facts.system_health.issue_count_check, "MATCH");
assert.equal(facts.system_health.counted_issue_records_by_severity.critical, 0);
assert.equal(facts.pipeline.error_count, 3, "pipeline errors must use the source's exact count");
assert.equal(facts.pipeline.market_matching.coverage_denominator, 120);
assert.ok(Math.abs(facts.pipeline.market_matching.calculated_coverage - (58 / 120)) < 1e-6, "coverage is rounded to six decimal places");
assert.equal(facts.builder_ticket_results.settled_tickets, 32);
assert.equal(facts.builder_ticket_results.ticket_accuracy_excluding_pending, 0.15625);
assert.equal(facts.builder_ticket_results.ticket_shape_records[0].settled_tickets, 13);
assert.ok(facts.flags.some(function(flag) { return flag.includes("different cohort scopes"); }));
assert.equal(facts.artifacts.core_pipeline.status, "WITHIN_THRESHOLD");
assert.equal(facts.odds_builder.evaluated_candidates, 1547);
assert.equal(facts.odds_builder.live_value_candidates, 818);
assert.equal(facts.odds_builder.rejected_candidates, 729);
assert.ok(facts.flags.some(function(flag) { return flag.includes("TENNIS_FEED_EMPTY") && flag.includes("No current tennis predictions"); }));
assert.ok(facts.flags.some(function(flag) { return flag.toLowerCase().includes("tennis forward discovery") && flag.includes("cannot be treated as proof"); }));
assert.equal(facts.tennis_forward_discovery.tours.ATP.events_seen, 236);
assert.equal(facts.tennis_forward_discovery.tours.ATP.valid_singles, 0);
assert.ok(facts.flags.some(function(flag) { return flag.includes("VFootball Under 7.5") && flag.includes("10/30"); }));
assert.ok(facts.flags.some(function(flag) { return flag.includes("VFootball Under 8.5") && flag.includes("0/30"); }));
assert.equal(facts.prediction_desk.publication_filters.past_kickoff_rows_hidden, 13);
assert.equal(facts.artifacts.prediction_desk.status, "WITHIN_THRESHOLD");
const sanitizedAnswer = sanitizeAnalystAnswer("Finding: 3 pipeline errors.\n\nEvidence: ```json\n{\"private\":\"raw data\"}\n```");
assert.ok(sanitizedAnswer.includes("3 pipeline errors"));
assert.ok(!sanitizedAnswer.includes("raw data"));
assert.ok(sanitizedAnswer.includes("Raw JSON omitted"));
console.log("AI Analyst module tests passed.");
