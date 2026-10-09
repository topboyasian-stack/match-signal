import assert from "node:assert/strict";
import {
  analyzeLeg,
  classifyLineAdjustment,
  emptyReviewDocument,
  evaluatePick,
  extractJsonObject,
  summarizeReviewDocument,
  validateReviewDocument
} from "../functions/_shared/analyst.mjs";

const stamp = "2026-10-09T10:00:00Z";
function makeLeg(actualPick, actualLine, deskPick, deskLine, home = 1, away = 1) {
  return {
    leg_ref: "leg_1",
    product: "vfootball",
    match: "Sample FC vs Example FC",
    actual_selection: { market: "total_goals_over_under", pick: actualPick, line: actualLine, odds: 1.5 },
    desk_snapshot: { market: "total_goals_over_under", pick: deskPick, line: deskLine, odds: 1.8, model_probability: 0.72, captured_at: stamp },
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
console.log("AI Analyst module tests passed.");
