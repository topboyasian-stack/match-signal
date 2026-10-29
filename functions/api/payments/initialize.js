import { json, randomToken, sha256, allowedOrigin } from '../../_lib/api-auth.js';
const BASE_HEADERS = { 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
function emailValid(value) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length <= 254; }
export async function onRequestPost(context) {
  const origin = allowedOrigin(context.request, context.env);
  const cors = origin ? { 'Access-Control-Allow-Origin': origin, 'Vary': 'Origin' } : {};
  if (!origin) return json({ error: 'ORIGIN_NOT_ALLOWED' }, 403, { ...BASE_HEADERS, ...cors });
  if (!context.env.PAYSTACK_SECRET_KEY || !context.env.MATCH_SIGNAL_DB) return json({ error: 'PAYMENTS_NOT_CONFIGURED', message: 'Payment processing is not configured yet.' }, 503, { ...BASE_HEADERS, ...cors });
  let body;
  try { body = await context.request.json(); } catch { return json({ error: 'INVALID_JSON' }, 400, { ...BASE_HEADERS, ...cors }); }
  const email = String(body.email || '').trim().toLowerCase();
  if (!emailValid(email)) return json({ error: 'INVALID_EMAIL' }, 400, { ...BASE_HEADERS, ...cors });
  const plan = 'api_monthly';
  const amount = 500000; // Fixed server-side launch price: NGN 5,000. Never accept price from the browser.
  if (!Number.isSafeInteger(amount) || amount < 10000 || amount > 100000000) return json({ error: 'INVALID_PRICE_CONFIGURATION' }, 503, { ...BASE_HEADERS, ...cors });
  const reference = 'MS_' + Date.now().toString(36) + '_' + randomToken(12);
  const checkoutToken = randomToken(32);
  const tokenHash = await sha256(checkoutToken);
  const callbackUrl = new URL('/payment-success.html', new URL(context.request.url).origin).toString();
  try {
    await context.env.MATCH_SIGNAL_DB.prepare(
      'INSERT INTO ms_payments (reference,email,amount_kobo,plan_code,status,checkout_token_hash) VALUES (?,?,?,?,?,?)'
    ).bind(reference,email,amount,plan,'initialized',tokenHash).run();
    const response = await fetch('https://api.paystack.co/transaction/initialize', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + context.env.PAYSTACK_SECRET_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email, amount, currency: 'NGN', reference, callback_url: callbackUrl,
        metadata: { product: 'Match Signal Research API', plan_code: plan, integration: 'match-signal' }
      })
    });
    const result = await response.json();
    if (!response.ok || !result.status || !result.data?.authorization_url) {
      await context.env.MATCH_SIGNAL_DB.prepare('UPDATE ms_payments SET status=?, updated_at=CURRENT_TIMESTAMP WHERE reference=?').bind('failed',reference).run();
      return json({ error: 'PAYSTACK_INITIALIZATION_FAILED', message: 'Paystack could not initialize this payment. No charge was confirmed.' }, 502, { ...BASE_HEADERS, ...cors });
    }
    return json({ authorization_url: result.data.authorization_url, reference, checkout_token: checkoutToken, amount_kobo: amount, currency: 'NGN', plan }, 200, { ...BASE_HEADERS, ...cors });
  } catch {
    return json({ error: 'PAYMENT_INITIALIZATION_UNAVAILABLE' }, 503, { ...BASE_HEADERS, ...cors });
  }
}
export function onRequestOptions(context) {
  const origin = allowedOrigin(context.request, context.env);
  return new Response(null, { status: 204, headers: { ...BASE_HEADERS, ...(origin ? { 'Access-Control-Allow-Origin': origin, 'Vary': 'Origin' } : {}), 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' } });
}
