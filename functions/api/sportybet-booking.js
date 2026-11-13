import { onRequestGet as getSportyBetBasketballFeed } from './sportybet-basketball.js';

const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

// Returned with every JSON response so production probes can identify the
// exact fixture resolver version that is serving manual booking validation.
const BOOKING_FIXTURE_MATCHER_VERSION = 'sportybet-alias-v1';

const ORIGIN = 'https://www.sportybet.com';
const SPORTYBET_PROXY_ORIGIN = 'https://match-signal-sportybet-proxy.topboyasian.workers.dev';
const BROWSER_HEADERS = {
  'Accept': 'application/json, text/plain, */*',
  'Content-Type': 'application/json',
  'Current-Country': 'NG',
  'Cache-Control': 'no-cache',
  'Pragma': 'no-cache',
  'Origin': 'https://www.sportybet.com',
  'Referer': 'https://www.sportybet.com/ng/',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36'
};

function json(body, status = 200) {
  const payload = body && typeof body === 'object' && !Array.isArray(body)
    ? { ...body, fixture_matcher_version: BOOKING_FIXTURE_MATCHER_VERSION }
    : { value: body, fixture_matcher_version: BOOKING_FIXTURE_MATCHER_VERSION };
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...JSON_HEADERS,
      'X-Match-Signal-Booking-Fixture-Matcher': BOOKING_FIXTURE_MATCHER_VERSION,
      'Access-Control-Expose-Headers': 'X-Match-Signal-Booking-Fixture-Matcher'
    }
  });
}

export function ticketCatalogueTimeline(legs, now = Date.now(), maxHours = 720) {
  const starts = (Array.isArray(legs) ? legs : [])
    .map(leg => Date.parse(String(leg?.start_time || '')))
    .filter(start => Number.isFinite(start) && start > now);
  if (!starts.length) return 168;
  // SportyBet's timeline parameter is expressed in hours. Add one day of
  // headroom so the catalogue query includes the full kickoff date, not merely
  // the exact kickoff timestamp.
  const requiredHours = Math.ceil((Math.max(...starts) - now) / 3600000) + 24;
  return Math.max(168, Math.min(720, requiredHours));
}

const NBA_RELEASE_CUTOFF='2026-11-02T02:00:00+00:00';
export const NBA_RELEASE_MODEL='nba-total-v5.1-pace-efficiency-calibrated';
function nbaReleaseClose(a,b){return Number.isFinite(Number(a))&&Number.isFinite(Number(b))&&Math.abs(Number(a)-Number(b))<=1e-9;}
function nbaMarketCohortMatchesSnapshotEvidence(e,p){
 const m=e?.market_holdout||{},rows=e?.market_record_audit,c=p?.prospective_pregame_snapshot_coverage||{},v=p?.prospective_clv_diagnostics||{},clvRows=v.fixtures;
 const expected=Number(m.n);
 if(!Number.isInteger(expected)||expected<1||!Array.isArray(rows)||!Array.isArray(clvRows)||rows.length!==expected||clvRows.length!==expected)return false;
 if(Number(c.prospective_settled_unique_market_selections)!==expected||Number(c.prospective_settled_selections_with_exact_snapshot_match)!==expected||Number(c.prospective_settled_selections_missing_or_mismatched_snapshot)!==0||c.snapshot_linkage_complete_for_settled_selections!==true)return false;
 const roiByEvent=new Map(),roiSnapshotIds=new Set();
 for(const row of rows){
  const eventId=String(row?.event_id||'').trim(),snapshotId=String(row?.publication_snapshot_id||'').trim(),side=String(row?.selected_side||'').trim().toUpperCase();
  const line=Number(row?.sportybet_market_225_line),over=Number(row?.over_odds),under=Number(row?.under_odds),selectedOdds=Number(row?.selected_side_odds);
  if(!eventId||!snapshotId||roiByEvent.has(eventId)||roiSnapshotIds.has(snapshotId)||!['OVER','UNDER'].includes(side)||!Number.isFinite(line)||!Number.isFinite(over)||over<=1||!Number.isFinite(under)||under<=1||!nbaReleaseClose(selectedOdds,side==='OVER'?over:under))return false;
  roiByEvent.set(eventId,{snapshotId,side,line,over,under});
  roiSnapshotIds.add(snapshotId);
 }
 const clvEvents=new Set(),clvSnapshotIds=new Set();
 for(const row of clvRows){
  const eventId=String(row?.event_id||'').trim(),snapshotId=String(row?.opening?.snapshot_id||'').trim(),base=roiByEvent.get(eventId),side=String(row?.selected_side||'').trim().toUpperCase();
  const line=Number(row?.opening?.line),over=Number(row?.opening?.over_odds),under=Number(row?.opening?.under_odds);
  if(!base||!snapshotId||clvEvents.has(eventId)||clvSnapshotIds.has(snapshotId)||snapshotId!==base.snapshotId||side!==base.side||!nbaReleaseClose(line,base.line)||!nbaReleaseClose(over,base.over)||!nbaReleaseClose(under,base.under))return false;
  clvEvents.add(eventId);
  clvSnapshotIds.add(snapshotId);
 }
 return clvEvents.size===expected&&clvSnapshotIds.size===expected;
}
export function nbaTotalsReleaseQualified(e,p){
 const h=e?.walk_forward?.holdout||{},m=e?.market_holdout||{},c=p?.prospective_pregame_snapshot_coverage||{},pc=p?.prospective_probability_fixture_coverage||{},s=p?.prospective_probability_score_summary||{},v=p?.prospective_clv_diagnostics||{},cal=p?.calibration_protocol||{};
 const probabilitySample=Number(s.n)>=30&&s.sufficient_for_probability_validation===true&&Number(pc.valid_unique_settled_fixtures)>=30&&Number(pc.binary_scored_unique_fixtures)>=30&&Number(pc.snapshot_linkage_failure_count)===0&&pc.cutoff_utc===NBA_RELEASE_CUTOFF&&pc.sample_threshold_met===true;
 const selectionEvidence=Number(c.prospective_settled_selections_with_exact_snapshot_match)>=100&&Number(c.prospective_settled_selections_missing_or_mismatched_snapshot)===0&&Number(c.prospective_settled_unique_market_selections)>=100;
 return !!(e?.paper_only===true&&e?.evaluation_type==='NBA_TOTALS_FIXED_CUTOFF_V2'&&e?.holdout_protocol?.fixed_cutoff_utc===NBA_RELEASE_CUTOFF&&e?.market_id==='225'&&e?.market_definition==='full_game_total_including_overtime'&&e?.model_version===NBA_RELEASE_MODEL&&e?.release_decision==='QUALIFIED'&&Number(h.n)>=100&&Number.isFinite(Number(h.mae))&&Number.isFinite(Number(h.baseline_mae))&&Number(h.mae)<Number(h.baseline_mae)&&Number.isFinite(Number(h.bias))&&Math.abs(Number(h.bias))<=3&&Number(m.n)>=100&&nbaMarketCohortMatchesSnapshotEvidence(e,p)&&Number(m.roi)>0&&Number(m.roi_ci95_lower)>0&&Number(m.roi_vs_market_favorite)>0&&p?.paper_only===true&&p?.experiment==='NBA_TOTALS_EMPIRICAL_RESIDUAL_VALUE_V3'&&p?.model_version===NBA_RELEASE_MODEL&&p?.model_projection_market_blind===true&&p?.prospective_holdout_cutoff_utc===NBA_RELEASE_CUTOFF&&p?.prospective_holdout_used_for_calibration===false&&p?.live_value_decisions_authorized===false&&Number(cal.probability_edge_threshold)===0.04&&Number(cal.expected_value_threshold)===0.03&&c.cutoff_utc===NBA_RELEASE_CUTOFF&&probabilitySample&&selectionEvidence&&p?.prospective_minimum_sample_reached===true&&p?.prospective_probability_validation_sample_met===true&&p?.prospective_clv_release_check_passed===true&&v.positive_clv_release_check_passed===true&&Number(v.near_close_observations)>=1&&Number(v.mean_probability_clv)>0&&Number(v.mean_line_clv_points)>0);
}
async function readNbaReleaseJson(path, deadlineAt = null){
 const remainingMs = deadlineAt == null ? 10000 : Math.max(250, Math.min(10000, deadlineAt - Date.now()));
 const response=await fetch('https://raw.githubusercontent.com/topboyasian-stack/match-signal/main/'+path+'?v='+Date.now(),{headers:{Accept:'application/json','Cache-Control':'no-cache','Pragma':'no-cache'},signal:AbortSignal.timeout(remainingMs)});
 const body=await response.text();
 if(!response.ok)throw new Error(path+' HTTP '+response.status);
 try{return JSON.parse(body);}catch(_){throw new Error(path+' returned non-JSON release evidence (HTTP '+response.status+', content-type '+String(response.headers.get('content-type')||'unknown')+').');}
}
export async function loadNbaReleaseContext(deadlineAt = null){
 const [evidence,probability,predictions,snapshots]=await Promise.all([readNbaReleaseJson('data/nba_totals_oos_value_test.json',deadlineAt),readNbaReleaseJson('data/nba_totals_probability_value_experiment.json',deadlineAt),readNbaReleaseJson('data/nba_predictions.json',deadlineAt),readNbaReleaseJson('data/nba_totals_publication_snapshots.json',deadlineAt)]);
 if(!Array.isArray(predictions)||!Array.isArray(snapshots))throw new Error('Invalid NBA release evidence arrays.');
 return{evidence,probability,predictions,snapshots};
}
export function nbaTotalTicketLegQualified(leg,selection,ctx,now=Date.now()){
 const fail=reason=>({ok:false,reason});
 if(!ctx||!nbaTotalsReleaseQualified(ctx.evidence,ctx.probability))return fail('The global NBA totals release gate is locked.');
 if(leg?.sport!=='basketball'||leg?.market!=='total'||leg?.market_id!=='225'||!['over','under'].includes(leg?.pick)||leg?.model_qualified!==true)return fail('Only a globally qualified market-225 Over/Under leg is allowed.');
 const id=String(leg.event_id||''),ps=(ctx.predictions||[]).filter(x=>String(x?.event_id||'')===id&&x?.totals_model_version===NBA_RELEASE_MODEL);
 if(ps.length!==1)return fail('No unique V5 prediction matches this fixture.');
 const p=ps[0],m=p?.markets?.total_ou||{},start=Date.parse(String(p.start_time||'')),legStart=Date.parse(String(leg.start_time||'')),quote=Date.parse(String(m.quote_timestamp||'')),report=Date.parse(String(ctx.probability?.generated_at||'')),forecast=Number(p.expected_total),line=Number(m.line),over=Number(m.over_odds),under=Number(m.under_odds),side=String(leg.pick);
 if(p.paper_only!==true||!Number.isFinite(start)||start<=now||legStart!==start||!Number.isFinite(quote)||quote>now+120000||now-quote>900000||quote>=start||!Number.isFinite(report)||report>now+120000||now-report>900000)return fail('Prediction, value report or quote is stale or mismatched.');
 if(String(m.market_id||'')!=='225'||String(m.source||'').toLowerCase()!=='sportybet nigeria'||m.quote_capture_basis!=='SportyBet API response observed_at'||String(leg.sportybet_event_id||'')!==String(m.sportybet_event_id||'')||String(m.pick||'').toLowerCase()!==side||!nbaReleaseClose(leg.line,line)||!Number.isFinite(forecast)||!Number.isFinite(over)||over<=1||!Number.isFinite(under)||under<=1)return fail('The exact market-225 side, line or price pair does not match.');
 const fetched=Date.parse(String(selection?.fetchedAt||''));
 if(!selection||String(selection.marketId)!=='225'||String(selection.eventId)!==String(m.sportybet_event_id)||!nbaReleaseClose(selection.line,line)||!nbaReleaseClose(selection.overOdds,over)||!nbaReleaseClose(selection.underOdds,under)||!nbaReleaseClose(selection.odds,side==='over'?over:under)||!Number.isFinite(fetched)||fetched>now+120000||now-fetched>900000||fetched>=start)return fail('The live SportyBet event, line or either side price changed.');
 const ds=(ctx.probability?.upcoming_exact_fresh_market_225_value_diagnostics||[]).filter(x=>String(x?.event_id||'')===id);if(ds.length!==1)return fail('No unique value diagnostic matches this fixture.');
 const d=ds[0],lo=d.bootstrap_95_lower_bound||{};
 if(Date.parse(String(d.start_time||''))!==start||String(d.quote_timestamp||'')!==String(m.quote_timestamp)||!nbaReleaseClose(d.forecast_total,forecast)||!nbaReleaseClose(d.sportybet_line,line)||!nbaReleaseClose(d.over_odds,over)||!nbaReleaseClose(d.under_odds,under)||d.decision!==(side==='over'?'OVER VALUE':'UNDER VALUE')||d.calibration_check!=='PASS'||!Number.isFinite(Number(lo[side+'_probability_edge']))||Number(lo[side+'_probability_edge'])<0.04||!Number.isFinite(Number(lo[side+'_expected_value']))||Number(lo[side+'_expected_value'])<0.03)return fail('The exact quote does not meet the preregistered value thresholds.');
 const cutoff=Date.parse(NBA_RELEASE_CUTOFF),snaps=(ctx.snapshots||[]).filter(x=>{const sm=x?.markets?.total_ou||{},pub=Date.parse(String(x?.published_at||'')),qt=Date.parse(String(sm.quote_timestamp||''));return x?.publication_snapshot_verified===true&&x?.publication_snapshot_kind==='immutable_sportybet_market_225_revision'&&x?.totals_model_version===NBA_RELEASE_MODEL&&String(x?.event_id||'')===id&&Date.parse(String(x?.start_time||''))===start&&pub>=cutoff&&pub<start&&pub<=now+120000&&qt<=now+120000&&String(sm.quote_timestamp||'')===String(m.quote_timestamp)&&qt<=pub&&pub-qt<=900000&&now-qt<=900000&&String(sm.market_id||'')==='225'&&String(sm.source||'').toLowerCase()==='sportybet nigeria'&&sm.quote_capture_basis==='SportyBet API response observed_at'&&String(sm.sportybet_event_id||'')===String(m.sportybet_event_id)&&String(sm.pick||'').toLowerCase()===side&&nbaReleaseClose(x?.expected_total,forecast)&&nbaReleaseClose(sm.expected_total,forecast)&&nbaReleaseClose(sm.line,line)&&nbaReleaseClose(sm.over_odds,over)&&nbaReleaseClose(sm.under_odds,under);});
 if(snaps.length!==1)return fail('No unique immutable fresh snapshot matches the exact NBA quote.');
 const sid=String(snaps[0].publication_snapshot_id||'');if(!sid||(ctx.snapshots||[]).filter(x=>String(x?.publication_snapshot_id||'')===sid).length!==1)return fail('The immutable snapshot ID is missing or duplicated.');
 return{ok:true,snapshot_id:sid};
}

