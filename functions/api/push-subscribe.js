const jsonHeaders = { "content-type": "application/json; charset=utf-8", "Cache-Control": "no-store" };

async function keyForEndpoint(endpoint) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return "sub:" + [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function response(body, status=200) {
  return new Response(JSON.stringify(body), { status, headers: jsonHeaders });
}

function allowedOrigin(request) {
  const origin = request.headers.get("Origin");
  return !origin || origin === "https://match-signal.pages.dev" || origin === "https://match-signal.pages.dev/";
}

export async function onRequestPost(context) {
  if (!allowedOrigin(context.request)) return response({ ok:false, error:"origin_not_allowed" }, 403);
  if (!context.env.PUSH_SUBSCRIPTIONS) return response({ ok:false, error:"push_storage_not_configured" }, 503);
  let body;
  try { body = await context.request.json(); } catch (_) { return response({ ok:false, error:"invalid_json" }, 400); }
  const endpoint = String(body?.endpoint || "").trim();
  const keys = body?.keys;
  if (!endpoint || !keys?.p256dh || !keys?.auth) return response({ ok:false, error:"invalid_subscription" }, 400);
  const key = await keyForEndpoint(endpoint);
  const subscription = {
    endpoint,
    expirationTime: body?.expirationTime ?? null,
    keys: { p256dh: String(keys.p256dh), auth: String(keys.auth) },
  };
  await context.env.PUSH_SUBSCRIPTIONS.put(key, JSON.stringify(subscription));
  return response({ ok:true, stored:true });
}

export async function onRequestDelete(context) {
  if (!context.env.PUSH_SUBSCRIPTIONS) return response({ ok:false, error:"push_storage_not_configured" }, 503);
  let body;
  try { body = await context.request.json(); } catch (_) { return response({ ok:false, error:"invalid_json" }, 400); }
  const endpoint = String(body?.endpoint || "").trim();
  if (!endpoint) return response({ ok:false, error:"endpoint_required" }, 400);
  await context.env.PUSH_SUBSCRIPTIONS.delete(await keyForEndpoint(endpoint));
  return response({ ok:true, removed:true });
}
