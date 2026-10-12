#!/usr/bin/env node
/**
 * Production-data diagnostic for the Upcoming Desk's live eFootball quote join.
 * Uses the exact qualification functions from sport-hubs.js and mirrors the
 * browser's event/participant/kickoff/exact-line matching. PAPER ONLY.
 */
import { readFile, writeFile } from "node:fs/promises";
import vm from "node:vm";

const BASE = (process.env.MATCH_SIGNAL_PUBLIC_BASE || "https://match-signal.pages.dev").replace(/\/+$/, "");
console.log("[coverage] start; base=" + BASE);
const MAX_PAGES = 3; // Keep this deployment diagnostic bounded; it is not a full feed crawler.
const source = await readFile(new URL("../sport-hubs.js", import.meta.url), "utf8");
console.log("[coverage] loaded desk source bytes=" + source.length);
const sourceStart = source.indexOf("function isOverUnderPrediction(x){");
const sourceEnd = source.indexOf("function ladderAnchor(rows){", sourceStart);
if (sourceStart < 0 || sourceEnd <= sourceStart) throw new Error("Production desk gate functions could not be extracted");

const sandbox = { Date, Number, String, Math, Array, Boolean, Object, Map, Set, RegExp };
vm.createContext(sandbox);
vm.runInContext(
  source.slice(sourceStart, sourceEnd) +
    "\n;globalThis.__desk={isVirtualDeskCandidate,qualificationState,exactVirtualMarketLine,qualifiedBestSelections};",
  sandbox,
  { filename: "sport-hubs.js#live-quote-coverage" }
);
const { isVirtualDeskCandidate, qualificationState, exactVirtualMarketLine, qualifiedBestSelections } = sandbox.__desk;

const candidateRaw = await readFile(new URL("../data/selection_candidates.json", import.meta.url), "utf8");
console.log("[coverage] read candidate artifact bytes=" + candidateRaw.length);
const rows = JSON.parse(candidateRaw);
console.log("[coverage] parsed candidate rows=" + rows.length);
const now = Date.now();
// Qualified Best can only promote rows that pass the model gate. High-probability
// research projections and explicitly pending rows are intentionally excluded;
// otherwise this checker paginates the whole research pool and can time out.
const virtualCandidates = rows.filter(isVirtualDeskCandidate).filter(row => {
  const product = String(row?.product || "").toLowerCase();
  const kickoff = Date.parse(String(row?.start_time || ""));
  return ["efootball_gt", "efootball_adriatic"].includes(product) &&
    Number.isFinite(kickoff) && kickoff > now && kickoff <= now + 7 * 24 * 60 * 60 * 1000 &&
    qualificationState(row).modelQualified === true;
});
console.log("[coverage] model-qualified eFootball candidate rows=" + virtualCandidates.length);
const poolGate = qualifiedBestSelections(virtualCandidates, now);
console.log("[coverage] pre-refresh gate diagnostics computed");

function identity(row, keys) {
  let value = "";
  for (const key of keys) {
    if (row?.[key] != null && String(row[key]).trim()) {
      value = String(row[key]).trim();
      break;
    }
  }
  const embedded = value.match(/\(([^()]*)\)\s*$/);
  if (embedded && embedded[1].trim()) value = embedded[1].trim();
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
function startTimestamp(row) {
  const raw = row?.start_time_ms ?? row?.startTimeMs ?? row?.start_time ?? row?.startTime ?? row?.timestamp ?? row?.date;
  if (typeof raw === "number" || (typeof raw === "string" && /^\d{10,13}$/.test(raw.trim()))) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n < 1e11 ? n * 1000 : n;
  }
  const parsed = Date.parse(String(raw ?? ""));
  return Number.isFinite(parsed) ? parsed : null;
}
function sameEvent(row, live) {
  const rowProduct = String(row?.product || "").toLowerCase();
  const liveProduct = String(live?.product || "").toLowerCase();
  if (rowProduct && liveProduct && rowProduct !== liveProduct) return false;
  const rowA = identity(row, ["participant_1", "player_1", "team_1", "home", "home_name", "homeName", "player1"]);
  const rowB = identity(row, ["participant_2", "player_2", "team_2", "away", "away_name", "awayName", "player2"]);
  const liveA = identity(live, ["participant_1", "player_1", "team_1", "home", "home_name", "homeName", "player1"]);
  const liveB = identity(live, ["participant_2", "player_2", "team_2", "away", "away_name", "awayName", "player2"]);
  if (!rowA || !rowB || !liveA || !liveB) return false;
  if ([rowA, rowB].sort().join("|") !== [liveA, liveB].sort().join("|")) return false;
  const rowTime = startTimestamp(row), liveTime = startTimestamp(live);
  // Match sport-hubs.js: event ID, product and both participant identities are still required; allow ten minutes for kickoff normalization drift.
  return rowTime != null && liveTime != null && Math.abs(rowTime - liveTime) <= 10 * 60 * 1000;
}