function lineFromMarket(market) {
  // SportyBet may expose an integer base in market.line while its specifier
  // carries the actual half-point total (for example line=25, total=25.5).
  const specifierText = [market?.specifier, market?.specifiers, market?.marketSpecifier]
    .map(value => String(value || '')).join(' ');
  const explicitLine = specifierText.match(/(?:^|[,\s;|&])(?:total|line)\s*=\s*(-?\d+(?:\.\d+)?)(?=$|[,\s;|&])/i);
  if (explicitLine) return Number(explicitLine[1]);

  const rawLine = market?.line;
  if (rawLine != null && String(rawLine).trim() !== '') {
    const direct = Number(rawLine);
    if (Number.isFinite(direct)) return direct;
  }
  const text = [market?.desc, market?.name, market?.title, specifierText]
    .map(value => String(value || '')).join(' ');
  const match = text.match(/(?:total|line|over|under)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)/i)
    || text.match(/\b([0-9]+(?:\.[0-9]+)?)\b/);
  return match ? Number(match[1]) : null;
}

function catalogueTournaments(payload) {
  const data = payload?.data;
  // pcUpcomingEvents groups fixtures under data.tournaments. The WAP
  // configurable-upcoming endpoint can instead return data as a flat event
  // array, so normalize both response shapes before scanning.
  if (Array.isArray(data)) {
    return data.some(item => Array.isArray(item?.events))
      ? data
      : [{ name: '', events: data }];
  }
  if (Array.isArray(data?.tournaments)) return data.tournaments;
  if (Array.isArray(data?.events)) return [{ name: String(data?.name || ''), events: data.events }];
  if (Array.isArray(payload?.events)) return [{ name: '', events: payload.events }];
  return [];
}

function normalizeEvent(event, tournament) {
  const rawStart = Number(event?.estimateStartTime ?? event?.startTime ?? event?.start_time_ms ?? 0);
  const estimateStartTime = Number.isFinite(rawStart) && rawStart > 0
    ? (rawStart < 100000000000 ? rawStart * 1000 : rawStart)
    : 0;
  return {
    eventId: String(event?.eventId || event?.id || ''),
    homeTeamName: String(event?.homeTeamName || event?.homeTeam?.name || event?.home || ''),
    awayTeamName: String(event?.awayTeamName || event?.awayTeam?.name || event?.away || ''),
    estimateStartTime,
    matchStatus: String(event?.matchStatus || event?.status || 'Not start'),
    tournament: String(tournament?.name || event?.tournamentName || ''),
    markets: Array.isArray(event?.markets) ? event.markets : []
  };
}

// SportyBet's single-event endpoint returns full current markets for one
// provider ID. Try these exact IDs first; only changed/missing IDs need the
// slower participant/time catalogue search.
async function collectCurrentEventsById(legs, deadlineAt = null, sharedMatchedLegs = null) {
  const found = new Map();
  const sharedMatches = sharedMatchedLegs instanceof Set ? sharedMatchedLegs : null;
  const targets = Array.isArray(legs) ? legs : [];
  const ids = new Set();

  for (const leg of targets) {
    for (const value of [leg?.sportybet_event_id, leg?.event_id]) {
      const id = String(value || '').trim();
      if (id.startsWith('sr:match:')) ids.add(id);
    }
  }
  if (!ids.size) return found;

  const results = await Promise.all([...ids].map(async eventId => {
    try {
      const payload = await upstream('/api/ng/factsCenter/event', {
        eventId,
        _t: Date.now()
      }, {
        timeoutMs: 3000,
        deadlineAt
      });
      const raw = payload?.data?.event || payload?.data;
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
      const tournament = raw?.sport?.category?.tournament || {};
      const event = normalizeEvent(raw, tournament);
      // fetchedAt is this exact response observation time, not a prediction
      // timestamp or a stale cached quote.
      event.fetchedAt = new Date().toISOString();
      return event.eventId ? event : null;
    } catch (_) {
      // An expired or changed provider ID is not a hard failure. The caller
      // falls back to fixture aliases, participants and kickoff time.
      return null;
    }
  }));

  for (const event of results) {
    if (!event) continue;
    found.set(event.eventId, event);
    for (const leg of targets) {
      if (targetFixtureMatches(leg, event)) sharedMatches?.add(leg);
    }
  }
  return found;
}

export async function upstream(path, params, { timeoutMs = 6000, deadlineAt = null } = {}) {
  const failures = [];
  // SportyBet sometimes answers JSON API requests with an HTML edge/challenge
  // page. Retry the same catalogue query through the Match Signal proxy.
  for (const origin of [SPORTYBET_PROXY_ORIGIN, ORIGIN]) {
    if (deadlineAt != null && deadlineAt - Date.now() < 250) {
      failures.push('manual booking time budget exhausted before next catalogue source');
      break;
    }
    try {
      const url = new URL(origin + path);
      for (const [key, value] of Object.entries(params || {})) {
        if (value != null) url.searchParams.set(key, String(value));
      }
      if (!url.searchParams.has('_t')) url.searchParams.set('_t', String(Date.now()));
      const response = await fetch(url.toString(), {
        headers: BROWSER_HEADERS, signal: AbortSignal.timeout(Math.max(250, Math.min(timeoutMs, deadlineAt == null ? timeoutMs : deadlineAt - Date.now())))
      });
      const body = await response.text();
      const contentType = String(response.headers.get('content-type') || 'unknown');
      if (!response.ok) {
        let providerError = '';
        if (contentType.toLowerCase().includes('application/json')) {
          try {
            const errorPayload = JSON.parse(body);
            providerError = [errorPayload?.error, errorPayload?.detail, errorPayload?.message]
              .filter(value => typeof value === 'string' && value.trim())
              .join(': ');
          } catch (_) {}
        }
        throw new Error('HTTP ' + response.status + (providerError ? ' (' + providerError + ')' : '') + ' (content-type ' + contentType + ')');
      }
      if (!body.trim()) throw new Error('empty response (HTTP ' + response.status + ')');
      if (/^\s*</.test(body)) throw new Error('returned HTML instead of JSON (HTTP ' + response.status + ', content-type ' + contentType + ')');
      let payload;
      try { payload = JSON.parse(body); }
      catch (_) { throw new Error('returned malformed JSON (HTTP ' + response.status + ', content-type ' + contentType + ')'); }
      if (payload?.bizCode != null && Number(payload.bizCode) !== 10000) throw new Error('bizCode ' + payload.bizCode);
      return payload;
    } catch (error) {
      failures.push(origin + ': ' + String(error?.message || error));
    }
  }
  throw new Error('SportyBet catalogue unavailable for ' + path + ': ' + failures.join(' || ').slice(0, 700));
}


