import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const diagnostic = await readFile(new URL("./test_live_virtual_quote_coverage.mjs", import.meta.url), "utf8");
const desk = await readFile(new URL("../sport-hubs.js", import.meta.url), "utf8");

for (const field of [
  "raw_virtual_rows_in_next_7_days",
  "desk_candidate_rows_in_next_7_days",
  "model_qualified_rows_in_next_7_days",
  "qualification_status_counts",
  "qualification_blocker_counts",
  "raw_probability_bucket_counts"
]) {
  assert.ok(diagnostic.includes(field), "production diagnostics must report " + field);
}
assert.ok(diagnostic.includes("rawVirtualRowsInNext7Days"), "raw feed inventory must be counted separately");
assert.ok(diagnostic.includes("qualificationState(row).modelQualified === true"),
  "only model-qualified rows may enter live quote matching");
assert.ok(diagnostic.includes("currentPricePass !== true"),
  "model-qualified but price-blocked rows must be reported as a separate blocker");
assert.ok(desk.includes("wfN<30"), "exact-line walk-forward minimum must remain at 30 observations");
assert.ok(desk.includes("edge<0.02"), "minimum market edge must remain at 2%");
assert.ok(desk.includes("expectedReturn<0.02"), "minimum expected return must remain at 2%");
console.log("Virtual gate diagnostic contract passed: inventory, model gates and price blockers are distinct; thresholds unchanged.");
