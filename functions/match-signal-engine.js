/**
 * Match Signal — protected engine boundary
 * Public presentation layer must call this boundary rather than shipping
 * proprietary V6 execution logic to the browser.
 *
 * This endpoint intentionally fails closed until the protected runtime is
 * configured. Do NOT put V6 source, SportyBet credentials, or private
 * provider credentials in this public repository.
 */
export default async (request, context) => {
  const method = request.method.toUpperCase();
  if (method !== "POST") {
    return new Response(JSON.stringify({
      ok: false,
      code: "METHOD_NOT_ALLOWED",
      engine: "V6",
      status: "PROTECTED_RUNTIME_REQUIRED"
    }), { status: 405, headers: {"content-type":"application/json","cache-control":"no-store"} });
  }

  const configured = String(context.env?.MATCH_SIGNAL_PROTECTED_ENGINE_URL || "").trim();
  if (!configured) {
    return new Response(JSON.stringify({
      ok: false,
      code: "PROTECTED_RUNTIME_NOT_CONFIGURED",
      engine: "V6",
      owner: "Diddy",
      build: "MS-V6-IP-2026.09.21",
      status: "NO_PUBLIC_ENGINE_FALLBACK",
      message: "The proprietary V6 runtime is intentionally not exposed in the public presentation repository."
    }), { status: 503, headers: {"content-type":"application/json","cache-control":"no-store"} });
  }

  let body;
  try { body = await request.json(); }
  catch {
    return new Response(JSON.stringify({ok:false, code:"INVALID_JSON"}), {
      status:400, headers:{"content-type":"application/json","cache-control":"no-store"}
    });
  }

  const upstream = await fetch(configured, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-match-signal-build": "MS-V6-IP-2026.09.21",
      "x-match-signal-owner": "Diddy"
    },
    body: JSON.stringify(body)
  });

  const headers = new Headers(upstream.headers);
  headers.set("cache-control", "no-store");
  headers.set("x-match-signal-boundary", "protected-v6");

  return new Response(upstream.body, { status: upstream.status, headers });
};

export const config = { path: "/api/match-signal-engine" };