export async function requestSportyBetShare(selections, { deadlineAt = null, timeoutMs = 6500 } = {}) {
  const failures = [];
  const payload = JSON.stringify({
    selections: selections.map(selection => ({
      eventId: String(selection.eventId),
      marketId: String(selection.marketId),
      specifier: selection.specifier ?? null,
      outcomeId: String(selection.outcomeId)
    }))
  });

  // Route the fixed SportyBet share POST through the regional Worker first.
  // Fall back to the direct origin only if the proxy did not return usable JSON.
  // A valid provider business rejection is authoritative and is not retried.
  for (const origin of [SPORTYBET_PROXY_ORIGIN, ORIGIN]) {
    const remainingMs = deadlineAt == null ? timeoutMs : Math.min(timeoutMs, deadlineAt - Date.now());
    if (remainingMs < 250) {
      failures.push(origin + ': manual booking time budget exhausted before share response');
      break;
    }
    const url = origin + '/api/ng/orders/share?_t=' + Date.now();
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          ...BROWSER_HEADERS,
          'Accept-Language': 'en-NG,en;q=0.9',
          'Cache-Control': 'no-cache',
          'Pragma': 'no-cache',
          'Sec-Fetch-Dest': 'empty',
          'Sec-Fetch-Mode': 'cors',
          'Sec-Fetch-Site': 'same-origin'
        },
        body: payload,
        redirect: 'follow',
        signal: AbortSignal.timeout(remainingMs)
      });
      const text = await response.text();
      const contentType = String(response.headers.get('content-type') || 'unknown');
      let parsed = null;
      try { parsed = JSON.parse(text); } catch (_) {}

      if (parsed && parsed.bizCode != null && Number(parsed.bizCode) !== 10000) {
        return { status: response.status, payload: parsed, origin, contentType };
      }
      if (response.ok && parsed && !/^\s*</.test(text)) {
        return { status: response.status, payload: parsed, origin, contentType };
      }

      const upstreamError = parsed
        ? [parsed.error, parsed.detail, parsed.message].filter(v => typeof v === 'string' && v.trim()).join(': ')
        : 'returned non-JSON response';
      failures.push(origin + ': HTTP ' + response.status + ' (' + upstreamError + '; content-type ' + contentType + ')');
    } catch (error) {
      failures.push(origin + ': ' + String(error?.message || error).slice(0, 180));
    }
  }

  return {
    error: 'SPORTYBET_SHARE_UPSTREAM_UNAVAILABLE',
    message: 'SportyBet could not return a JSON share response through the regional proxy or direct endpoint: ' + failures.join(' || ').slice(0, 700),
    attempts: failures
  };
}

function currentSelectionForTarget(leg, event) {
  const sport = String(leg?.sport || '').toLowerCase();
  const market = String(leg?.market || '').toLowerCase();
  const product = productForLeg(leg);
  if (sport === 'basketball') return market === 'winner'
    ? findBasketballWinnerSelection(leg, event)
    : findBasketballSelection(leg, event);
  if (sport === 'tennis' && market === 'set_winner') return findSetWinnerSelection(leg, event);
  // Odds Builder's eFootball legs are serialized as sport="virtual",
  // market="virtual_total", product="efootball_gt". Treat that shape as an
  // exact totals market during direct-ID matching, not as a match-winner pick.
  const isTotalsMarket = market === 'total' || market === 'virtual_total' ||
    (['vfootball', 'efootball'].includes(product) && Boolean(pickVirtualSide(leg)));
  return isTotalsMarket
    ? findVirtualSelection(leg, event)
    : findWinnerSelection(leg, event);
}

function targetFixtureMatches(leg, event) {
  const participants = legParticipants(leg);
  const hasParticipants = Boolean(participants[0] && participants[1]);
  const expectedIds = [
    String(leg?.sportybet_event_id || ''),
    String(leg?.event_id || '')
  ].filter(Boolean);
  if (hasParticipants) {
    if (!legParticipantPairMatches(leg, event)) return false;
  } else if (!expectedIds.includes(String(event?.eventId || ''))) {
    return false;
  }

  const requestedStart = Date.parse(String(leg?.start_time || ''));
  const currentStart = Number(event?.estimateStartTime || 0);
  if (Number.isFinite(requestedStart) && currentStart &&
      Math.abs(requestedStart - currentStart) > 45 * 60 * 1000) return false;

  // A fixture match alone is not enough to stop discovery or accept an ID hit:
  // the exact requested market, line and active side must also exist right now.
  const selection = currentSelectionForTarget(leg, event);
  return Boolean(selection && !selection.error && selection.outcomeId &&
    Number.isFinite(Number(selection.odds)) && Number(selection.odds) > 1);
}

export async function collectEvents({
  sportId,
  marketId,
  timeline = 168,
  pageSize = 100,
  maxPages = 5,
  primaryPath = '/api/ng/factsCenter/pcUpcomingEvents',
  fallbackPath = null,
  fallbackParams = {},
  deadlineAt = null,
  requestTimeoutMs = 6000,
  pageBatchSize = 5,
  sharedMatchedLegs = null
}, targetIds, targetLegs = []) {
  const found = new Map();
  const matchedTargets = new Set();
  const fixtureTargets = Array.isArray(targetLegs) ? targetLegs : [];
  const matchedFixtureTargets = new Set();
  const sharedMatches = sharedMatchedLegs instanceof Set ? sharedMatchedLegs : null;

  // Other parallel catalogue sources may already have resolved one or more
  // legs. Stop paging those targets as soon as an exact current selection exists.
  const targetsComplete = () => fixtureTargets.length
    ? fixtureTargets.every((leg, index) => matchedFixtureTargets.has(index) || sharedMatches?.has(leg))
    : matchedTargets.size >= targetIds.size;

  function addCataloguePage(data) {
    const tournaments = catalogueTournaments(data);
    let count = 0;
    for (const tournament of tournaments) {
      for (const event of Array.isArray(tournament?.events) ? tournament.events : []) {
        const normalized = normalizeEvent(event, tournament);
        if (normalized.eventId) {
          found.set(normalized.eventId, normalized);
          if (targetIds.has(normalized.eventId)) matchedTargets.add(normalized.eventId);
          fixtureTargets.forEach((leg, index) => {
            // A stale provider ID can still exist in the catalogue but point to a
            // different event. It must not satisfy a manual target or stop paging
            // before the real participant/kickoff/market match is found.
            if (targetFixtureMatches(leg, normalized)) {
              matchedFixtureTargets.add(index);
              sharedMatches?.add(leg);
            }
          });
        }
        count++;
      }
    }
    return count;
  }

  async function scanPath(path) {
    let hadRequestError = false;
    let nextPage = 1;
    while (nextPage <= maxPages && !targetsComplete()) {
      // Read page 1 alone to avoid fan-out when a source is empty. Once a
      // full page is confirmed, read bounded groups concurrently. The
      // football catalogue can exceed 1,000 fixtures; sequential page scans
      // previously found only the first five hundred, while the canonical
      // prediction market collector searches up to twenty pages.
      const batch = nextPage === 1
        ? [1]
        : Array.from({ length: Math.min(pageBatchSize, maxPages - nextPage + 1) }, (_, i) => nextPage + i);
      const results = await Promise.all(batch.map(async pageNum => {
        const params = {
          sportId,
          marketId,
          pageSize,
          pageNum,
          todayGames: 'false',
          timeline,
          _t: Date.now(),
          ...fallbackParams
        };
        try {
          const data = await upstream(path, params, { timeoutMs: requestTimeoutMs, deadlineAt });
          return { pageNum, data, error: null };
        } catch (error) {
          return { pageNum, data: null, error };
        }
      }));

      let reachedEnd = false;
      for (const result of results.sort((x, y) => x.pageNum - y.pageNum)) {
        if (result.error) {
          hadRequestError = true;
          continue;
        }
        const count = addCataloguePage(result.data);
        if (count < pageSize) {
          reachedEnd = true;
          break;
        }
        if (targetsComplete()) break;
      }
      if (targetsComplete() || reachedEnd) break;
      nextPage += batch.length;
    }
    return hadRequestError;
  }

  // Football's current SportyBet PC feed is the source used by the scheduled
  // market collector. It can place academy/U21 fixtures beyond page 5, so use
  // the full 20-page bounded window before declaring a selected fixture absent.
  const primaryHadErrors = await scanPath(primaryPath);
  if (!targetsComplete() && fallbackPath) {
    // The configurable WAP endpoint remains a secondary catalogue, useful
    // when the PC endpoint is unavailable or omits a supported competition.
    await scanPath(fallbackPath);
  }
  return found;
}

function targetBasketballFixtureMatches(leg, event) {
  const [first, second] = legParticipants(leg);
  if (!sameParticipantPair([first, second], event, 'basketball')) return false;
  const requestedStart = Date.parse(String(leg?.start_time || ''));
  const currentStart = Number(event?.estimateStartTime || 0);
  return Number.isFinite(requestedStart) && currentStart > 0 &&
    Math.abs(requestedStart - currentStart) <= 45 * 60 * 1000;
}

