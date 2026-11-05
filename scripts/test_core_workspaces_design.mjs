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
assert.match(css, /body\[data-page="hub"\] \.cd-rail-card\s*\{/, "Football/Tennis side rails need the same card hierarchy");
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
  ["Main Desk", index, "MS-DESK-2026.10.14-V1", /sport-hubs\.js\?v=[^"']+/, null],
  ["Football", football, "MS-FOOTBALL-DESK-2026.10.14-V1", "league-logos.js?v=20261013-competition-logos2", "football"],
  ["Tennis", tennis, "MS-TENNIS-DESK-2026.10.14-V1", "sport-hubs.js?v=20261102-single-ticket1", "tennis"]
]) {
  assert.ok(html.includes(marker), name + " must declare the new page design marker");
  assert.ok(html.includes("core-workspaces-design.css?v=20261014-full-v1"), name + " must load the full-recomposition style");
  assert.ok(html.includes('id="msNav"'), name + " must retain the shared navigation mount");
  assert.ok(script instanceof RegExp ? script.test(html) : html.includes(script), name + " must preserve the existing renderer/logo script");
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
assert.ok(workflow.includes("getFrom(base, contract.css)"), "the primary production hostname must re-fetch the CSS for each redesigned workspace");
assert.ok(workflow.includes("cssBody.includes(contract.cssMarker)"), "the primary production hostname must verify the stylesheet marker, not just HTTP 200");
assert.ok(workflow.includes("MS-DESK-2026.10.14-V1"), "production smoke must verify the main Desk");
assert.ok(workflow.includes("MS-FOOTBALL-DESK-2026.10.14-V1"), "production smoke must verify Football");
assert.ok(workflow.includes("MS-TENNIS-DESK-2026.10.14-V1"), "production smoke must verify Tennis");


const [headers, sharedRenderer, workspaceUi, builderClient, virtualLabClient, livePage] = await Promise.all([
  read("_headers"),
  read("sport-hubs.js"),
  read("workspace-ui.js"),
  read("expansion-odds-builder.js"),
  read("virtual-lab-app.js"),
  read("live.html")
]);
assert.match(headers, /^\/api\/\*\n  Cache-Control: no-store, no-cache, must-revalidate, max-age=0/m,
  "live API responses must never be cached");
assert.match(headers, /^\/\*\.js\n  Cache-Control: public, max-age=300, stale-while-revalidate=300/m,
  "static JavaScript should be reused during workspace navigation");
assert.match(headers, /^\/\*\.css\n  Cache-Control: public, max-age=300, stale-while-revalidate=300/m,
  "static stylesheets should be reused during workspace navigation");
assert.match(headers, /^\/data\/\*\n  Cache-Control: public, max-age=30, stale-while-revalidate=60/m,
  "published data should have only a short bounded browser/edge cache");
assert.match(headers, /^\/index\.html\n  Cache-Control: no-store, no-cache, must-revalidate, max-age=0/m,
  "HTML routes must remain immediately revalidated after a deployment");
assert.match(sharedRenderer, /async function get\(path\)\{const url=String\(path\),live=.*cache:live\?'no-store':'default'/,
  "shared renderer must cache static artifacts but revalidate API routes");
assert.doesNotMatch(sharedRenderer, /async function get\(path\)\{[^}]*Date\.now\(\)[^}]*cache:'no-store'/,
  "shared renderer must not uniquely cache-bust all static data");
assert.match(workspaceUi, /club-logo-registry\.json'\),\{cache:'default'\}/,
  "shared navigation should reuse the club-logo registry across pages");
assert.match(workspaceUi, /async function json\(path\).*cache:live\?'no-store':'default'/,
  "workspace report artifacts should be cacheable without caching API calls");
assert.ok(builderClient.includes("fetch('./api/odds-builder-data?v=20261020-live-source2-'+Date.now(),{cache:'no-store'})"),
  "Odds Builder live data endpoint must remain live and uncached");
assert.ok(builderClient.includes("fetch('./data/odds_builder.json',{cache:'default'})") &&
  builderClient.includes("fetch('./data/odds_ticket_tracker.json',{cache:'default'})"),
  "Odds Builder static fallback/ledger artifacts should use the short shared data cache");
assert.ok(virtualLabClient.includes("fetch(DESK_LEARNING,{cache:'default'") &&
  virtualLabClient.includes("fetch(SNAPSHOT,{cache:'default'"),
  "Virtual Lab published artifacts should use the short shared data cache");
assert.ok(virtualLabClient.includes("fetch(base+'?'+params.toString(),{cache:'no-store'"),
  "Virtual Lab's live SportyBet feed must remain uncached");
assert.match(virtualLabClient, /await Promise\.all\(\[\s*loadDeskLearning\(\),\s*loadModelEvaluation\(\),\s*loadConfirmedWatch\(\),\s*loadParticipantProfiles\(\),\s*loadParticipantH2H\(\),\s*loadExternalH2H\(\)\s*\]\)/,
  "Virtual Lab should load independent evidence artifacts concurrently instead of serially delaying first render");

assert.match(livePage, /function getJson\(url\).*cache:isStatic\?'default':'no-store'/,
  "Live desk should reuse cached prediction snapshots but keep live API calls fresh");


console.log("Core workspaces design checks passed: scoped selectors, responsive/mobile layouts, keyboard/reduced-motion states, production markers and preserved renderer mounts.");
