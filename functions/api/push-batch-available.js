import { sendPushBatch } from "@mmmike/web-push/send";

const MIN_ODDS = 2.8;
function json(body, status=200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
  });
}

async function keyForEndpoint(endpoint) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return "sub:" + [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function fingerprint(batch) {
  const legs = Array.isArray(batch?.legs) ? batch.legs : [];
  const source = legs.map((leg) => [
    leg?.event_id ?? "",
    leg?.market ?? "",
    leg?.line ?? "",
    leg?.pick ?? "",
    leg?.bookmaker_odds ?? "",
  ].join("|")).join("||");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(source));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function summarize(batch) {
  const odds = Number(batch?.combined_odds || 0);
  const legs = Array.isArray(batch?.legs) ? batch.legs : [];
  return {
    batch_id: String(batch?.batch_id || "BATCH-01"),
    fingerprint: "",
    combined_odds: odds,
    leg_count: legs.length,
    legs: legs.map((x) => ({
      match: String(x?.match || ""),
      pick: String(x?.pick || ""),
      odds: Number(x?.bookmaker_odds || 0)
    }))
  };
}

export async function onRequestPost(context) {
  const env = context.env;
  if (!env.PUSH_SUBSCRIPTIONS) return json({ ok:false, error:"push_storage_not_configured" }, 503);
  if (!env.VAPID_PRIVATE_KEY) return json({ ok:false, error:"vapid_private_key_not_configured" }, 503);

  let body = {};
  try { body = await context.request.json(); } catch (_) { body = {}; }
  const artifactUrl = "https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/data/odds_builder.json?t=" + Date.now();
  let artifact;
  try {
    const source = await fetch(artifactUrl, { headers: { "Cache-Control":"no-cache", "User-Agent":"Match-Signal-Push-Verifier" } });
    if (!source.ok) return json({ ok:false, error:"builder_artifact_unavailable", status:source.status }, 502);
    artifact = await source.json();
  } catch (_) {
    return json({ ok:false, error:"builder_artifact_unavailable" }, 502);
  }
  const batches = Array.isArray(artifact?.batches) ? artifact.batches : [];
  const candidates = [];
  for (const batch of batches) {
    const odds = Number(batch?.combined_odds || 0);
    const legs = Array.isArray(batch?.legs) ? batch.legs : [];
    if (odds < MIN_ODDS || legs.length < 2) continue;
    const clean = summarize(batch);
    clean.fingerprint = await fingerprint(batch);
    candidates.push(clean);
  }
  if (!candidates.length) return json({ ok:true, notified:0, reason:"no_qualified_2_80_batch" });

  const subscriptions = [];
  let cursor;
  do {
    const page = await env.PUSH_SUBSCRIPTIONS.list({ prefix:"sub:", cursor, limit:1000 });
    cursor = page.list_complete ? undefined : page.cursor;
    for (const item of page.keys || []) {
      const raw = await env.PUSH_SUBSCRIPTIONS.get(item.name);
      if (!raw) continue;
      try {
        const sub = JSON.parse(raw);
        if (sub?.endpoint && sub?.keys?.p256dh && sub?.keys?.auth) subscriptions.push({ kvKey:item.name, sub });
      } catch (_) {}
    }
  } while (cursor);

  if (!subscriptions.length) return json({ ok:true, notified:0, reason:"no_subscribers", candidates });

  const ready = [];
  for (const item of candidates) {
    const marker = "notified:" + item.fingerprint;
    if (await env.PUSH_SUBSCRIPTIONS.get(marker)) continue;
    const payload = {
      title: "🔔 Match Signal — Odds Builder",
      body: `${item.leg_count}-leg batch available · ${item.combined_odds.toFixed(3)}x combined odds`,
      url: "/odds-builder.html",
      tag: "match-signal-batch-" + item.fingerprint.slice(0, 24)
    };
    ready.push({ item, marker, payload });
  }

  if (!ready.length) return json({ ok:true, notified:0, reason:"already_notified", candidates });

  const vapid = {
    publicKey: String(env.VAPID_PUBLIC_KEY || ""),
    privateKey: String(env.VAPID_PRIVATE_KEY),
    subject: String(env.VAPID_SUBJECT || "mailto:matchsignal@match-signal.pages.dev")
  };

  let delivered = 0, gone = 0, failed = 0;
  const toDelete = [];
  for (const item of ready) {
    const result = await sendPushBatch(
      subscriptions.map((x) => x.sub),
      item.payload,
      vapid,
      { ttl: 3600, urgency:"high", concurrency:25 }
    );
    delivered += result.delivered.length;
    gone += result.gone.length;
    failed += result.failed.length;
    for (const endpoint of result.gone) {
      const hit = subscriptions.find((x) => x.sub.endpoint === endpoint);
      if (hit) toDelete.push(hit.kvKey);
    }
    await env.PUSH_SUBSCRIPTIONS.put(item.marker, new Date().toISOString(), { expirationTtl: 60 * 60 * 24 * 30 });
  }
  for (const key of toDelete) await env.PUSH_SUBSCRIPTIONS.delete(key);

  return json({
    ok:true,
    notified:ready.length,
    delivered,
    gone,
    failed,
    batches:ready.map((x)=>x.item)
  });
}
