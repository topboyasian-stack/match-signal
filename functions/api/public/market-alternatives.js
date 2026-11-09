// Production promotion: keep this endpoint on the guarded Cloudflare Pages deploy path.
const EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1";
const MAX_QUOTE_AGE_SECONDS = 900;
const MIN_RECOMMENDED_PROBABILITY = 0.65;
const RESEARCH_DISPLAY_BASELINE = 0.55;
const TOTAL_MARKETS = new Set(["total_goals", "total_games", "total_ou", "virtual_total", "over_under"]);
const SUPPORTED_MARKETS = new Set(["1X2", "winner", "total_goals", "total_games", "total_ou", "virtual_total", "over_under", "btts", "double_chance"]);

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

function marketKind(market) {
  if (TOTAL_MARKETS.has(String(market || ""))) return "total";
  if (String(market || "") === "btts") return "btts";
  if (String(market || "") === "double_chance") return "double_chance";
  return "winner";
}

function isTicketSelectable(sport, product, market, pick, line, marketId) {
  if (market === "total") {
    if (!["over", "under"].includes(pick) || !Number.isFinite(line) || line <= 0) return false;
    if (sport === "football") return marketId === "18";
    if (sport === "tennis") return marketId === "189";
    if (sport === "basketball") return marketId === "225" && line >= 100 && line <= 300;
    if (sport === "efootball") return ["efootball_gt", "efootball_adriatic"].includes(product) && ["18", "189"].includes(marketId);
    return false;
  }
  if (market !== "winner" || !["football", "tennis"].includes(sport)) return false;
  if (!["p1", "p2", "draw"].includes(pick) || (sport === "tennis" && pick === "draw")) return false;
  return sport === "football" ? ["1", "186"].includes(marketId) : marketId === "186";
}

export function publicAlternative(row, quote = {}) {
  const sourceSport = String(row.sport || "").toLowerCase();
  const product = String(row.product || "").toLowerCase();
  const sport = sourceSport === "virtual" && ["efootball_gt", "efootball_adriatic"].includes(product) ? "efootball" : sourceSport;
  const sourceMarket = String(row.market || "");
  const market = marketKind(sourceMarket);
  const total = market === "total";
  const btts = market === "btts";
  const doubleChance = market === "double_chance";
  const pick = String(row.pick || "").toLowerCase();
  if (!["football", "tennis", "basketball", "efootball"].includes(sport) || !SUPPORTED_MARKETS.has(sourceMarket)) return null;
  if (sport === "efootball" && (!["efootball_gt", "efootball_adriatic"].includes(product) || !total)) return null;
  if (total && !["over", "under"].includes(pick)) return null;
  if (btts && !["yes", "no"].includes(pick)) return null;
  if (doubleChance && !["1x", "12", "x2"].includes(pick)) return null;
  if (!total && !btts && !doubleChance && !["p1", "p2", "draw"].includes(pick)) return null;
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
  const oddsValue = Number(row.bookmaker_odds);
  const odds = Number.isFinite(oddsValue) && oddsValue > 1 ? oddsValue : null;
  const line = row.line == null ? null : Number(row.line);
  if (!eventId || !sportybetEventId || !marketId || !Number.isFinite(probability) ||
      probability <= 0 || probability > 1 || !timestamp(startTime)) return null;
  if (total && (!Number.isFinite(line) || line <= 0)) return null;
  if (sport === "efootball" && !["18", "189"].includes(marketId)) return null;
  const ticketSelectable = isTicketSelectable(sport, product, market, pick, line, marketId);
  const quoteFresh = quote.quoteFresh === true && odds !== null;
  const quoteStatus = odds === null && quote.quoteStatus === "FRESH_EXACT"
    ? "PRICE_UNAVAILABLE" : (quote.quoteStatus || "UNVERIFIED");
  const builderQualified = row.passed_builder_gates === true && quoteFresh &&
    probability >= MIN_RECOMMENDED_PROBABILITY && ticketSelectable;
  const belowBaseline = probability < RESEARCH_DISPLAY_BASELINE;
  const qualificationStatus = builderQualified ? "BUILDER_QUALIFIED" :
    !ticketSelectable ? "RESEARCH_ONLY_MARKET_NOT_TICKET_MAPPED" :
    !quoteFresh ? "RESEARCH_ONLY_QUOTE_NOT_CURRENT" :
    belowBaseline ? "RESEARCH_ONLY_BELOW_BASELINE" : "RESEARCH_ONLY";
  const marketLabel = total
    ? (sport === "tennis" ? "Total games" : sport === "basketball" ? "Full-game total" : "Total goals")
    : btts ? "Both teams to score"
    : doubleChance ? "Double chance"
    : "Winner";
  return {
    sport, product: sport === "efootball" ? product : null,
    event_id: eventId, sportybet_event_id: sportybetEventId,
    start_time: startTime, player_1: player1, player_2: player2,
    match, market, market_label: marketLabel,
    pick, line, market_id: marketId, odds,
    probability,
    builder_qualified: builderQualified,
    ticket_selectable: ticketSelectable,
    quote_status: quoteStatus,
    below_research_baseline: belowBaseline,
    qualification_status: qualificationStatus,
    role: "ALTERNATIVE", source: "SYSTEM_RECOMMENDED"
  };
}

