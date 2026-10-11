#!/usr/bin/env node
/**
 * Production-data diagnostic for the Upcoming Desk's live eFootball quote join.
 * Uses the exact qualification functions from sport-hubs.js and mirrors the
 * browser's event/participant/kickoff/exact-line matching. PAPER ONLY.
 */
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const BASE = (process.env.MATCH_SIGNAL_PUBLIC_BASE || "https://match-signal.pages.dev").replace(/\/+$/, "");
const MAX_PAGES = 5;
const source = await readFile(new URL("../sport-hubs.js", import.meta.url), "utf8");
const sourceStart = source.indexOf("function isOverUnderPrediction(x){");
const sourceEnd = source.indexOf("function ladderAnchor(rows){", sourceStart);
if (sourceStart < 0 || sourceEnd <= sourceStart) throw new Error("Production desk gate functions could not be extracted");

const sandbox = { Date, Number, String, Math, Array, Boolean, Object, Map, Set, RegExp };
vm.createContext(sandbox);
vm.runInContext(
  source.slice(sourceStart, sourceEnd) +
    "\n;globalThis.__desk={isVirtualDeskCandidate,exactVirtualMarketLine,qualifiedBestSelections};",
  sandbox,
  { filename: "sport-hubs.js#live-quote-coverage" }
);
const { isVirtualDeskCandidate, exactVirtualMarketLine, qualifiedBestSelections } = sandbox.__desk;

const rows = JSON.parse(await readFile(new URL("../data/selection_candidates.json", import.meta.url), "utf8"));
const now = Date.now();
const virtualCandidates = rows.filter(isVirtualDeskCandidate).filter(row => {
  const kickoff = Date.parse(String(row?.start_time || ""));
  return Number.isFinite(kickoff) && kickoff > now && kickoff <= now + 7 * 24 * 60 * 60 * 1000;
});
const poolGate = qualifiedBestSelections(virtualCandidates, now);

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
  return rowTime != null && liveTime != null && Math.abs(rowTime - liveTime) <= 90 * 1000;
}

const byEvent = new Map();
const pages = [];
for (let page = 1; page <= MAX_PAGES; page++) {
  const url = BASE + "/api/sportybet-virtual?sources=efootball,vfootball&pageSize=100&pageNum=" + page + "&timeline=168&deskCoverage=" + Date.now();
  const response = await fetch(url, { cache: "no-store", headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) throw new Error("Live quote source returned HTTP " + response.status + " on page " + page);
  const payload = await response.json();
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const fetchedAt = payload?.updated_at || payload?.server_time || null;
  pages.push({ page, count: events.length, fetched_at: fetchedAt, status: payload?.status || null });
  for (const event of events) {
    const id = String(event?.event_id || "");
    if (!id) continue;
    if (!byEvent.has(id)) byEvent.set(id, []);
    byEvent.get(id).push({ ...event, __quote_fetched_at: fetchedAt });
  }
  const allResolved = virtualCandidates.every(row =>
    (byEvent.get(String(row?.event_id || "")) || []).some(live => sameEvent(row, live))
  );
  if (allResolved || events.length < 100) break;
}

let matchedEvents = 0, exactLineRows = 0, exactSideRows = 0, timestampsPresent = 0;
const currentRows = [];
const missed = [];
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
  if (!Number.isFinite(line) || (side !== "over" && side !== "under")) continue;
  let over = null, under = null, matchedMarket = null;
  for (const market of Array.isArray(live?.markets) ? live.markets : []) {
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
  status: "DIAGNOSTIC",
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

// If the snapshot has qualified picks but absolutely none of those active
// eFootball candidate events can be matched to production's live feed, this is
// a broken data bridge, not a reason to loosen qualification thresholds.
if (poolGate.rows.length > 0 && matchedEvents === 0) {
  throw new Error("Qualified snapshot candidates exist, but the live eFootball quote bridge matched zero candidate events.");
}
