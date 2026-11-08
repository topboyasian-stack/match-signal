// Production promotion: keep this endpoint on the guarded Cloudflare Pages deploy path.
const EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1";
const MAX_QUOTE_AGE_SECONDS = 900;
const MIN_RECOMMENDED_PROBABILITY = 0.65;
const MIN_RESEARCH_ALTERNATIVE_PROBABILITY = 0.55;
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
  const builderQualified = row.passed_builder_gates === true;
  const minimumProbability = builderQualified ? MIN_RECOMMENDED_PROBABILITY : MIN_RESEARCH_ALTERNATIVE_PROBABILITY;
  const odds = Number(row.bookmaker_odds);
  const line = row.line == null ? null : Number(row.line);
  if (!eventId || !sportybetEventId || !marketId || !Number.isFinite(probability) ||
      probability < minimumProbability || probability > 1 ||
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
    probability,
    builder_qualified: builderQualified,
    qualification_status: String(row.candidate_status || (builderQualified ? "BUILDER_QUALIFIED" : "RESEARCH_ONLY")),
    role: "ALTERNATIVE", source: "SYSTEM_RECOMMENDED"
  };
}

function publicAlternativeRejectReason(row) {
  const sourceSport = String(row?.sport || "").toLowerCase();
  const product = String(row?.product || "").toLowerCase();
  const sport = sourceSport === "virtual" && ["efootball_gt", "efootball_adriatic"].includes(product) ? "efootball" : sourceSport;
  const market = String(row?.market || "");
  const pick = String(row?.pick || "").toLowerCase();
  const total = ["total_goals", "total_games", "total_ou", "virtual_total"].includes(market);
  if (!["football", "tennis", "basketball", "efootball"].includes(sport)) return "unsupported_sport";
  if (!SUPPORTED_MARKETS.has(market)) return "unsupported_market";
  if (sport === "efootball" && (!["efootball_gt", "efootball_adriatic"].includes(product) || !total)) return "unsupported_efootball_market";
  if (total && !["over", "under"].includes(pick)) return "unsupported_total_pick";
  if (!total && !["p1", "p2", "draw"].includes(pick)) return "unsupported_winner_pick";
  if (sport === "tennis" && pick === "draw") return "tennis_draw_not_supported";
  const eventId = String(row.event_id || "");
  const sportybetEventId = String(row.sportybet_event_id || (sport === "efootball" ? row.event_id : ""));
  const marketId = String(row.sportybet_market_id || "");
  if (!eventId || !sportybetEventId || !marketId) return "missing_exact_market_identity";
  const probability = Number(row.model_probability);
  const builderQualified = row.passed_builder_gates === true;
  const minimumProbability = builderQualified ? MIN_RECOMMENDED_PROBABILITY : MIN_RESEARCH_ALTERNATIVE_PROBABILITY;
  if (!Number.isFinite(probability) || probability > 1 || probability < minimumProbability) return "below_probability_floor_or_invalid_probability";
  const odds = Number(row.bookmaker_odds);
  if (!Number.isFinite(odds) || odds <= 1) return "missing_or_invalid_bookmaker_odds";
  if (!timestamp(row.start_time)) return "invalid_kickoff_time";
  const line = row.line == null ? null : Number(row.line);
  if (total && (!Number.isFinite(line) || line <= 0)) return "missing_or_invalid_total_line";
  if (sport === "efootball" && !["18", "189"].includes(marketId)) return "unsupported_efootball_market_id";
  return "other_public_validation_failure";
}

function repeatsPrimaryPick(source, item) {
  // A system alternative must not merely echo the primary winner selection.
  // Other markets (especially totals) remain eligible to compete on the same fixture.
  const originalPick = String(source.original_pick || "").toLowerCase();
  return item.market === "winner" && originalPick && originalPick === item.pick;
}