export async function collectBasketballEvents(context, targetIds, timeline = 168, targetLegs = [], deadlineAt = null) {
  const found = new Map();
  const ids = targetIds instanceof Set ? targetIds : new Set();
  const targets = Array.isArray(targetLegs) ? targetLegs : [];
  const matchedTargets = new Set();
  if (!ids.size && !targets.length) return found;

  const targetsComplete = () => targets.length
    ? matchedTargets.size >= targets.length
    : [...ids].every(id => found.has(id));

  for (let page = 1; page <= 5 && !targetsComplete(); page++) {
    const remainingMs = deadlineAt == null ? 10000 : deadlineAt - Date.now();
    if (remainingMs < 250) break;
    const url = new URL('/api/sportybet-basketball?pageSize=100&timeline=' + encodeURIComponent(String(timeline)) + '&pageNum=' + page + '&_t=' + Date.now(), context.request.url);
    // Call the sibling Pages Function directly; do not HTTP self-fetch the public hostname.
    const feedRequest = new Request(url.toString(), {
      headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache' },
      signal: AbortSignal.timeout(Math.max(250, Math.min(4500, remainingMs)))
    });
    const response=await getSportyBetBasketballFeed({request:feedRequest,env:context.env,params:context.params,data:context.data});
    const body = await response.text();
    if (!response.ok) throw new Error('Current SportyBet basketball feed HTTP ' + response.status);
    let payload;
    try {
      payload = JSON.parse(body);
    } catch (_) {
      throw new Error('Current SportyBet basketball feed returned non-JSON content (HTTP ' + response.status + ', content-type ' + String(response.headers.get('content-type') || 'unknown') + ').');
    }
    if (payload?.ok !== true || !Array.isArray(payload.events)) {
      throw new Error(payload?.error || 'Current SportyBet basketball feed unavailable');
    }

    for (const row of payload.events) {
      const eventId = String(row?.event_id || '');
      if (!eventId) continue;
      const start = Date.parse(String(row?.start_time || ''));
      const markets = (Array.isArray(row?.markets) ? row.markets : []).map(m => ({
        id: String(m?.id || ''),
        name: String(m?.name || ''),
        desc: String(m?.name || ''),
        specifier: m?.specifier ?? null,
        status: String(m?.status || ''),
        outcomes: (Array.isArray(m?.outcomes) ? m.outcomes : []).map(o => ({
          id: String(o?.id || ''),
          name: String(o?.name || ''),
          desc: String(o?.name || ''),
          odds: Number(o?.odds),
          active: o?.active !== false,
          isActive: o?.active === false ? 0 : 1
        }))
      }));
      const event = {
        eventId,
        homeTeamName: String(row?.home || ''),
        awayTeamName: String(row?.away || ''),
        estimateStartTime: Number.isFinite(start) ? start : 0,
        matchStatus: 'Not start',
        tournament: String(row?.tournament || ''),
        fetchedAt: String(row?.fetched_at || payload?.fetched_at || ''),
        markets
      };
      const identityMatches = targets
        .map((leg, index) => ({ leg, index }))
        .filter(({ leg }) => {
          // Discovery may retain an identity/time match so the final validator
          // can explain a missing market accurately. It does not stop paging.
          return targetBasketballFixtureMatches(leg, event);
        })
        .map(({ index }) => index);
      const exactSelectionMatches = targets
        .map((leg, index) => ({ leg, index }))
        .filter(({ leg }) => targetFixtureMatches(leg, event))
        .map(({ index }) => index);
      if (ids.has(eventId) || identityMatches.length || exactSelectionMatches.length) {
        found.set(eventId, event);
      }
      // Only an exact active market-225 line + side + two prices completes
      // discovery for this leg; an ID or team match alone never does.
      exactSelectionMatches.forEach(index => matchedTargets.add(index));
    }
    if (payload.catalogue_page_has_more !== true) break;
  }
  return found;
}
function findBasketballWinnerSelection(leg,event){
  const pick=String(leg?.pick||'').toLowerCase();
  if(pick!=='p1'&&pick!=='p2')return{error:'NBA match winners must select Player 1 or Player 2.'};
  if(String(leg?.market_id||'')!=='219')return{error:'NBA match winners require exact SportyBet market 219 (Winner incl. overtime).'};
  if(!sameParticipantPair([leg?.player_1,leg?.player_2],event,'basketball'))return{error:'Basketball participants changed in the current SportyBet catalogue.'};
  const rs=Date.parse(String(leg?.start_time||'')),es=Number(event?.estimateStartTime||0);
  if(!Number.isFinite(rs)||!es||Math.abs(rs-es)>2700000)return{error:'Basketball fixture start time changed; refresh the ticket.'};
  const p1IsHome=participantNameMatches(leg?.player_1,event?.homeTeamName);
  const p1IsAway=participantNameMatches(leg?.player_1,event?.awayTeamName);
  const p2IsHome=participantNameMatches(leg?.player_2,event?.homeTeamName);
  const p2IsAway=participantNameMatches(leg?.player_2,event?.awayTeamName);
  if(!((p1IsHome&&p2IsAway)||(p1IsAway&&p2IsHome)))return{error:'NBA Player 1/Player 2 orientation does not match the current SportyBet home/away teams.'};
  for(const market of (Array.isArray(event?.markets)?event.markets:[])){
    const status=String(market?.status??'').trim().toLowerCase();
    if(String(market?.id||'')!=='219'||/suspend|closed|inactive|settled|unavailable|stop/i.test(status)||(status!==''&&/^\d+$/.test(status)&&status!=='0'))continue;
    const outcomes=Array.isArray(market?.outcomes)?market.outcomes:[];
    const active=side=>outcomes.find(o=>{
      const label=canonicalParticipant(o?.desc||o?.name||o?.title||'');
      const ok=o?.isActive==null?(o?.active!==false):(Number(o.isActive)===1||o.isActive===true);
      const odds=Number(o?.odds);
      return ok&&String(o?.id||'')&&label===side&&Number.isFinite(odds)&&odds>1;
    });
    const home=active('home'),away=active('away');
    if(!home||!away)continue;
    const selectedHome=pick==='p1'?p1IsHome:p2IsHome;
    const selected=selectedHome?home:away;
    return{
      eventId:event.eventId,marketId:'219',specifier:market?.specifier??null,
      outcomeId:String(selected.id),outcomeName:String(selected.desc||selected.name||(selectedHome?'Home':'Away')),
      odds:Number(selected.odds),homeOdds:Number(home.odds),awayOdds:Number(away.odds),
      fetchedAt:String(event?.fetchedAt||''),sportybetEventId:String(event.eventId||'')
    };
  }
  return{error:'Exact current SportyBet market-219 Home/Away winner prices are unavailable.'};
}
function findBasketballSelection(leg,event){
  const side=String(leg?.pick||'').toLowerCase(),line=Number(leg?.line);
  if(!['over','under'].includes(side)||!Number.isFinite(line)||line<100||line>300||String(leg?.market_id||'225')!=='225')return{error:'Only exact SportyBet market-225 full-game totals are supported.'};
  if(!sameParticipantPair([leg?.player_1,leg?.player_2],event,'basketball'))return{error:'Basketball participants changed in the current SportyBet catalogue.'};
  const rs=Date.parse(String(leg?.start_time||'')),es=Number(event?.estimateStartTime||0);if(Number.isFinite(rs)&&es&&Math.abs(rs-es)>2700000)return{error:'Basketball fixture start time changed; refresh the ticket.'};
  for(const market of (Array.isArray(event?.markets)?event.markets:[])){
    const status=String(market?.status||'').trim().toLowerCase();if(String(market?.id||'')!=='225'||/suspend|closed|inactive|settled|unavailable|stop/i.test(status)||(status!==''&&/^\d+$/.test(status)&&status!=='0'))continue;
    const currentLine=lineFromMarket(market);if(!Number.isFinite(currentLine)||Math.abs(currentLine-line)>1e-9)continue;
    const outcomes=Array.isArray(market?.outcomes)?market.outcomes:[];
    const active=name=>outcomes.find(o=>{const label=String(o?.desc||o?.name||o?.title||'').toLowerCase(),ok=o?.isActive==null?(o?.active!==false):(Number(o.isActive)===1||o.isActive===true),odds=Number(o?.odds);return ok&&new RegExp('\\b'+name+'\\b').test(label)&&String(o?.id||'')&&Number.isFinite(odds)&&odds>1;});
    const over=active('over'),under=active('under');if(!over||!under)continue;const out=side==='over'?over:under;
    return{eventId:event.eventId,marketId:'225',specifier:market?.specifier??null,outcomeId:String(out.id),outcomeName:String(out.desc||out.name||side),odds:Number(out.odds),line:currentLine,overOdds:Number(over.odds),underOdds:Number(under.odds),fetchedAt:String(event?.fetchedAt||''),sportybetEventId:String(event.eventId||'')};
  }
  return{error:'Exact current market-225 line or both side prices are unavailable.'};
}
function canonicalParticipant(value) {
  let raw = String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  // Some bookmaker feeds return "Surname, Firstname".
  if (raw.includes(',')) {
    const parts = raw.split(',').map(part => part.trim()).filter(Boolean);
    if (parts.length === 2) raw = parts[1] + ' ' + parts[0];
  }
  const tokens = raw.replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  // Handle the common trailing-initial form "Surname A." as "A Surname".
  if (tokens.length === 2 && tokens[1].length === 1 && tokens[0].length > 1) {
    tokens.reverse();
  }
  return tokens.join(' ');
}

function participantNameMatches(first, second) {
  const a = canonicalParticipant(first);
  const b = canonicalParticipant(second);
  if (!a || !b) return false;
  if (a === b) return true;
  const left = a.split(' ');
  const right = b.split(' ');
  // Some feeds return the full two-part player name in surname-first order.
  if (left.length === 2 && right.length === 2 &&
      left[0] === right[1] && left[1] === right[0]) return true;
  if (left.length < 2 || right.length < 2) return false;
  const leftSurname = left[left.length - 1];
  const rightSurname = right[right.length - 1];
  const leftFirst = left[0];
  const rightFirst = right[0];
  // Accept a first initial only when both the surname and initial agree.
  return leftSurname === rightSurname &&
    (leftFirst.length === 1 || rightFirst.length === 1) &&
    leftFirst[0] === rightFirst[0];
}

function legParticipants(leg) {
  let first = String(leg?.player_1 || leg?.home || '').trim();
  let second = String(leg?.player_2 || leg?.away || '').trim();
  if ((!first || !second) && (leg?.match || leg?.fixture)) {
    const parts = String(leg.match || leg.fixture).split(/\s+(?:vs?\.?)\s+/i);
    if (parts.length === 2) {
      first = first || parts[0].trim();
      second = second || parts[1].trim();
    }
  }
  return [first, second];
}

function sameParticipantPair(first, event, sport = '') {
  const [a, b] = Array.isArray(first) ? first : [];
  const home = event?.homeTeamName || '';
  const away = event?.awayTeamName || '';
  return Boolean(a && b && home && away &&
    ((teamNameMatches(a, home, sport) && teamNameMatches(b, away, sport)) ||
     (teamNameMatches(a, away, sport) && teamNameMatches(b, home, sport))));
}

// SportyBet's football catalogue often uses official club names while the
// Desk uses familiar short names (e.g. "Málaga" / "Malaga CF",
// "VfB Stuttgart" / "Stuttgart", and "Paderborn" / "SC Paderborn 07").
// Only remove standard club markers and the documented "07" suffix; keep the
// kickoff-window and opposing-team checks as independent identity safeguards.
const FOOTBALL_CLUB_MARKERS = new Set([
  'afc', 'ac', 'cf', 'fc', 'sc', 'sv', 'vfb', 'vfl', 'tsv', 'ssv',
  'fsv', 'ksc', 'bsc', 'ssc'
]);
function canonicalFootballClubName(value) {
  const tokens = canonicalParticipant(value).split(' ').filter(Boolean);
  const kept = tokens.filter((token, index) => {
    if (FOOTBALL_CLUB_MARKERS.has(token) || token === '07') return false;
    // "1. FC Köln" uses the leading 1 as part of the competition-style name,
    // not as a distinguishing team token.
    if (token === '1' && tokens[index + 1] === 'fc') return false;
    return true;
  });
  return kept.join(' ');
}
// SportyBet's catalogue and the prediction feeds use different display names
// for the same clubs. Keep these aliases sport-scoped and exact: never infer a
// fixture from a loose substring or from one participant alone.
const FOOTBALL_TEAM_ALIAS_GROUPS = [
  ['manchester united', 'man utd', 'man united', 'manchester utd'],
  ['manchester city', 'man city'],
  ['tottenham hotspur', 'tottenham', 'spurs'],
  ['newcastle united', 'newcastle'],
  ['west ham united', 'west ham'],
  ['wolverhampton wanderers', 'wolverhampton', 'wolves'],
  ['nottingham forest', 'nottm forest'],
  ['brighton and hove albion', 'brighton', 'brighton hove albion'],
  ['paris saint germain', 'paris sg', 'psg', 'paris st germain'],
  ['bayern munich', 'bayern munchen', 'fc bayern munchen', 'bayern'],
  ['borussia dortmund', 'dortmund', 'bvb', 'bvb 09'],
  ['bayer leverkusen', 'leverkusen', 'bayer 04 leverkusen'],
  ['rb leipzig', 'rasenballsport leipzig', 'leipzig'],
  ['inter milan', 'internazionale', 'fc internazionale milano'],
  ['ac milan', 'milan'],
  ['as roma', 'roma'],
  ['real betis', 'betis', 'real betis balompie'],
  ['real sociedad', 'sociedad', 'real sociedad de futbol'],
  ['olympique marseille', 'olympique de marseille', 'marseille'],
  ['olympique lyonnais', 'olympique lyon', 'lyon'],
  ['psv eindhoven', 'psv'],
  ['sporting cp', 'sporting lisbon', 'sporting clube de portugal', 'sporting portugal'],
  ['sl benfica', 'benfica', 'sport lisboa e benfica'],
  ['fc porto', 'porto'],
  ['galatasaray', 'galatasaray sk'],
  ['fenerbahce', 'fenerbahce sk'],
  ['besiktas', 'besiktas jk'],
  ['celtic', 'celtic fc'],
  ['rangers', 'rangers fc'],
  ['ssc napoli', 'napoli']
];

