export async function onRequestGet(context) {
  const requestUrl = new URL(context.request.url);
  const source = new URL('/data/virtual_lab_history.json', requestUrl.origin);
  source.searchParams.set('v', 'VL-V1-20260922');
  source.searchParams.set('_t', String(Date.now()));
  try {
    const response = await fetch(source.toString(), {
      headers: { 'Accept': 'application/json' },
      cf: { cacheTtl: 0, cacheEverything: false }
    });
    if (!response.ok) {
      return new Response(JSON.stringify({
        ok: false,
        error: 'History source HTTP ' + response.status,
        source: source.toString()
      }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'no-store',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }
    const body = await response.text();
    const parsed = JSON.parse(body);
    const count = Array.isArray(parsed) ? parsed.length : (Array.isArray(parsed.rows) ? parsed.rows.length : 0);
    return new Response(JSON.stringify({
      ok: true,
      schema_version: 1,
      build: 'VL-V1-20260922',
      source: 'same-origin-static-history',
      count,
      rows: Array.isArray(parsed) ? parsed : (Array.isArray(parsed.rows) ? parsed.rows : [])
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store, max-age=0, must-revalidate',
        'Access-Control-Allow-Origin': '*',
        'X-Match-Signal-Source': 'Cloudflare Pages same-origin /data/virtual_lab_history.json'
      }
    });
  } catch (error) {
    return new Response(JSON.stringify({
      ok: false,
      error: String(error && error.message ? error.message : error)
    }), {
      status: 502,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }
}
