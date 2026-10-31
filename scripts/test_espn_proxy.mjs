import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../functions/api/espn.js", import.meta.url), "utf8");
const moduleUrl = "data:text/javascript;base64," + Buffer.from(source, "utf8").toString("base64");
const { onRequestGet } = await import(moduleUrl);

const originalFetch = globalThis.fetch;
const upstreamRequests = [];
globalThis.fetch = async (url) => {
  upstreamRequests.push(String(url));
  return new Response(JSON.stringify({ events: [], fixture: "ESPN summary test" }), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
};

try {
  const summaryPath = "/apis/site/v2/sports/basketball/nba/summary";
  const request = new Request(
    "https://match-signal.test/api/espn?path=" +
      encodeURIComponent(summaryPath) +
      "&event=401909277"
  );
  const response = await onRequestGet({ request });
  assert.equal(response.status, 200, "a real numeric ESPN event ID must pass proxy validation");
  assert.equal(response.headers.get("X-Match-Signal-Proxy"), "ESPN");
  const target = new URL(upstreamRequests[0]);
  assert.equal(target.origin, "https://site.api.espn.com");
  assert.equal(target.pathname, summaryPath);
  assert.equal(target.searchParams.get("event"), "401909277");
  assert.equal(target.searchParams.get("region"), "us");
  assert.equal(target.searchParams.get("lang"), "en");

  const beforeInvalid = upstreamRequests.length;
  const invalidRequest = new Request(
    "https://match-signal.test/api/espn?path=" +
      encodeURIComponent(summaryPath) +
      "&event=not-a-number"
  );
  const invalidResponse = await onRequestGet({ request: invalidRequest });
  assert.equal(invalidResponse.status, 400);
  assert.equal((await invalidResponse.json()).error, "INVALID_ESPN_EVENT");
  assert.equal(upstreamRequests.length, beforeInvalid, "invalid event IDs must not reach ESPN");

  const externalPathRequest = new Request(
    "https://match-signal.test/api/espn?path=" +
      encodeURIComponent("https://example.com/apis/site/v2/sports/basketball/nba/summary") +
      "&event=401909277"
  );
  const externalPathResponse = await onRequestGet({ request: externalPathRequest });
  assert.equal(externalPathResponse.status, 400, "the proxy must remain restricted to ESPN");

  assert.equal(upstreamRequests.length, beforeInvalid + 1, "only the valid summary request may reach ESPN");

  console.log("ESPN proxy regression passed: numeric summary event IDs accepted; malformed IDs and external hosts rejected.");
} finally {
  globalThis.fetch = originalFetch;
}
