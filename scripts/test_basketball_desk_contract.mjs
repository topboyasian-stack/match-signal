import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const root = new URL("../", import.meta.url);
const read = p => readFile(new URL(p, root), "utf8");
const [html, css, ui, api, workflow] = await Promise.all([
  read("basketball.html"), read("basketball-design.css"), read("basketball-live.js"),
  read("functions/api/sportybet-basketball.js"), read(".github/workflows/cloudflare-pages.yml")
]);
assert.ok(html.includes("MS-BASKETBALL-DESK-2026.10.23-V3"), "Basketball must publish the new design marker");
assert.ok(html.includes("core-workspaces-design.css?v=20261014-full-v1"), "Basketball must use the shared Match Signal design layer");
assert.ok(html.includes("basketball-design.css?v=20261023-full-v1"), "Basketball must load its own scoped design layer");
assert.ok(html.includes('id="msNav"') && html.includes('workspace-ui.js?v=20261023-basketball-nav1'), "Basketball must use the single shared site navigation");
for (const id of ["liveGames","upcomingGames","totalsBoard","finalResults","performance","marketStatus","totalsStatus"]) assert.ok(html.includes('id="'+id+'"'), "Basketball must preserve renderer mount "+id);
assert.ok(css.includes("MATCH-SIGNAL-BASKETBALL-DESK-V1"), "Basketball scoped design marker missing");
assert.ok(css.includes("@media(max-width:480px)") && css.includes("@media(prefers-reduced-motion:reduce)") && css.includes(":focus-visible"), "Basketball design must remain responsive and accessible");
assert.ok(ui.includes("String(x.id)==='225'") || ui.includes("String(x.id)==='225'") || ui.includes("String(x.id)==='225'"), "Totals must use the explicit SportyBet market ID for full-game O/U including overtime");
assert.ok(ui.includes("Math.abs(a-b)<=45*60*1000"), "SportyBet quotes must match exact teams and near-identical kickoff times");
assert.ok(ui.includes("Date.now()-fetched>15*60*1000"), "Stale SportyBet quotes must be withheld");
assert.ok(ui.includes("No odds inferred from ESPN, OddsPapi, or another bookmaker."), "Other-bookmaker odds must never be labelled SportyBet");
assert.ok(api.includes("sportId:'sr:sport:2'"), "SportyBet basketball feed must request the basketball sport ID");
assert.ok(api.includes("marketId:'1,18,219,223,225,227,228'"), "Feed must request basketball markets including O/U incl overtime");
assert.ok(api.includes("total_including_overtime:'225'"), "API contract must explicitly identify total incl overtime");
assert.ok(workflow.includes("node scripts/test_basketball_desk_contract.mjs"), "Deployment must execute Basketball contract tests");
console.log("Basketball desk contract passed: shared UI, scoped responsive design, exact SportyBet event matching, fresh full-game totals including OT.");
