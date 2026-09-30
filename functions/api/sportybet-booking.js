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
  const direct = Number(market?.line);
  if (Number.isFinite(direct)) return direct;
  const text = [
    market?.specifier,
    market?.desc,
    market?.name,
    market?.title
  ].map(value => String(value || '')).join(' ');
  const match = text.match(/(?:total|line|over|under)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)/i)
    || text.match(/\b([0-9]+(?:\.[0-9]+)?)\b/);
  return match ? Number(match[1]) : null;
}

function normalizeEvent(event, tournament) {
  const rawStart = Number(event?.estimateStartTime || 0);
  const estimateStartTime = Number.isFinite(rawStart) && rawStart > 0
    ? (rawStart < 100000000000 ? rawStart * 1000 : rawStart)
    : 0;
  return {
    eventId: String(event?.eventId || ''),
    homeTeamName: String(event?.homeTeamName || ''),
    awayTeamName: String(event?.awayTeamName || ''),
    estimateStartTime,
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

async function collectEvents({ sportId, marketId, timeline = 168, pageSize = 100, maxPages = 8, primaryPath = '/api/ng/factsCenter/pcUpcomingEvents', fallbackPath = null, fallbackParams = {} }, targetIds) {
  const found = new Map();
  const matchedTargets = new Set();
  let page = 1;
  let usedFallback = false;

  while (page <= maxPages && matchedTargets.size < targetIds.size) {
    let data;
    try {
      const path = usedFallback && fallbackPath ? fallbackPath : primaryPath;
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
        if (normalized.eventId) {
          found.set(normalized.eventId, normalized);
          if (targetIds.has(normalized.eventId)) matchedTargets.add(normalized.eventId);
        }
        count++;
      }
    }

    if (count < pageSize) break;
    page++;
  }
  // A valid Builder event can disappear from the first WAP pages while the
  // current catalogue is reordered. If the bounded primary scan did not find
  // every target, rescan the fallback catalogue from page 1 before declaring
  // the leg unavailable. This preserves the bounded request budget without
  // making stale event IDs synonymous with unavailable fixtures.
  if (matchedTargets.size < targetIds.size && fallbackPath && !usedFallback) {
    usedFallback = true;
    page = 1;
    while (page <= maxPages && matchedTargets.size < targetIds.size) {
      let data;
      try {
        data = await upstream(fallbackPath, {
          sportId,
          marketId,
          pageSize,
          pageNum: page,
          todayGames: 'false',
          timeline,
          _t: Date.now(),
          ...fallbackParams
        });
      } catch (error) {
        break;
      }
      const tournaments = Array.isArray(data?.data?.tournaments) ? data.data.tournaments : [];
      let count = 0;
      for (const tournament of tournaments) {
        for (const event of Array.isArray(tournament?.events) ? tournament.events : []) {
          const normalized = normalizeEvent(event, tournament);
          if (normalized.eventId) {
            found.set(normalized.eventId, normalized);
            if (targetIds.has(normalized.eventId)) matchedTargets.add(normalized.eventId);
          }
          count++;
        }
      }
      if (count < pageSize) break;
      page++;
    }
  }
  return found;
}

function normalizeFixture(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/\s*vs\s*/g, ' vs ')
    .trim();
}

function resolveCurrentEvent(leg, found) {
  const direct = found.get(String(leg?.event_id || ''));
  if (direct) return { event: direct, matched_by: 'event_id' };

  const targetMatch = normalizeFixture(
    leg?.match ||
    leg?.fixture ||
    String(leg?.pick || '').split('—')[0]
  );
  if (!targetMatch) return { event: null, matched_by: 'none' };

  const targetStart = Date.parse(String(leg?.start_time || ''));
  let best = null;
  let bestDiff = Infinity;

  for (const event of found.values()) {
    const candidateMatch = normalizeFixture(
      String(event?.homeTeamName || '') + ' vs ' + String(event?.awayTeamName || '')
    );
    if (!candidateMatch || candidateMatch !== targetMatch) continue;

    const candidateStart = Number(event?.estimateStartTime || 0);
    if (!candidateStart) {
      if (!best) best = event;
      continue;
    }

    const diff = Number.isFinite(targetStart)
      ? Math.abs(candidateStart - targetStart)
      : 0;
    if (diff <= 30 * 60 * 1000 && diff < bestDiff) {
      best = event;
      bestDiff = diff;
    }
  }

  return { event: best, matched_by: best ? 'fixture_time' : 'none' };
}

