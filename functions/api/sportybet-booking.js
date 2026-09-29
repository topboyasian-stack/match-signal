const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

const ORIGIN = 'https://www.sportybet.com';
const BROWSER_HEADERS = {
  'Accept': 'application/json, text/plain, */*',
  'Content-Type': 'application/json',
  'Current-Country': 'NG',
  'Origin': 'https://www.sportybet.com',
  'Referer': 'https://www.sportybet.com/ng/',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function lineFromMarket(market) {
  if (market?.line != null && Number.isFinite(Number(market.line))) return Number(market.line);
  const match = String(market?.specifier || '').match(/(?:total|line)=([0-9]+(?:\.[0-9]+)?)/i);
  return match ? Number(match[1]) : null;
}

function normalizeEvent(event, tournament) {
  return {
    eventId: String(event?.eventId || ''),
    homeTeamName: String(event?.homeTeamName || ''),
    awayTeamName: String(event?.awayTeamName || ''),
    estimateStartTime: Number(event?.estimateStartTime || 0),
    matchStatus: String(event?.matchStatus || 'Not start'),
    tournament: String(tournament?.name || ''),
    markets: Array.isArray(event?.markets) ? event.markets : []
  };
}

async function upstream(path, params) {
  const url = new URL(ORIGIN + path);
  for (const [key, value] of Object.entries(params || {})) {
    if (value != null) url.searchParams.set(key, String(value));
  }
  const response = await fetch(url.toString(), {
    headers: BROWSER_HEADERS,
    cache: 'no-store',
    signal: AbortSignal.timeout(12000)
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(path + ' HTTP ' + response.status + ' ' + text.slice(0, 200));
  }
  if (!text.trim()) throw new Error(path + ' empty response');
  const payload = JSON.parse(text);
  if (payload?.bizCode != null && Number(payload.bizCode) !== 10000) {
    throw new Error(path + ' bizCode ' + payload.bizCode);
  }
  return payload;
}

async function collectEvents({ sportId, marketId, timeline = 168, pageSize = 100, maxPages = 8, fallbackPath = null, fallbackParams = {} }, targetIds) {
  const found = new Map();
  let page = 1;
  let usedFallback = false;

  while (page <= maxPages && found.size < targetIds.size) {
    let data;
    try {
      const path = usedFallback && fallbackPath ? fallbackPath : '/api/ng/factsCenter/pcUpcomingEvents';
      const params = {
        sportId,
        marketId,
        pageSize,
        pageNum: page,
        todayGames: 'false',
        timeline,
        _t: Date.now(),
        ...fallbackParams
      };
      data = await upstream(path, params);
    } catch (error) {
      if (!usedFallback && fallbackPath) {
        usedFallback = true;
        page = 1;
        continue;
      }
      throw error;
    }

    const tournaments = Array.isArray(data?.data?.tournaments) ? data.data.tournaments : [];
    let count = 0;
    for (const tournament of tournaments) {
      for (const event of Array.isArray(tournament?.events) ? tournament.events : []) {
        const normalized = normalizeEvent(event, tournament);
        if (targetIds.has(normalized.eventId)) {
          found.set(normalized.eventId, normalized);
        }
        count++;
      }
    }

    if (count < pageSize) break;
    page++;
  }
  return found;
}

function productForLeg(leg) {
  const product = String(leg?.product || '').toLowerCase();
  if (product === 'vfootball') return 'vfootball';
  if (product === 'efootball_gt' || product === 'efootball_adriatic' || product === 'zoom') return 'efootball';
  return '';
}

async function loadBuilder(context) {
  const assetUrl = new URL('/data/odds_builder.json', context.request.url);
  let response;
  if (context.env?.ASSETS?.fetch) {
    response = await context.env.ASSETS.fetch(new Request(assetUrl.toString(), {
      headers: { 'Accept': 'application/json' }
    }));
  } else {
    response = await fetch(assetUrl.toString(), { cache: 'no-store' });
  }
  if (!response.ok) throw new Error('Builder artifact HTTP ' + response.status);
  const payload = await response.json();
  if (payload?.mode !== 'PAPER_ONLY') throw new Error('Builder is not in PAPER_ONLY mode');
  return payload;
}

function pickVirtualSide(leg) {
  const text = String(leg?.pick || '').toLowerCase();
  if (/\bover\b/.test(text)) return 'over';
  if (/\bunder\b/.test(text)) return 'under';
  return '';
}

function isOpenEvent(event) {
  const start = Number(event?.estimateStartTime || 0);
  const status = String(event?.matchStatus || '').toLowerCase();
  if (start && start <= Date.now()) return false;
  return !status || /not start|not started|scheduled|prematch/.test(status);
}

function lineFromLeg(leg) {
  if (leg?.line != null && Number.isFinite(Number(leg.line))) return Number(leg.line);
  const pick = String(leg?.pick || '');
  const match = pick.match(/(?:over|under)\s+([0-9]+(?:\.[0-9]+)?)/i);
  return match ? Number(match[1]) : null;
}

function findVirtualSelection(leg, event) {
  const requestedLine = lineFromLeg(leg);
  const side = pickVirtualSide(leg);
  if (!Number.isFinite(requestedLine) || !side) {
    return { error: 'Could not map the Builder O/U selection to an exact line and side.' };
  }

  const markets = Array.isArray(event?.markets) ? event.markets : [];
  for (const market of markets) {
    const marketId = String(market?.id || '');
    const desc = String(market?.desc || market?.name || market?.title || '').toLowerCase();
    const line = lineFromMarket(market);
    const isOu = marketId === '189' || /over.?under|total/.test(desc);
    if (!isOu || line == null || Math.abs(line - requestedLine) > 1e-9) continue;

    const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
    const outcome = outcomes.find(o => {
      const name = String(o?.desc || o?.name || o?.title || '').toLowerCase();
      const active = o?.isActive == null || Number(o.isActive) === 1 || o.isActive === true;
      return active && name.startsWith(side);
    });
    if (!outcome) continue;

    return {
      eventId: event.eventId,
      marketId,
      specifier: market?.specifier ?? null,
      outcomeId: String(outcome?.id || ''),
      outcomeName: String(outcome?.desc || outcome?.name || outcome?.title || ''),
      odds: Number(outcome?.odds || 0)
    };
  }
  return { error: 'The exact SportyBet O/U line or selected side is no longer available.' };
}

function findWinnerSelection(leg, event) {
  const pick = String(leg?.pick || '').toLowerCase();
  const markets = Array.isArray(event?.markets) ? event.markets : [];
  const market = markets.find(m => {
    const id = String(m?.id || '');
    const desc = String(m?.desc || m?.name || m?.title || '').toLowerCase();
    return id === '1' || /3.?way|1x2|match winner|winner/.test(desc);
  });
  if (!market) return { error: 'SportyBet winner market is no longer available.' };

  const targetTeam = pick === 'p1' ? event.homeTeamName : pick === 'p2' ? event.awayTeamName : '';
  const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
  const outcome = outcomes.find(o => {
    const name = String(o?.desc || o?.name || o?.title || '').trim().toLowerCase();
    const active = o?.isActive == null || Number(o.isActive) === 1 || o.isActive === true;
    if (!active) return false;
    if (pick === 'draw') return /^(draw|x)$/.test(name);
    return targetTeam && name === String(targetTeam).trim().toLowerCase();
  });
  if (!outcome) return { error: 'The exact SportyBet winner outcome is no longer available.' };

  return {
    eventId: event.eventId,
    marketId: String(market?.id || '1'),
    specifier: market?.specifier ?? null,
    outcomeId: String(outcome?.id || ''),
    outcomeName: String(outcome?.desc || outcome?.name || outcome?.title || ''),
    odds: Number(outcome?.odds || 0)
  };
}

async function buildSelection(leg, event) {
  const product = productForLeg(leg);
  if (product === 'vfootball' || product === 'efootball') return findVirtualSelection(leg, event);

  const sport = String(leg?.sport || '').toLowerCase();
  const market = String(leg?.market || '').toLowerCase();
  if (sport === 'football' || market === '1x2' || market === 'winner') {
    return findWinnerSelection(leg, event);
  }
  if (sport === 'tennis') {
    const totalSide = pickVirtualSide(leg);
    if (totalSide) return findVirtualSelection(leg, event);
    return findWinnerSelection(leg, event);
  }
  return { error: 'No verified SportyBet booking mapper exists for product "' + product + '".' };
}

async function handlePost(context) {
  try {
    const body = await context.request.json();
    const batchId = String(body?.batch_id || '').trim();
    if (!/^BATCH-[0-9]{2}$/.test(batchId)) {
      return json({ ok: false, error: 'INVALID_BATCH_ID' }, 400);
    }

    const builder = await loadBuilder(context);
    const batches = Array.isArray(builder?.batches) ? builder.batches : [];
    const batch = batches.find(item => String(item?.batch_id || '') === batchId);
    if (!batch) {
      return json({ ok: false, error: 'BATCH_NOT_FOUND', batch_id: batchId }, 404);
    }

    const legs = Array.isArray(batch?.legs) ? batch.legs : [];
    if (!legs.length) {
      return json({ ok: false, error: 'EMPTY_BATCH', batch_id: batchId }, 422);
    }
    if (legs.length > 20) {
      return json({ ok: false, error: 'TOO_MANY_SELECTIONS', message: 'SportyBet booking codes support at most 20 selections.' }, 422);
    }

    const virtualIds = new Set(legs.filter(l => productForLeg(l) === 'vfootball').map(l => String(l.event_id || '')));
    const efootballIds = new Set(legs.filter(l => productForLeg(l) === 'efootball').map(l => String(l.event_id || '')));
    const footballIds = new Set(legs.filter(l => String(l?.sport || '').toLowerCase() === 'football').map(l => String(l.event_id || '')));
    const tennisIds = new Set(legs.filter(l => String(l?.sport || '').toLowerCase() === 'tennis').map(l => String(l.event_id || '')));

    const found = new Map();

    if (virtualIds.size) {
      const events = await collectEvents({
        sportId: 'sr:sport:202120001',
        marketId: '1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
        fallbackPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents'
      }, virtualIds);
      for (const [id, event] of events) found.set(id, event);
    }

    if (efootballIds.size) {
      const events = await collectEvents({
        sportId: 'sr:sport:137',
        marketId: '1,18,10,29,11,26,36,14,60100,186,189,202,204,210'
      }, efootballIds);
      for (const [id, event] of events) found.set(id, event);
    }

    if (footballIds.size) {
      const events = await collectEvents({
        sportId: 'sr:sport:1',
        marketId: '1,18,10,14,16,29,45,47'
      }, footballIds);
      for (const [id, event] of events) found.set(id, event);
    }

    if (tennisIds.size) {
      const events = await collectEvents({
        sportId: 'sr:sport:5',
        marketId: '186,210,202,204,189,203,188,187'
      }, tennisIds);
      for (const [id, event] of events) found.set(id, event);
    }

    const selections = [];
    const validation = [];
    for (const leg of legs) {
      const eventId = String(leg?.event_id || '');
      const event = found.get(eventId);
      if (!event) {
        validation.push({ event_id: eventId, ok: false, reason: 'Event is no longer present in SportyBet current catalogue.' });
        continue;
      }
      if (!isOpenEvent(event)) {
        validation.push({ event_id: eventId, ok: false, reason: 'Event has started or SportyBet has closed pre-match booking.' });
        continue;
      }

      const selection = await buildSelection(leg, event);
      if (selection?.error || !selection?.marketId || !selection?.outcomeId) {
        validation.push({ event_id: eventId, ok: false, reason: selection?.error || 'Selection could not be mapped to a live SportyBet market.' });
        continue;
      }

      selections.push(selection);
      validation.push({
        event_id: eventId,
        ok: true,
        market_id: selection.marketId,
        outcome_id: selection.outcomeId,
        specifier: selection.specifier,
        outcome: selection.outcomeName,
        current_odds: selection.odds
      });
    }

    if (validation.some(item => item.ok !== true)) {
      const startedCount = validation.filter(item => /started|closed pre-match booking/i.test(String(item?.reason || ''))).length;
      const unavailableCount = validation.length - startedCount - validation.filter(item => item.ok === true).length;
      return json({
        ok: false,
        error: startedCount ? 'BATCH_HAS_STARTED_LEGS' : 'VALIDATION_FAILED',
        batch_id: batchId,
        message: startedCount
          ? 'This batch contains ' + startedCount + ' selection(s) that have already started or closed on SportyBet; one booking code cannot be created for the full batch.'
          : 'The ticket changed on SportyBet, so no partial booking code was created.',
        started_count: startedCount,
        unavailable_count: Math.max(0, unavailableCount),
        validation
      }, 409);
    }

    const shareResponse = await fetch(ORIGIN + '/api/ng/orders/share', {
      method: 'POST',
      headers: BROWSER_HEADERS,
      body: JSON.stringify({
        selections: selections.map(selection => ({
          eventId: selection.eventId,
          marketId: selection.marketId,
          specifier: selection.specifier,
          outcomeId: selection.outcomeId
        }))
      }),
      cache: 'no-store',
      signal: AbortSignal.timeout(15000)
    });

    const shareText = await shareResponse.text();
    if (!shareResponse.ok) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_HTTP_' + shareResponse.status,
        body_prefix: shareText.slice(0, 240)
      }, 502);
    }

    const share = JSON.parse(shareText);
    if (share?.bizCode != null && Number(share.bizCode) !== 10000) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_REJECTED',
        biz_code: share.bizCode
      }, 409);
    }

    const data = share?.data;
    const shareCode = String(data?.shareCode || '').trim().toUpperCase();
    if (!shareCode) {
      return json({
        ok: false,
        error: 'NO_BOOKING_CODE',
        message: 'SportyBet did not return a booking code. Refresh the ticket and try again.'
      }, 502);
    }

    const unavailable = Array.isArray(data?.unavailableOutcomes) ? data.unavailableOutcomes : [];
    if (unavailable.length) {
      return json({
        ok: false,
        error: 'PARTIAL_BOOKING_REJECTED',
        message: 'SportyBet could not preserve every Builder selection, so the partial code was not accepted.',
        unavailable_count: unavailable.length
      }, 409);
    }

    const deadline = Number(data?.deadline || 0);
    return json({
      ok: true,
      mode: 'NON_STAKING_BETSLIP_PREPARATION',
      batch_id: batchId,
      booking_code: shareCode,
      share_url: String(data?.shareURL || ('https://www.sportybet.com/ng/?c=ng&shareCode=' + encodeURIComponent(shareCode))),
      expires_at: Number.isFinite(deadline) && deadline > 0 ? new Date(deadline).toISOString() : null,
      selection_count: selections.length,
      selections: validation,
      note: 'This creates a SportyBet betslip reservation/share code only. No wager, stake, payment, or account action is performed by Match Signal.'
    });
  } catch (error) {
    return json({
      ok: false,
      error: 'BOOKING_PREPARATION_FAILED',
      message: String(error?.message || error).slice(0, 500)
    }, 502);
  }
}

export async function onRequest(context) {
  if (context.request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: JSON_HEADERS });
  }
  if (context.request.method !== 'POST') {
    return json({ ok: false, error: 'METHOD_NOT_ALLOWED', message: 'Use POST to prepare a SportyBet booking code.' }, 405);
  }
  return handlePost(context);
}
