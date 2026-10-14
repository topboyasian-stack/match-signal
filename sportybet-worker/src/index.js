const ORIGIN = "https://www.sportybet.com";
const PLACEMENT_HINT = "aws:eu-west-1";
const PC_ENDPOINT = "/api/ng/factsCenter/pcUpcomingEvents";
const WAP_UPCOMING_ENDPOINT = "/api/ng/factsCenter/wapConfigurableUpcomingEvents";
const WAP_LIVE_ENDPOINT = "/api/ng/factsCenter/wapConfigurableIndexLiveEvents";
const ALLOWED_ENDPOINTS = new Set([PC_ENDPOINT, WAP_UPCOMING_ENDPOINT, WAP_LIVE_ENDPOINT]);
const ALLOWED_SPORTS = new Set(["sr:sport:137", "sr:sport:202120001"]);
const ALLOWED_MARKETS = new Set(["1","18","10","29","11","26","36","14","60100","186","189","202","204","210"]);

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
      "Access-Control-Allow-Methods": "GET,OPTIONS",
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
  const sportId = String(url.searchParams.get("sportId") || "");
  if (!ALLOWED_SPORTS.has(sportId)) throw new Error("Unsupported sportId");
  const pageSize = Number(url.searchParams.get("pageSize") || 100);
  const pageNum = Number(url.searchParams.get("pageNum") || 1);
  const timeline = Number(url.searchParams.get("timeline") || 168);
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new Error("pageSize must be an integer from 1 to 100");
  if (!Number.isInteger(pageNum) || pageNum < 1 || pageNum > 5) throw new Error("pageNum must be an integer from 1 to 5");
  if (!Number.isInteger(timeline) || timeline < 12 || timeline > 720) throw new Error("timeline must be an integer from 12 to 720");
  const params = new URLSearchParams({
    sportId,
    pageSize: String(pageSize),
    pageNum: String(pageNum),
    todayGames: url.searchParams.get("todayGames") === "true" ? "true" : "false",
    timeline: String(timeline),
    _t: String(Date.now())
  });
  if (path === PC_ENDPOINT) {
    const raw = String(url.searchParams.get("marketId") || [...ALLOWED_MARKETS].join(","));
    const ids = raw.split(",").map(value => value.trim()).filter(Boolean);
    if (!ids.length || ids.some(id => !ALLOWED_MARKETS.has(id))) throw new Error("Unsupported marketId");
    params.set("marketId", [...new Set(ids)].join(","));
  }
  return params;
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
    try {
      const payload = JSON.parse(body);
      isJson = true;
      bizCode = payload?.bizCode ?? null;
      const counts = eventCounts(payload);
      tournamentCount = counts.tournament_count;
      eventCount = counts.event_count;
    } catch (_) {}
    return {
      endpoint: path,
      status: response.status,
      ok: response.ok,
      content_type: contentType,
      is_json: isJson,
      biz_code: bizCode,
      tournament_count: tournamentCount,
      event_count: eventCount,
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
