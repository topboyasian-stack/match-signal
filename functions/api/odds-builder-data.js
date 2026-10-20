const UPSTREAM_URL = 'https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/data/odds_builder.json';

const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
  'Pragma': 'no-cache',
  'X-Content-Type-Options': 'nosniff'
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export async function onRequestGet() {
  try {
    const url = new URL(UPSTREAM_URL);
    // Bypass intermediary cache so a newer GitHub commit can become visible immediately.
    url.searchParams.set('_ms_refresh', String(Date.now()));
    const response = await fetch(url.toString(), {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(10000)
    });

    if (!response.ok) {
      return json({ ok: false, error: 'odds_builder_source_unavailable', upstream_status: response.status }, 502);
    }

    const raw = await response.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return json({ ok: false, error: 'odds_builder_source_invalid_json' }, 502);
    }

    if (
      !data ||
      data.mode !== 'PAPER_ONLY' ||
      data.engine_version !== 'V6.1-RESEARCH-GATED' ||
      !data.generated_at ||
      !Array.isArray(data.batches)
    ) {
      return json({ ok: false, error: 'odds_builder_source_invalid_shape' }, 502);
    }

    return new Response(JSON.stringify(data), { status: 200, headers: JSON_HEADERS });
  } catch {
    return json({ ok: false, error: 'odds_builder_source_unavailable' }, 502);
  }
}
