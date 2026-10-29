export function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    ...extra
  }});
}
export async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
}
export async function authorizeApi(context) {
  const supplied = (context.request.headers.get('authorization') || '').trim();
  const expected = context.env.MATCH_SIGNAL_API_KEY;
  if (expected && supplied === `Bearer ${expected}`) return null;
  if (!context.env.MATCH_SIGNAL_DB) return json({ error: 'API_NOT_CONFIGURED' }, 503);
  const match = /^Bearer ([A-Za-z0-9_-]{32,120})$/.exec(supplied);
  if (!match) return json({ error: 'UNAUTHORIZED' }, 401);
  const hash = await sha256(match[1]);
  const row = await context.env.MATCH_SIGNAL_DB.prepare(
    'SELECT id FROM ms_api_keys WHERE key_hash = ? AND status = ? AND (expires_at IS NULL OR expires_at > datetime(\'now\')) LIMIT 1'
  ).bind(hash, 'active').first();
  return row ? null : json({ error: 'UNAUTHORIZED' }, 401);
}
export function allowedOrigin(request, env) {
  const origin = request.headers.get('Origin');
  const configured = String(env.MATCH_SIGNAL_ALLOWED_ORIGINS || 'https://match-signal.pages.dev')
    .split(',').map(s => s.trim()).filter(Boolean);
  return origin && configured.includes(origin) ? origin : null;
}
export function randomToken(bytes = 32) {
  const data = crypto.getRandomValues(new Uint8Array(bytes));
  let binary = '';
  for (const b of data) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
