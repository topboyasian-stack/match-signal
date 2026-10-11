#!/usr/bin/env node
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../workspace-ui.js", import.meta.url), "utf8");
const start = source.indexOf("function clean(");
const end = source.indexOf("function initials(", start);
if (start < 0 || end <= start || !source.slice(start, end).includes("function teamLogoTitleMatches(")) {
  throw new Error("Could not extract the production team-logo title validator");
}
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end) + "\nglobalThis.__testTeamLogoTitleMatches = teamLogoTitleMatches;", sandbox, { filename: "workspace-ui.js#team-logo-title-matcher" });
const matches = sandbox.__testTeamLogoTitleMatches;

for (const [name, title] of [
  ["Boca Juniors", "File:Club Atlético Boca Juniors logo (70 stars).png"],
  ["Germany", "File:Germany national football team logo.png"],
  ["Liverpool", "File:Logo Liverpool FC (2024).png"],
  ["Monaco", "File:AS Monaco FC logo.png"],
  ["PSG", "File:Logo PSG.png"],
]) {
  assert.equal(matches(name, title), true, `expected exact team crest to match: ${name} / ${title}`);
}
for (const [name, title] of [
  ["Paris", "File:Logo PSG.png"],
  ["Monaco", "File:Club Monaco Official Logo.png"],
  ["Twente", "File:FC Twente logo's in graffiti.jpg"],
  ["AC Milan", "File:AC Milan badge stadio Giuseppe Meazza.jpg"],
  ["Southampton", "File:Southampton FC crest - geograph.org.uk - 1723706.jpg"],
  ["Barcelona", "File:FC Barcelona Logo on Window.jpg"],
  ["Athletic Club Bilbao", "File:Athletic Club Miami NEW Logo 3 copy.png"],
  ["Arsenal", "File:Arsenal FC old crest small.png"],
  ["Liverpool FC", "File:Liverpool FC crest, Main Stand - side view.jpg"],
]) {
  assert.equal(matches(name, title), false, `wrong/photographic crest must be rejected: ${name} / ${title}`);
}
console.log("Workspace media resolver tests passed: 5 valid crests accepted, 9 misleading/ambiguous crests rejected.");
