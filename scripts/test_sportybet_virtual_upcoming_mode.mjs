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

function createResponseCache() {
  const entries = new Map();
  const keyOf = key => String(key?.url || key);
  return {
    entries,
    async match(key) {
      const response = entries.get(keyOf(key));
      return response ? response.clone() : null;
    },
    async put(key, response) {
      entries.set(keyOf(key), response.clone());
    }
  };
}

async function runQuery(query, responseSequence = [feed], responseCache = null) {
  const requestedPaths = [];
  const mockFetch = async input => {
    requestedPaths.push(new URL(String(input)).pathname);
    const index = Math.min(requestedPaths.length - 1, responseSequence.length - 1);
    const payload = responseSequence[index] ?? feed;
    if (payload && typeof payload === "object" && Object.hasOwn(payload, "rawBody")) {
      return new Response(payload.rawBody, {
        status: payload.status ?? 200,
        headers: { "Content-Type": payload.contentType ?? "text/html" }
      });
    }
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  };
  const sandbox = {
    URL, Request, Set, Date, Math, JSON, Number, String, Object, Array, Boolean,
    Response, AbortSignal, fetch: mockFetch, setTimeout,
    ...(responseCache ? { caches: { default: responseCache } } : {})
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

const htmlError = {
  rawBody: "<!doctype html><html><body>temporary upstream error</body></html>",
  status: 200,
  contentType: "text/html"
};
const fallbackRecovered = await runQuery(
  "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false",
  [htmlError, htmlError, feed]
);
assert.equal(fallbackRecovered.payload.status, "LIVE",
  "an HTML error page from the primary endpoint should recover through the separate SportyBet upcoming endpoint");
assert.equal(fallbackRecovered.payload.events.length, 1,
  "fallback events must still come from a parsed provider response");
assert.equal(fallbackRecovered.payload.source_status.efootball.fallback_attempted, true);
assert.equal(fallbackRecovered.payload.source_status.efootball.fallback_used, true);
assert.equal(fallbackRecovered.payload.source_status.efootball.endpoint, "/api/ng/factsCenter/wapConfigurableUpcomingEvents");
assert.deepEqual(fallbackRecovered.requestedPaths, [
  "/api/ng/factsCenter/pcUpcomingEvents",
  "/api/ng/factsCenter/pcUpcomingEvents",
  "/api/ng/factsCenter/wapConfigurableUpcomingEvents"
], "fallback should be bounded to one separate official endpoint call after the two primary attempts");

const stillHtml = await runQuery(
  "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false",
  [htmlError]
);
assert.equal(stillHtml.payload.status, "UPSTREAM_EMPTY",
  "persistent non-JSON upstream failures must remain explicitly unavailable without inventing event rows");
assert.equal(stillHtml.payload.source_status.efootball.status, "ERROR",
  "the detailed eFootball source status must identify the persistent upstream failure");
assert.equal(stillHtml.payload.source_status.efootball.fallback_used, false);
assert.match(stillHtml.payload.source_status.efootball.error, /HTML response/);
assert.equal(stillHtml.payload.events.length, 0, "HTML must never be interpreted as event data");
assert.equal(stillHtml.requestedPaths.length, 3, "a persistent HTML failure is bounded to two primary tries and one fallback");

const stillEmpty = await runQuery(
  "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false",
  [emptyFeed]
);
assert.equal(stillEmpty.payload.status, "UPSTREAM_EMPTY", "a feed that remains empty after retries must remain explicitly unavailable");
assert.equal(stillEmpty.payload.source_status.efootball.status, "EMPTY");
assert.equal(stillEmpty.payload.events.length, 0, "retry logic must never manufacture fixture rows");
assert.equal(stillEmpty.payload.source_status.efootball.fallback_attempted, true,
  "persistent primary emptiness gets one alternate-provider-endpoint check");
assert.equal(stillEmpty.payload.source_status.efootball.fallback_used, false,
  "the alternate endpoint must not be reported as used when it returns no events");
assert.equal(stillEmpty.requestedPaths.length, 3,
  "persistently empty upstream response is bounded to two primary attempts plus one fallback");


const cacheQuery = "sources=efootball&pageSize=100&pageNum=1&timeline=168&includeLive=false";
const responseCache = createResponseCache();
const seededSnapshot = await runQuery(cacheQuery, [feed], responseCache);
assert.equal(seededSnapshot.payload.status, "LIVE");
assert.ok(responseCache.entries.size > 0, "a successful provider snapshot should seed the edge cache");
const originalObservationTime = seededSnapshot.payload.updated_at;

const cachedAfterHtmlFailure = await runQuery(cacheQuery, [htmlError], responseCache);
assert.equal(cachedAfterHtmlFailure.payload.status, "LIVE",
  "a recent successful edge snapshot can bridge a temporary HTML provider failure");
assert.equal(cachedAfterHtmlFailure.payload.cache_fallback_used, true,
  "edge fallback must be visible in the API response");
assert.equal(cachedAfterHtmlFailure.payload.updated_at, originalObservationTime,
  "cache fallback must preserve the original provider observation timestamp");
assert.equal(cachedAfterHtmlFailure.payload.source_status.efootball.status, "CACHED");
assert.equal(cachedAfterHtmlFailure.payload.errors.length, 0);
assert.match(cachedAfterHtmlFailure.payload.cache_fallback_reason, /returned HTML response/);

const cachedAfterHtmlThenEmptyFallback = await runQuery(
  cacheQuery,
  [htmlError, htmlError, emptyFeed],
  responseCache
);
assert.equal(cachedAfterHtmlThenEmptyFallback.payload.status, "LIVE",
  "a hard primary HTML failure must remain an error when the alternate endpoint returns an empty response, allowing only a still-fresh last-good snapshot to bridge the outage");
assert.equal(cachedAfterHtmlThenEmptyFallback.payload.cache_fallback_used, true,
  "a failed primary endpoint plus an empty alternate endpoint must use a recent cached provider snapshot");
assert.equal(cachedAfterHtmlThenEmptyFallback.payload.updated_at, originalObservationTime,
  "the mixed-failure recovery must preserve the real observation timestamp");
assert.equal(cachedAfterHtmlThenEmptyFallback.payload.source_status.efootball.status, "CACHED");
assert.equal(cachedAfterHtmlThenEmptyFallback.payload.events.length, 1,
  "mixed upstream failure recovery must reuse only the previously observed event");

const emptyWithAvailableCache = await runQuery(cacheQuery, [emptyFeed], responseCache);
assert.equal(emptyWithAvailableCache.payload.source_status.efootball.status, "EMPTY",
  "genuinely valid empty primary and alternate responses remain classified as EMPTY");
assert.notEqual(emptyWithAvailableCache.payload.cache_fallback_used, true,
  "valid empty provider responses alone must never resurrect cached events");

const expiredResponseCache = createResponseCache();
await runQuery(cacheQuery, [feed], expiredResponseCache);
const [cachedKey, cachedResponse] = [...expiredResponseCache.entries.entries()][0];
const expiredPayload = await cachedResponse.clone().json();
expiredPayload.updated_at = new Date(Date.now() - 16 * 60 * 1000).toISOString();
expiredPayload.server_time = expiredPayload.updated_at;
expiredResponseCache.entries.set(cachedKey, new Response(JSON.stringify(expiredPayload), {
  headers: cachedResponse.headers
}));
const expiredCacheRejected = await runQuery(cacheQuery, [htmlError], expiredResponseCache);
assert.equal(expiredCacheRejected.payload.status, "UPSTREAM_EMPTY",
  "an edge snapshot older than the 15-minute quote gate must remain unavailable");
assert.notEqual(expiredCacheRejected.payload.cache_fallback_used, true,
  "expired cached odds must never be served as current data");

const combined = await runQuery("sources=efootball&pageSize=100&pageNum=1&timeline=168");
assert.equal(combined.response.status, 200);
assert.equal(combined.payload.ok, true);
assert.ok(combined.requestedPaths.includes("/api/ng/factsCenter/wapConfigurableIndexLiveEvents"),
  "default mode must preserve the combined upcoming/live feed behavior for other consumers");

console.log("SportyBet quote snapshot tests passed: transient empty feeds retry and recover; persistent emptiness stays unavailable; default combined mode remains unchanged.");
