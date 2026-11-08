const ORIGIN = "https://www.sportybet.com";
const PLACEMENT_HINT = "aws:eu-west-1";
const PC_ENDPOINT = "/api/ng/factsCenter/pcUpcomingEvents";
const WAP_UPCOMING_ENDPOINT = "/api/ng/factsCenter/wapConfigurableUpcomingEvents";
const WAP_LIVE_ENDPOINT = "/api/ng/factsCenter/wapConfigurableIndexLiveEvents";
const EVENT_DETAILS_ENDPOINT = "/api/ng/factsCenter/event";
const SHARE_ENDPOINT = "/api/ng/orders/share";
const ALLOWED_ENDPOINTS = new Set([PC_ENDPOINT, WAP_UPCOMING_ENDPOINT, WAP_LIVE_ENDPOINT, EVENT_DETAILS_ENDPOINT]);
const ALLOWED_SPORTS = new Set(["sr:sport:1", "sr:sport:2", "sr:sport:5", "sr:sport:137", "sr:sport:202120001"]);
const ALLOWED_TOURNAMENTS = new Set(["sr:tournament:132"]);
const ALLOWED_MARKETS = new Set(["1","10","11","14","16","18","26","29","36","45","47","60100","186","187","188","189","202","203","204","210","219","223","225","227","228"]);

const UPSTREAM_HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Content-Type": "application/json",
  "Current-Country": "NG",
  "Origin": ORIGIN,
  "Referer": "https://www.sportybet.com/ng/",
  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    }
  });
}

function ingressMetadata(request) {
  const cf = request.cf || {};
  return {
    colo: typeof cf.colo === "string" ? cf.colo : null,
    country: typeof cf.country === "string" ? cf.country : null,
    region: typeof cf.region === "string" ? cf.region : null
  };
}

function readSafeParams(url, path) {
  if (path === EVENT_DETAILS_ENDPOINT) {
    const eventId = String(url.searchParams.get("eventId") || "").trim();
    if (!eventId.startsWith("sr:match:") || eventId.length > 128 || /[\r\n]/.test(eventId)) {
      throw new Error("eventId must be a bounded SportyBet sr:match identifier");
    }
    return new URLSearchParams({ eventId, _t: String(Date.now()) });
  }
  const sportId = String(url.searchParams.get("sportId") || "");
  if (!ALLOWED_SPORTS.has(sportId)) throw new Error("Unsupported sportId");
  const pageSize = Number(url.searchParams.get("pageSize") || 100);
  const pageNum = Number(url.searchParams.get("pageNum") || 1);
  const timeline = Number(url.searchParams.get("timeline") || 168);
  const tournamentId = String(url.searchParams.get("tournamentId") || "");
  if (tournamentId && !ALLOWED_TOURNAMENTS.has(tournamentId)) throw new Error("Unsupported tournamentId");
  if (tournamentId && sportId !== "sr:sport:2") throw new Error("Tournament filtering is only allowed for basketball");
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new Error("pageSize must be an integer from 1 to 100");
  if (!Number.isInteger(pageNum) || pageNum < 1 || pageNum > 20) throw new Error("pageNum must be an integer from 1 to 20");
  if (!Number.isInteger(timeline) || timeline < 12 || timeline > 720) throw new Error("timeline must be an integer from 12 to 720");
  const params = new URLSearchParams({
    sportId,
    pageSize: String(pageSize),
    pageNum: String(pageNum),
    todayGames: url.searchParams.get("todayGames") === "true" ? "true" : "false",
    timeline: String(timeline),
    _t: String(Date.now())
  });
  if (tournamentId) params.set("tournamentId", tournamentId);
  if (path === PC_ENDPOINT) {
    const raw = String(url.searchParams.get("marketId") || [...ALLOWED_MARKETS].join(","));
    const ids = raw.split(",").map(value => value.trim()).filter(Boolean);
    if (!ids.length || ids.some(id => !ALLOWED_MARKETS.has(id))) throw new Error("Unsupported marketId");
    params.set("marketId", [...new Set(ids)].join(","));
  }
  return params;
}


