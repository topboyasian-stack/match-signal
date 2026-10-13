import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const [oddsCss, reportsCss, labCss, oddsHtml, reportsHtml, labHtml, deploy] = await Promise.all([
  read("odds-builder-design.css"),
  read("reports-design.css"),
  read("virtual-lab-terminal.css"),
  read("odds-builder.html"),
  read("reports.html"),
  read("virtual-lab/index.html"),
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

for (const [name, html, scope, href, marker] of [
  ["Odds Builder", oddsHtml, 'data-page="odds-builder"', "odds-builder-design.css?v=20261014-terminal2", "MS-ODDS-BUILDER-2026.10.14-TERMINAL2"],
  ["Reports", reportsHtml, 'data-page="reports"', "reports-design.css?v=20261014-terminal2", "MS-REPORTS-2026.10.14-TERMINAL2"],
  ["Virtual Lab", labHtml, 'data-page="virtual-lab"', "../virtual-lab-terminal.css?v=20261014-terminal2", "MS-VIRTUAL-LAB-V1-2026.10.14-TERMINAL2"]
]) {
  assert.ok(html.includes(scope), name + " must carry its page scope");
  assert.ok(html.includes(href), name + " must load the versioned design layer");
  assert.ok(html.includes(marker), name + " must expose a production-verifiable build marker");
}
assert.ok(oddsHtml.includes("sport-hubs.js?v=20261013-qualified-best-kickoff-sort1"), "Odds Builder must retain the shared renderer");
assert.ok(oddsHtml.includes("expansion-odds-builder.js?v=20261011-efootball65-evidence1"), "Odds Builder must retain its existing engine");
assert.ok(oddsHtml.includes('id="oddsBuilder"'), "Odds Builder engine mount must remain");
assert.ok(reportsHtml.includes('id="reportGrid"') && reportsHtml.includes('id="researchLabSummary"'), "Reports mounts must remain");
for (const mount of ['id="predictionDesk"', 'id="nearQualifiedRadar"', 'id="oddsBuilder"', 'id="labDiagnostics"', 'id="researchConclusion"']) {
  assert.ok(labHtml.includes(mount), "Virtual Lab mount must remain: " + mount);
}
assert.ok(labHtml.includes("../virtual-lab-app.js?v=20261011-redesign3"), "Virtual Lab engine script must remain");
assert.ok(labHtml.includes("../virtual-lab-confirmed-watch.js?v=20261011-annotate-fix1"), "Virtual Lab participant monitor must remain");

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
  "odds-builder-design.css?v=20261014-terminal2",
  "reports-design.css?v=20261014-terminal2",
  "../virtual-lab-terminal.css?v=20261014-terminal2"
]) {
  assert.ok(deploy.includes(marker), "production smoke tests must verify asset wiring: " + marker);
}


for (const [name, css, marker] of [
  ["Odds Builder", oddsCss, "MATCH-SIGNAL-DESIGN-V2: ODDS BUILDER HIGH-CONTRAST VISUAL DELTA"],
  ["Reports", reportsCss, "MATCH-SIGNAL-DESIGN-V2: REPORTS HIGH-CONTRAST ANALYTICS VISUAL DELTA"],
  ["Virtual Lab", labCss, "MATCH-SIGNAL-DESIGN-V2: VIRTUAL LAB HIGH-CONTRAST RESEARCH VISUAL DELTA"]
]) assert.ok(css.includes(marker), name + " must ship the distinct V2 visual treatment");
assert.ok(oddsCss.includes('"PAPER MODE  /  EXACT-QUOTE GATES"'), "Odds Builder must show its mode ribbon");
assert.ok(reportsCss.includes('"READ-ONLY  /  EVIDENCE & TRACK RECORD"'), "Reports must show its evidence ribbon");
assert.ok(labCss.includes(".labJump button"), "Virtual Lab must show the new navigation treatment");

console.log("Workspace terminal design regressions passed: page-scoped styles, responsive/accessibility behavior, unchanged mounts/scripts, and guarded promotion wiring.");
