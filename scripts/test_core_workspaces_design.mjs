import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const [css, index, football, tennis, workflow] = await Promise.all([
  read("core-workspaces-design.css"),
  read("index.html"),
  read("football.html"),
  read("tennis.html"),
  read(".github/workflows/cloudflare-pages.yml")
]);

assert.match(css, /MATCH-SIGNAL-FULL-RECOMPOSITION-V1: CORE DESK \/ FOOTBALL \/ TENNIS/);
assert.match(css, /@media \(max-width: 1040px\)/);
assert.match(css, /@media \(max-width: 680px\)/);
assert.match(css, /@media \(max-width: 420px\)/);
assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
assert.match(css, /:focus-visible/, "interactive controls must expose keyboard focus");
const normalizedCss = css.replace(/\/\*[\s\S]*?\*\//g, "");
const selectors = [...normalizedCss.matchAll(/(?:^|})\s*([^{}]+)\{/g)]
  .map(match => match[1].trim())
  .filter(selector => !selector.startsWith("@media"));
assert.ok(selectors.length >= 70, "full page recomposition rules should be present");
for (const group of selectors) {
  if (group.startsWith("@media")) continue;
  for (const selector of group.split(",")) {
    const s = selector.trim();
    assert.ok(
      s.startsWith('body[data-page="home"]') || s.startsWith('body[data-page="hub"]'),
      "unscoped page selector: " + s
    );
  }
}

for (const [name, html, marker, script, sport] of [
  ["Main Desk", index, "MS-DESK-2026.10.14-V1", "sport-hubs.js?v=20261013-qualified-best-live-coverage-retry1", null],
  ["Football", football, "MS-FOOTBALL-DESK-2026.10.14-V1", "league-logos.js?v=20261013-competition-logos2", "football"],
  ["Tennis", tennis, "MS-TENNIS-DESK-2026.10.14-V1", "sport-hubs.js?v=20261013-qualified-best-kickoff-sort1", "tennis"]
]) {
  assert.ok(html.includes(marker), name + " must declare the new page design marker");
  assert.ok(html.includes("core-workspaces-design.css?v=20261014-full-v1"), name + " must load the full-recomposition style");
  assert.ok(html.includes('id="msNav"'), name + " must retain the shared navigation mount");
  assert.ok(html.includes(script), name + " must preserve the existing renderer/logo script");
  if (sport) {
    assert.ok(html.includes('data-page="hub"'), name + " must retain the shared hub renderer mode");
    assert.ok(html.includes('data-sport="' + sport + '"'), name + " must retain the sport identity");
    for (const mount of ['id="count"', 'id="upcoming"', 'id="leagues"', 'id="leagueGrid"']) {
      assert.ok(html.includes(mount), name + " must preserve engine mount " + mount);
    }
  } else {
    assert.ok(html.includes('data-page="home"'), "Main Desk must retain home renderer mode");
    for (const mount of ['id="upCount"', 'id="upLast"', 'id="upQualified"', 'id="upSport"', 'id="upDate"', 'id="upSearch"', 'id="unifiedBoard"', 'id="qualifiedBestDataStatus"', 'id="qualifiedBestSummary"']) {
      assert.ok(html.includes(mount), "Main Desk must preserve engine mount " + mount);
    }
    assert.ok(html.includes("MS-UNIFIED-2026.10.13.4-DESIGN-PILOT1"), "keep legacy production route contract during migration");
  }
}
assert.match(football, /league-logos\.js\?v=20261013-competition-logos2/);
assert.match(football, /MS-SPORT-HUBS-2026\.10\.13-COMPETITION-LOGOS2-DESIGN1/);
assert.match(tennis, /MS-SPORT-HUBS-2026\.10\.13-DESIGN1/);
assert.ok(workflow.includes("'core-workspaces-design.css'"), "promotion allowlist must include the new stylesheet");
assert.ok(workflow.includes("node scripts/test_core_workspaces_design.mjs"), "deployment must execute this regression suite");
assert.ok(workflow.includes("MATCH-SIGNAL-FULL-RECOMPOSITION-V1: CORE DESK / FOOTBALL / TENNIS"), "production smoke must verify the live design asset marker");
assert.ok(workflow.includes("MS-DESK-2026.10.14-V1"), "production smoke must verify the main Desk");
assert.ok(workflow.includes("MS-FOOTBALL-DESK-2026.10.14-V1"), "production smoke must verify Football");
assert.ok(workflow.includes("MS-TENNIS-DESK-2026.10.14-V1"), "production smoke must verify Tennis");

console.log("Core workspaces design checks passed: scoped selectors, responsive/mobile layouts, keyboard/reduced-motion states, production markers and preserved renderer mounts.");
