import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = (process.env.MATCH_SIGNAL_BASE_URL || "https://match-signal.pages.dev").replace(/\/$/, "");
// Cache-bust the public feed so the production test cannot mistake an edge-cached
// pre-refresh EMPTY response for the current private-evidence refresh.
const api = await fetch(base + "/api/public/market-alternatives?smoke=" + Date.now(), {
  cache: "no-store",
  headers: { Accept: "application/json", "Cache-Control": "no-cache" },
  signal: AbortSignal.timeout(20000)
});
assert.equal(api.status, 200, "Public alternatives API must return HTTP 200");
assert.match(String(api.headers.get("content-type") || ""), /application\/json/i);
const feed = await api.json();
assert.equal(feed.status, "OK", "Public alternatives feed must be ready");
assert.equal(Number(feed.min_probability), 0.55, "The research lane must declare its 55% probability floor");
assert.equal(Number(feed.builder_min_probability), 0.65, "Builder-qualified picks must retain the 65% floor");
assert.ok(Array.isArray(feed.alternatives) && feed.alternatives.length, "Public alternatives must be non-empty");

const diagnostics = feed.diagnostics || {};
assert.ok(Number(diagnostics.quote_fresh_within_15_minutes) > 0, "The server must confirm fresh exact quotes exist");
assert.equal(Number(diagnostics.selected_alternatives), feed.alternatives.length, "Aggregate selected count must match the public feed");
const now = Date.now();
const eligible = feed.alternatives.filter((row) => {
  // Quote timestamps stay private; the API performs per-row freshness validation
  // and publishes aggregate freshness counters for safe production verification.
  const start = Date.parse(String(row.start_time || ""));
  return ["football", "tennis", "basketball", "efootball"].includes(String(row.sport || "")) &&
    row.event_id && row.sportybet_event_id && row.market_id &&
    row.role === "ALTERNATIVE" && row.source === "SYSTEM_RECOMMENDED" &&
    Number.isFinite(start) && start > now + 5 * 60 * 1000 &&
    typeof row.builder_qualified === "boolean" &&
    Number.isFinite(Number(row.probability)) && Number(row.probability) >= (row.builder_qualified ? 0.65 : 0.55) &&
    Number.isFinite(Number(row.odds)) && Number(row.odds) > 1 &&
    (row.market === "total"
      ? ["over", "under"].includes(String(row.pick || "")) && Number.isFinite(Number(row.line)) && Number(row.line) > 0
      : row.market === "winner" && ["p1", "p2", "draw"].includes(String(row.pick || "")));
});
assert.ok(eligible.length, "At least one alternative must remain safely pre-match for a real click test");
const byKey = new Map(eligible.map(row => [String(row.sport) + "|" + String(row.event_id), row]));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", error => pageErrors.push(String(error)));
const routes = ["/upcoming.html", "/", "/qualified-best.html", "/virtual-lab/", "/football.html", "/tennis.html", "/basketball.html"];
const diagnostics = [];
let result = null;