const BASKETBALL_TEAM_ALIAS_GROUPS = [
  ['los angeles lakers', 'la lakers'],
  ['los angeles clippers', 'la clippers'],
  ['golden state warriors', 'gs warriors', 'gsw'],
  ['oklahoma city thunder', 'okc thunder', 'okc'],
  ['new york knicks', 'ny knicks', 'nyk'],
  ['san antonio spurs', 'sa spurs'],
  ['portland trail blazers', 'portland trailblazers', 'portland blazers'],
  ['minnesota timberwolves', 'minnesota timber wolves'],
  ['new orleans pelicans', 'nola pelicans'],
  ['brooklyn nets', 'bk nets']
];

function splitVirtualParticipant(value) {
  const normalized = canonicalParticipant(value);
  const match = normalized.match(/^(.*?)(?:\s+(virtual|vfootball|efootball)\s+([a-z0-9]+))$/);
  return match
    ? { base: match[1].trim(), suffix: match[2] + ' ' + match[3] }
    : { base: normalized, suffix: '' };
}

function teamAliasKey(value, sport) {
  const virtual = sport === 'efootball';
  const split = virtual ? splitVirtualParticipant(value) : { base: String(value || ''), suffix: '' };
  const normalized = sport === 'basketball'
    ? canonicalParticipant(split.base)
    : canonicalFootballClubName(split.base);
  const groups = sport === 'basketball' ? BASKETBALL_TEAM_ALIAS_GROUPS : FOOTBALL_TEAM_ALIAS_GROUPS;
  const group = groups.find(items => items.some(alias => {
    const candidate = sport === 'basketball'
      ? canonicalParticipant(alias)
      : canonicalFootballClubName(alias);
    return candidate === normalized;
  }));
  const base = group ? group[0] : normalized;
  return split.suffix ? base + ' ' + split.suffix : base;
}

function teamNameMatches(first, second, sport = '') {
  if (participantNameMatches(first, second)) return true;
  if (!['football', 'basketball', 'efootball'].includes(sport)) return false;
  const a = teamAliasKey(first, sport);
  const b = teamAliasKey(second, sport);
  return Boolean(a && b && a.length >= 3 && a === b);
}

function footballTeamNameMatches(first, second) {
  return teamNameMatches(first, second, 'football');
}
function sameFootballParticipantPair(first, event) {
  return sameParticipantPair(first, event, 'football');
}
function legParticipantPairMatches(leg, event) {
  const participants = legParticipants(leg);
  const sport = String(leg?.sport || '').toLowerCase();
  const product = productForLeg(leg);
  const aliasSport = product === 'vfootball' ? 'football' : product === 'efootball' ? 'efootball' : sport;
  return sameParticipantPair(participants, event, aliasSport);
}

function normalizeFixture(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/\s*vs\s*/g, ' vs ')
    .trim();
}

function resolveCurrentEvent(leg, found) {
  const [first, second] = legParticipants(leg);
  const hasParticipants = Boolean(first && second);
  const sportybetId = String(leg?.sportybet_event_id || '');
  const directProvider = sportybetId ? found.get(sportybetId) : null;
  const direct = directProvider || found.get(String(leg?.event_id || ''));
  // Resolve by ID only when the live record is also the exact requested
  // fixture, kickoff and active market selection. A stale ID can remain present
  // in SportyBet's catalogue but point at a variant with the wrong market.
  if (direct && targetFixtureMatches(leg, direct)) {
    return { event: direct, matched_by: directProvider ? 'sportybet_event_id' : 'event_id' };
  }

  const targetMatch = normalizeFixture(
    leg?.match ||
    leg?.fixture ||
    String(leg?.pick || '').split('—')[0]
  );
  if (!hasParticipants && !targetMatch) return { event: null, matched_by: 'none' };

  const targetStart = Date.parse(String(leg?.start_time || ''));
  let best = null;
  let bestDiff = Infinity;

  for (const event of found.values()) {
    const participantsMatch = hasParticipants
      ? legParticipantPairMatches(leg, event)
      : normalizeFixture(String(event?.homeTeamName || '') + ' vs ' + String(event?.awayTeamName || '')) === targetMatch;
    if (!participantsMatch) continue;

    if (!targetFixtureMatches(leg, event)) continue;
    const candidateStart = Number(event?.estimateStartTime || 0);
    if (!candidateStart) {
      if (!best) best = event;
      continue;
    }

    const diff = Number.isFinite(targetStart)
      ? Math.abs(candidateStart - targetStart)
      : 0;
    if (diff <= 45 * 60 * 1000 && diff < bestDiff) {
      best = event;
      bestDiff = diff;
    }
  }

  return { event: best, matched_by: best ? 'fixture_participants_time' : 'none' };
}

async function collectVirtualEventsFromLiveFeed(
  context,
  targetIds,
  sources = 'efootball,vfootball',
  deadlineAt = null,
  targetLegs = [],
  timeline = 168,
  sharedMatchedLegs = null
) {
  const found = new Map();
  const ids = targetIds instanceof Set ? targetIds : new Set();
  const targets = Array.isArray(targetLegs) ? targetLegs : [];
  if (!ids.size && !targets.length) return found;
  const matched = new Set();
  const sharedMatches = sharedMatchedLegs instanceof Set ? sharedMatchedLegs : null;
  const targetsComplete = () => targets.length
    ? targets.every((leg, index) => matched.has(index) || sharedMatches?.has(leg))
    : [...ids].every(id => found.has(id));

  try {
    // This endpoint caps pageSize at 100. Search bounded subsequent pages too:
    // the selected fixture can move to a new provider ID and sit beyond page 1.
    for (let pageNum = 1; pageNum <= 5 && !targetsComplete(); pageNum++) {
      const remainingMs = deadlineAt == null ? 5000 : deadlineAt - Date.now();
      if (remainingMs < 250) break;
      const url = new URL('/api/sportybet-virtual', context.request.url);
      url.searchParams.set('pageSize', '100');
      url.searchParams.set('pageNum', String(pageNum));
      url.searchParams.set('timeline', String(timeline));
      url.searchParams.set('sources', sources);
      url.searchParams.set('_t', String(Date.now()));
      const response = await fetch(url.toString(), {
        headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' },
        signal: AbortSignal.timeout(Math.max(250, Math.min(5000, remainingMs)))
      });
      if (!response.ok) break;
      const payload = await response.json();
      const events = Array.isArray(payload?.events) ? payload.events : [];
      for (const row of events) {
        const eventId = String(row?.event_id || row?.eventId || '');
        if (!eventId) continue;
        const rawStart = Number(row?.start_time_ms || 0);
        let estimateStartTime = rawStart;
        if (!estimateStartTime && row?.start_time) {
          const parsed = Date.parse(String(row.start_time));
          if (Number.isFinite(parsed)) estimateStartTime = parsed;
        }
        const event = {
          eventId,
          homeTeamName: String(row?.team_1 || row?.participant_1 || ''),
          awayTeamName: String(row?.team_2 || row?.participant_2 || ''),
          estimateStartTime,
          matchStatus: String(row?.match_status || 'Not start'),
          tournament: String(row?.competition || ''),
          markets: Array.isArray(row?.markets) ? row.markets : []
        };
        const matchedIndexes = targets
          .map((leg, index) => ({ leg, index }))
          .filter(({ leg }) => targetFixtureMatches(leg, event))
          .map(({ index }) => index);
        if (ids.has(eventId) || matchedIndexes.length) found.set(eventId, event);
        matchedIndexes.forEach(index => {
          matched.add(index);
          sharedMatches?.add(targets[index]);
        });
      }
      if (targetsComplete()) break;
      if (events.length < 100) break;
    }
  } catch (error) {
    // Existing SportyBet catalogue lookup remains the primary path.
  }
  return found;
}

function validationFailure(leg, reason) {
  return {
    event_id: String(leg?.event_id || ''),
    sport: String(leg?.sport || ''),
    match: String(leg?.match || (String(leg?.player_1 || '') + ' vs ' + String(leg?.player_2 || ''))),
    market: String(leg?.market || ''),
    pick: String(leg?.pick || ''),
    line: leg?.line ?? null,
    ok: false,
    excluded: true,
    reason
  };
}

function productForLeg(leg) {
  const product = String(leg?.product || '').toLowerCase();
  if (product === 'vfootball') return 'vfootball';
  if (product === 'efootball_gt' || product === 'efootball_adriatic' || product === 'zoom') return 'efootball';
  return '';
}

