import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const coverage = await readFile(new URL("./test_live_virtual_quote_coverage.mjs", import.meta.url), "utf8");
const deploy = await readFile(new URL("../.github/workflows/cloudflare-pages.yml", import.meta.url), "utf8");

assert.match(coverage, /const upcomingVirtualCandidates = rows\.filter\(isVirtualDeskCandidate\)/);
assert.match(coverage, /const noModelQualifiedCandidates = virtualCandidates\.length === 0/);
assert.match(coverage, /if \(noModelQualifiedCandidates\)/);
assert.match(coverage, /scanStopReason = "no_model_qualified_candidates"/);
assert.match(coverage, /coverage_state: noModelQualifiedCandidates \? "VALID_ZERO"/);
assert.match(coverage, /candidate_pool_rows_in_next_7_days: upcomingVirtualCandidates\.length/);
assert.match(coverage, /model_qualified_candidate_rows_in_next_7_days: virtualCandidates\.length/);

assert.match(deploy, /valid_zero_coverage = live\.get\('no_model_qualified_candidates'\) is True and live\.get\('scan_complete'\) is True/);
assert.match(deploy, /'qualified_best_quote_coverage_status':'VALID_ZERO' if valid_zero_coverage/);
assert.match(deploy, /'qualified_best_candidate_pool_rows':live\.get\('candidate_pool_rows_in_next_7_days',0\)/);
assert.match(deploy, /'qualified_best_model_qualified_rows':live\.get\('model_qualified_candidate_rows_in_next_7_days'/);
assert.match(deploy, /qualified_best_valid_zero/);

console.log("Qualified Best zero-candidate reporting: 12 assertions passed.");
