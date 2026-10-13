import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const [css, football, tennis, basketball] = await Promise.all([
  read("sport-hubs-design.css"),
  read("football.html"),
  read("tennis.html"),
  read("basketball.html")
]);

assert.match(css, /body\[data-page="hub"\]/, "all styling must be scoped to hub pages");
assert.match(css, /@media \(max-width: 640px\)/, "hub pages need small-screen layout rules");
assert.match(css, /@media \(prefers-reduced-motion: reduce\)/, "hub pages must respect reduced-motion preferences");
assert.match(css, /:focus-visible/, "interactive navigation must expose keyboard focus");
const normalizedCss = css.replace(/\/\*[\s\S]*?\*\//g, "");
const selectors = [...normalizedCss.matchAll(/(?:^|})\s*([^{}]+)\{/g)]
  .map(match => match[1].trim())
  .filter(selector => !selector.startsWith("@media"));
assert.ok(selectors.length > 25, "the hub design layer should contain the expected set of scoped rules");
for (const selectorGroup of selectors) {
  for (const selector of selectorGroup.split(",")) {
    assert.ok(selector.trim().startsWith('body[data-page="hub"]'), "unscoped CSS selector: " + selector.trim());
  }
}

for (const [name, html, marker] of [
  ["Football", football, "MS-SPORT-HUBS-2026.10.13-COMPETITION-LOGOS2-DESIGN1"],
  ["Tennis", tennis, "MS-SPORT-HUBS-2026.10.13-DESIGN1"],
  ["Basketball", basketball, "MS-SPORT-HUBS-2026.10.13-DESIGN1"]
]) {
  assert.match(html, /data-page="hub"/, name + " must keep the shared hub renderer mode");
  assert.match(html, /data-sport="/, name + " must retain its sport identity");
  assert.ok(html.includes(marker), name + " must expose the versioned build marker");
  assert.ok(html.includes("sport-hubs-design.css?v=20261013-premium-terminal3"), name + " must load the new versioned stylesheet");
  assert.ok(html.includes("sport-hubs.js"), name + " must keep the shared functional renderer");
  assert.ok(html.includes('id="leagueGrid"'), name + " must keep the competition grid mount");
}
assert.match(football, /league-logos\.js\?v=20261013-competition-logos2/, "Football's competition-logo registry must remain wired");
assert.doesNotMatch(await read("index.html"), /sport-hubs-design\.css/, "the hub stylesheet must not be loaded on Upcoming");
assert.doesNotMatch(await read("qualified-best.html"), /sport-hubs-design\.css/, "the hub stylesheet must not be loaded on Qualified Best");

console.log("Sport hub design checks passed: scoped selectors, versioned page markers, responsive/accessibility rules, renderer mounts and existing Football logo wiring.");