function publicAlternativeRejectReason(row) {
  const sourceSport = String(row?.sport || "").toLowerCase();
  const product = String(row?.product || "").toLowerCase();
  const sport = sourceSport === "virtual" && ["efootball_gt", "efootball_adriatic"].includes(product) ? "efootball" : sourceSport;
  const market = String(row?.market || "");
  const kind = marketKind(market);
  const pick = String(row?.pick || "").toLowerCase();
  if (!["football", "tennis", "basketball", "efootball"].includes(sport)) return "unsupported_sport";
  if (!SUPPORTED_MARKETS.has(market)) return "unsupported_market";
  if (sport === "efootball" && (!["efootball_gt", "efootball_adriatic"].includes(product) || kind !== "total")) return "unsupported_efootball_market";
  if (kind === "total" && !["over", "under"].includes(pick)) return "unsupported_total_pick";
  if (kind === "btts" && !["yes", "no"].includes(pick)) return "unsupported_btts_pick";
  if (kind === "double_chance" && !["1x", "12", "x2"].includes(pick)) return "unsupported_double_chance_pick";
  if (kind === "winner" && !["p1", "p2", "draw"].includes(pick)) return "unsupported_winner_pick";
  if (sport === "tennis" && pick === "draw") return "tennis_draw_not_supported";
  const eventId = String(row.event_id || "");
  const sportybetEventId = String(row.sportybet_event_id || (sport === "efootball" ? row.event_id : ""));
  const marketId = String(row.sportybet_market_id || "");
  if (!eventId || !sportybetEventId || !marketId) return "missing_exact_market_identity";
  const probability = Number(row.model_probability);
  if (!Number.isFinite(probability) || probability <= 0 || probability > 1) return "invalid_model_probability";
  if (!timestamp(row.start_time)) return "invalid_kickoff_time";
  const line = row.line == null ? null : Number(row.line);
  if (kind === "total" && (!Number.isFinite(line) || line <= 0)) return "missing_or_invalid_total_line";
  if (sport === "efootball" && !["18", "189"].includes(marketId)) return "unsupported_efootball_market_id";
  return "other_public_validation_failure";
}

