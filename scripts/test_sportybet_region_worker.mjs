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
  let seenUrls = [];
  globalThis.fetch = async (input, options = {}) => {
    fetchCount += 1;
    lastUrl = new URL(String(input));
    lastOptions = options;
    seenUrls.push(lastUrl);
    return new Response(JSON.stringify(jsonPayload), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    });
  };

  const invalidSport = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A999"
  ));
  assert.equal(invalidSport.status, 400);
  assert.equal(fetchCount, 0, "unknown sport ids must not reach the provider");

  const nbaTotals = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A2&pageSize=100&pageNum=1&timeline=96&marketId=225&tournamentId=sr%3Atournament%3A132"
  ));
  assert.equal(nbaTotals.status, 200, "NBA full-game totals market 225 must pass the allowlist");
  assert.equal(lastUrl.searchParams.get("sportId"), "sr:sport:2");
  assert.equal(lastUrl.searchParams.get("marketId"), "225");
  assert.equal(lastUrl.searchParams.get("tournamentId"), "sr:tournament:132");
  assert.equal(fetchCount, 1);
  fetchCount = 0;

  const football = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A1&pageSize=100&pageNum=1&timeline=168&marketId=1%2C18%2C10%2C14%2C16%2C29%2C45%2C47"
  ));
  assert.equal(football.status, 200, "shared ticket football revalidation must pass the source allowlist");
  assert.equal(lastUrl.searchParams.get("sportId"), "sr:sport:1");
  assert.equal(lastUrl.searchParams.get("marketId"), "1,18,10,14,16,29,45,47");
  assert.equal(fetchCount, 1);
  fetchCount = 0;

  const tennis = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A5&pageSize=100&pageNum=1&timeline=168&marketId=186%2C210%2C202%2C204%2C189%2C203%2C188%2C187"
  ));
  assert.equal(tennis.status, 200, "shared ticket tennis revalidation must pass the source allowlist");
  assert.equal(lastUrl.searchParams.get("sportId"), "sr:sport:5");
  assert.equal(lastUrl.searchParams.get("marketId"), "186,210,202,204,189,203,188,187");
  assert.equal(fetchCount, 1);
  fetchCount = 0;

  const singleEventId = "sr:match:BAaG1-6IhflmW86fjM|83vw";
  const singleEvent = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/event?eventId=" + encodeURIComponent(singleEventId)
  ));
  assert.equal(singleEvent.status, 200, "bounded single-event detail lookup must use the regional proxy");
  assert.equal(lastUrl.pathname, "/api/ng/factsCenter/event");
  assert.equal(lastUrl.searchParams.get("eventId"), singleEventId);
  assert.equal(fetchCount, 1, "the single-event endpoint should need only one upstream request");

  fetchCount = 0;
  const invalidEventId = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/event?eventId=" + encodeURIComponent("https://example.com/")
  ));
  assert.equal(invalidEventId.status, 400, "single-event lookup must reject non-SportyBet identifiers");
  assert.equal(fetchCount, 0, "invalid event IDs must never reach the provider");

  const invalidMarket = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A1&pageSize=10&pageNum=1&timeline=168&marketId=9999"
  ));
  assert.equal(invalidMarket.status, 400);
  assert.equal(fetchCount, 0, "market IDs outside the allowlist must still be rejected");

  fetchCount = 0;
  const invalidTournament = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A2&tournamentId=sr%3Atournament%3A999"
  ));
  assert.equal(invalidTournament.status, 400);
  assert.equal(fetchCount, 0, "unknown tournament filters must not reach the provider");

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

  const pageSix = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A1&pageSize=100&pageNum=6&timeline=168&marketId=1%2C18"
  ));
  assert.equal(pageSix.status, 200, "football catalogue pages beyond page 5 must be available to bounded manual ticket lookup");
  assert.equal(lastUrl.searchParams.get("pageNum"), "6");
  assert.equal(fetchCount, 1);

  fetchCount = 0;
  const pageTwenty = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A1&pageSize=100&pageNum=20&timeline=168&marketId=1%2C18"
  ));
  assert.equal(pageTwenty.status, 200, "the twentieth bounded football catalogue page must pass");
  assert.equal(lastUrl.searchParams.get("pageNum"), "20");
  assert.equal(fetchCount, 1);

  fetchCount = 0;
  const pageTwentyOne = await worker.fetch(new Request(
    "https://worker.test/api/ng/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A1&pageSize=100&pageNum=21&timeline=168&marketId=1%2C18"
  ));
  assert.equal(pageTwentyOne.status, 400);
  assert.equal((await pageTwentyOne.json()).error, "INVALID_QUERY");
  assert.equal(fetchCount, 0, "page 21 must remain outside the bounded proxy window");

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

  fetchCount = 0;
  seenUrls = [];
  const nbaQueryDiagnostic = await worker.fetch(new Request("https://worker.test/__nba-diagnostics"));
  const nbaQueryDiagnosticBody = await nbaQueryDiagnostic.json();
  assert.equal(nbaQueryDiagnostic.status, 200);
  assert.equal(nbaQueryDiagnosticBody.ok, true);
  assert.equal(nbaQueryDiagnosticBody.diagnostic, "sportybet-nba-query-variants-v1");
  assert.equal(nbaQueryDiagnosticBody.probes.length, 4);
  assert.deepEqual(nbaQueryDiagnosticBody.probes.map(item => item.variant), [
    "timeline168_with_nba_tournament",
    "timeline168_without_tournament_filter",
    "timeline720_with_nba_tournament",
    "timeline720_without_tournament_filter"
  ]);
  assert.deepEqual(nbaQueryDiagnosticBody.probes.map(item => item.query.timeline), [168, 168, 720, 720]);
  assert.deepEqual(nbaQueryDiagnosticBody.probes.map(item => item.query.tournament_id), [
    "sr:tournament:132", null, "sr:tournament:132", null
  ]);
  assert.deepEqual(nbaQueryDiagnosticBody.probes.map(item => item.query.market_id), ["225", "225", "225", "225"]);
  assert.ok(nbaQueryDiagnosticBody.probes.every(item => item.status === 200 && item.is_json));
  assert.equal(fetchCount, 4, "NBA diagnostic route must make exactly four bounded upstream probes");
  assert.deepEqual(seenUrls.map(requestUrl => Number(requestUrl.searchParams.get("timeline"))), [168, 168, 720, 720]);
  assert.deepEqual(seenUrls.map(requestUrl => requestUrl.searchParams.get("tournamentId")), [
    "sr:tournament:132", null, "sr:tournament:132", null
  ]);
  assert.ok(nbaQueryDiagnosticBody.probes.every(item => item.data_keys.includes("tournaments")));
  assert.ok(nbaQueryDiagnosticBody.probes.every(item => item.response_shape === "TOURNAMENTS_PRESENT"));

  fetchCount = 0;
  const shareSelections = [
    { eventId: "sr:match:football-test-1", marketId: "18", specifier: "total=2.5", outcomeId: "under" },
    { eventId: "sr:match:tennis-test-2", marketId: "186", specifier: null, outcomeId: "home" }
  ];
  const sharePost = await worker.fetch(new Request("https://worker.test/api/ng/orders/share", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selections: shareSelections })
  }));
  assert.equal(sharePost.status, 200, "bounded SportyBet share POST must reach the fixed upstream");
  assert.equal(sharePost.headers.get("X-Match-Signal-Upstream-Endpoint"), "/api/ng/orders/share");
  assert.equal(lastUrl.origin, "https://www.sportybet.com");
  assert.equal(lastUrl.pathname, "/api/ng/orders/share");
  assert.equal(lastOptions.method, "POST");
  assert.deepEqual(JSON.parse(lastOptions.body), { selections: shareSelections });
  assert.equal(fetchCount, 1);

  fetchCount = 0;
  const invalidShare = await worker.fetch(new Request("https://worker.test/api/ng/orders/share", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selections: [{ eventId: "one" }] })
  }));
  assert.equal(invalidShare.status, 422);
  assert.equal(fetchCount, 0, "invalid share slips must be rejected before provider access");

  globalThis.fetch = async () => new Response("<!doctype html><html>challenge</html>", {
    status: 200, headers: { "Content-Type": "text/html; charset=utf-8" }
  });
  const shareHtml = await worker.fetch(new Request("https://worker.test/api/ng/orders/share", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selections: shareSelections })
  }));
  assert.equal(shareHtml.status, 502);
  const shareHtmlBody = await shareHtml.json();
  assert.equal(shareHtmlBody.error, "SPORTYBET_SHARE_NON_JSON");
  assert.match(shareHtmlBody.detail, /non-JSON content/);

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

  console.log("Regional SportyBet Worker tests passed: NBA, football and tennis allowlists; exact market forwarding; invalid-input rejection; bounded diagnostics; upstream errors; and HTML blocks.");
} finally {
  globalThis.fetch = originalFetch;
}
