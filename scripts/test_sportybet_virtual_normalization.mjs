import assert from "node:assert/strict";
import { marketLineFromSportyBet, participantFromName } from "../functions/_shared/sportybet-virtual-normalization.mjs";

for (const line of [0.5, 1.5, 2.5, 4.5, 7.5, 8.5, 10.5]) {
  assert.equal(
    marketLineFromSportyBet({ specifier: `total=${line}` }),
    line,
    `decimal/integer total specifier ${line} must normalize`,
  );
  assert.equal(
    marketLineFromSportyBet({ specifier: `line=${line}` }),
    line,
    `line specifier ${line} must normalize`,
  );
}
assert.equal(marketLineFromSportyBet({ line: 7.5, specifier: "total=8.5" }), 7.5);
assert.equal(marketLineFromSportyBet({ specifier: "total=10" }), 10);
assert.equal(marketLineFromSportyBet({ specifier: "total=unknown" }), null);
assert.equal(marketLineFromSportyBet({}), null);

assert.equal(participantFromName("Barcelona (Virtual_3)"), "Virtual_3");
assert.equal(participantFromName("Spurs (MAGICIAN) "), "MAGICIAN");
assert.equal(participantFromName("plain participant"), "");
assert.equal(participantFromName("Team (with (nested) text)"), "text");

console.log("SportyBet virtual market normalization checks passed");
