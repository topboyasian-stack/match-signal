const DEFAULT_PUBLIC_KEY = "BFFGz7rdms4JOhI6Ht-FeNtO0u9ijAwsunxtcjwXm5YKl4lscPc_Hw5VEU3fePStevIoPKMBPwJGBm4EgXDEAE8";

export async function onRequestGet(context) {
  const publicKey = String(context.env.VAPID_PUBLIC_KEY || DEFAULT_PUBLIC_KEY).trim();
  return Response.json({
    ok: Boolean(publicKey),
    supported: Boolean(publicKey && "serviceWorker" in navigator),
    public_key: publicKey,
    configured: Boolean(context.env.VAPID_PRIVATE_KEY && context.env.PUSH_SUBSCRIPTIONS),
  }, { headers: { "Cache-Control": "no-store" } });
}