async function collectVirtualEventsFromLiveFeed(context, targetIds) {
  const found = new Map();
  if (!targetIds || !targetIds.size) return found;
  try {
    const url = new URL('/api/sportybet-virtual', context.request.url);
    url.searchParams.set('pageSize', '100');
    url.searchParams.set('pageNum', '1');
    url.searchParams.set('timeline', '168');
    url.searchParams.set('sources', 'vfootball');
    url.searchParams.set('_t', String(Date.now()));
    const response = await fetch(url.toString(), {
      headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache' },
      cache: 'no-store',
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) return found;
    const payload = await response.json();
    const events = Array.isArray(payload?.events) ? payload.events : [];
    for (const row of events) {
      const eventId = String(row?.event_id || row?.eventId || '');
      if (!eventId || !targetIds.has(eventId)) continue;
      const rawStart = Number(row?.start_time_ms || 0);
      let estimateStartTime = rawStart;
      if (!estimateStartTime && row?.start_time) {
        const parsed = Date.parse(String(row.start_time));
        if (Number.isFinite(parsed)) estimateStartTime = parsed;
      }
      found.set(eventId, {
        eventId,
        homeTeamName: String(row?.team_1 || row?.participant_1 || ''),
        awayTeamName: String(row?.team_2 || row?.participant_2 || ''),
        estimateStartTime,
        matchStatus: String(row?.match_status || 'Not start'),
        tournament: String(row?.competition || ''),
        markets: Array.isArray(row?.markets) ? row.markets : []
      });
    }
  } catch (error) {
    // Existing SportyBet catalogue lookup remains the primary path.
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
  const closed = /live|running|playing|in.?play|started|finish|ended|final|completed|settled|closed/.test(status);
  if (closed) return false;
  if (start && start <= Date.now()) return false;
  return !status || /not start|not started|scheduled|prematch|waiting/.test(status);
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
    const desc = [
      market?.desc,
      market?.name,
      market?.title,
      market?.specifier
    ].map(value => String(value || '')).join(' ').toLowerCase();
    const line = lineFromMarket(market);
    const isOu = marketId === '189' || /over\s*\/?\s*under|over.?under|total|\bou\b/.test(desc);
    if (!isOu || line == null || Math.abs(line - requestedLine) > 1e-9) continue;

    const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
    const outcome = outcomes.find(o => {
      const rawName = String(o?.desc || o?.name || o?.title || '').toLowerCase().trim();
      const normalized = rawName.replace(/[^a-z0-9]+/g, ' ');
      const active = o?.isActive == null
        ? (o?.active == null || o.active !== false)
        : Number(o.isActive) === 1 || o.isActive === true;
      const sideMatch = side === 'under'
        ? /\bunder\b/.test(normalized) || /^u\b/.test(normalized)
        : /\bover\b/.test(normalized) || /^o\b/.test(normalized);
      const outcomeLine = lineFromMarket(o);
      const lineMatch = outcomeLine == null || Math.abs(Number(outcomeLine) - requestedLine) < 1e-9;
      return active && sideMatch && lineMatch;
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
        primaryPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents',
        fallbackPath: '/api/ng/factsCenter/pcUpcomingEvents'
      }, virtualIds);
      for (const [id, event] of events) found.set(id, event);

      // The Builder prices vFootball from the same normalized live feed.
      // Reconcile against that feed before declaring an exact O/U market
      // unavailable; this preserves the event/line actually used to qualify
      // the paper ticket when SportyBet's catalogue endpoint omits market data.
      const liveFeedEvents = await collectVirtualEventsFromLiveFeed(context, virtualIds);
      for (const [id, event] of liveFeedEvents) {
        const current = found.get(id);
        if (!current || !Array.isArray(current.markets) || !current.markets.length) {
          found.set(id, event);
        } else {
          const currentHasOu = current.markets.some(m => {
            const desc = String(m?.desc || m?.name || m?.title || m?.specifier || '').toLowerCase();
            return String(m?.id || '') === '189' || /over.?under|total|\bou\b/.test(desc);
          });
          if (!currentHasOu && Array.isArray(event.markets) && event.markets.length) {
            found.set(id, { ...current, markets: event.markets });
          }
        }
      }
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
      const resolved = resolveCurrentEvent(leg, found);
      const event = resolved.event;
      if (!event) {
        validation.push({ event_id: eventId, ok: false, excluded: true, reason: 'Event is no longer present in SportyBet current catalogue.' });
        continue;
      }
      if (!isOpenEvent(event)) {
        validation.push({ event_id: eventId, ok: false, excluded: true, reason: 'Event has started or SportyBet has closed pre-match booking.' });
        continue;
      }

      const selection = await buildSelection(leg, event);
      if (selection?.error || !selection?.marketId || !selection?.outcomeId) {
        validation.push({ event_id: eventId, ok: false, excluded: true, reason: selection?.error || 'Selection could not be mapped to a live SportyBet market.' });
        continue;
      }

      selections.push(selection);
      validation.push({
        event_id: eventId,
        ok: true,
        resolved_by: resolved.matched_by,
        resolved_event_id: event.eventId,
        market_id: selection.marketId,
        outcome_id: selection.outcomeId,
        specifier: selection.specifier,
        outcome: selection.outcomeName,
        current_odds: selection.odds
      });
    }

    const preExcluded = validation.filter(item => item.ok !== true);
    if (!selections.length) {
      return json({
        ok: false,
        error: 'NO_AVAILABLE_SELECTIONS',
        batch_id: batchId,
        message: 'No Builder selections could be mapped to a currently open SportyBet event/market.',
        initial_selection_count: legs.length,
        selection_count: 0,
        excluded_count: preExcluded.length,
        unavailable_count: preExcluded.length,
        validation
      }, 409);
    }

    if (selections.length < 3) {
      return json({
        ok: false,
        error: 'TOO_FEW_AVAILABLE_SELECTIONS',
        batch_id: batchId,
        message: 'Only ' + selections.length + ' selection(s) remain available. SportyBet requires more than two valid selections for this type of booking.',
        initial_selection_count: legs.length,
        selection_count: selections.length,
        excluded_count: preExcluded.length,
        validation
      }, 409);
    }

    const sharePayload = JSON.stringify({
      selections: selections.map(selection => ({
        eventId: selection.eventId,
        marketId: selection.marketId,
        specifier: selection.specifier,
        outcomeId: selection.outcomeId
      }))
    });

    // SportyBet's undocumented share endpoint occasionally returns an HTML
    // 5xx edge page instead of JSON. Retry only transient upstream failures;
    // never retry validation/rejection responses. The operation only creates a
    // non-staking share code, so a successful response remains safe to replace
    // with the most recent valid code.
    const transientStatuses = new Set([502, 503, 504]);
    let shareResponse = null;
    let shareText = '';
    let lastStatus = null;
    let lastBody = '';
    for (let attempt = 1; attempt <= 3; attempt++) {
      const shareUrl = ORIGIN + '/api/ng/orders/share?_t=' + Date.now();
      const requestHeaders = {
        ...BROWSER_HEADERS,
        'Accept-Language': 'en-NG,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin'
      };
      try {
        shareResponse = await fetch(shareUrl, {
          method: 'POST',
          headers: requestHeaders,
          body: sharePayload,
          cache: 'no-store',
          redirect: 'follow',
          signal: AbortSignal.timeout(15000)
        });
        shareText = await shareResponse.text();
        lastStatus = shareResponse.status;
        lastBody = shareText.slice(0, 320);
        if (shareResponse.ok || !transientStatuses.has(shareResponse.status)) break;
      } catch (error) {
        lastStatus = null;
        lastBody = String(error?.message || error).slice(0, 320);
        if (attempt === 3) {
          return json({
            ok: false,
            error: 'SPORTYBET_BOOKING_NETWORK',
            message: lastBody
          }, 502);
        }
      }
      if (attempt < 3) {
        const delayMs = 400 * Math.pow(2, attempt - 1);
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }

    if (!shareResponse) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_NO_RESPONSE'
      }, 502);
    }

    if (!shareResponse.ok) {
      const fallbackSelections = selections.map(selection => ({
        eventId: selection.eventId,
        marketId: selection.marketId,
        specifier: selection.specifier,
        outcomeId: selection.outcomeId
      }));
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_HTTP_' + shareResponse.status,
        body_prefix: lastBody,
        attempts: 3,
        fallback_direct_origin: true,
        fallback_selections: fallbackSelections
      }, 502);
    }

    let share;
    try {
      share = JSON.parse(shareText);
    } catch (error) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_MALFORMED_RESPONSE',
        message: 'SportyBet returned a non-JSON response after a successful HTTP status.',
        body_prefix: shareText.slice(0, 240)
      }, 502);
    }
    if (share?.bizCode != null && Number(share.bizCode) !== 10000) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_REJECTED',
        biz_code: share.bizCode
      }, 409);
    }

    const data = share?.data;
    const shareCode = String(data?.shareCode || '').trim().toUpperCase();
    const unavailable = Array.isArray(data?.unavailableOutcomes) ? data.unavailableOutcomes : [];
    const acceptedOutcomes = Array.isArray(data?.outcomes) ? data.outcomes : [];
    if (!shareCode) {
      return json({
        ok: false,
        error: 'NO_BOOKING_CODE',
        message: unavailable.length
          ? 'SportyBet removed unavailable selections, but no booking code was returned for the remaining selections. Refresh the ticket and try again.'
          : 'SportyBet did not return a booking code. Refresh the ticket and try again.',
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        unavailable_count: unavailable.length,
        excluded_count: preExcluded.length + unavailable.length,
        validation
      }, 502);
    }

    const acceptedCount = acceptedOutcomes.length || Math.max(0, selections.length - unavailable.length);
    const partial = preExcluded.length > 0 || unavailable.length > 0 || acceptedCount < legs.length;
    const combinedOddsSource = acceptedOutcomes.length ? acceptedOutcomes : selections;
    const combinedOdds = combinedOddsSource.length
      ? combinedOddsSource.reduce((product, item) => {
          const odds = Number(item?.odds);
          return Number.isFinite(odds) && odds > 0 ? product * odds : product;
        }, 1)
      : null;

    const deadline = Number(data?.deadline || 0);
    return json({
      ok: true,
      mode: 'NON_STAKING_BETSLIP_PREPARATION',
      batch_id: batchId,
      booking_code: shareCode,
      share_url: String(data?.shareURL || ('https://www.sportybet.com/ng/?c=ng&shareCode=' + encodeURIComponent(shareCode))),
      expires_at: Number.isFinite(deadline) && deadline > 0 ? new Date(deadline).toISOString() : null,
      initial_selection_count: legs.length,
      requested_selection_count: selections.length,
      selection_count: acceptedCount,
      excluded_count: Math.max(0, legs.length - acceptedCount),
      unavailable_count: unavailable.length,
      pre_excluded_count: preExcluded.length,
      partial,
      combined_odds: Number.isFinite(combinedOdds) ? Number(combinedOdds.toFixed(4)) : null,
      selections: validation,
      note: partial
        ? 'SportyBet changed one or more selections. The booking code contains only the selections still available at booking time; its combined odds may be lower than the original Builder batch.'
        : 'This creates a SportyBet betslip reservation/share code only. No wager, stake, payment, or account action is performed by Match Signal.'
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