try {
  for (const route of routes) {
    await page.goto(base + route, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(2500);
    const state = await page.evaluate(() => ({
      cards: document.querySelectorAll("[data-ms-fixture-id]").length,
      options: [...document.querySelectorAll(".ms-qualified-alternatives button[data-ms-ticket-add]")].map(button => ({
        sport: button.getAttribute("data-ticket-sport"),
        eventId: button.getAttribute("data-ticket-event"),
        providerEventId: button.getAttribute("data-ticket-sportybet-event"),
        product: button.getAttribute("data-ticket-product"),
        market: button.getAttribute("data-ticket-market"),
        pick: button.getAttribute("data-ticket-pick"),
        line: button.getAttribute("data-ticket-line"),
        marketId: button.getAttribute("data-ticket-market-id"),
        startTime: button.getAttribute("data-ticket-start"),
        player1: button.getAttribute("data-ticket-player1"),
        player2: button.getAttribute("data-ticket-player2"),
        match: button.getAttribute("data-ticket-match"),
        qualified: button.getAttribute("data-ticket-model-qualified")
      }))
    }));

    const matched = state.options.find(button => {
      const row = byKey.get(String(button.sport) + "|" + String(button.eventId));
      return row && button.qualified === String(row.builder_qualified === true) &&
        button.providerEventId === String(row.sportybet_event_id) &&
        button.market === String(row.market) &&
        button.marketId === String(row.market_id) &&
        button.startTime === String(row.start_time) &&
        button.pick === String(row.pick) &&
        Number(button.line) === Number(row.line) &&
        button.player1 && button.player2;
    });
    diagnostics.push({ route, fixtureCards: state.cards, renderedAlternativeButtons: state.options.length, matchedLiveFeedRow: Boolean(matched) });
    if (!matched) continue;

    const index = state.options.findIndex(button =>
      button.sport === matched.sport && button.eventId === matched.eventId &&
      button.market === matched.market && button.pick === matched.pick &&
      button.marketId === matched.marketId && Number(button.line) === Number(matched.line));
    assert.ok(index >= 0, "Matched alternative button must be addressable in the live DOM");
    await page.locator(".ms-qualified-alternatives button[data-ms-ticket-add]").nth(index).click();
    await page.locator("#msTicketDrawer").waitFor({ state: "visible", timeout: 10000 });
    await page.waitForFunction(() =>
      window.MatchSignalTicket?.getSelectionCount?.() === 1 &&
      document.querySelectorAll("#msTicketDrawer .ms-ticket-slip-leg").length === 1,
      null,
      { timeout: 10000 }
    );

    const drawer = await page.evaluate(() => ({
      visible: !document.querySelector("#msTicketDrawer")?.hidden,
      count: window.MatchSignalTicket?.getSelectionCount?.(),
      countLabel: document.querySelector("#msTicketDrawer [data-ms-ticket-count]")?.textContent || "",
      legText: document.querySelector("#msTicketDrawer .ms-ticket-slip-leg")?.innerText || "",
      resultText: document.querySelector("#msTicketDrawer [data-ms-ticket-result]")?.textContent || "",
      persistedCount: (() => {
        try { return JSON.parse(localStorage.getItem("match-signal:sportybet-manual-ticket:v2") || "[]").length; }
        catch { return -1; }
      })()
    }));
    assert.equal(drawer.visible, true, "The shared drawer must open after the alternative is clicked");
    assert.equal(drawer.count, 1, "Exactly one selection must enter the shared ticket");
    assert.equal(drawer.persistedCount, 1, "The selected leg must persist in the shared ticket");
    assert.match(drawer.countLabel, /1 selection/i);
    assert.match(drawer.resultText, /Added to your single shared ticket/i);
    assert.ok(drawer.legText.includes(matched.match), "The shared drawer must display the clicked fixture");
    if (matched.qualified !== "true") assert.match(drawer.legText, /RESEARCH ONLY — Builder gate not passed/, "Research-only alternatives must remain visibly unqualified in the ticket");

    result = {
      route,
      sport: matched.sport,
      product: matched.product || null,
      event_id: matched.eventId,
      match: matched.match,
      market: matched.market,
      pick: matched.pick,
      line: matched.line,
      market_id: matched.marketId,
      builder_qualified: matched.qualified === "true",
      drawer_selection_count: drawer.count,
      persisted_selection_count: drawer.persistedCount,
      confirmation_text: drawer.resultText
    };
    break;
  }

  assert.ok(result, "No API-qualified alternative mounted and entered the drawer on the tested production routes. Diagnostics: " + JSON.stringify(diagnostics));
  console.log(JSON.stringify({
    status: "PASS",
    feed_status: feed.status,
    available_alternatives: feed.alternatives.length,
    safely_pre_match_alternatives: eligible.length,
    verified_click: result,
    route_diagnostics: diagnostics,
    page_errors: pageErrors
  }, null, 2));
} finally {
  await context.close();
  await browser.close();
}
