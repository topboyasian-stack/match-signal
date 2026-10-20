import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

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

const cloudflare = fs.readFileSync(path.join(workflowsDir, "cloudflare-pages.yml"), "utf8");
assert.match(cloudflare, /name:\s*Deploy Match Signal to Cloudflare Pages/);
assert.match(cloudflare, /https:\/\/match-signal\.pages\.dev/);
assert.ok(
  cloudflare.includes("|scripts/ensure_odds_builder_refresh.py|scripts/test_ensure_odds_builder_refresh.py|") &&
    cloudflare.includes("|scripts/test_workflow_trigger_boundaries.py|") &&
    cloudflare.includes("|scripts/test_cloudflare_only_deploy.mjs|") &&
    cloudflare.includes("|functions/api/odds-builder-data.js|") &&
    cloudflare.includes("|functions/api/sportybet-virtual-results.js|") &&
    cloudflare.includes("      - 'functions/api/sportybet-virtual-results.js'"),
  "Builder refresh, the live odds-data endpoint, and deployment-guard regression paths must be explicitly approved by the direct-promotion guard.",
);
assert.ok(
  cloudflare.includes("      - 'functions/api/odds-builder-data.js'"),
  "A change to the live Builder data endpoint must trigger a Cloudflare Pages deployment.",
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
