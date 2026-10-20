import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const [oddsCss, reportsCss, labCss, oddsHtml, reportsHtml, labHtml, builderJs, deploy] = await Promise.all([
  read("odds-builder-design.css"),
  read("reports-design.css"),
  read("virtual-lab-terminal.css"),
  read("odds-builder.html"),
  read("reports.html"),
  read("virtual-lab/index.html"),
  read("expansion-odds-builder.js"),
  read(".github/workflows/cloudflare-pages.yml")
]);

const scopes = [
  ["Odds Builder", oddsCss, 'body[data-page="odds-builder"]'],
  ["Reports", reportsCss, 'body[data-page="reports"]'],
  ["Virtual Lab", labCss, 'body[data-page="virtual-lab"]']
];
for (const [name, css, scope] of scopes) {
  const normalized = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(normalized.includes(scope), name + " must declare a page-scoped design layer");
  assert.match(css, /@media \(max-width: 420px\)/, name + " must handle narrow phones");
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/, name + " must respect reduced-motion preferences");
  assert.match(css, /:focus-visible/, name + " must expose visible keyboard focus");
  const selectors = [...normalized.matchAll(/(?:^|})\s*([^{}]+)\{/g)]
    .map(match => match[1].trim())
    .filter(selector => !selector.startsWith("@media"));
  assert.ok(selectors.length >= 20, name + " should contain a complete design layer");
  for (const group of selectors) {
    for (const selector of group.split(",")) {
      assert.ok(selector.trim().startsWith(scope), name + " has an unscoped selector: " + selector.trim());
    }
  }
}

const builderMarker = oddsHtml.match(/<meta name="match-signal-build" content="([^"]+)"/)?.[1] || "";
const builderCssHref = oddsHtml.match(/href="(\.\/odds-builder-design\.css\?v=[^"]+)"/)?.[1] || "";
const builderEngineSrc = oddsHtml.match(/src="(\.\/expansion-odds-builder\.js\?v=[^"]+)"/)?.[1] || "";
assert.ok(builderMarker.startsWith("MS-ODDS-BUILDER-"), "Odds Builder must expose a versioned production build marker");
assert.ok(builderCssHref.startsWith("./odds-builder-design.css?v="), "Odds Builder must load its versioned design layer");
assert.ok(builderEngineSrc.startsWith("./expansion-odds-builder.js?v="), "Odds Builder must load its versioned renderer");
assert.ok(oddsHtml.includes('data-page="odds-builder"'), "Odds Builder must carry its page scope");
for (const [name, html, scope, href, marker] of [
  ["Reports", reportsHtml, 'data-page="reports"', "reports-design.css?v=20261014-full-v3", "MS-REPORTS-2026.10.14-V3"],
  ["Virtual Lab", labHtml, 'data-page="virtual-lab"', "../virtual-lab-terminal.css?v=20261014-full-v3", "MS-VIRTUAL-LAB-V1-2026.10.14-V3"]
]) {
  assert.ok(html.includes(scope), name + " must carry its page scope");
  assert.ok(html.includes(href), name + " must load the versioned design layer");
  assert.ok(html.includes(marker), name + " must expose a production-verifiable build marker");
}
assert.ok(oddsHtml.includes("sport-hubs.js?v=20261013-qualified-best-kickoff-sort1"), "Odds Builder must retain the shared renderer");
assert.ok(oddsHtml.includes('id="oddsBuilder"'), "Odds Builder engine mount must remain");
assert.ok(reportsHtml.includes('id="reportGrid"') && reportsHtml.includes('id="researchLabSummary"'), "Reports mounts must remain");
for (const mount of ['id="predictionDesk"', 'id="nearQualifiedRadar"', 'id="oddsBuilder"', 'id="labDiagnostics"', 'id="researchConclusion"']) {
  assert.ok(labHtml.includes(mount), "Virtual Lab mount must remain: " + mount);
}
assert.ok(labHtml.includes("../virtual-lab-app.js?v=20261011-redesign3"), "Virtual Lab engine script must remain");
assert.ok(labHtml.includes("../virtual-lab-confirmed-watch.js?v=20261011-annotate-fix1"), "Virtual Lab participant monitor must remain");

