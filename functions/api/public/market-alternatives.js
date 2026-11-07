// Production promotion: keep this endpoint on the guarded Cloudflare Pages deploy path.
const EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1";
const MAX_QUOTE_AGE_SECONDS = 900;
const MIN_RECOMMENDED_PROBABILITY = 0.65;
const SUPPORTED_MARKETS = new Set(["1X2", "winner", "total_goals", "total_games", "total_ou", "virtual_total"]);

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=30, stale-while-revalidate=30",
      "x-content-type-options": "nosniff"
    }
  });
}

function timestamp(value) {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

export function publicAlternative(row) {
  const sourceSport = String(row.sport || "").toLowerCase();
  const product = String(row.product || "").toLowerCase();
  const sport = sourceSport === "virtual" && ["efootball_gt", "efootball_adriatic"].includes(product) ? "efootball" : sourceSport;
  const market = String(row.market || "");
  const pick = String(row.pick || "").toLowerCase();
  const total = ["total_goals", "total_games", "total_ou", "virtual_total"].includes(market);
  if (!["football", "tennis", "basketball", "efootball"].includes(sport) || !SUPPORTED_MARKETS.has(market)) return null;
  if (sport === "efootball" && (!["efootball_gt", "efootball_adriatic"].includes(product) || !total)) return null;
  if (total && !["over", "under"].includes(pick)) return null;
  if (!total && !["p1", "p2", "draw"].includes(pick)) return null;
  if (sport === "tennis" && pick === "draw") return null;
  const eventId = String(row.event_id || "");
  const sportybetEventId = String(row.sportybet_event_id || (sport === "efootball" ? row.event_id : ""));
  const marketId = String(row.sportybet_market_id || "");
  const startTime = String(row.start_time || "");
  const match = String(row.match || "");
  const matchParts = match.split(/\s+vs\s+/i);
  const player1 = String(row.player_1 || row.home_team || matchParts[0] || "").trim();
  const player2 = String(row.player_2 || row.away_team || matchParts[1] || "").trim();
  const probability = Number(row.model_probability);
  const odds = Number(row.bookmaker_odds);
  const line = row.line == null ? null : Number(row.line);
  if (!eventId || !sportybetEventId || !marketId || !Number.isFinite(probability) ||
      probability < MIN_RECOMMENDED_PROBABILITY || probability > 1 ||
      !Number.isFinite(odds) || odds <= 1 || !timestamp(startTime)) return null;
  if (total && (!Number.isFinite(line) || line <= 0)) return null;
  if (sport === "efootball" && !["18", "189"].includes(marketId)) return null;
  return {
    sport, product: sport === "efootball" ? product : null,
    event_id: eventId, sportybet_event_id: sportybetEventId,
    start_time: startTime, player_1: player1, player_2: player2,
    match, market: total ? "total" : "winner",
    market_label: total ? (market === "total_games" ? "Total games" : "Total goals") : "Winner",
    pick, line, market_id: marketId, odds,
    probability, role: "ALTERNATIVE", source: "SYSTEM_RECOMMENDED"
  };
}

function repeatsPrimaryPick(source, item) {
  // A system alternative must not merely echo the primary winner selection.
  // Other markets (especially totals) remain eligible to compete on the same fixture.
  const originalPick = String(source.original_pick || "").toLowerCase();
  return item.market === "winner" && originalPick && originalPick === item.pick;
}

export function buildPublicAlternatives(document, nowMs = Date.now()) {
  const grouped = new Map();
  for (const row of document.records) {
    // Alternatives are evaluated beside the primary prediction. They do not
    // need to pass the accumulator/Builder promotion gate first. Exact event,
    // market and outcome IDs, a fresh quote, and the alternative probability
    // floor still apply below.
    if (!row || row.fresh_exact_quote !== true ||
        row.prediction_role !== "ALTERNATIVE" || row.alternative_source !== "SYSTEM_RECOMMENDED") continue;
    // If Builder rejected this row, it must still be explicitly linked to the
    // primary pick for the same fixture; an unlinked row is not an alternative.
    if (row.passed_builder_gates !== true && !String(row.original_pick || row.primary_prediction_id || "").trim()) continue;
    const start = timestamp(row.start_time);
    const quote = timestamp(row.quote_timestamp);
    if (start === null || start <= nowMs + 120000 || quote === null) continue;
    const age = (nowMs - quote) / 1000;
    if (age < 0 || age > MAX_QUOTE_AGE_SECONDS) continue;
    const item = publicAlternative(row);
    if (!item || repeatsPrimaryPick(row, item)) continue;
    const key = item.sport + "|" + item.event_id;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(item);
  }

  const alternatives = [];
  for (const rows of grouped.values()) {
    rows.sort((a, b) => b.probability - a.probability || b.odds - a.odds);
    // Show at most two distinct market/line options per fixture.
    const selected = [];
    for (const row of rows) {
      if (selected.some(x => x.market === row.market && x.line === row.line)) continue;
      selected.push(row);
      if (selected.length === 2) break;
    }
    alternatives.push(...selected);
  }
  return {
    status: "OK",
    generated_at: document.updated_at || document.generated_at || null,
    min_probability: MIN_RECOMMENDED_PROBABILITY,
    max_per_fixture: 2,
    alternatives
  };
}

export async function onRequestGet({ request, env }) {
  if (request.method !== "GET") return json({ error: "METHOD_NOT_ALLOWED" }, 405);
  try {
    const raw = await env.MATCH_SIGNAL_ANALYST_STORE.get(EVIDENCE_KEY);
    if (!raw) return json({ status: "EMPTY", alternatives: [] });
    const document = JSON.parse(raw);
    if (!document || document.record_type !== "cross_sport_market_reassessment" || !Array.isArray(document.records)) {
      return json({ error: "EVIDENCE_UNAVAILABLE" }, 503);
    }
    return json(buildPublicAlternatives(document));
  } catch {
    return json({ error: "PUBLIC_ALTERNATIVES_UNAVAILABLE" }, 503);
  }
}
