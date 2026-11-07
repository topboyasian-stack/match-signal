import assert from "node:assert/strict";
import { onRequestPost } from "../functions/api/analyst/parse-ticket.js";

const token = "analyst-test-token-" + "b".repeat(48);
const origin = "https://match-signal.test";
class MemoryKV {
  constructor() { this.items = new Map(); }
  async get(key) { return this.items.has(key) ? this.items.get(key) : null; }
  async put(key, value) { this.items.set(key, value); }
  async delete(key) { this.items.delete(key); }
}
const parsedTicket = {
  reported_ticket_outcome: "LOST",
  currency: "NGN",
  total_odds: 5.2,
  legs: [
    {
      product: "tennis",
      match: "Wallin vs Sonego",
      actual_selection: { market: "total_games_over_under", pick: "over", line: 18.5, odds: 1.46 },
      qualification_state: "NOT_QUALIFIED"
    },
    {
      product: "tennis",
      match: "Shelton vs Van Assche",
      actual_selection: { market: "match_winner", pick: "p2", odds: 1.27 },
      qualification_state: "UNKNOWN",
      leg_outcome: "WON"
    },
    {
      product: "football",
      match: "Example FC vs Sample FC",
      actual_selection: { market: "total_goals_over_under", pick: "under", line: 4.5, odds: 1.19 },
      leg_outcome: "LOST",
      qualification_state: "NOT_QUALIFIED"
    }
  ]
};
const store = new MemoryKV();
let observedSystemPrompt = "";
const context = {
  request: new Request(origin + "/api/analyst/parse-ticket", {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + token,
      "Origin": origin,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ receipt_text: "Wallin vs Sonego Over 18.5 tennis games at 1.46; accumulator marked lost." })
  }),
  env: {
    MATCH_SIGNAL_ANALYST_TOKEN: token,
    MATCH_SIGNAL_ANALYST_STORE: store,
    AI: { async run(_model, options) {
      observedSystemPrompt = options.messages[0].content;
      return { response: JSON.stringify(parsedTicket) };
    } }
  }
};
const response = await onRequestPost(context);
assert.equal(response.status, 200, "mixed-market receipt should produce a review draft");
const result = await response.json();
assert.equal(result.ticket.reported_ticket_outcome, "LOST", "accumulator status is kept at ticket level");
assert.equal(result.ticket.legs.length, 3, "every leg remains in the draft regardless of accumulator status");
assert.equal(result.ticket.legs[0].actual_selection.market, "total_games_over_under");
assert.equal(result.ticket.legs[0].leg_outcome, undefined, "unreported per-leg outcomes are not guessed");
assert.equal(result.ticket.legs[0].qualification_state, "NOT_QUALIFIED");
assert.equal(result.ticket.legs[1].actual_selection.market, "match_winner");
assert.equal(result.ticket.legs[1].actual_selection.line, undefined, "winner markets do not require a line");
assert.equal(result.ticket.legs[1].leg_outcome, "WON");
assert.equal(result.ticket.legs[2].leg_outcome, "LOST");
assert.deepEqual(result.validation_errors, [], "fully described mixed-market legs validate");
assert.ok(observedSystemPrompt.includes("never infer every leg lost from a lost accumulator"));
assert.equal(await store.get("private-user-ticket-review-v1"), null, "parsing creates a draft only; it never saves automatically");
console.log("Mixed-market private ticket parser tests passed.");
