import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync("league-logos.js", "utf8");
const sandbox = {
  window: {},
  document: {
    readyState: "loading",
    addEventListener() {}
  }
};
vm.runInNewContext(source, sandbox, { filename: "league-logos.js" });

const logos = sandbox.window.MatchSignalLeagueLogos;
assert.ok(logos, "competition logo resolver is exposed for deterministic regression tests");

const expected = [
  ["La Liga", 140],
  ["LaLiga", 140],
  ["UEFA Champions League", 2],
  ["Champions League", 2],
  ["Bundesliga", 78],
  ["Ligue 1", 61],
  ["EPL", 39],
  ["English Premier League", 39],
  ["Serie A", 135],
  ["MLS", 253],
  ["Primeira Liga", 94],
  ["Liga Portugal", 94],
  ["England Amateur - U21 Professional Development League", 703],
  ["Professional Development League", 703],
  ["Saudi Pro League", 307]
];

for (const [name, id] of expected) {
  assert.equal(logos.logoIdForCompetition(name), id, name + " must resolve to its explicit competition ID");
  assert.equal(
    logos.logoUrlForCompetition(name),
    "https://media.api-sports.io/football/leagues/" + id + ".png",
    name + " must use the matching competition artwork"
  );
}

assert.equal(logos.logoIdForCompetition("Unknown Cup"), null, "unknown competitions must not be assigned an unrelated league logo");
assert.equal(logos.fallbackLabel("England Amateur - U21 Professional Development League"), "PDL", "PDL has a truthful initials fallback if the external image is unavailable");
assert.ok(logos.fallbackLabel("Unknown Cup"), "unknown competitions must still receive a stable initials fallback");
assert.equal(logos.logoUrlForCompetition("Unknown Cup"), null, "unknown competitions must not request the wrong logo");
assert.equal(logos.logoIdForCompetition("UEFA Europa League"), 3, "Europa League remains separate from Champions League");
assert.equal(logos.logoIdForCompetition("UEFA Conference League"), 848, "Conference League must have its own logo");
assert.equal(logos.logoIdForCompetition("England Amateur - U21 Professional Development League"), 703, "the specific PDL card resolves to API-Football v3 league 703");

const page = readFileSync("football.html", "utf8");
assert.match(page, /sport-hubs\.css\?v=20261013-competition-logos1/, "the Football page must bust the logo styling cache");
assert.match(page, /league-logos\.js\?v=20261013-competition-logos1/, "the Football page must load the competition logo enhancer");

console.log("Football competition logo regressions passed: league IDs and aliases, separate UEFA competitions, PDL mapping, wrong-logo fail-closed behavior, and page asset wiring.");
