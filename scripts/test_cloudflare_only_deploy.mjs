import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const workflowsDir = ".github/workflows";
const workflowFiles = fs.readdirSync(workflowsDir).filter((name) => /\.(?:yml|yaml)$/i.test(name));
const publisherWorkflows = workflowFiles.filter((name) => {
  const source = fs.readFileSync(path.join(workflowsDir, name), "utf8");
  return /uses:\s*actions\/deploy-pages@/i.test(source)
    || /uses:\s*(?:peaceiris\/actions-gh-pages|JamesIves\/github-pages-deploy-action|crazy-max\/ghaction-github-pages)@/i.test(source);
});

assert.deepEqual(
  publisherWorkflows,
  ["deploy-pages.yml"],
  "Cloudflare must publish the application; GitHub Pages may only serve the legacy redirect.",
);

const legacyWorkflowPath = path.join(workflowsDir, "deploy-pages.yml");
assert.equal(fs.existsSync(legacyWorkflowPath), true, "Keep the one-time legacy redirect workflow.");
const legacyWorkflow = fs.readFileSync(legacyWorkflowPath, "utf8");
assert.match(legacyWorkflow, /name:\s*Retire legacy GitHub Pages mirror \(Cloudflare redirect only\)/);
assert.doesNotMatch(legacyWorkflow, /workflow_run:/, "The legacy host must not redeploy on other workflow completions.");
assert.doesNotMatch(legacyWorkflow, /['"]data\/\*\*['"]/, "Sports data changes must never trigger a secondary site deployment.");
assert.match(
  legacyWorkflow,
  /paths:\s*\n\s*-\s*['"]\.github\/workflows\/deploy-pages\.yml['"]/,
  "The legacy redirect may publish only when its own workflow changes or is manually dispatched.",
);
assert.match(legacyWorkflow, /Prepare redirect-only artifact/);
assert.match(legacyWorkflow, /cp public\/index\.html public\/404\.html/);
assert.match(legacyWorkflow, /https:\/\/match-signal\.pages\.dev/);
assert.doesNotMatch(legacyWorkflow, /DEPLOY-VERIFY-GITHUB-PAGES\.json/, "Do not write a competing production verification marker.");

const otherLegacyHostReferences = workflowFiles.filter((name) => {
  if (name === "deploy-pages.yml") return false;
  return /topboyasian-stack\.github\.io\/match-signal/i.test(
    fs.readFileSync(path.join(workflowsDir, name), "utf8"),
  );
});
assert.deepEqual(
  otherLegacyHostReferences,
  [],
  "No other workflow should treat the retired GitHub Pages mirror as a production host.",
);

const alternativesApi = fs.readFileSync("functions/api/public/market-alternatives.js", "utf8");
const alternativesUi = fs.readFileSync("qualified-alternatives.js", "utf8");
const ticketDrawer = fs.readFileSync("ticket-drawer.js", "utf8");
assert.ok(alternativesApi.includes("const MIN_RECOMMENDED_PROBABILITY = 0.65;"));
assert.ok(alternativesApi.includes("const MIN_RESEARCH_ALTERNATIVE_PROBABILITY = 0.55;"));
assert.ok(alternativesApi.includes("const minimumProbability = builderQualified ? MIN_RECOMMENDED_PROBABILITY : MIN_RESEARCH_ALTERNATIVE_PROBABILITY;"));
assert.ok(alternativesApi.includes('row.passed_builder_gates !== true && !String(row.original_pick || row.primary_prediction_id || "").trim()'));
assert.ok(alternativesApi.includes("builder_qualified: builderQualified"));
assert.ok(alternativesUi.includes("Research only — Builder gate not passed"));
assert.ok(alternativesUi.includes("String(x.builder_qualified===true)"));
assert.ok(ticketDrawer.includes("model_qualified:raw.model_qualified===true"));
assert.ok(ticketDrawer.includes("MANUAL PICK — model qualification not claimed; live recheck required"));
const researchLaneProbe = [
  'import assert from "node:assert/strict";',
  'import { buildPublicAlternatives } from "./functions/api/public/market-alternatives.js";',
  "const now = Date.now();",
  "const future = new Date(now + 60 * 60 * 1000).toISOString();",
  "const fresh = new Date(now - 60 * 1000).toISOString();",
  'const base = { sport: "football", event_id: "fixture-research", start_time: future, match: "Home FC vs Away FC", market: "total_goals", line: 2.5, pick: "over", model_probability: 0.60, bookmaker_odds: 1.82, quote_timestamp: fresh, sportybet_event_id: "sr:match:research-123", sportybet_market_id: "18", prediction_role: "ALTERNATIVE", alternative_source: "SYSTEM_RECOMMENDED", passed_builder_gates: false, fresh_exact_quote: true, original_pick: "p1", primary_prediction_id: "fixture-research-primary", candidate_status: "RESEARCH_ONLY" };',
  'const evaluate = row => buildPublicAlternatives({ record_type: "cross_sport_market_reassessment", records: [row] }, now).alternatives;',
  "const research = evaluate(base);",
  'assert.equal(research.length, 1, "A linked 55%+ research alternative with an exact fresh quote should be public");',
  'assert.equal(research[0].builder_qualified, false);',
  'assert.equal(research[0].qualification_status, "RESEARCH_ONLY");',
  'assert.equal(evaluate({ ...base, primary_prediction_id: "", original_pick: "" }).length, 0, "Unlinked candidates must remain withheld");',
  'assert.equal(evaluate({ ...base, model_probability: 0.54 }).length, 0, "Research alternatives below 55% must remain withheld");',
  'assert.equal(evaluate({ ...base, passed_builder_gates: true, model_probability: 0.60 }).length, 0, "Builder-qualified candidates still require 65%");',
  'console.log("Linked exact-quote research alternative lane passed.");'
].join("\n");
const laneProbe = spawnSync(process.execPath, ["--experimental-default-type=module", "--input-type=module", "-e", researchLaneProbe], { encoding: "utf8" });
assert.equal(laneProbe.status, 0, "Research-alternative executable contract failed: " + (laneProbe.stdout || "") + (laneProbe.stderr || ""));
const cloudflare = fs.readFileSync(path.join(workflowsDir, "cloudflare-pages.yml"), "utf8");
assert.match(cloudflare, /name:\s*Deploy Match Signal to Cloudflare Pages/);
assert.match(cloudflare, /https:\/\/match-signal\.pages\.dev/);
assert.ok(
  cloudflare.includes("|scripts/predict_today.py|") &&
    cloudflare.includes("|scripts/test_predict_today_market_matching.py|") &&
    cloudflare.includes("|.github/workflows/efootball-recent-evidence-regression.yml|") &&
    cloudflare.includes("|.github/workflows/single-selection-gate-regression.yml|") &&
    cloudflare.includes("|scripts/test_selection_gate_contract.py|") &&
    cloudflare.includes("|scripts/test_single_selection_gate_bridge.mjs|") &&
    cloudflare.includes("--exclude='data/nba_live_observations.json'") &&
    cloudflare.includes("test ! -e .pages-deploy/data/nba_live_observations.json"),
  "The private 30-day NBA live-observation archive must stay out of the public Pages asset package.",
);
assert.ok(
  cloudflare.includes("|scripts/ensure_odds_builder_refresh.py|scripts/test_ensure_odds_builder_refresh.py|") &&
    cloudflare.includes("|scripts/test_workflow_trigger_boundaries.py|") &&
    cloudflare.includes("|scripts/test_cloudflare_only_deploy.mjs|") &&
    cloudflare.includes("|scripts/test_sportybet_booking_resilience.mjs|") &&
    cloudflare.includes("|league.html|") &&
    cloudflare.includes("|live.html|") &&
    cloudflare.includes("|match-signal-ip.js|") &&
    cloudflare.includes("|api-access.html|") &&
    cloudflare.includes("      - 'match-signal-ip.js'") &&
    cloudflare.includes("      - 'api-access.html'") &&
    cloudflare.includes("      - 'live.html'") &&
    cloudflare.includes("|functions/api/odds-builder-data.js|") &&
    cloudflare.includes("|functions/api/public/market-alternatives.js|") &&
    cloudflare.includes("|qualified-alternatives.js|") &&
    cloudflare.includes("|functions/api/sportybet-virtual-results.js|") &&
    cloudflare.includes("      - 'functions/api/sportybet-virtual-results.js'"),
  "Builder refresh, the live odds-data endpoint, and deployment-guard regression paths must be explicitly approved by the direct-promotion guard.",
);
assert.ok(
  cloudflare.includes("      - 'functions/api/odds-builder-data.js'"),
  "A change to the live Builder data endpoint must trigger a Cloudflare Pages deployment.",
);
assert.ok(
  cloudflare.includes("      - 'functions/api/espn.js'") &&
    cloudflare.includes("|functions/api/espn.js|"),
  "The ESPN summary proxy must trigger and be permitted in Cloudflare deployments when its implementation changes.",
);

const analystDeploymentPaths = [
  "analyst.html",
  "analyst.js",
  "workspace-ui.css",
  "functions/_shared/analyst.mjs",
  "functions/api/analyst/chat.js",
  "functions/api/analyst/market-evidence.js",
  "functions/api/analyst/parse-ticket.js",
  "functions/api/analyst/records.js",
];
for (const file of analystDeploymentPaths) {
  assert.ok(cloudflare.includes("      - '" + file + "'"), file + " must trigger Cloudflare production deployment");
  assert.ok(cloudflare.includes("|" + file + "|"), file + " must be approved by the direct-promotion guard");
}
assert.ok(
  cloudflare.includes("      - 'functions/api/analyst/**'") &&
    cloudflare.includes("      - 'scripts/test_analyst_module.mjs'") &&
    cloudflare.includes("      - 'scripts/test_analyst_routes.mjs'") &&
    cloudflare.includes("      - 'scripts/test_analyst_parse_ticket.mjs'"),
  "Analyst changes and the independent-leg regression suite must activate the Cloudflare pull-request validator",
);
assert.ok(
  cloudflare.includes("test -s analyst.html") &&
    cloudflare.includes("test -s analyst.js") &&
    cloudflare.includes("test -s functions/_shared/analyst.mjs") &&
    cloudflare.includes("node --check functions/api/analyst/parse-ticket.js"),
  "The deployed artifact must contain and syntax-check the private Analyst UI and API",
);
assert.ok(
  cloudflare.includes("'/analyst.js'") &&
    cloudflare.includes("'/workspace-ui.css'") &&
    cloudflare.includes("'/workspace-ui.js'") &&
    cloudflare.includes("'/analyst.html'"),
  "Production smoke tests must request the private Analyst page and all browser assets",
);

assert.ok(
  cloudflare.includes("|scripts/test_live_virtual_quote_coverage.mjs|") &&
    cloudflare.includes("|scripts/test_nba_live_projection.mjs|") &&
    cloudflare.includes("|scripts/visual_site_audit.mjs|") &&
    cloudflare.includes("/apis/site/v2/sports/basketball/nba/summary") &&
    cloudflare.includes("NBA live-summary proxy passed"),
  "The eFootball quote-coverage regression, NBA projection test, visual audit and ESPN summary proxy must be explicitly approved and verified.",
);
const virtualLabHtml = fs.readFileSync("virtual-lab/index.html", "utf8");
const virtualLabAppAsset = virtualLabHtml.match(/<script src="(\.\.\/virtual-lab-app\.js\?v=[^"]+)" defer><\/script>/);
assert.ok(virtualLabAppAsset, "Virtual Lab page must reference a versioned engine script");
assert.ok(
  cloudflare.includes(virtualLabAppAsset[1]),
  "Cloudflare production smoke test must verify the same Virtual Lab app version referenced by the page",
);

const liveCoverageTest = fs.readFileSync("scripts/test_live_virtual_quote_coverage.mjs", "utf8");
assert.ok(
  liveCoverageTest.includes("../data/efootball_desk_learning.json") &&
    liveCoverageTest.includes("efootballDeskLearning"),
  "The eFootball quote-coverage VM must load its product-specific learning artifact before evaluating production qualification functions.",
);

assert.ok(
  cloudflare.includes("gzip -c data/efootball_market_research.json > .pages-deploy/data/efootball_market_research.json.gz") &&
    cloudflare.includes("--exclude='data/efootball_market_research.json'") &&
    cloudflare.includes("test ! -e .pages-deploy/data/efootball_market_research.json") &&
    cloudflare.includes("/data/efootball_market_research.json.gz") &&
    cloudflare.includes("Refusing Cloudflare Pages upload while oversized assets remain."),
  "Keep the full research archive in Git, publish its compressed Pages copy, and fail preflight before uploading oversized assets.",
);

assert.ok(
  cloudflare.includes("gzip -c data/efootball_desk_prediction_history.json > .pages-deploy/data/efootball_desk_prediction_history.json.gz") &&
    cloudflare.includes("test ! -e .pages-deploy/data/efootball_desk_prediction_history.json") &&
    cloudflare.includes('test "$desk_compressed_bytes" -lt "$MAX_PAGES_FILE_BYTES"') &&
    !cloudflare.includes('test "$desk_original_bytes" -gt "$MAX_PAGES_FILE_BYTES"'),
  "The eFootball desk archive must always have a bounded compressed Pages copy; deployment must not fail when the canonical source shrinks below the provider file-size limit.",
);

const monitor = fs.readFileSync(path.join(workflowsDir, "qualified-best-production-watch.yml"), "utf8");
assert.match(
  monitor,
  /QUALIFIED_BEST_URL:\s*https:\/\/match-signal\.pages\.dev\/qualified-best\.html/,
  "The browser monitor must inspect the canonical Cloudflare production page.",
);
assert.doesNotMatch(
  monitor,
  /topboyasian-stack\.github\.io\/match-signal/i,
  "The production browser monitor must not use the legacy GitHub Pages mirror.",
);

console.log("Cloudflare production hosting checks passed; legacy GitHub Pages is redirect-only.");