const byEvent = new Map();
const pages = [];
let scanComplete = false;
let scanStopReason = "maximum_pages_reached";
const REQUEST_TIMEOUT_MS = 18_000;

async function fetchCoveragePage(url, page) {
  const controller = new AbortController();
  let timeoutId;
  const request = (async () => {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache" },
      signal: controller.signal
    });
    if (!response.ok) throw new Error("Live quote source returned HTTP " + response.status + " on page " + page);
    return await response.json();
  })();
  const hardTimeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      controller.abort();
      reject(new Error("Live quote page " + page + " timed out after " + REQUEST_TIMEOUT_MS + "ms"));
    }, REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([request, hardTimeout]);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function fetchCoverageText(path) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(BASE + path, {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache" },
      signal: controller.signal
    });
    if (!response.ok) throw new Error("Production renderer asset returned HTTP " + response.status + " for " + path);
    return await response.text();
  } finally {
    clearTimeout(timeoutId);
  }
}

// Confirm the actual Cloudflare HTML references the updated renderer, and
// that this exact versioned asset contains the current candidate-pool refresh.
// A 200 for an unversioned JS URL alone cannot detect a stale browser bundle.
async function verifyDeployedRenderer() {
  const [homeHtml, upcomingHtml] = await Promise.all([
    fetchCoverageText("/?rendererCheck=" + Date.now()),
    fetchCoverageText("/upcoming.html?rendererCheck=" + Date.now())
  ]);
  const getVersion = (html, label) => {
    const match = html.match(/<script src=["']\.\/sport-hubs\.js\?v=([^"']+)["']/);
    if (!match) throw new Error(label + " does not reference a versioned sport-hubs.js renderer");
    return match[1];
  };
  const homeVersion = getVersion(homeHtml, "root page");
  const upcomingVersion = getVersion(upcomingHtml, "Upcoming page");
  if (homeVersion !== upcomingVersion) throw new Error("root and /upcoming.html reference different renderer versions");
  if (homeVersion === "20261012-qualified-candidate-status-fix1") {
    throw new Error("production HTML still references the stale pre-fix renderer cache key");
  }
  const deployedRenderer = await fetchCoverageText("/sport-hubs.js?v=" + encodeURIComponent(homeVersion));
  if (!deployedRenderer.includes("const requiredQuoteRows=virtualCandidates;")) {
    throw new Error("the deployed versioned renderer still lets non-candidate board rows block snapshot completeness");
  }
  if (!deployedRenderer.includes("api/sportybet-virtual?sources=efootball&pageSize=100&pageNum=")) {
    throw new Error("the deployed versioned renderer is not using the active eFootball-only quote feed");
  }
  console.log("Production Upcoming renderer verified: root + /upcoming.html share cache key " + homeVersion + "; candidate-pool scope and eFootball-only quote request are live.");
}

await verifyDeployedRenderer();

