import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const cloudflareWorkflow = await read(".github/workflows/cloudflare-pages.yml");
const [css, tableTennis, darts] = await Promise.all([
  read("independent-sport-design.css"),
  read("table-tennis.html"),
  read("darts.html")
]);

const normalizedCss = css.replace(/\/\*[\s\S]*?\*\//g, "");
assert.match(css, /body\[data-page="independent-sport"\]/, "style rules must target the independent sport pages");
assert.match(css, /@media \(max-width: 420px\)/, "the UI must handle narrow phones");
assert.match(css, /@media \(prefers-reduced-motion: reduce\)/, "the UI must respect reduced-motion preferences");
assert.match(css, /:focus-visible/, "key interactive controls must expose keyboard focus");
const selectors = [...normalizedCss.matchAll(/(?:^|})\s*([^{}]+)\{/g)]
  .map(match => match[1].trim())
  .filter(selector => !selector.startsWith("@media"));
assert.ok(selectors.length >= 35, "the expected scoped design layer should be present");
for (const selectorGroup of selectors) {
  for (const selector of selectorGroup.split(",")) {
    assert.ok(selector.trim().startsWith('body[data-page="independent-sport"]'), "unscoped selector: " + selector.trim());
  }
}

for (const [sport, html, app, title] of [
  ["table-tennis-x", tableTennis, "table-tennis-app.js?v=20260924-v1", "Table Tennis-X"],
  ["darts-x", darts, "darts-app.js?v=20260924-v1", "Darts-X"]
]) {
  assert.match(html, /data-page="independent-sport"/, title + " must declare its independent layout scope");
  assert.ok(html.includes('data-sport="' + sport + '"'), title + " must retain its own accent identity");
  assert.ok(html.includes('MS-INDEPENDENT-SPORTS-2026.10.13-DESIGN1'), title + " must expose a build marker");
  assert.ok(html.includes("independent-sport-design.css?v=20261013-premium-terminal4"), title + " must load the versioned design layer");
  assert.ok(html.includes(app), title + " must retain its original engine script");
  for (const mount of ['id="history"', 'id="upcoming"', 'id="gate"', 'id="gateBadge"', 'id="refresh"', 'id="feedMeta"', 'id="cards"']) {
    assert.ok(html.includes(mount), title + " must preserve engine mount " + mount);
  }
}
assert.ok(cloudflareWorkflow.includes("'independent-sport-design.css'"), "the deploy must allow the design asset");
assert.ok(cloudflareWorkflow.includes("node scripts/test_independent_sports_design.mjs"), "the deploy must run the isolated sport page test");
assert.ok(cloudflareWorkflow.includes("independent-sport-design.css?v=20261013-premium-terminal4"), "the production smoke test must verify the built asset on both pages");
assert.ok(cloudflareWorkflow.includes("MS-INDEPENDENT-SPORTS-2026.10.13-DESIGN1"), "the production smoke test must verify the build marker");
console.log("Independent sport design checks passed: scoped selectors, mobile/accessibility states, build markers, preserved engine scripts/mounts and deployment smoke wiring.");
