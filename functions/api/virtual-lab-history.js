export async function onRequestGet(context) {
  const requestUrl = new URL(context.request.url);
  const sources = [
    {
      path: '/data/virtual_lab_history.json.gz',
      compressed: true,
      label: 'same-origin-static-history-gzip'
    },
    {
      path: '/data/virtual_lab_history.json',
      compressed: false,
      label: 'same-origin-static-history'
    }
  ];
  const headers = {
    'Accept': 'application/json, application/gzip',
    'Accept-Encoding': 'identity'
  };

  for (const candidate of sources) {
    const source = new URL(candidate.path, requestUrl.origin);
    source.searchParams.set('v', 'VL-V1-20260922');
    source.searchParams.set('_t', String(Date.now()));

    try {
      const response = await fetch(source.toString(), {
        headers,
        cf: { cacheTtl: 0, cacheEverything: false }
      });
      if (!response.ok || !response.body) continue;

      const body = candidate.compressed
        ? response.body.pipeThrough(new DecompressionStream('gzip'))
        : response.body;

      return new Response(body, {
        status: 200,
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'no-store, max-age=0, must-revalidate',
          'Access-Control-Allow-Origin': '*',
          'X-Match-Signal-Source': candidate.label
        }
      });
    } catch (error) {
      if (candidate === sources[sources.length - 1]) {
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
  }

  return new Response(JSON.stringify({
    ok: false,
    error: 'History source unavailable'
  }), {
    status: 502,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*'
    }
  });
}
