import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");

const [qualifiedHtml, css, homeHtml, footballHtml] = await Promise.all([
  read("qualified-best.html"),
  read("qualified-best-design.css"),
  read("index.html"),
  read("football.html")
]);

assert.match(qualifiedHtml, /data-page="qualified-best"/, "Qualified Best must have its own page scope");
assert.match(qualifiedHtml, /MS-UNIFIED-2026\.10\.13\.5-DESIGN-PILOT2/, "Qualified Best must expose the current design build marker");
assert.match(qualifiedHtml, /qualified-best-design\.css\?v=20261013-premium-terminal2/, "Qualified Best must load the versioned stylesheet");
assert.match(qualifiedHtml, /id="qualifiedBestBoard"/, "the live qualified board mount must remain intact");
assert.match(qualifiedHtml, /id="qualifiedBestLastSeenBoard"/, "the not-current archive mount must remain intact");
assert.match(css, /body\[data-page="qualified-best"\]/, "all page visuals must target Qualified Best");
assert.match(css, /\.ms-qualified-best-row/, "current qualified picks need dedicated styling");
assert.match(css, /\.ms-qualified-best-lastseen-row/, "last-seen rows need separate styling");
assert.match(css, /@media \(max-width: 760px\)/, "the page must include tablet/mobile layout rules");
assert.match(css, /@media \(prefers-reduced-motion: reduce\)/, "the page must respect reduced-motion preferences");
assert.match(css, /:focus-visible/, "interactive controls must expose a visible keyboard focus");
assert.doesNotMatch(homeHtml, /qualified-best-design\.css/, "the Qualified Best stylesheet must not load on Upcoming");
assert.doesNotMatch(footballHtml, /qualified-best-design\.css/, "the Qualified Best stylesheet must not load on Football");
assert.match(homeHtml, /ms-design-system\.css\?v=20261013-premium-terminal1/, "the existing Upcoming pilot must remain present");
console.log("Qualified Best design scope, build markers, page mounts, responsive layout and accessibility checks passed.");