async function proxyShareRequest(request) {
  let raw;
  try {
    raw = await request.text();
  } catch (_) {
    return json({ ok: false, error: "INVALID_SHARE_PAYLOAD" }, 400);
  }
  if (raw.length > 32768) return json({ ok: false, error: "SHARE_PAYLOAD_TOO_LARGE" }, 413);

  let body;
  try {
    body = JSON.parse(raw);
  } catch (_) {
    return json({ ok: false, error: "INVALID_SHARE_JSON" }, 400);
  }
  const selections = body && body.selections;
  if (!Array.isArray(selections) || selections.length < 2 || selections.length > 20) {
    return json({ ok: false, error: "INVALID_SHARE_SELECTION_COUNT", detail: "A share request requires 2 to 20 selections." }, 422);
  }

  const clean = [];
  for (const item of selections) {
    const eventId = String(item?.eventId ?? "").trim();
    const marketId = String(item?.marketId ?? "").trim();
    const outcomeId = String(item?.outcomeId ?? "").trim();
    const specifier = item?.specifier == null ? null : String(item.specifier);
    if (!eventId || eventId.length > 128 || /[\r\n]/.test(eventId) ||
        !outcomeId || outcomeId.length > 128 || /[\r\n]/.test(outcomeId) ||
        !ALLOWED_MARKETS.has(marketId) ||
        (specifier !== null && (specifier.length > 256 || /[\r\n]/.test(specifier)))) {
      return json({ ok: false, error: "INVALID_SHARE_SELECTION", detail: "Each selection must contain a valid eventId, allowlisted marketId, outcomeId, and optional bounded specifier." }, 422);
    }
    clean.push({ eventId, marketId, specifier, outcomeId });
  }

  const url = new URL(ORIGIN + SHARE_ENDPOINT);
  url.searchParams.set("_t", String(Date.now()));
  try {
    const upstream = await fetch(url.toString(), {
      method: "POST",
      headers: {
        ...UPSTREAM_HEADERS,
        "Accept-Language": "en-NG,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
      },
      body: JSON.stringify({ selections: clean }),
      cache: "no-store",
      redirect: "follow",
      signal: AbortSignal.timeout(15000)
    });
    const contentType = String(upstream.headers.get("content-type") || "unknown");
    const text = await upstream.text();
    let payload = null;
    try { payload = JSON.parse(text); } catch (_) {}
    if (!payload) {
      return json({
        ok: false,
        error: "SPORTYBET_SHARE_NON_JSON",
        detail: "SportyBet share endpoint returned non-JSON content (HTTP " + upstream.status + ", content-type " + contentType + ")."
      }, 502);
    }
    return new Response(JSON.stringify(payload), {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "X-Match-Signal-Upstream-Status": String(upstream.status),
        "X-Match-Signal-Upstream-Endpoint": SHARE_ENDPOINT
      }
    });
  } catch (error) {
    return json({
      ok: false,
      error: "SPORTYBET_SHARE_UPSTREAM_FAILED",
      detail: String(error?.message || error || "share upstream request failed").slice(0, 200)
    }, 502);
  }
}

function eventCounts(payload) {
  const tournaments = Array.isArray(payload?.data?.tournaments) ? payload.data.tournaments : [];
  return {
    tournament_count: tournaments.length,
    event_count: tournaments.reduce((sum, tournament) =>
      sum + (Array.isArray(tournament?.events) ? tournament.events.length : 0), 0)
  };
}