function repeatsPrimaryPick(source, item) {
  const originalPick = String(source.original_primary_pick || source.original_pick || "").toLowerCase();
  // Backward-compatible protection for older winner records that lack explicit
  // primary-market metadata.
  if (item.market === "winner" && originalPick && originalPick === item.pick) return true;
  const originalMarketRaw = String(source.original_primary_market || source.original_market || "");
  if (!originalMarketRaw || !originalPick || originalPick !== item.pick) return false;
  const originalMarket = marketKind(originalMarketRaw);
  if (originalMarket !== item.market) return false;
  if (item.market !== "total") return true;
  const rawLine = source.original_primary_line ?? source.original_line;
  const primaryLine = rawLine == null ? null : Number(rawLine);
  return Number.isFinite(primaryLine) && Number.isFinite(Number(item.line)) &&
    Math.abs(primaryLine - Number(item.line)) < 1e-9;
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
    quote_not_current: 0,
    public_schema_valid: 0,
    different_from_primary_pick: 0,
    more_likely_than_primary: 0,
    primary_probability_unavailable: 0,
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

    if (row.fresh_exact_quote === true) diagnostics.marked_fresh_exact_quote++;

    if (row.passed_builder_gates !== true &&
        !String(row.original_primary_pick || row.original_pick || row.primary_prediction_id || "").trim()) {
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

    // Visibility is not qualification. Keep otherwise valid research options
    // visible when their recorded price is stale or unverified; the ticket layer
    // independently rechecks the live event, market, line and current price.
    const quote = timestamp(row.quote_timestamp || row.market_odds_timestamp || row.odds_timestamp);
    const age = quote === null ? null : (nowMs - quote) / 1000;
    const oddsValue = Number(row.bookmaker_odds);
    const oddsAvailable = Number.isFinite(oddsValue) && oddsValue > 1;
    const quoteFreshByTime = row.fresh_exact_quote === true && age !== null && age >= 0 && age <= MAX_QUOTE_AGE_SECONDS;
    const quoteFresh = quoteFreshByTime && oddsAvailable;
    const quoteStatus = quoteFresh ? "FRESH_EXACT" :
      age === null ? "UNVERIFIED" :
      age < 0 ? "INVALID_TIMESTAMP" :
      age > MAX_QUOTE_AGE_SECONDS ? "STALE" :
      !oddsAvailable ? "PRICE_UNAVAILABLE" :
      row.fresh_exact_quote === true ? "NOT_VERIFIED_EXACT" : "NOT_MARKED_EXACT";
    if (quoteFresh) diagnostics.quote_fresh_within_15_minutes++;
    else diagnostics.quote_not_current++;

    const item = publicAlternative(row, { quoteFresh, quoteStatus });
    if (!item) {
      reject(publicAlternativeRejectReason(row));
      continue;
    }
    diagnostics.public_schema_valid++;

    if (repeatsPrimaryPick(row, item)) {
      reject("repeats_primary_pick");
      continue;
    }
    diagnostics.different_from_primary_pick++;

    const primaryProbability = Number(row.original_primary_probability ?? row.original_probability);
    if (Number.isFinite(primaryProbability) && primaryProbability > 0 && primaryProbability <= 1) {
      if (item.probability <= primaryProbability + 1e-9) {
        reject("not_more_likely_than_primary");
        continue;
      }
      item.primary_comparison_status = "MORE_LIKELY_THAN_PRIMARY";
      diagnostics.more_likely_than_primary++;
    } else {
      item.primary_comparison_status = "PRIMARY_PROBABILITY_UNAVAILABLE";
      diagnostics.primary_probability_unavailable++;
    }

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
      // Opposite sides on the same total line are distinct predictions. Only
      // collapse an exact market/line/side duplicate, not the Under alternative
      // merely because an Over on that line was ranked first.
      if (selected.some(x => x.market === row.market && x.line === row.line && x.pick === row.pick)) continue;
      selected.push(row);
      if (selected.length === 2) break;
    }
    alternatives.push(...selected);
  }
  diagnostics.candidates_before_fixture_limit = [...grouped.values()].reduce((sum, rows) => sum + rows.length, 0);
  diagnostics.selected_alternatives = alternatives.length;

  return {
    status: alternatives.length ? "OK" : "EMPTY",
    generated_at: document.updated_at || document.generated_at || null,
    min_probability: 0,
    research_display_baseline: RESEARCH_DISPLAY_BASELINE,
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
    if (!raw) return json({ status: "EMPTY", min_probability: 0, research_display_baseline: RESEARCH_DISPLAY_BASELINE, builder_min_probability: MIN_RECOMMENDED_PROBABILITY, max_per_fixture: 2, alternatives: [] });
    const document = JSON.parse(raw);
    if (!document || document.record_type !== "cross_sport_market_reassessment" || !Array.isArray(document.records)) {
      return json({ error: "EVIDENCE_UNAVAILABLE" }, 503);
    }
    return json(buildPublicAlternatives(document));
  } catch {
    return json({ error: "PUBLIC_ALTERNATIVES_UNAVAILABLE" }, 503);
  }
}