console.log("[coverage] beginning live source scan; maxPages=" + MAX_PAGES + "; requestTimeoutMs=" + REQUEST_TIMEOUT_MS);
for (let page = 1; page <= MAX_PAGES; page++) {
  const url = BASE + "/api/sportybet-virtual?sources=efootball&pageSize=100&pageNum=" + page + "&timeline=168&deskCoverage=" + Date.now();
  let payload;
  try {
    payload = await fetchCoveragePage(url, page);
  } catch (error) {
    scanComplete = false;
    scanStopReason = String(error?.message || error);
    console.error("Live eFootball coverage scan incomplete: " + scanStopReason);
    break;
  }
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const fetchedAt = payload?.updated_at || payload?.server_time || null;
  pages.push({ page, count: events.length, fetched_at: fetchedAt, status: payload?.status || null });
  for (const event of events) {
    const id = String(event?.event_id || "");
    if (!id) continue;
    if (!byEvent.has(id)) byEvent.set(id, []);
    byEvent.get(id).push({ ...event, __quote_fetched_at: fetchedAt });
  }
  const matchedNow = virtualCandidates.filter(row =>
    (byEvent.get(String(row?.event_id || "")) || []).some(live => sameEvent(row, live))
  ).length;
  console.log("Live eFootball coverage page " + page + ": " + JSON.stringify({
    returned_events: events.length,
    model_qualified_candidates: virtualCandidates.length,
    matched_candidate_rows: matchedNow,
    seen_unique_events: byEvent.size
  }));
  const allResolved = matchedNow === virtualCandidates.length;
  if (allResolved) {
    scanComplete = true;
    scanStopReason = "all_model_qualified_candidates_matched";
    break;
  }
  if (events.length < 100) {
    scanComplete = true;
    scanStopReason = "feed_page_exhausted";
    break;
  }
  if (page === MAX_PAGES) {
    scanComplete = false;
    scanStopReason = "maximum_pages_reached";
  }
}