async function probe(path, params) {
  const started = Date.now();
  const url = new URL(ORIGIN + path);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  try {
    const response = await fetch(url.toString(), {
      headers: UPSTREAM_HEADERS,
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    const contentType = response.headers.get("content-type") || "unknown";
    const body = await response.text();
    let isJson = false;
    let bizCode = null;
    let tournamentCount = null;
    let eventCount = null;
    let topLevelKeys = [];
    let dataKeys = [];
    let totalNum = null;
    let tournamentNames = [];
    let tournamentIds = [];
    let responseShape = "NON_JSON";
    try {
      const payload = JSON.parse(body);
      isJson = true;
      bizCode = payload?.bizCode ?? null;
      const data = payload?.data && typeof payload.data === "object" ? payload.data : {};
      const tournaments = Array.isArray(data.tournaments) ? data.tournaments : [];
      const counts = eventCounts(payload);
      tournamentCount = counts.tournament_count;
      eventCount = counts.event_count;
      topLevelKeys = Object.keys(payload || {}).slice(0, 12);
      dataKeys = Object.keys(data).slice(0, 12);
      const rawTotal = data.totalNum ?? data.totalEvents ?? data.totalCount ?? payload?.totalNum ?? null;
      const parsedTotal = rawTotal === null ? null : Number(rawTotal);
      totalNum = Number.isFinite(parsedTotal) ? parsedTotal : null;
      tournamentNames = tournaments.map(item => String(item?.name ?? item?.tournamentName ?? "")).filter(Boolean).slice(0, 12);
      tournamentIds = tournaments.map(item => String(item?.id ?? item?.tournamentId ?? "")).filter(Boolean).slice(0, 12);
      responseShape = !Array.isArray(data.tournaments)
        ? "TOURNAMENTS_FIELD_MISSING"
        : tournaments.length ? "TOURNAMENTS_PRESENT" : "TOURNAMENTS_ARRAY_EMPTY";
    } catch (_) {}
    return {
      endpoint: path,
      query: {
        sport_id: String(params.sportId || ""),
        page_size: Number(params.pageSize || 0),
        page_num: Number(params.pageNum || 0),
        timeline: Number(params.timeline || 0),
        today_games: String(params.todayGames ?? "false"),
        market_id: params.marketId == null ? null : String(params.marketId),
        tournament_id: params.tournamentId == null ? null : String(params.tournamentId)
      },
      status: response.status,
      ok: response.ok,
      content_type: contentType,
      is_json: isJson,
      biz_code: bizCode,
      total_num: totalNum,
      top_level_keys: topLevelKeys,
      data_keys: dataKeys,
      tournament_count: tournamentCount,
      tournament_names: tournamentNames,
      tournament_ids: tournamentIds,
      event_count: eventCount,
      response_shape: responseShape,
      body_prefix: body.replace(/\s+/g, " ").slice(0, 200),
      elapsed_ms: Date.now() - started
    };
  } catch (error) {
    return {
      endpoint: path,
      status: null,
      ok: false,
      content_type: null,
      is_json: false,
      error: String(error?.message || error || "request failed").slice(0, 200),
      elapsed_ms: Date.now() - started
    };
  }
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return json({ ok: true });
    if (url.pathname === SHARE_ENDPOINT) {
      if (request.method !== "POST") return json({ ok: false, error: "METHOD_NOT_ALLOWED" }, 405);
      return proxyShareRequest(request);
    }
    if (request.method !== "GET") return json({ ok: false, error: "METHOD_NOT_ALLOWED" }, 405);

    if (url.pathname === "/health") {
      return json({
        ok: true,
        service: "match-signal-sportybet-proxy",
        placement_hint: PLACEMENT_HINT,
        edge_ingress: ingressMetadata(request),
        time: new Date().toISOString()
      });
    }

    if (url.pathname === "/__diagnostics") {
      const pageParams = {
        sportId: "sr:sport:137",
        pageSize: 1,
        pageNum: 1,
        todayGames: "false",
        timeline: 168,
        _t: Date.now()
      };
      const [primary, fallback] = await Promise.all([
        probe(PC_ENDPOINT, {
          ...pageParams,
          marketId: [...ALLOWED_MARKETS].join(",")
        }),
        probe(WAP_UPCOMING_ENDPOINT, pageParams)
      ]);
      return json({
        ok: true,
        diagnostic: "sportybet-region-worker-v1",
        placement_hint: PLACEMENT_HINT,
        request_ingress: ingressMetadata(request),
        note: "request_ingress identifies the visitor-to-Worker entry colo; placement_hint identifies the configured back-end placement target.",
        probes: [primary, fallback],
        checked_at: new Date().toISOString()
      });
    }

    if (url.pathname === "/__nba-diagnostics") {
      const variants = [
        {
          variant: "timeline168_with_nba_tournament",
          params: {
            sportId: "sr:sport:2", pageSize: 100, pageNum: 1,
            todayGames: "false", timeline: 168, marketId: "225",
            tournamentId: "sr:tournament:132", _t: Date.now()
          }
        },
        {
          variant: "timeline168_without_tournament_filter",
          params: {
            sportId: "sr:sport:2", pageSize: 100, pageNum: 1,
            todayGames: "false", timeline: 168, marketId: "225", _t: Date.now()
          }
        },
        {
          variant: "timeline720_with_nba_tournament",
          params: {
            sportId: "sr:sport:2", pageSize: 100, pageNum: 1,
            todayGames: "false", timeline: 720, marketId: "225",
            tournamentId: "sr:tournament:132", _t: Date.now()
          }
        },
        {
          variant: "timeline720_without_tournament_filter",
          params: {
            sportId: "sr:sport:2", pageSize: 100, pageNum: 1,
            todayGames: "false", timeline: 720, marketId: "225", _t: Date.now()
          }
        }
      ];
      const probes = await Promise.all(variants.map(async item => ({
        variant: item.variant,
        ...(await probe(PC_ENDPOINT, item.params))
      })));
      return json({
        ok: true,
        diagnostic: "sportybet-nba-query-variants-v1",
        note: "Bounded read-only source diagnostics. Counts and response shape only; no raw fixtures or prices are exposed beyond the existing body prefix.",
        probes,
        checked_at: new Date().toISOString()
      });
    }

    if (!ALLOWED_ENDPOINTS.has(url.pathname)) return json({ ok: false, error: "ENDPOINT_NOT_ALLOWED" }, 404);

    let params;
    try {
      params = readSafeParams(url, url.pathname);
    } catch (error) {
      return json({ ok: false, error: "INVALID_QUERY", detail: String(error.message || error) }, 400);
    }

    const upstreamUrl = new URL(ORIGIN + url.pathname);
    for (const [key, value] of params) upstreamUrl.searchParams.set(key, value);
    try {
      const upstream = await fetch(upstreamUrl.toString(), {
        headers: UPSTREAM_HEADERS,
        cache: "no-store",
        signal: AbortSignal.timeout(10000)
      });
      const body = await upstream.text();
      return new Response(body, {
        status: upstream.status,
        headers: {
          "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
          "Cache-Control": "no-store",
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "X-Match-Signal-Upstream-Status": String(upstream.status),
          "X-Match-Signal-Upstream-Endpoint": url.pathname
        }
      });
    } catch (error) {
      return json({
        ok: false,
        error: "SPORTYBET_UPSTREAM_FETCH_FAILED",
        endpoint: url.pathname,
        detail: String(error?.message || error || "upstream fetch failed").slice(0, 200)
      }, 502);
    }
  }
};
