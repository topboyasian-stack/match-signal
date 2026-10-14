import assert from "node:assert/strict";
import worker from "../sportybet-worker/src/index.js";

const originalFetch = globalThis.fetch;
const jsonPayload = {
  bizCode: 10000,
  data: {
    tournaments: [{
      name: "Regression Cup",
      events: [{ eventId: "test-event" }]
    }]
  }
};

try {
  const health = await worker.fetch(new Request("https://worker.test/health"));
  const healthBody = await health.json();
  assert.equal(health.status, 200);
  assert.equal(healthBody.ok, true);
  assert.equal(healthBody.placement_hint, "aws:eu-west-1");

  const post = await worker.fetch(new Request("https://worker.test/health", { method: "POST" }));
  assert.equal(post.status, 405);

  const disallowed = await worker.fetch(new Request("https://worker.test/fetch?url=https://example.com"));
  assert.equal(disallowed.status, 404);

  let fetchCount = 0;
  let lastUrl = null;
  let lastOptions = null;
  globalThis.fetch = async (input, options = {}) => {
    fetchCount += 1;
    lastUrl = new URL(String(input));
    lastOptions = options;
    return new Response(JSON.stringify(jsonPayload), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    });
  };

  const invalidSport = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A5"
  ));
  assert.equal(invalidSport.status, 400);
  assert.equal(fetchCount, 0, "unsupported sport ids must not reach the provider");

  const proxied = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A137&pageSize=100&pageNum=2&timeline=168&marketId=1%2C18&untrusted=https%3A%2F%2Fexample.com"
  ));
  assert.equal(proxied.status, 200);
  assert.equal(proxied.headers.get("X-Match-Signal-Upstream-Status"), "200");
  assert.equal(proxied.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await proxied.json(), jsonPayload);
  assert.equal(lastUrl.origin, "https://www.sportybet.com");
  assert.equal(lastUrl.pathname, "/api/ng/factsCenter/pcUpcomingEvents");
  assert.equal(lastUrl.searchParams.get("sportId"), "sr:sport:137");
  assert.equal(lastUrl.searchParams.get("pageNum"), "2");
  assert.equal(lastUrl.searchParams.get("marketId"), "1,18");
  assert.equal(lastUrl.searchParams.has("untrusted"), false, "arbitrary query parameters must not be forwarded");
  assert.equal(lastOptions.headers["Current-Country"], "NG");
  assert.equal(lastOptions.cache, "no-store");
  assert.equal(fetchCount, 1);

  fetchCount = 0;
  const diagnostic = await worker.fetch(new Request("https://worker.test/__diagnostics"));
  const diagnostics = await diagnostic.json();
  assert.equal(diagnostic.status, 200);
  assert.equal(diagnostics.diagnostic, "sportybet-region-worker-v1");
  assert.equal(diagnostics.probes.length, 2);
  assert.deepEqual(diagnostics.probes.map(item => item.endpoint), [
    "/api/ng/factsCenter/pcUpcomingEvents",
    "/api/ng/factsCenter/wapConfigurableUpcomingEvents"
  ]);
  assert.deepEqual(diagnostics.probes.map(item => item.event_count), [1, 1]);
  assert.equal(fetchCount, 2, "the probe must perform only two bounded requests");

  globalThis.fetch = async () => {
    throw new Error("synthetic network failure");
  };
  const failed = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A137"
  ));
  assert.equal(failed.status, 502);
  assert.equal((await failed.json()).error, "SPORTYBET_UPSTREAM_FETCH_FAILED");

  globalThis.fetch = async () => new Response("<html>blocked</html>", {
    status: 403,
    headers: { "Content-Type": "text/html" }
  });
  const blocked = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A137"
  ));
  assert.equal(blocked.status, 403, "provider blocks must stay visible rather than be disguised as an empty feed");
  assert.match(await blocked.text(), /blocked/);
  assert.equal(blocked.headers.get("Content-Type"), "text/html");

  console.log("Regional SportyBet Worker tests passed: safe routes, input limits, exact parameter forwarding, bounded diagnostics, upstream errors, and HTML blocks.");
} finally {
  globalThis.fetch = originalFetch;
}
