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
assert.equal(classifyLineAdjustment({ market: "total_goals_over_under", pick: "over", line: 2.5 }, { market: "total_games_over_under", pick: "over", line: 18.5 }), "market_changed");
assert.equal(evaluatePick("over", 18.5, { sets: [{ home: 6, away: 4 }, { home: 6, away: 2 }] }, "total_games_over_under"), "LOST");
assert.equal(evaluatePick("under", 18.5, { sets: [{ home: 6, away: 4 }, { home: 6, away: 2 }] }, "total_games_over_under"), "WON");
assert.equal(evaluatePick("p2", null, { sets: [{ home: 6, away: 4 }, { home: 4, away: 6 }, { home: 6, away: 3 }] }, "match_winner"), "LOST");

const mixedTicketDocument = makeDocument({
  leg_ref: "leg_1", product: "tennis", match: "Wallin vs Sonego",
  actual_selection: { market: "total_games_over_under", pick: "over", line: 18.5, odds: 1.46 },
  final_score: { sets: [{ home: 6, away: 4 }, { home: 6, away: 2 }] },
  qualification_state: "NOT_QUALIFIED"
});
mixedTicketDocument.tickets[0].reported_ticket_outcome = "LOST";
mixedTicketDocument.tickets[0].legs.push({
  leg_ref: "leg_2", product: "tennis", match: "Shelton vs Van Assche",
  actual_selection: { market: "match_winner", pick: "p2", odds: 1.27 },
  final_score: { sets: [{ home: 6, away: 4 }, { home: 4, away: 6 }, { home: 6, away: 3 }] },
  qualification_state: "QUALIFIED"
});
mixedTicketDocument.tickets[0].legs.push({
  leg_ref: "leg_3", product: "football", match: "Example FC vs Sample FC",
  actual_selection: { market: "total_goals_over_under", pick: "over", line: 1.5, odds: 1.2 },
  final_score: { home: 2, away: 1 },
  qualification_state: "NOT_QUALIFIED"
});
mixedTicketDocument.tickets[0].legs.push({
  leg_ref: "leg_4", product: "tennis", match: "Live match pending",
  actual_selection: { market: "total_games_over_under", pick: "over", line: 18.5, odds: 1.4 },
  leg_outcome: "PENDING", leg_outcome_source: "user_reported",
  qualification_state: "UNKNOWN"
});
assert.deepEqual(validateReviewDocument(mixedTicketDocument), [], "mixed-market user tickets and independently tracked leg outcomes must validate");
const mixedSummary = summarizeReviewDocument(mixedTicketDocument);
assert.equal(mixedSummary.ticket_count, 1);
assert.equal(mixedSummary.leg_count, 4);
assert.equal(mixedSummary.actual_selection_outcomes.WON, 1);
assert.equal(mixedSummary.actual_selection_outcomes.LOST, 2);
assert.equal(mixedSummary.actual_selection_outcomes.PENDING, 1);
assert.equal(mixedSummary.outcome_by_qualification_state.NOT_QUALIFIED.WON, 1);
assert.equal(mixedSummary.outcome_by_qualification_state.NOT_QUALIFIED.LOST, 1);
assert.equal(mixedSummary.outcome_by_qualification_state.UNKNOWN.PENDING, 1);
assert.equal(mixedSummary.actual_leg_hit_rate_excluding_pushes, 0.3333);
assert.ok(mixedSummary.interpretation_guard.includes("independently"));

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
    issues: [{ code: "TENNIS_FEED_EMPTY", severity: "warning", detail: "No current tennis predictions are published" }, { code: "SELECTION_GATE_EMPTY", severity: "info", detail: "Selected-candidate layer returned zero qualified selections" }]
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
    status: "GENERATED",
    generated_at: "2026-10-09T17:35:00.000Z", horizon_days: 7, event_count: 80, live_count: 4, pending_settlement_count: 0,
    publication_filters: { past_kickoff_rows_hidden: 13, stale_live_flags_hidden: 2, expired_settled_rows_hidden: 5 },
    high_line_under_evidence: [
      { product: "vfootball", line: 7.5, side: "under", event_rows: 4, walkforward_n: 10, walkforward_hit_rate: 1, walkforward_brier: 0.0006, walkforward_model_variant: "participant_model", qualification_status: "HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING", betting_qualified: false },
      { product: "vfootball", line: 8.5, side: "under", event_rows: 2, walkforward_n: 0, walkforward_hit_rate: null, walkforward_brier: null, walkforward_model_variant: null, qualification_status: "HIGH_LINE_UNDER_EVIDENCE_GATE_PENDING", betting_qualified: false },
      { product: "efootball_gt", line: 10.5, side: "under", event_rows: 3, walkforward_n: 69, walkforward_hit_rate: 0.5652, walkforward_brier: 0.2617, walkforward_model_variant: "participant_model", qualification_status: "BETTING_QUALIFIED_PAPER", betting_qualified: true }
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
assert.ok(!facts.flags.some(function(flag) { return flag.includes("VFootball Under 10.5"); }), "VFootball's high-line threshold must not be applied to eFootball");
assert.equal(facts.prediction_desk.publication_filters.past_kickoff_rows_hidden, 13);
assert.equal(facts.artifacts.prediction_desk.status, "WITHIN_THRESHOLD");
const notGeneratedFacts = summarizeDiagnosticFacts({
  collected_at: "2026-10-09T17:39:48.000Z",
  system_health: { generated_at: "2026-10-09T17:39:00.000Z", status: "HEALTHY", critical_issues: 0, warning_issues: 0, info_issues: 0, issue_count_by_severity: { critical: 0, warning: 0, info: 0, other: 0 }, issues: [] },
  core_pipeline: { updated_at: "2026-10-09T17:20:00.000Z", prediction_count: 1, football_count: 1, tennis_count: 0, errors: [] },
  tennis_forward_status: { updated_at: "2026-10-09T17:20:00.000Z", window_days: 14, tours: {} },
  prediction_desk: { status: "NOT_GENERATED", generated_at: null, event_count: null, publication_filters: {}, high_line_under_evidence: [] }
}, new Date("2026-10-09T17:39:48.000Z"));
assert.ok(notGeneratedFacts.flags.some(function(flag) { return flag.includes("sidecar status is NOT_GENERATED"); }));
const sanitizedAnswer = sanitizeAnalystAnswer("Finding: 3 pipeline errors.\n\nEvidence: ```json\n{\"private\":\"raw data\"}\n```");
assert.ok(sanitizedAnswer.includes("3 pipeline errors"));
assert.ok(!sanitizedAnswer.includes("raw data"));
assert.ok(sanitizedAnswer.includes("Raw JSON omitted"));
console.log("AI Analyst module tests passed.");

const withTimeline = makeDocument({
  leg_ref: "leg_1", product: "football", match: "Alpha vs Beta",
  actual_selection: { market: "total_goals_over_under", pick: "over", line: 1.5, odds: 1.4 },
  match_observations: [
    { observed_at: "2026-11-07T10:00:00Z", phase: "IN_PLAY", home: 0, away: 0, source: "user_reported" },
    { observed_at: "2026-11-07T10:45:00Z", phase: "HALF_TIME", home: 0, away: 0, source: "user_reported" }
  ]
});
assert.deepEqual(validateReviewDocument(withTimeline), []);
const unorderedTimeline = makeDocument({
  leg_ref: "leg_1", product: "football", match: "Alpha vs Beta",
  actual_selection: { market: "total_goals_over_under", pick: "over", line: 1.5, odds: 1.4 },
  match_observations: [
    { observed_at: "2026-11-07T10:45:00Z", phase: "HALF_TIME", home: 0, away: 0, source: "user_reported" },
    { observed_at: "2026-11-07T10:00:00Z", phase: "IN_PLAY", home: 0, away: 0, source: "user_reported" }
  ]
});
assert.ok(validateReviewDocument(unorderedTimeline).some(error => error.includes("strictly increasing")));
