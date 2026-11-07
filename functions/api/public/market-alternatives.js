const EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1";
const MAX_QUOTE_AGE_SECONDS = 900;
const MIN_RECOMMENDED_PROBABILITY = 0.65;
const SUPPORTED_MARKETS = new Set(["1X2", "winner", "total_goals", "total_games", "total_ou"]);

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

function publicAlternative(row) {
  const sport = String(row.sport || "").toLowerCase();
  const market = String(row.market || "");
  const pick = String(row.pick || "").toLowerCase();
  const total = ["total_goals", "total_games", "total_ou"].includes(market);
  if (!["football", "tennis", "basketball"].includes(sport) || !SUPPORTED_MARKETS.has(market)) return null;
  if (total && !["over", "under"].includes(pick)) return null;
  if (!total && !["p1", "p2", "draw"].includes(pick)) return null;
  if (sport === "tennis" && pick === "draw") return null;
  const eventId = String(row.event_id || "");
  const sportybetEventId = String(row.sportybet_event_id || "");
  const marketId = String(row.sportybet_market_id || "");
  const startTime = String(row.start_time || "");
  const probability = Number(row.model_probability);
  const odds = Number(row.bookmaker_odds);
  const line = row.line == null ? null : Number(row.line);
  if (!eventId || !sportybetEventId || !marketId || !Number.isFinite(probability) ||
      probability < MIN_RECOMMENDED_PROBABILITY || probability > 1 ||
      !Number.isFinite(odds) || odds <= 1 || !timestamp(startTime)) return null;
  if (total && (!Number.isFinite(line) || line <= 0)) return null;
  return {
    sport, event_id: eventId, sportybet_event_id: sportybetEventId,
    start_time: startTime, player_1: String(row.player_1 || row.home_team || row.match || "").split(/\\s+vs\\s+/i)[0].trim(),
    player_2: String(row.player_2 || row.away_team || row.match || "").split(/\\s+vs\\s+/i)[1]?.trim() || "",
    match: String(row.match || ""), market: total ? "total" : "winner",
    market_label: total ? (market === "total_games" ? "Total games" : "Total goals") : "Winner",
    pick, line, market_id: marketId, odds,
    probability, role: "ALTERNATIVE", source: "SYSTEM_RECOMMENDED"
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
    const now = Date.now();
    const grouped = new Map();
    for (const row of document.records) {
      if (!row || row.passed_builder_gates !== true || row.fresh_exact_quote !== true ||
          row.prediction_role !== "ALTERNATIVE" || row.alternative_source !== "SYSTEM_RECOMMENDED") continue;
      const start = timestamp(row.start_time);
      const quote = timestamp(row.quote_timestamp);
      if (start === null || start <= now + 120000 || quote === null) continue;
      const age = (now - quote) / 1000;
      if (age < 0 || age > MAX_QUOTE_AGE_SECONDS) continue;
      const item = publicAlternative(row);
      if (!item) continue;
      const key = item.sport + "|" + item.event_id;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(item);
    }
    const alternatives = [];
    for (const rows of grouped.values()) {
      rows.sort((a, b) => b.probability - a.probability || b.odds - a.odds);
      // One or two only: a second option must be a genuinely distinct market/pick.
      const selected = [];
      for (const row of rows) {
        if (selected.some(x => x.market === row.market && x.pick === row.pick && x.line === row.line)) continue;
        selected.push(row);
        if (selected.length === 2) break;
      }
      alternatives.push(...selected);
    }
    return json({ status: "OK", generated_at: document.updated_at || document.generated_at || null,
      min_probability: MIN_RECOMMENDED_PROBABILITY, max_per_fixture: 2, alternatives });
  } catch {
    return json({ error: "PUBLIC_ALTERNATIVES_UNAVAILABLE" }, 503);
  }
}