export function buildPublicAlternatives(document, nowMs = Date.now()) {
  const grouped = new Map();
  const diagnostics = {
    records_seen: Array.isArray(document.records) ? document.records.length : 0,
    role_source_match: 0,
    marked_fresh_exact_quote: 0,
    primary_link_present: 0,
    kickoff_more_than_two_minutes_away: 0,
    quote_fresh_within_15_minutes: 0,
    public_schema_valid: 0,
    different_from_primary_pick: 0,
    candidates_before_fixture_limit: 0,
    selected_alternatives: 0,
    rejected_by_reason: {}
  };
  const reject = (reason) => {
    diagnostics.rejected_by_reason[reason] = (diagnostics.rejected_by_reason[reason] || 0) + 1;
  };

  for (const row of Array.isArray(document.records) ? document.records : []) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      reject("invalid_record");
      continue;
    }
    if (row.prediction_role !== "ALTERNATIVE" || row.alternative_source !== "SYSTEM_RECOMMENDED") {
      reject("not_system_alternative");
      continue;
    }
    diagnostics.role_source_match++;

    if (row.fresh_exact_quote !== true) {
      reject("quote_not_marked_exact_fresh");
      continue;
    }
    diagnostics.marked_fresh_exact_quote++;

    if (row.passed_builder_gates !== true && !String(row.original_pick || row.primary_prediction_id || "").trim()) {
      reject("missing_primary_link");
      continue;
    }
    diagnostics.primary_link_present++;

    const start = timestamp(row.start_time);
    if (start === null) {
      reject("invalid_kickoff_time");
      continue;
    }
    if (start <= nowMs + 120000) {
      reject("kickoff_within_two_minutes_or_started");
      continue;
    }
    diagnostics.kickoff_more_than_two_minutes_away++;

    const quote = timestamp(row.quote_timestamp);
    if (quote === null) {
      reject("missing_quote_timestamp");
      continue;
    }
    const age = (nowMs - quote) / 1000;
    if (age < 0) {
      reject("quote_timestamp_in_future");
      continue;
    }
    if (age > MAX_QUOTE_AGE_SECONDS) {
      reject("quote_older_than_15_minutes");
      continue;
    }
    diagnostics.quote_fresh_within_15_minutes++;

    const item = publicAlternative(row);
    if (!item) {
      reject(publicAlternativeRejectReason(row));
      continue;
    }
    diagnostics.public_schema_valid++;

    if (repeatsPrimaryPick(row, item)) {
      reject("repeats_primary_winner_pick");
      continue;
    }
    diagnostics.different_from_primary_pick++;

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
  diagnostics.candidates_before_fixture_limit = [...grouped.values()].reduce((sum, rows) => sum + rows.length, 0);
  diagnostics.selected_alternatives = alternatives.length;

  return {
    status: "OK",
    generated_at: document.updated_at || document.generated_at || null,
    min_probability: MIN_RESEARCH_ALTERNATIVE_PROBABILITY,
    builder_min_probability: MIN_RECOMMENDED_PROBABILITY,
    max_per_fixture: 2,
    diagnostics,
    alternatives
  };
}

export async function onRequestGet({ request, env }) {
  if (request.method !== "GET") return json({ error: "METHOD_NOT_ALLOWED" }, 405);
  try {
    const raw = await env.MATCH_SIGNAL_ANALYST_STORE.get(EVIDENCE_KEY);
    if (!raw) return json({ status: "EMPTY", min_probability: MIN_RESEARCH_ALTERNATIVE_PROBABILITY, builder_min_probability: MIN_RECOMMENDED_PROBABILITY, max_per_fixture: 2, alternatives: [] });
    const document = JSON.parse(raw);
    if (!document || document.record_type !== "cross_sport_market_reassessment" || !Array.isArray(document.records)) {
      return json({ error: "EVIDENCE_UNAVAILABLE" }, 503);
    }
    return json(buildPublicAlternatives(document));
  } catch {
    return json({ error: "PUBLIC_ALTERNATIVES_UNAVAILABLE" }, 503);
  }
}
