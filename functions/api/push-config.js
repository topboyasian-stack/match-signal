export async function onRequestGet(context) {
  const publicKey = String(context.env.VAPID_PUBLIC_KEY || "").trim();
  return Response.json({
    ok: Boolean(publicKey),
    supported: Boolean(publicKey),
    public_key: publicKey,
    configured: Boolean(context.env.VAPID_PRIVATE_KEY && context.env.PUSH_SUBSCRIPTIONS),
  }, { headers: { "Cache-Control": "no-store" } });
}
