import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../functions/api/sportybet-virtual.js", import.meta.url), "utf8");
const exportDeclaration = "export async function onRequestGet(context){";
assert.ok(source.includes(exportDeclaration), "SportyBet virtual endpoint handler must be present");

const feed = {
  bizCode: 10000,
  data: {
    tournaments: [{
      id: "regression-tournament",
      name: "Regression Cup",
      categoryName: "eFootball",
      events: [{
        eventId: "regression-event",
        estimateStartTime: Date.now() + 60 * 60 * 1000,
        homeTeamName: "Roma (RegressionPlayerA)",
        awayTeamName: "Aston Villa (RegressionPlayerB)",
        markets: [{
          id: "18",
          name: "Over/Under",
          specifier: "total=2.5",
          line: 2.5,
          outcomes: [
            { id: "over", name: "Over 2.5", odds: 1.9, isActive: true },
            { id: "under", name: "Under 2.5", odds: 1.9, isActive: true }
          ]
        }]
      }]
    }]
  }
};

async function runQuery(query, responseSequence = [feed]) {
  const requestedPaths = [];
  const mockFetch = async input => {
    requestedPaths.push(new URL(String(input)).pathname);
    const index = Math.min(requestedPaths.length - 1, responseSequence.length - 1);
    const payload = responseSequence[index] ?? feed;
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  };
  const sandbox = {
    URL, Set, Date, Math, JSON, Number, String, Object, Array, Boolean,
    Response, AbortSignal, fetch: mockFetch, setTimeout
  };
  vm.createContext(sandbox);
  const executable = source.replace(exportDeclaration, "async function onRequestGet(context){") +
    "\n;globalThis.__handler=onRequestGet;";
  vm.runInContext(executable, sandbox, { filename: "sportybet-virtual.js", timeout: 5000 });

  const response = await sandbox.__handler({
    request: { url: "https://match-signal.pages.dev/api/sportybet-virtual?" + query }
  });
  return { response, payload: await response.json(), requestedPaths };
}

const upcomingOnly = await runQuery("sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false");
assert.equal(upcomingOnly.response.status, 200);
assert.equal(upcomingOnly.payload.ok, true);
assert.equal(upcomingOnly.payload.status, "LIVE");
assert.equal(upcomingOnly.payload.events.length, 1, "upcoming eFootball events remain available");
assert.equal(upcomingOnly.payload.source_status.efootball.status, "LIVE");
assert.equal(Object.hasOwn(upcomingOnly.payload.source_status, "efootball_live"), false,
  "upcoming-only mode does not add live-endpoint status/errors to quote completeness diagnostics");
assert.deepEqual(upcomingOnly.requestedPaths, ["/api/ng/factsCenter/pcUpcomingEvents"],
  "upcoming-only mode should request only the upcoming event endpoint");

const emptyFeed = { bizCode: 10000, data: { tournaments: [] } };
const recovered = await runQuery(
  "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false",
  [emptyFeed, feed]
);
assert.equal(recovered.payload.status, "LIVE", "a transient empty upstream page should recover on the retry");
assert.equal(recovered.payload.events.length, 1, "the retry should restore usable exact event markets");
assert.equal(recovered.payload.source_status.efootball.status, "LIVE");
assert.equal(recovered.payload.source_status.efootball.attempts, 2);
assert.equal(recovered.payload.source_status.efootball.retried, true);
assert.equal(recovered.requestedPaths.length, 2, "the eFootball upcoming endpoint is retried once after an empty upstream response");

const stillEmpty = await runQuery(
  "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false",
  [emptyFeed]
);
assert.equal(stillEmpty.payload.status, "UPSTREAM_EMPTY", "a feed that remains empty after retries must remain explicitly unavailable");
assert.equal(stillEmpty.payload.source_status.efootball.status, "EMPTY");
assert.equal(stillEmpty.payload.events.length, 0, "retry logic must never manufacture fixture rows");
assert.equal(stillEmpty.requestedPaths.length, 2, "persistently empty upstream response is bounded to two attempts");

const combined = await runQuery("sources=efootball&pageSize=100&pageNum=1&timeline=168");
assert.equal(combined.response.status, 200);
assert.equal(combined.payload.ok, true);
assert.ok(combined.requestedPaths.includes("/api/ng/factsCenter/wapConfigurableIndexLiveEvents"),
  "default mode must preserve the combined upcoming/live feed behavior for other consumers");

console.log("SportyBet quote snapshot tests passed: transient empty feeds retry and recover; persistent emptiness stays unavailable; default combined mode remains unchanged.");
