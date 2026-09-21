export async function onRequestGet() {
  const source = 'https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/data/virtual_lab_history.json?v=' + Date.now();
  try {
    const response = await fetch(source, {
      headers: { 'Accept': 'application/json' },
      cf: { cacheTtl: 30, cacheEverything: false }
    });
    if (!response.ok) {
      return new Response(JSON.stringify({
        ok: false,
        error: 'History source HTTP ' + response.status
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
    JSON.parse(body);
    return new Response(body, {
      status: 200,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*',
        'X-Match-Signal-Source': 'GitHub main / virtual_lab_history.json'
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
