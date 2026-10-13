import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { classifyQualifiedBestMonitor } from "./qualified_best_monitor_lib.mjs";

const workflow = await readFile(new URL("../.github/workflows/qualified-best-monitor.yml", import.meta.url), "utf8");
const monitorSource = await readFile(new URL("./qualified_best_monitor.mjs", import.meta.url), "utf8");
assert.ok(workflow.includes("cron: '7-59/5 * * * *'"), "the independent monitor checks production every five minutes, staggered away from minute zero");
assert.match(workflow, /workflow_run:[\s\S]*?workflows:\s*\n\s*- "Deploy Match Signal to Cloudflare Pages"/, "production monitoring starts after the Cloudflare deploy workflow");
assert.doesNotMatch(workflow, /\n  push:/, "the production browser monitor must not race the Cloudflare deployment on main pushes");
assert.match(workflow, /github\.event\.workflow_run\.conclusion == 'success'/, "failed deployments must not trigger a production monitor");
assert.match(monitorSource, /run\.event === "schedule"/, "schedule-gap calculations must compare cron-triggered runs, not deployment-triggered runs");
assert.match(monitorSource, /PRODUCTION_CHECK_RECOVERED_AFTER_RETRY/, "a retry recovery must stay visible as a warning");


const now = Date.parse("2026-10-13T12:00:00.000Z");
const healthyZero = {
  stage: "completed",
  board_payload_loaded: true,
  selection_candidates_loaded: true,
  source_fresh: true,
  source_fallback_used: false,
  live_quote_refresh_state: "complete",
  required_quote_rows: 0,
  live_quote_last_verified_at: null,
  current_qualified_count: 0,
  schedule_gap_status: "ok",
  schedule_gap_minutes: 5,
  page_errors: []
};
const zeroResult = classifyQualifiedBestMonitor(healthyZero, { nowMs: now });
assert.equal(zeroResult.status, "healthy");
assert.equal(zeroResult.exit_code, 0, "zero qualified picks is not itself a monitor failure");
assert.equal(zeroResult.classification, "valid_zero_qualified");

const healthyPicks = classifyQualifiedBestMonitor({
  ...healthyZero,
  current_qualified_count: 3
}, { nowMs: now });
assert.equal(healthyPicks.status, "healthy");
assert.equal(healthyPicks.classification, "qualified_fixtures_present");

for (const [label, patch, reason] of [
  ["renderer exception", { stage: "failed" }, "QUALIFICATION_RENDER_FAILED"],
  ["check still pending", { stage: "checking" }, "QUALIFICATION_CHECK_INCOMPLETE"],
  ["board source failure", { board_payload_loaded: false }, "CANONICAL_BOARD_FETCH_FAILED"],
  ["candidate source failure", { selection_candidates_loaded: false }, "SELECTION_CANDIDATES_FETCH_FAILED"],
  ["stale board timestamp", { source_fresh: false }, "SOURCE_DATA_STALE_OR_TIMESTAMP_INVALID"],
  ["synthetic fallback timestamp", { source_fallback_used: true }, "CANONICAL_BOARD_EMPTY_OR_UNAVAILABLE_FALLBACK_USED"],
  ["partial quote response", { live_quote_refresh_state: "partial" }, "LIVE_QUOTE_REFRESH_PARTIAL"],
  ["unavailable quote response", { live_quote_refresh_state: "unavailable" }, "LIVE_QUOTE_REFRESH_UNAVAILABLE"],
  ["cached rather than refreshed quote snapshot", { live_quote_refresh_state: "cached" }, "LIVE_QUOTE_REFRESH_CACHED"],
  ["missing qualified count", { current_qualified_count: null }, "QUALIFIED_COUNT_MISSING_OR_INVALID"],
  ["three missed five-minute checks", { schedule_gap_minutes: 16 }, "MONITOR_SCHEDULE_GAP_EXCEEDED"],
  ["long monitoring gap", { schedule_gap_minutes: 40 }, "MONITOR_SCHEDULE_GAP_EXCEEDED"],
  ["browser runtime exception", { page_errors: ["TypeError: test"] }, "BROWSER_RUNTIME_ERRORS"]
]) {
  const result = classifyQualifiedBestMonitor({ ...healthyZero, ...patch }, { nowMs: now });
  assert.equal(result.status, "failed", label + " must not be reported as healthy");
  assert.ok(result.reasons.includes(reason), label + " exposes an actionable reason");
}

const freshRequiredQuote = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 2,
  live_quote_matched_required_rows: 2,
  live_quote_missing_required_rows: 0,
  live_quote_last_verified_at: new Date(now - 5 * 60 * 1000).toISOString(),
  current_qualified_count: 0
}, { nowMs: now });
assert.equal(freshRequiredQuote.status, "healthy", "freshly verified exact quotes can validly produce zero qualified selections");

const staleRequiredQuote = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 2,
  live_quote_last_verified_at: new Date(now - 16 * 60 * 1000).toISOString()
}, { nowMs: now });
assert.ok(staleRequiredQuote.reasons.includes("LIVE_QUOTE_VERIFICATION_TIMESTAMP_STALE_OR_FUTURE"));

const futureRequiredQuote = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 1,
  live_quote_last_verified_at: new Date(now + 4 * 60 * 1000).toISOString()
}, { nowMs: now });
assert.ok(futureRequiredQuote.reasons.includes("LIVE_QUOTE_VERIFICATION_TIMESTAMP_STALE_OR_FUTURE"));


const incompleteCoverage = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 25,
  live_quote_matched_required_rows: 24,
  live_quote_missing_required_rows: 1,
  live_quote_last_verified_at: new Date(now - 30 * 1000).toISOString()
}, { nowMs: now });
assert.ok(incompleteCoverage.reasons.includes("REQUIRED_QUOTE_COVERAGE_INCOMPLETE"), "a nominally complete refresh must fail if required candidate quotes remain missing");

const missingCoverageDiagnostics = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 25,
  live_quote_last_verified_at: new Date(now - 30 * 1000).toISOString()
}, { nowMs: now });
assert.ok(missingCoverageDiagnostics.reasons.includes("REQUIRED_QUOTE_COVERAGE_DIAGNOSTICS_MISSING"), "production monitor requires explicit required-row coverage counts");

const completeCoverage = classifyQualifiedBestMonitor({
  ...healthyZero,
  required_quote_rows: 25,
  live_quote_matched_required_rows: 25,
  live_quote_missing_required_rows: 0,
  live_quote_last_verified_at: new Date(now - 30 * 1000).toISOString()
}, { nowMs: now });
assert.equal(completeCoverage.status, "healthy", "fully matched exact quote rows preserve valid-zero semantics");

const noScheduleApi = classifyQualifiedBestMonitor({
  ...healthyZero,
  schedule_gap_status: "unknown",
  schedule_gap_minutes: null
}, { nowMs: now });
assert.equal(noScheduleApi.status, "healthy");
assert.ok(noScheduleApi.warnings.includes("MONITOR_SCHEDULE_GAP_COULD_NOT_BE_VERIFIED"));

console.log("Qualified Best monitor tests passed: valid zero vs failed check, source freshness, fallback detection, exact quote verification freshness, browser exceptions, and schedule-gap alerting.");