assert.ok(oddsHtml.includes('class="ob-page-header"') && oddsHtml.includes('class="ob-section-nav"') && oddsHtml.includes('class="ob-guide-grid"'), "Odds Builder must use the reorganized page hierarchy");
assert.ok(reportsHtml.includes('class="rp-dashboard-grid"') && reportsHtml.includes('id="report-scoreboard"') && reportsHtml.includes('class="rp-side-column"'), "Reports must use the new scoreboard/main/side-rail composition");
assert.ok(labHtml.includes('class="vl-command-grid"') && labHtml.includes('class="vl-command-rail"') && labHtml.includes('class="vl-insights-grid"'), "Virtual Lab must use the feed/control/evidence composition");
for (const id of ['predictionDesk','nearQualifiedRadar','oddsBuilder','product','market','split','fileInput','rounds','winRate','oosRate','roi','seqDelta','fingerprint','signalGate','sequence','oos','participantLab','modelLab','labDiagnostics','researchConclusion','schema']) {
  assert.ok(labHtml.includes('id="' + id + '"'), "Virtual Lab must preserve existing mount/control: " + id);
}
assert.ok(builderJs.includes('target.innerHTML=pushNotificationHtml()'), "Odds Builder must retain its original render entry point");
for (const selector of [
  '#oddsBuilder > .builder-console',
  '#oddsBuilder > .builder-batch-panel:nth-of-type(2)',
  '#oddsBuilder > .push-notify-panel',
  '#oddsBuilder > .builder-batch-panel:nth-of-type(3)',
  '#oddsBuilder > .ticket-track'
]) assert.ok(oddsCss.includes(selector), "Odds Builder layout must reflow existing renderer element: " + selector);
for (const anchor of ['id="builder-overview"', 'href="#oddsBuilder"', 'id="ob-guide-title"', 'id="ob-page-footer"']) {
  assert.ok(oddsHtml.includes(anchor), "Odds Builder navigation must target an existing page anchor: " + anchor);
}
assert.ok(builderJs.includes('ACTIVE_VIRTUAL_MIN_PROBABILITY = 0.80'), "Odds Builder active-leg qualification floor must remain");
assert.ok(builderJs.includes('function isActiveVirtualBatch(batch)'), "Odds Builder active batch filter must remain");
assert.ok(builderJs.includes('ensureBookingCodes(activeBatches)'), "Odds Builder booking-code path must remain");
assert.ok(builderJs.includes('function checkBuilderBuildVersion'), "open Odds Builder tabs must detect a new deployed renderer build");
assert.ok(builderJs.includes('window.setInterval(checkBuilderBuildVersion,60000)'), "open Odds Builder tabs must automatically reload changed renderer builds");
assert.ok(!builderJs.includes("var fallback=Array.isArray(data.qualified_legs)"), "A standalone leg must never render as a qualified accumulator when no batch survives");
assert.ok(builderJs.includes("No qualified '+floorLabel+' batches are currently available."), "An empty qualified set must explain that no full batch passed");

const directPaths = [
  "odds-builder.html", "odds-builder-design.css",
  "reports.html", "reports-design.css",
  "virtual-lab/index.html", "virtual-lab-terminal.css",
  "scripts/test_workspace_terminal_design.mjs", ".github/workflows/cloudflare-pages.yml"
];
for (const path of directPaths) {
  assert.ok(deploy.includes("'" + path + "'"), "Cloudflare push trigger must include " + path);
  assert.ok(deploy.includes("|" + path + "|"), "Cloudflare static promotion allowlist must include " + path);
}
assert.ok(deploy.includes("node scripts/test_workspace_terminal_design.mjs"), "production promotion must run workspace visual regressions");
for (const marker of [
  "reports-design.css?v=20261014-full-v3",
  "../virtual-lab-terminal.css?v=20261014-full-v3"
]) {
  assert.ok(deploy.includes(marker), "production smoke tests must verify asset wiring: " + marker);
}
assert.ok(deploy.includes("currentBuilderBuildMarker"), "production smoke tests must follow the current checked-out Odds Builder build marker");
assert.ok(deploy.includes("currentBuilderCssHref"), "production smoke tests must follow the current checked-out Builder CSS asset");
assert.ok(deploy.includes("currentBuilderEngineSrc"), "production smoke tests must follow the current checked-out Builder engine asset");


for (const [name, css, marker] of [
  ["Odds Builder", oddsCss, "MATCH-SIGNAL-FULL-RECOMPOSITION-V3: ODDS BUILDER PAGE LAYOUT"],
  ["Reports", reportsCss, "MATCH-SIGNAL-FULL-RECOMPOSITION-V3: REPORTS PAGE LAYOUT"],
  ["Virtual Lab", labCss, "MATCH-SIGNAL-FULL-RECOMPOSITION-V3: VIRTUAL LAB PAGE LAYOUT"]
]) assert.ok(css.includes(marker), name + " must ship the full V3 page re-composition");
assert.ok(oddsCss.includes('"PAPER MODE  /  EXACT-QUOTE GATES"'), "Odds Builder must show its mode ribbon");
assert.ok(reportsCss.includes('"READ-ONLY  /  EVIDENCE & TRACK RECORD"'), "Reports must show its evidence ribbon");
assert.ok(labCss.includes(".labJump button"), "Virtual Lab must show the new navigation treatment");

console.log("Workspace terminal design regressions passed: page-scoped styles, responsive/accessibility behavior, unchanged mounts/scripts, and guarded promotion wiring.");