async function loadBuilder(context) {
  const assetUrl = new URL('/data/odds_builder.json', context.request.url);
  assetUrl.searchParams.set('_t', String(Date.now()));
  let response;
  if (context.env?.ASSETS?.fetch) {
    response = await context.env.ASSETS.fetch(new Request(assetUrl.toString(), {
      headers: { 'Accept': 'application/json' }
    }));
  } else {
    response = await fetch(assetUrl.toString(), { headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' } });
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
  const sport = String(leg?.sport || '').toLowerCase();
  const efootballProduct = productForLeg(leg) === 'efootball' || sport === 'efootball';
  const requiredMarketId = sport === 'football' ? '18' : sport === 'tennis' ? '189' : efootballProduct ? String(leg?.market_id || '') : '';
  if (efootballProduct && !['18', '189'].includes(requiredMarketId)) return { error: 'Only an exact SportyBet eFootball totals market (18 or 189) is supported.' };
  if (!Number.isFinite(requestedLine) || !side) {
    return { error: 'Could not map the Builder O/U selection to an exact line and side.' };
  }
  if (requiredMarketId && String(leg?.market_id || '') !== requiredMarketId) {
    return { error: 'The requested sport total market ID does not match the supported full-match market.' };
  }
  const markets = Array.isArray(event?.markets) ? event.markets : [];
  for (const market of markets) {
    const marketId = String(market?.id || '');
    const status = String(market?.status || '').trim().toLowerCase();
    if (/suspend|closed|inactive|settled|unavailable|stop/i.test(status) ||
        (status !== '' && /^\d+$/.test(status) && status !== '0')) continue;
    const desc = [market?.desc,market?.name,market?.title,market?.specifier]
      .map(value => String(value || '')).join(' ').toLowerCase();
    const line = lineFromMarket(market);
    const isOu = requiredMarketId
      ? marketId === requiredMarketId
      : (marketId === '189' || /over\s*\/?\s*under|over.?under|total|\bou\b/.test(desc));
    if (!isOu || line == null || Math.abs(line - requestedLine) > 1e-9) continue;
    const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
    const outcome = outcomes.find(o => {
      const rawName = String(o?.desc || o?.name || o?.title || '').toLowerCase().trim();
      const normalized = rawName.replace(/[^a-z0-9]+/g, ' ');
      const active = o?.isActive == null ? (o?.active == null || o.active !== false) : Number(o.isActive) === 1 || o.isActive === true;
      const sideMatch = side === 'under' ? /\bunder\b/.test(normalized) || /^u\b/.test(normalized) : /\bover\b/.test(normalized) || /^o\b/.test(normalized);
      const outcomeLine = lineFromMarket(o);
      const lineMatch = outcomeLine == null || Math.abs(Number(outcomeLine) - requestedLine) < 1e-9;
      return active && sideMatch && lineMatch;
    });
    if (!outcome) continue;
    return { eventId:event.eventId,marketId,specifier:market?.specifier??null,outcomeId:String(outcome?.id||''),outcomeName:String(outcome?.desc||outcome?.name||outcome?.title||''),odds:Number(outcome?.odds||0) };
  }
  return { error: 'The exact SportyBet O/U line or selected side is no longer available.' };
}

function findSetWinnerSelection(leg, event) {
  const sport = String(leg?.sport || '').toLowerCase();
  const setNumber = Number(leg?.set_number);
  const pick = String(leg?.pick || '').toLowerCase();
  if (sport !== 'tennis' || ![1, 2].includes(setNumber) ||
      !['p1', 'p2'].includes(pick) || String(leg?.market_id || '') !== '202') {
    return { error: 'Tennis set-winner selections require Set 1 or Set 2 and exact SportyBet market 202.' };
  }
  if (!sameParticipantPair([leg?.player_1, leg?.player_2], event, 'tennis')) {
    return { error: 'Tennis participants changed in the current SportyBet event.' };
  }
  const requestedStart = Date.parse(String(leg?.start_time || ''));
  const currentStart = Number(event?.estimateStartTime || 0);
  if (Number.isFinite(requestedStart) && currentStart &&
      Math.abs(requestedStart - currentStart) > 45 * 60 * 1000) {
    return { error: 'Tennis fixture start time changed; refresh the ticket.' };
  }
  const selectedName = String(pick === 'p1' ? leg?.player_1 || '' : leg?.player_2 || '').trim();
  if (!selectedName) return { error: 'The selected tennis player identity is missing.' };
  const escapedSet = String(setNumber);
  const markets = Array.isArray(event?.markets) ? event.markets : [];
  for (const market of markets) {
    if (String(market?.id || '') !== '202') continue;
    const specifier = [market?.specifier, market?.specifiers, market?.marketSpecifier]
      .find(value => typeof value === 'string' && value.trim())?.trim() || '';
    const scope = specifier.match(/(?:^|[|,;\s])setnr\s*=\s*([12])(?=$|[|,;\s])/i);
    if (!scope || scope[1] !== escapedSet) continue;
    const desc = String(market?.desc || market?.name || market?.title || '').toLowerCase();
    if (desc && !/winner/.test(desc)) continue;
    const status = String(market?.status || '').trim().toLowerCase();
    if (/suspend|closed|inactive|settled|unavailable|stop/i.test(status) ||
        (status !== '' && /^\d+$/.test(status) && status !== '0')) continue;
    const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
    const outcome = outcomes.find(item => {
      const rawName = String(item?.desc || item?.name || item?.title || '').trim();
      const active = item?.isActive == null ? item?.active !== false :
        Number(item.isActive) === 1 || item.isActive === true;
      const odds = Number(item?.odds);
      return active && Boolean(String(item?.id || '')) && Number.isFinite(odds) && odds > 1 &&
        participantNameMatches(selectedName, rawName);
    });
    if (!outcome) continue;
    return {
      eventId: String(event.eventId || ''),
      marketId: '202',
      specifier,
      outcomeId: String(outcome.id),
      outcomeName: String(outcome.desc || outcome.name || outcome.title || ''),
      odds: Number(outcome.odds),
      fetchedAt: String(event?.fetchedAt || '')
    };
  }
  return { error: 'The exact current SportyBet Set ' + setNumber + ' winner market (202), specifier and selected player outcome are unavailable.' };
}

function findWinnerSelection(leg, event) {
  const pick = String(leg?.pick || '').toLowerCase();
  const sport = String(leg?.sport || '').toLowerCase();
  const selectedName = pick === 'p1' ? String(leg?.player_1 || '') :
    pick === 'p2' ? String(leg?.player_2 || '') : '';
  const selected = canonicalParticipant(selectedName);
  const home = canonicalParticipant(event?.homeTeamName);
  const away = canonicalParticipant(event?.awayTeamName);
  const participantMatches = sport === 'football' ? footballTeamNameMatches : participantNameMatches;
  const selectedIsHome = selected ? participantMatches(selectedName, event?.homeTeamName) : pick === 'p1';
  const selectedIsAway = selected ? participantMatches(selectedName, event?.awayTeamName) : pick === 'p2';

  if ((pick === 'p1' || pick === 'p2') && selected && !selectedIsHome && !selectedIsAway) {
    return { error: 'The selected tennis/football participant no longer matches the current SportyBet event.' };
  }

  const markets = Array.isArray(event?.markets) ? event.markets : [];
  for (const market of markets) {
    const id = String(market?.id || '');
    const desc = String(market?.desc || market?.name || market?.title || '').toLowerCase();
    const status = String(market?.status || '').trim().toLowerCase();
    const closed = /suspend|closed|inactive|settled|unavailable|stop/i.test(status) ||
      (status !== '' && /^\d+$/.test(status) && status !== '0');
    if (closed) continue;

    const isWinnerMarket = sport === 'tennis'
      ? ['186', '210'].includes(id) || /match winner|winner|to win/.test(desc)
      : id === '1' || /3.?way|1x2|match winner|winner/.test(desc);
    if (!isWinnerMarket) continue;

    const outcomes = Array.isArray(market?.outcomes) ? market.outcomes : [];
    const outcome = outcomes.find(o => {
      const rawName = String(o?.desc || o?.name || o?.title || '').trim();
      const name = canonicalParticipant(rawName);
      const active = o?.isActive == null ? o?.active !== false :
        (Number(o.isActive) === 1 || o.isActive === true);
      const odds = Number(o?.odds);
      if (!active || !String(o?.id || '') || !Number.isFinite(odds) || odds <= 1) return false;

      if (pick === 'draw') return /^(draw|x)$/.test(name);
      if (selected && participantNameMatches(selectedName, rawName)) return true;
      if (pick === 'p1' || pick === 'p2') {
        const homeLabel = /^(home|1|p1|player 1)$/.test(name);
        const awayLabel = /^(away|2|p2|player 2)$/.test(name);
        return (homeLabel && selectedIsHome) || (awayLabel && selectedIsAway);
      }
      return false;
    });
    if (!outcome) continue;

    return {
      eventId: event.eventId,
      marketId: String(market?.id || (sport === 'tennis' ? '186' : '1')),
      specifier: market?.specifier ?? null,
      outcomeId: String(outcome?.id || ''),
      outcomeName: String(outcome?.desc || outcome?.name || outcome?.title || ''),
      odds: Number(outcome?.odds)
    };
  }

  return { error: 'The exact current SportyBet winner market or selected player outcome is no longer available.' };
}
async function buildSelection(leg, event) {
  const product = productForLeg(leg);
  if (product === 'vfootball' || product === 'efootball') return findVirtualSelection(leg, event);

  const sport = String(leg?.sport || '').toLowerCase();
  const market = String(leg?.market || '').toLowerCase();
  // Keep final mapping aligned with currentSelectionForTarget: NBA winners
  // use the two-way 219 market; full-game totals remain on 225.
  // The direct-ID preflight and final share mapper must use the same
  // market-specific resolver so an NBA winner cannot fall back to O/U totals.
  if (sport === 'basketball') return market === 'winner'
    ? findBasketballWinnerSelection(leg,event)
    : findBasketballSelection(leg,event);
  if (sport === 'tennis' && market === 'set_winner') return findSetWinnerSelection(leg,event);
  if (market === 'total' && ['football','tennis'].includes(sport)) return findVirtualSelection(leg,event);
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
    const manualMode = body?.mode === 'manual' || Array.isArray(body?.manual_selections);
    const batchId = manualMode ? 'MANUAL-TICKET' : String(body?.batch_id || '').trim();
    // Bound catalogue discovery and the final share request for Builder and manual
    // tickets alike. This prevents a slow provider from exhausting the Pages request.
    const requestDeadlineAt = Date.now() + 22000;
    const catalogueDeadlineAt = Date.now() + 13000;
    let legs = [];

    if (manualMode) {
      const supplied = Array.isArray(body?.manual_selections) ? body.manual_selections : [];
      if (supplied.length < 2 || supplied.length > 20) {
        return json({ ok: false, error: 'INVALID_MANUAL_LEG_COUNT', message: 'A manual SportyBet slip needs 2–20 selections.' }, 422);
      }
      legs = supplied.map(item => ({
        event_id: String(item?.event_id || ''),
        sportybet_event_id: String(item?.sportybet_event_id || ''),
        sport: String(item?.sport || '').toLowerCase(),
        product: String(item?.product || '').toLowerCase(),
        market: String(item?.market || 'winner').toLowerCase(),
        pick: String(item?.pick || '').toLowerCase(),
        line: item?.line == null ? null : Number(item.line),
        market_id: String(item?.market_id || ''),
        set_number: item?.set_number == null ? null : Number(item.set_number),
        model_qualified: item?.model_qualified === true,
        start_time: String(item?.start_time || ''),
        player_1: String(item?.player_1 || ''),
        player_2: String(item?.player_2 || ''),
        match: String(item?.match || (String(item?.player_1 || '') + ' vs ' + String(item?.player_2 || '')))
      }));
      const ids = legs.map(leg => leg.event_id);
      const basketballProviderIds = legs.filter(leg => leg.sport === 'basketball').map(leg => leg.sportybet_event_id).filter(Boolean);
      if (new Set(basketballProviderIds).size !== basketballProviderIds.length || legs.some(leg => {
          if (!leg.event_id || !leg.player_1 || !leg.player_2) return true;
          if (leg.sport === 'basketball') {
            if (leg.market === 'winner') {
              return !['p1', 'p2'].includes(leg.pick) || leg.market_id !== '219' || !leg.sportybet_event_id;
            }
            return leg.market !== 'total' || !['over', 'under'].includes(leg.pick) ||
              !Number.isFinite(Number(leg.line)) || Number(leg.line) < 100 || Number(leg.line) > 300 ||
              leg.market_id !== '225';
          }
          const isEfootballLeg = leg.sport === 'efootball' ||
            (leg.sport === 'virtual' && productForLeg(leg) === 'efootball' && leg.market === 'virtual_total');
          if (isEfootballLeg) {
            return !['efootball_gt', 'efootball_adriatic'].includes(leg.product) ||
              productForLeg(leg) !== 'efootball' || !['total', 'virtual_total'].includes(leg.market) ||
              !['over', 'under'].includes(leg.pick) ||
              !Number.isFinite(Number(leg.line)) || Number(leg.line) <= 0 || Number(leg.line) > 1000 ||
              !['18', '189'].includes(String(leg.market_id)) || !leg.sportybet_event_id;
          }
          if (!['football', 'tennis'].includes(leg.sport)) return true;
          if (leg.market === 'set_winner') {
            return leg.sport !== 'tennis' || !['p1', 'p2'].includes(leg.pick) ||
              ![1, 2].includes(Number(leg.set_number)) || leg.market_id !== '202' ||
              !leg.sportybet_event_id;
          }
          if (leg.market === 'total') {
            const requiredMarketId = leg.sport === 'football' ? '18' : '189';
            return !['over', 'under'].includes(leg.pick) ||
              !Number.isFinite(Number(leg.line)) || Number(leg.line) <= 0 || Number(leg.line) > 1000 ||
              leg.market_id !== requiredMarketId;
          }
          return !['winner', '1x2'].includes(leg.market) ||
            !['p1', 'p2', 'draw'].includes(leg.pick) ||
            (leg.sport === 'tennis' && leg.pick === 'draw');
        }) ||
          ids.some(id => !id) || new Set(ids).size !== ids.length) {
        return json({ ok: false, error: 'INVALID_MANUAL_SELECTION', message: 'Manual tickets support Football/Tennis match winners, Tennis Set 1/Set 2 winners, exact totals, experimental eFootball GT/eAdriatic, NBA market-219 full-game winners (overtime included) and NBA market-225 totals. Every leg must still match a currently open SportyBet event, exact market scope, participant outcome and live odds.' }, 422);
      }
    } else {
      // Desk research batches remain subject to their existing Builder qualification gates.
      if (!/^(?:DESK-)?BATCH-[0-9]{2}$/.test(batchId)) {
        return json({ ok: false, error: 'INVALID_BATCH_ID' }, 400);
      }
      const builder = await loadBuilder(context);
      const batches = Array.isArray(builder?.batches) ? builder.batches : [];
      const batch = batches.find(item => String(item?.batch_id || '') === batchId);
      if (!batch) return json({ ok: false, error: 'BATCH_NOT_FOUND', batch_id: batchId }, 404);
      legs = Array.isArray(batch?.legs) ? batch.legs : [];
      if (!legs.length) return json({ ok: false, error: 'EMPTY_BATCH', batch_id: batchId }, 422);
    }
    if (legs.length > 20) {
      return json({ ok: false, error: 'TOO_MANY_SELECTIONS', message: 'SportyBet booking codes support at most 20 selections.' }, 422);
    }

    // If an NBA totals leg is present, the shared slip must remain all-or-nothing.
    // Never surface a share code for a mixed or partially accepted NBA ticket.
    const hasBasketballLeg = legs.some(leg => String(leg?.sport || '').toLowerCase() === 'basketball');
    const hasEfootballLeg = legs.some(leg => productForLeg(leg) === 'efootball');
    // Manual selections can be scheduled beyond the feed's seven-day default.
    // Keep the lookup bounded by SportyBet's supported 30-day catalogue window.
    const catalogueTimeline = manualMode ? ticketCatalogueTimeline(legs) : 168;
    let nbaReleaseContext = null;
    if (hasBasketballLeg && !manualMode) {
      // The automated NBA Builder remains locked to independent model-release
      // evidence. A user-created manual ticket is a different operation: it may
      // include an explicitly unqualified NBA selection only after the exact
      // current SportyBet event, market, line, both prices and kickoff are checked.
      try { nbaReleaseContext = await loadNbaReleaseContext(requestDeadlineAt); }
      catch (error) { return json({ ok: false, error: 'NBA_RELEASE_EVIDENCE_UNAVAILABLE', message: 'NBA release evidence could not be verified. No Builder ticket code was requested.' }, 503); }
      if (!nbaTotalsReleaseQualified(nbaReleaseContext.evidence, nbaReleaseContext.probability)) return json({ ok: false, error: 'NBA_RELEASE_GATE_LOCKED', booking_code_withheld: true, message: 'The independent NBA totals release gate has not passed. No Builder ticket code was requested.' }, 423);
    }
    // Started selections cannot be pre-match bookable. Avoid looking them up
    // as upcoming fixtures; final validation reports the precise reason.
    const lookupLegs = manualMode ? legs.filter(leg => {
      const start = Date.parse(String(leg?.start_time || ''));
      return !Number.isFinite(start) || start > Date.now();
    }) : legs;
    const virtualLegs = lookupLegs.filter(l => productForLeg(l) === 'vfootball');
    const efootballLegs = lookupLegs.filter(l => productForLeg(l) === 'efootball');
    const virtualIds = new Set(virtualLegs.map(l => String(l.event_id || '')).filter(Boolean));
    const efootballIds = new Set(efootballLegs.flatMap(l => [l.sportybet_event_id, l.event_id]).map(String).filter(Boolean));
    const footballLegs = lookupLegs.filter(l => String(l?.sport || '').toLowerCase() === 'football');
    const tennisLegs = lookupLegs.filter(l => String(l?.sport || '').toLowerCase() === 'tennis');
    const basketballLegs = lookupLegs.filter(l => String(l?.sport || '').toLowerCase() === 'basketball');
    const footballIds = new Set(footballLegs.map(l => String(l.sportybet_event_id || l.event_id || '')).filter(Boolean));
    const tennisIds = new Set(tennisLegs.map(l => String(l.sportybet_event_id || l.event_id || '')).filter(Boolean));
    const basketballIds = new Set(basketballLegs.flatMap(l => [l.sportybet_event_id, l.event_id]).map(String).filter(Boolean));

    const found = new Map();
    const sharedMatchedLegs = new Set();

    // First ask SportyBet for the exact stored provider event IDs. This is a
    // single-event details request and returns the complete live market list;
    // the expensive catalogue search is reserved for genuinely changed IDs.
    const directEvents = await collectCurrentEventsById(lookupLegs, catalogueDeadlineAt, sharedMatchedLegs);
    for (const [id, event] of directEvents) found.set(id, event);

    const unresolvedLegs = lookupLegs.filter(leg => !sharedMatchedLegs.has(leg));
    const unresolvedVirtualLegs = unresolvedLegs.filter(leg => productForLeg(leg) === 'vfootball');
    const unresolvedEfootballLegs = unresolvedLegs.filter(leg => productForLeg(leg) === 'efootball');
    const unresolvedFootballLegs = unresolvedLegs.filter(leg => String(leg?.sport || '').toLowerCase() === 'football');
    const unresolvedTennisLegs = unresolvedLegs.filter(leg => String(leg?.sport || '').toLowerCase() === 'tennis');
    const unresolvedBasketballLegs = unresolvedLegs.filter(leg => String(leg?.sport || '').toLowerCase() === 'basketball');
    const unresolvedVirtualIds = new Set(unresolvedVirtualLegs.map(leg => String(leg.event_id || '')).filter(Boolean));
    const unresolvedEfootballIds = new Set(unresolvedEfootballLegs.flatMap(leg => [leg.sportybet_event_id, leg.event_id]).map(String).filter(Boolean));
    const unresolvedFootballIds = new Set(unresolvedFootballLegs.map(leg => String(leg.sportybet_event_id || leg.event_id || '')).filter(Boolean));
    const unresolvedTennisIds = new Set(unresolvedTennisLegs.map(leg => String(leg.sportybet_event_id || leg.event_id || '')).filter(Boolean));
    const unresolvedBasketballIds = new Set(unresolvedBasketballLegs.flatMap(leg => [leg.sportybet_event_id, leg.event_id]).map(String).filter(Boolean));

    // Only changed/missing IDs go to the bounded alias search. Sources run in
    // parallel and share exact-match state, preventing redundant page scans.
    const allVirtualIds = new Set([...unresolvedVirtualIds, ...unresolvedEfootballIds]);
    const allVirtualLegs = [...unresolvedVirtualLegs, ...unresolvedEfootballLegs];
    const fastVirtualFeedDeadline = Math.min(catalogueDeadlineAt, Date.now() + 8000);

    const [
      vfootballEvents,
      efootballEvents,
      liveFeedEvents,
      footballEvents,
      tennisEvents,
      basketballEvents
    ] = await Promise.all([
      unresolvedVirtualLegs.length
        ? collectEvents({
            sportId: 'sr:sport:202120001',
            marketId: '1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
            timeline: catalogueTimeline,
            primaryPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents',
            fallbackPath: '/api/ng/factsCenter/pcUpcomingEvents',
            maxPages: manualMode ? 20 : 5,
            deadlineAt: catalogueDeadlineAt,
            requestTimeoutMs: manualMode ? 3000 : 6000,
            pageBatchSize: manualMode ? 10 : 5,
            sharedMatchedLegs
          }, unresolvedVirtualIds, unresolvedVirtualLegs)
        : Promise.resolve(new Map()),
      unresolvedEfootballLegs.length
        ? collectEvents({
            sportId: 'sr:sport:137',
            marketId: '1,18,10,29,11,26,36,14,60100,186,189,202,204,210',
            timeline: catalogueTimeline,
            maxPages: manualMode ? 20 : 5,
            deadlineAt: catalogueDeadlineAt,
            requestTimeoutMs: manualMode ? 3000 : 6000,
            pageBatchSize: manualMode ? 10 : 5,
            sharedMatchedLegs
          }, unresolvedEfootballIds, unresolvedEfootballLegs)
        : Promise.resolve(new Map()),
      allVirtualLegs.length
        ? collectVirtualEventsFromLiveFeed(
            context, allVirtualIds, 'efootball,vfootball',
            fastVirtualFeedDeadline, allVirtualLegs, catalogueTimeline, sharedMatchedLegs
          )
        : Promise.resolve(new Map()),
      unresolvedFootballLegs.length
        ? collectEvents({
            sportId: 'sr:sport:1',
            marketId: '1,18,10,14,16,29,45,47',
            timeline: catalogueTimeline,
            maxPages: manualMode ? 20 : 5,
            primaryPath: '/api/ng/factsCenter/pcUpcomingEvents',
            fallbackPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents',
            deadlineAt: catalogueDeadlineAt,
            requestTimeoutMs: manualMode ? 3000 : 6000,
            pageBatchSize: manualMode ? 10 : 5,
            sharedMatchedLegs
          }, unresolvedFootballIds, unresolvedFootballLegs)
        : Promise.resolve(new Map()),
      unresolvedTennisLegs.length
        ? collectEvents({
            sportId: 'sr:sport:5',
            marketId: '186,210,202,204,189,203,188,187',
            timeline: catalogueTimeline,
            fallbackPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents',
            maxPages: manualMode ? 20 : 5,
            deadlineAt: catalogueDeadlineAt,
            requestTimeoutMs: manualMode ? 3000 : 6000,
            pageBatchSize: manualMode ? 10 : 5,
            sharedMatchedLegs
          }, unresolvedTennisIds, unresolvedTennisLegs)
        : Promise.resolve(new Map()),
      unresolvedBasketballLegs.length
        ? collectBasketballEvents(context, unresolvedBasketballIds, catalogueTimeline, unresolvedBasketballLegs, catalogueDeadlineAt)
        : Promise.resolve(new Map())
    ]);

    for (const [id, event] of vfootballEvents) found.set(id, event);
    for (const [id, event] of efootballEvents) found.set(id, event);

    // Prefer normalized virtual prices when the exact O/U ladder is present;
    // retain catalogue rows only when the normalized representation lacks it.
    for (const [id, event] of liveFeedEvents) {
      const current = found.get(id);
      const hasOu = Array.isArray(event?.markets) && event.markets.some(m => {
        const desc = String(m?.desc || m?.name || m?.title || m?.specifier || '').toLowerCase();
        return String(m?.id || '') === '18' || String(m?.id || '') === '189' || /over.?under|total|\\bou\\b/.test(desc);
      });
      if (!current || hasOu) found.set(id, event);
    }
    for (const [id, event] of footballEvents) found.set(id, event);
    for (const [id, event] of tennisEvents) found.set(id, event);
    for (const [id, event] of basketballEvents) found.set(id, event);
    const selections = [];
    const validation = [];
    for (const leg of legs) {
      const eventId = String(leg?.event_id || '');
      if (manualMode) {
        const requestedStart = Date.parse(String(leg?.start_time || ''));
        if (!Number.isFinite(requestedStart)) {
          validation.push(validationFailure(leg, 'Fixture start time is missing or invalid; refresh this selection.'));
          continue;
        }
        if (requestedStart <= Date.now()) {
          validation.push(validationFailure(leg, 'Fixture start time has passed; pre-match SportyBet booking is closed.'));
          continue;
        }
      }
      const resolved = resolveCurrentEvent(leg, found);
      const event = resolved.event;
      if (!event) {
        validation.push(validationFailure(leg, 'Event is no longer present in SportyBet current catalogue.'));
        continue;
      }
      if (manualMode) {
        const requestedStart = Date.parse(String(leg?.start_time || ''));
        const currentStart = Number(event?.estimateStartTime || 0);
        const namesMatch = legParticipantPairMatches(leg, event);
        if (!namesMatch || !leg.player_1 || !leg.player_2 || canonicalParticipant(leg.player_1) === canonicalParticipant(leg.player_2)) {
          validation.push(validationFailure(leg, 'Participant identity changed in SportyBet current catalogue.'));
          continue;
        }
        if (Number.isFinite(requestedStart) && currentStart &&
            Math.abs(requestedStart - currentStart) > 45 * 60 * 1000) {
          validation.push(validationFailure(leg, 'Fixture start time changed by more than 45 minutes; refresh the slip.'));
          continue;
        }
      }
      if (!isOpenEvent(event)) {
        validation.push(validationFailure(leg, 'Event has started or SportyBet has closed pre-match booking.'));
        continue;
      }

      const selection = await buildSelection(leg, event);
      if (selection?.error || !selection?.marketId || !selection?.outcomeId) {
        validation.push(validationFailure(leg, selection?.error || 'Selection could not be mapped to a live SportyBet market.'));
        continue;
      }
      let nbaQualification = null;
      const basketballLeg = String(leg?.sport || '').toLowerCase() === 'basketball';
      if (basketballLeg && !manualMode) {
        nbaQualification = nbaTotalTicketLegQualified(leg, selection, nbaReleaseContext);
        if (!nbaQualification.ok) { validation.push(validationFailure(leg, nbaQualification.reason)); continue; }
      }
      if (basketballLeg && manualMode) {
        // Manual basketball selections remain independent of the totals release
        // gate, but the exact market and both live outcomes must still be fresh.
        const quoteAt = Date.parse(String(selection?.fetchedAt || ''));
        const requestedStart = Date.parse(String(leg?.start_time || ''));
        const isWinner = leg.market === 'winner';
        const expectedMarket = isWinner ? '219' : '225';
        const pricesComplete = isWinner
          ? Number.isFinite(Number(selection?.homeOdds)) && Number(selection.homeOdds) > 1 &&
            Number.isFinite(Number(selection?.awayOdds)) && Number(selection.awayOdds) > 1
          : Number.isFinite(Number(selection?.overOdds)) && Number(selection.overOdds) > 1 &&
            Number.isFinite(Number(selection?.underOdds)) && Number(selection.underOdds) > 1;
        if (!Number.isFinite(quoteAt) || quoteAt > Date.now() + 120000 ||
            Date.now() - quoteAt > 15 * 60 * 1000 || !Number.isFinite(requestedStart) ||
            quoteAt >= requestedStart || String(selection?.marketId || '') !== expectedMarket ||
            String(selection?.sportybetEventId || selection?.eventId || '') !== String(event?.eventId || '') ||
            !pricesComplete || !Number.isFinite(Number(selection?.odds)) || Number(selection.odds) <= 1) {
          validation.push(validationFailure(leg, 'Current SportyBet NBA market quote is stale or incomplete; refresh this basketball selection.'));
          continue;
        }
      }
      selections.push(selection);
      validation.push({event_id:eventId,ok:true,resolved_by:resolved.matched_by,resolved_event_id:event.eventId,market_id:selection.marketId,outcome_id:selection.outcomeId,specifier:selection.specifier,outcome:selection.outcomeName,current_odds:selection.odds,current_line:selection.line??null,current_over_odds:selection.overOdds??null,current_under_odds:selection.underOdds??null,current_home_odds:selection.homeOdds??null,current_away_odds:selection.awayOdds??null,publication_snapshot_id:nbaQualification?.snapshot_id||null});
    }

    const preExcluded = validation.filter(item => item.ok !== true);
    // Manual tickets form one shared slip across every sport. Never return a
    // reduced football/tennis code while rejecting NBA/eFootball partial slips.
    // Automated Builder batches retain their separate qualification policy.
    if (manualMode && preExcluded.length > 0) {
      return json({
        ok: false,
        error: "MANUAL_TICKET_REJECTED_PARTIAL",
        message: "At least one selection failed current SportyBet validation. The entire manual ticket was rejected and no share code was requested. Refresh every leg and try again.",
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        excluded_count: preExcluded.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
    if (hasBasketballLeg && preExcluded.length > 0) {
      return json({
        ok: false,
        error: 'BASKETBALL_SLIP_REJECTED_PARTIAL',
        message: 'At least one NBA leg failed current SportyBet validation. No booking code was created or returned. Refresh the whole ticket and validate every leg again.',
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        excluded_count: preExcluded.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
    if (hasEfootballLeg && preExcluded.length > 0) {
      return json({
        ok: false,
        error: 'EFOOTBALL_SLIP_REJECTED_PARTIAL',
        message: 'At least one eFootball leg failed current SportyBet validation. No share code was created. Refresh the whole ticket and add the current qualified selections again.',
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        excluded_count: preExcluded.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
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

    // Match Signal deliberately supports the Builder's 2–4 leg research
    // construction. SportyBet's share endpoint can return a valid code for a
    // two-selection slip, so do not discard a valid 2-leg batch here.
    if (selections.length < 2) {
      return json({
        ok: false,
        error: 'TOO_FEW_AVAILABLE_SELECTIONS',
        batch_id: batchId,
        message: 'Fewer than two valid selections remain available on SportyBet.',
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

    const shareResult = await requestSportyBetShare(selections, { deadlineAt: requestDeadlineAt, timeoutMs: manualMode ? 6500 : 9000 });
    if (shareResult.error) {
      return json({
        ok: false,
        error: shareResult.error,
        message: shareResult.message,
        attempts: shareResult.attempts
      }, 502);
    }
    const share = shareResult.payload;
    if (shareResult.status < 200 || shareResult.status >= 300) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_HTTP_' + shareResult.status,
        message: String(share?.message || share?.detail || share?.error || 'SportyBet rejected the share request.'),
        content_type: shareResult.contentType
      }, shareResult.status >= 400 && shareResult.status < 500 ? 409 : 502);
    }
    if (share?.bizCode != null && Number(share.bizCode) !== 10000) {
      return json({
        ok: false,
        error: 'SPORTYBET_BOOKING_REJECTED',
        biz_code: share.bizCode,
        message: String(share?.message || share?.detail || 'SportyBet rejected the requested selections.')
      }, 409);
    }

    const data = share?.data;
    const shareCode = String(data?.shareCode || '').trim().toUpperCase();
    const unavailable = Array.isArray(data?.unavailableOutcomes) ? data.unavailableOutcomes : [];
    const acceptedOutcomes = Array.isArray(data?.outcomes) ? data.outcomes : [];
    const acceptedCount = acceptedOutcomes.length || Math.max(0, selections.length - unavailable.length);
    // All manual sports use the same provider-acceptance rule: SportyBet must
    // accept the complete requested set or Match Signal withholds the code.
    if (manualMode && (
      unavailable.length > 0 ||
      acceptedCount !== legs.length ||
      (acceptedOutcomes.length > 0 && acceptedOutcomes.length !== selections.length)
    )) {
      return json({
        ok: false,
        error: "MANUAL_TICKET_REJECTED_PARTIAL",
        message: "SportyBet accepted only part of this manual ticket. Match Signal has withheld the share code; refresh and rebuild the entire ticket.",
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        accepted_selection_count: acceptedCount,
        unavailable_count: unavailable.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
    if (hasBasketballLeg && (
      unavailable.length > 0 ||
      acceptedCount !== legs.length ||
      (acceptedOutcomes.length > 0 && acceptedOutcomes.length !== selections.length)
    )) {
      return json({
        ok: false,
        error: 'BASKETBALL_SLIP_REJECTED_PARTIAL',
        message: 'SportyBet accepted only part of this NBA-containing ticket. Match Signal has withheld the share code; refresh and rebuild the entire ticket.',
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        accepted_selection_count: acceptedCount,
        unavailable_count: unavailable.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
    if (hasEfootballLeg && (
      unavailable.length > 0 ||
      acceptedCount !== legs.length ||
      (acceptedOutcomes.length > 0 && acceptedOutcomes.length !== selections.length)
    )) {
      return json({
        ok: false,
        error: 'EFOOTBALL_SLIP_REJECTED_PARTIAL',
        message: 'SportyBet accepted only part of this eFootball-containing ticket. Match Signal has withheld the share code; refresh and rebuild the entire ticket.',
        batch_id: batchId,
        initial_selection_count: legs.length,
        requested_selection_count: selections.length,
        accepted_selection_count: acceptedCount,
        unavailable_count: unavailable.length,
        booking_code_withheld: true,
        validation
      }, 409);
    }
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
// Production rollout trigger: alias-aware, parallel current-catalogue booking lookup (2026-11-08).
// Production rollout trigger: provider-ID-first direct market lookup is regression-tested (2026-11-08).
// Production retry trigger: NBA projection artifact refreshed and passed six-hour guard (2026-11-08).