let matchedEvents = 0, exactLineRows = 0, exactSideRows = 0, timestampsPresent = 0;
let matchedEventsWithMarkets = 0, observedMarketRows = 0, exactLineMetadataMatches = 0;
const marketIdNameCounts = {};
const currentRows = [];
const missed = [];
const matchedMarketSamples = [];
for (const row of virtualCandidates) {
  const eventMatches = (byEvent.get(String(row?.event_id || "")) || []).filter(live => sameEvent(row, live));
  const live = eventMatches[0];
  if (!live) {
    missed.push({ event_id: row.event_id, product: row.product, players: [row.player_1, row.player_2], start_time: row.start_time });
    continue;
  }
  matchedEvents++;
  const line = Number(row?.line);
  const side = String(row?.pick || row?.selection || "").toLowerCase();
  const liveMarkets = Array.isArray(live?.markets) ? live.markets : [];
  observedMarketRows += liveMarkets.length;
  if (liveMarkets.length) matchedEventsWithMarkets++;
  for (const market of liveMarkets) {
    const key = String(market?.id || "NO_ID") + "|" + String(market?.name || "NO_NAME");
    marketIdNameCounts[key] = (marketIdNameCounts[key] || 0) + 1;
    const marketLine = exactVirtualMarketLine(market);
    const id = String(market?.id || "");
    const name = String(market?.name || "").toLowerCase();
    const isTotalsMarket = ["18", "189"].includes(id) || name.includes("total") || name.includes("over/under") || name.includes("over under");
    if (isTotalsMarket && Number.isFinite(line) && Number.isFinite(marketLine) && Math.abs(marketLine - line) <= 1e-9) {
      exactLineMetadataMatches++;
    }
  }
  if (matchedMarketSamples.length < 8) {
    const summarized = liveMarkets.map(market => ({
      id: String(market?.id || ""),
      name: String(market?.name || ""),
      line: exactVirtualMarketLine(market),
      specifier: String(market?.specifier || ""),
      outcomes: (Array.isArray(market?.outcomes) ? market.outcomes : []).slice(0, 6).map(outcome => ({
        name: String(outcome?.name || ""),
        odds: outcome?.odds == null ? null : Number(outcome.odds),
        active: outcome?.active !== false
      }))
    }));
    const isTotals = m => ["18", "189"].includes(m.id) || /total|over\/under|over under/i.test(m.name);
    const relevant = summarized.filter(isTotals);
    const marketPreview = (relevant.length ? relevant.slice(0, 10) : summarized.slice(0, 10));
    matchedMarketSamples.push({
      event_id: String(row?.event_id || ""),
      product: String(row?.product || ""),
      participants: [row?.player_1 || row?.participant_1 || "", row?.player_2 || row?.participant_2 || ""],
      candidate_line: Number.isFinite(line) ? line : null,
      candidate_side: side,
      start_time: row?.start_time || null,
      live_market_count: liveMarkets.length,
      totals_market_count: relevant.length,
      shown_markets: marketPreview
    });
  }
  if (!Number.isFinite(line) || (side !== "over" && side !== "under")) continue;
  let over = null, under = null, matchedMarket = null;
  for (const market of liveMarkets) {
    const marketLine = exactVirtualMarketLine(market);
    const id = String(market?.id || "");
    const name = String(market?.name || "").toLowerCase();
    if (!["18", "189"].includes(id) && !name.includes("total") && !name.includes("over/under") && !name.includes("over under")) continue;
    if (!Number.isFinite(marketLine) || Math.abs(marketLine - line) > 1e-9) continue;
    let marketOver = null, marketUnder = null;
    for (const outcome of Array.isArray(market?.outcomes) ? market.outcomes : []) {
      if (outcome?.active === false) continue;
      const outcomeName = String(outcome?.name || "").toLowerCase();
      const odds = Number(outcome?.odds);
      if (!Number.isFinite(odds) || odds <= 1) continue;
      if (outcomeName.startsWith("over")) marketOver = odds;
      if (outcomeName.startsWith("under")) marketUnder = odds;
    }
    if (marketOver != null || marketUnder != null) {
      over = marketOver;
      under = marketUnder;
      matchedMarket = market;
      break;
    }
  }
  if (over == null && under == null) continue;
  exactLineRows++;
  const selectedOdds = side === "over" ? over : under;
  if (selectedOdds == null) continue;
  exactSideRows++;
  const liveTimestamp = live?.__quote_fetched_at || matchedMarket?.lastOddsChangeTime || null;
  if (liveTimestamp) timestampsPresent++;
  currentRows.push({
    ...row,
    sport: "virtual",
    event_id: String(row.event_id || ""),
    market: "over_under",
    selection: "O/U " + side + " " + line,
    pick: side,
    probability: Number(row?.model_probability),
    confidence: Number(row?.model_probability),
    bookmaker_odds: selectedOdds,
    sportybet_odds: selectedOdds,
    sportybet_odds_market: "total",
    sportybet_odds_line: line,
    sportybet_odds_side: side,
    sportybet_over_odds: over,
    sportybet_under_odds: under,
    bookmaker_available: Boolean(over && under),
    bookmaker_source: "SportyBet NG",
    market_odds_timestamp: liveTimestamp,
    desk_quote_refresh: "fresh_exact_event_line_side"
  });
}
const liveGate = qualifiedBestSelections(currentRows, Date.now());
const output = {
  verified_at: new Date().toISOString(),
  status: scanComplete ? "DIAGNOSTIC" : "INCOMPLETE",
  scan_complete: scanComplete,
  scan_stop_reason: scanStopReason,
  paper_only: true,
  candidate_artifact_rows: rows.length,
  virtual_candidate_rows_in_next_7_days: virtualCandidates.length,
  snapshot_gate_qualified_fixtures: poolGate.rows.length,
  snapshot_gate_diagnostics: poolGate.diagnostics,
  live_source_pages: pages,
  unique_live_events_seen: byEvent.size,
  matched_candidate_market_rows: matchedEvents,
  exact_line_market_rows: exactLineRows,
  exact_side_price_rows: exactSideRows,
  rows_with_quote_timestamp: timestampsPresent,
  live_gate_qualified_fixtures: liveGate.rows.length,
  live_gate_diagnostics: liveGate.diagnostics,
  matched_event_market_inventory: {
    candidate_rows_with_any_live_markets: matchedEventsWithMarkets,
    observed_market_rows: observedMarketRows,
    candidate_exact_line_totals_market_metadata_matches: exactLineMetadataMatches,
    market_id_name_counts: marketIdNameCounts
  },
  matched_market_samples: matchedMarketSamples,
  unmatched_samples: missed.slice(0, 8),
  qualified_examples: liveGate.rows.slice(0, 5).map(row => ({
    event_id: row.event_id,
    product: row.product,
    players: [row.player_1, row.player_2],
    market: row.selection,
    odds: row.sportybet_odds,
    start_time: row.start_time,
    quote_time: row.market_odds_timestamp
  }))
};
console.log(JSON.stringify(output, null, 2));
await writeFile(
  new URL("../LIVE-PRODUCTION-CHECK.json", import.meta.url),
  JSON.stringify(output, null, 2) + "\n",
  "utf8"
);

// If the snapshot has qualified picks but absolutely none of those active
// eFootball candidate events can be matched to production's live feed, this is
// a broken data bridge, not a reason to loosen qualification thresholds.
if (scanComplete && poolGate.rows.length > 0 && matchedEvents === 0) {
  throw new Error("Qualified snapshot candidates exist, but the completed live eFootball quote scan matched zero candidate events.");
}
