import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../sport-hubs.js", import.meta.url), "utf8");
const entryPages = await Promise.all(["../index.html", "../upcoming.html", "../qualified-best.html"].map(path =>
  readFile(new URL(path, import.meta.url), "utf8")
));
const headerRules = await readFile(new URL("../_headers", import.meta.url), "utf8");
assert.match(headerRules,/\/upcoming\.html\s*\n\s*Cache-Control:\s*no-store, no-cache, must-revalidate, max-age=0/,"the Upcoming entry HTML must not remain cached after a renderer deployment");
assert.match(headerRules,/\/qualified-best\.html\s*\n\s*Cache-Control:\s*no-store, no-cache, must-revalidate, max-age=0/,"the standalone Qualified Best HTML must not remain cached after a renderer deployment");
const rendererVersions = entryPages.map(html =>
  html.match(/<script src=["']\.\/sport-hubs\.js\?v=([^"']+)["']/)?.[1] || null
);
assert.ok(rendererVersions.every(Boolean), "both Upcoming entry pages must load a versioned Prediction Desk renderer");
assert.equal(rendererVersions[0], rendererVersions[1], "root and /upcoming.html must use the same renderer cache key");
assert.ok(rendererVersions.every(version=>version===rendererVersions[0]), "the dedicated Qualified Best page must use the shared renderer cache key");
assert.match(entryPages[2],/data-page="qualified-best"/,"Qualified Best has a dedicated rendering mode");
assert.match(entryPages[2],/id="qualifiedBestLastSeenBoard"/,"the dedicated page exposes its last-seen, not-current section");
assert.notEqual(rendererVersions[0], "20261013-qualified-best-standalone-lastseen2-full-list", "the script cache key must change when the renderer fix changes");
assert.notEqual(rendererVersions[0], "20261012-qualified-best-snapshot-scope2", "the script cache key must change when last-good snapshot behavior changes");
assert.notEqual(rendererVersions[0], "20261013-qualified-best-kickoff-sort1", "the script cache key must change when live qualification diagnostics are added");
assert.match(source,/window\.__MATCH_SIGNAL_QUALIFIED_BEST_MONITOR__=\{/, "the real desk gate must emit structured monitor diagnostics");
assert.match(source,/stage:virtualQuoteRefreshState==="pending"\?"checking":"completed"/, "the monitor must distinguish a still-running quote check from a completed check");
assert.match(source,/source_fallback_used:sourceFallbackUsed/, "synthetic source-fallback timestamps cannot certify production health");
assert.match(source,/current_qualified_count:best\.rows\.length/, "monitor counts must come from the actual Qualified Best output");
assert.match(source,/stage:"failed"/, "renderer exceptions must be reported as monitor failures");
assert.match(source,/let virtualQuoteRefreshState="pending"/,"Virtual/eFootball starts in an explicit verification state");
assert.match(source,/virtualQuoteRefreshState==="complete"\)return true/,"only a complete snapshot can admit all Virtual/eFootball rows");
assert.match(source,/\(virtualQuoteRefreshState==="partial"\|\|virtualQuoteRefreshState==="cached"\)&&\s*x\.desk_quote_refresh==="fresh_exact_event_line_side"/,"partial or reused snapshots only admit rows with exact verified event/line/side quotes");
assert.match(source,/snapshot-level qualified fixtures/,"empty Qualified Best explains when saved snapshot rows fail current verification");
assert.match(source,/refreshVirtualQuoteData\(\)\.then\(snapshot=>/,"the redraw is driven by quote snapshot completeness");
assert.match(source,/function isRequiredVirtualQuoteRow\(row,now=Date\.now\(\)\)/,"snapshot completeness has a distinct shortlist-eligibility predicate");
assert.match(source,/filter\(row=>isRequiredVirtualQuoteRow\(row,quoteNow\)\)/,"only required shortlist rows can block snapshot completion");
assert.match(source,/const requiredQuoteRows=virtualCandidates\.filter\(row=>isRequiredVirtualQuoteRow\(row,Date\.now\(\)\)\)/,"the completeness check uses only model-qualified candidates inside the live quote window");
assert.doesNotMatch(source,/const requiredQuoteRows=\[\.\.\.all,\.\.\.virtualCandidates\]/,"unified-board research rows cannot block Qualified Best snapshot completeness");
assert.match(source,/api\/sportybet-virtual\?sources=efootball&pageSize=100&pageNum=/,"Upcoming quote refresh queries only active eFootball markets");
assert.match(source,/let lastVerifiedVirtualQuoteSnapshot=null/,"the last complete snapshot persists across board rerenders");
assert.match(source,/const qualifiedBestDisplayLimit=qualifiedOnly\?40:12/,"the dedicated page must show the full qualified shortlist while Upcoming remains compact");
assert.match(source,/const lastSeenDisplayLimit=qualifiedOnly\?40:12/,"the dedicated last-seen page must show the full retained shortlist");

assert.match(source,/usedLastGoodSnapshot:true/,"a partial refresh can reuse the last complete verified snapshot");
assert.match(source,/holdVerifiedBoardDuringRefresh/,"the previously verified shortlist remains visible while the next refresh is pending");
assert.match(source,/lastVerifiedVirtualSnapshotUsable\(lastVerifiedVirtualQuoteSnapshot,Date\.now\(\)\)/,"the cache reuse path is guarded by the last-snapshot freshness limit");
assert.match(source,/loadLastVerifiedVirtualQuoteSnapshot\(window\.localStorage,Date\.now\(\)\)/,"a still-fresh complete snapshot can survive a page reload in the same browser storage");
assert.match(source,/persistLastVerifiedVirtualQuoteSnapshot\(lastVerifiedVirtualQuoteSnapshot\)/,"only successfully complete snapshots are persisted");
assert.match(source,/for\(let attempt=1;attempt<=2;attempt\+\+\)/,"an individual transient quote-page failure is retried once before the refresh is marked incomplete");
assert.match(source,/live_quote_missing_required_rows:virtualQuoteMissingRequiredRows/,"monitor diagnostics expose unmatched required quote rows");
assert.match(source,/live_quote_retried_pages:virtualQuoteRetriedPages/,"monitor diagnostics expose which pages needed a retry");

// Persisted last-good quote snapshots may bridge a reload, but the same 15-minute
// verification ceiling applies and incomplete snapshots are never cached as good.
const cacheStart = source.indexOf("const QUALIFIED_BEST_LAST_GOOD_QUOTES_STORAGE_KEY=");
const cacheEnd = source.indexOf("function rowFixtureKey(", cacheStart);
assert.ok(cacheStart >= 0 && cacheEnd > cacheStart, "last-good snapshot persistence helpers are extractable");
const stored = new Map();
const mockStorage = {
  getItem: key => stored.has(key) ? stored.get(key) : null,
  setItem: (key, value) => stored.set(key, String(value)),
  removeItem: key => stored.delete(key)
};
const cacheSandbox = { Date, JSON, Object, Number, Math, window: { localStorage: mockStorage } };
vm.createContext(cacheSandbox);
vm.runInContext(
  source.slice(cacheStart, cacheEnd) +
    "\n;globalThis.__quoteCacheApi={QUALIFIED_BEST_LAST_GOOD_QUOTES_STORAGE_KEY,loadLastVerifiedVirtualQuoteSnapshot,persistLastVerifiedVirtualQuoteSnapshot,lastVerifiedVirtualSnapshotUsable};",
  cacheSandbox,
  { filename: "sport-hubs.js#last-good-quote-storage" }
);
const quoteCacheApi = cacheSandbox.__quoteCacheApi;
const quoteCacheNow = Date.now();
const verifiedCache = {
  snapshotAvailable: true,
  snapshotComplete: true,
  verifiedAt: quoteCacheNow,
  byEvent: { "quote-cache-event": [{ event_id: "quote-cache-event", __quote_fetched_at: new Date(quoteCacheNow).toISOString() }] }
};
assert.equal(quoteCacheApi.persistLastVerifiedVirtualQuoteSnapshot(verifiedCache, mockStorage), true, "complete fresh snapshots can be persisted");
const loadedCache = quoteCacheApi.loadLastVerifiedVirtualQuoteSnapshot(mockStorage, quoteCacheNow);
assert.equal(loadedCache.verifiedAt, quoteCacheNow, "a page reload can restore the still-fresh snapshot");
assert.equal(quoteCacheApi.persistLastVerifiedVirtualQuoteSnapshot({ ...verifiedCache, snapshotComplete: false }, mockStorage), false, "partial snapshots are never persisted as last-good");
mockStorage.setItem(quoteCacheApi.QUALIFIED_BEST_LAST_GOOD_QUOTES_STORAGE_KEY, JSON.stringify({
  ...verifiedCache,
  verifiedAt: quoteCacheNow - 16 * 60 * 1000
}));
assert.equal(quoteCacheApi.loadLastVerifiedVirtualQuoteSnapshot(mockStorage, quoteCacheNow), null, "snapshots older than 15 minutes are purged");
assert.equal(mockStorage.getItem(quoteCacheApi.QUALIFIED_BEST_LAST_GOOD_QUOTES_STORAGE_KEY), null, "expired snapshot storage is removed");

const start = source.indexOf("function isOverUnderPrediction(x){");
const end = source.indexOf("function ladderAnchor(rows){", start);
assert.ok(start >= 0 && end > start, "production desk gate functions are extractable");

const sandbox = { Date, Number, String, Math, Array, Boolean, Object, Map, Set, RegExp };
vm.createContext(sandbox);
vm.runInContext(
  source.slice(start, end) +
    "\n;globalThis.__deskTestApi={exactVirtualMarketLine,exactSportyBetQuote,exactMarketEdge,exactMarketExpectedReturn,qualificationState,primaryPrediction,qualifiedBestSelections,unmatchedVirtualQuoteUpdate,rawProbabilityValue,probabilityCalibrationInfo,probabilityValue,displayedFairOddsValue,isVirtualDeskCandidate,isRequiredVirtualQuoteRow,lastVerifiedVirtualSnapshotUsable,qualifiedBestSourceIsFresh,qualifiedBestLastSeenSnapshotUsable,qualifiedBestLastSeenRows,virtualCandidateStatus,sameVirtualEvent,virtualSnapshotHasCompleteFirstPage};",
  sandbox,
  { filename: "sport-hubs.js#prediction-desk-gates" }
);
const { exactVirtualMarketLine, exactMarketEdge, qualificationState, primaryPrediction, qualifiedBestSelections, unmatchedVirtualQuoteUpdate, rawProbabilityValue, probabilityCalibrationInfo, probabilityValue, displayedFairOddsValue, exactMarketExpectedReturn, isVirtualDeskCandidate, isRequiredVirtualQuoteRow, lastVerifiedVirtualSnapshotUsable, qualifiedBestSourceIsFresh, qualifiedBestLastSeenSnapshotUsable, qualifiedBestLastSeenRows, virtualCandidateStatus, sameVirtualEvent, virtualSnapshotHasCompleteFirstPage } = sandbox.__deskTestApi;

const lastKnownQuote = {
  event_id: "virtual-keep-last-quote",
  market_odds_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  odds_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  bookmaker_odds: 1.92
};
const partialSnapshot = unmatchedVirtualQuoteUpdate(lastKnownQuote, {snapshotAvailable:true, snapshotComplete:false});
assert.equal(partialSnapshot.market_odds_timestamp, lastKnownQuote.market_odds_timestamp, "partial snapshot preserves last quote timestamp");
assert.equal(partialSnapshot.odds_timestamp, lastKnownQuote.odds_timestamp, "partial snapshot preserves legacy timestamp");
assert.equal(partialSnapshot.desk_quote_refresh, "live_quote_snapshot_incomplete_previous_quote_preserved");
const unavailableSnapshot = unmatchedVirtualQuoteUpdate(lastKnownQuote, {snapshotAvailable:false, snapshotComplete:false});
assert.equal(unavailableSnapshot.market_odds_timestamp, lastKnownQuote.market_odds_timestamp, "failed live request preserves timestamp");
const completeSnapshot = unmatchedVirtualQuoteUpdate(lastKnownQuote, {snapshotAvailable:true, snapshotComplete:true});
assert.equal(completeSnapshot.market_odds_timestamp, null, "only a complete snapshot invalidates an unmatched quote");
assert.equal(completeSnapshot.odds_timestamp, null, "complete unmatched snapshot clears both timestamps");

function row(overrides = {}) {
  return {
    event_id: "fixture-1",
    start_time: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    sport: "football",
    league: "Regression Cup",
    player_1: "Alpha",
    player_2: "Beta",
    market: "over_under",
    line: 2.5,
    pick: "over",
    probability: 0.65,
    betting_qualified: true,
    qualified_for_builder: false,
    qualification_status: "BETTING_QUALIFIED_PAPER",
    bookmaker_odds: 1.9,
    sportybet_odds: 1.9,
    sportybet_odds_market: "total",
    sportybet_odds_line: 2.5,
    sportybet_odds_side: "over",
    sportybet_over_odds: 1.9,
    sportybet_under_odds: 2.0,
    market_odds_timestamp: new Date(Date.now() - 60 * 1000).toISOString(),
    ...overrides
  };
}


// Snapshot completeness must mirror the live qualified-shortlist scope, not
// demand exact matches for every high-probability research projection.
const scopeNow = Date.now();
const requiredVirtual = row({
  sport: "virtual",
  product: "efootball_gt",
  event_id: "efootball-qualified-required",
  start_time: new Date(scopeNow + 2 * 60 * 60 * 1000).toISOString(),
  line: 7.5,
  pick: "under",
  qualification_status: "BETTING_QUALIFIED_PAPER",
  betting_qualified: true,
  qualified_for_builder: true
});
assert.equal(isRequiredVirtualQuoteRow(requiredVirtual, scopeNow), true, "a model-qualified active eFootball row inside the seven-day feed window is required");

const highEstimateResearch = {
  ...requiredVirtual,
  qualification_status: "MODEL_90_PLUS",
  candidate_status: "MODEL_90_PLUS",
  betting_qualified: false,
  qualified_for_builder: false
};
assert.equal(isRequiredVirtualQuoteRow(highEstimateResearch, scopeNow), false, "a high-probability research row cannot hold Qualified Best snapshot completeness");

const pendingQualifiedFlag = {
  ...requiredVirtual,
  qualification_status: "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING",
  candidate_status: "BETTING_QUALIFIED_PAPER"
};
assert.equal(isRequiredVirtualQuoteRow(pendingQualifiedFlag, scopeNow), false, "a pending model gate remains excluded even when upstream flags conflict");

const outsideLiveWindow = {
  ...requiredVirtual,
  start_time: new Date(scopeNow + 8 * 24 * 60 * 60 * 1000).toISOString()
};
assert.equal(isRequiredVirtualQuoteRow(outsideLiveWindow, scopeNow), false, "a candidate outside the SportyBet 168-hour feed window cannot block completion");

const inactiveVirtualProduct = { ...requiredVirtual, product: "vfootball" };
assert.equal(isRequiredVirtualQuoteRow(inactiveVirtualProduct, scopeNow), false, "inactive VFootball research cannot block active eFootball snapshot completion");

const missingProbability = {
  ...requiredVirtual,
  probability: null,
  model_probability: null,
  confidence: null
};
assert.equal(isRequiredVirtualQuoteRow(missingProbability, scopeNow), false, "a row without a usable model probability cannot block quote snapshot completion");

const cacheNow = Date.now();
const recentCompleteSnapshot = {
  snapshotAvailable: true,
  snapshotComplete: true,
  verifiedAt: cacheNow - 4 * 60 * 1000,
  byEvent: { "efootball-event": [{ event_id: "efootball-event" }] }
};
assert.equal(lastVerifiedVirtualSnapshotUsable(recentCompleteSnapshot, cacheNow), true, "a complete prior snapshot can bridge a transient refresh while within 15 minutes");
assert.equal(lastVerifiedVirtualSnapshotUsable({
  ...recentCompleteSnapshot,
  verifiedAt: cacheNow - 16 * 60 * 1000
}, cacheNow), false, "a prior snapshot older than 15 minutes can never keep picks qualified");
assert.equal(lastVerifiedVirtualSnapshotUsable({
  ...recentCompleteSnapshot,
  snapshotComplete: false
}, cacheNow), false, "an incomplete snapshot can never become the reusable last-good snapshot");
assert.equal(lastVerifiedVirtualSnapshotUsable({
  ...recentCompleteSnapshot,
  byEvent: {}
}, cacheNow), false, "an empty event map is not a reusable verified snapshot");
assert.equal(lastVerifiedVirtualSnapshotUsable({
  ...recentCompleteSnapshot,
  verifiedAt: cacheNow + 3 * 60 * 1000
}, cacheNow), false, "a future-dated verification cannot be reused");
const sourceNow=Date.now();
assert.equal(qualifiedBestSourceIsFresh(new Date(sourceNow-29*60*1000).toISOString(),sourceNow),true,"a source artifact under 30 minutes can be evaluated for current picks");
assert.equal(qualifiedBestSourceIsFresh(new Date(sourceNow-31*60*1000).toISOString(),sourceNow),false,"stale source artifacts cannot certify current picks");
assert.equal(qualifiedBestSourceIsFresh(null,sourceNow),false,"missing source timestamps fail closed");
assert.equal(qualifiedBestSourceIsFresh(new Date(sourceNow+5*60*1000).toISOString(),sourceNow),false,"future-skewed source timestamps fail closed");
assert.match(source,/const sourceDataFresh=qualifiedBestSourceIsFresh\(generatedAt,now\.getTime\(\)\);\s*\/\/ A partial snapshot/ ,"source freshness must gate the current qualification list before it is evaluated");
const lastSeenNow=Date.now();
const futureLastSeen=row({
  event_id:"last-seen-future-event",
  start_time:new Date(lastSeenNow+3*60*60*1000).toISOString(),
  sport:"virtual",product:"efootball_gt",player_1:"Gamer One",player_2:"Gamer Two",
  market_odds_timestamp:new Date(lastSeenNow-25*60*1000).toISOString(),
  last_seen_at:new Date(lastSeenNow-25*60*1000).toISOString()
});
const pastLastSeen={...futureLastSeen,event_id:"last-seen-past-event",start_time:new Date(lastSeenNow-1*60*1000).toISOString()};
const lastSeenSnapshot={savedAt:lastSeenNow-25*60*1000,rows:[futureLastSeen,pastLastSeen]};
assert.equal(qualifiedBestLastSeenSnapshotUsable(lastSeenSnapshot,lastSeenNow),true,"a recent display-only snapshot survives beyond the 15-minute live-quote limit");
assert.equal(qualifiedBestLastSeenSnapshotUsable({...lastSeenSnapshot,savedAt:lastSeenNow-25*60*60*1000},lastSeenNow),false,"a last-seen snapshot expires after 24 hours");
assert.equal(qualifiedBestLastSeenRows(lastSeenSnapshot,lastSeenNow,[]).length,1,"last-seen output retains future fixtures but removes fixtures whose kickoff has passed");
assert.equal(qualifiedBestLastSeenRows(lastSeenSnapshot,lastSeenNow,[futureLastSeen]).length,0,"a currently qualified row is not duplicated in the last-seen panel");

const valid = row();
assert.equal(qualificationState(valid).currentPricePass, true, "fresh exact-line value can pass");

// A positive model-vs-no-vig edge alone can still have negative expected return
// at the actual offered odds. Qualified Best must require BOTH checks.
const positiveMarketEdgeNegativeEV = row({
  probability: 0.65,
  bookmaker_odds: 1.42,
  sportybet_odds: 1.42,
  sportybet_over_odds: 1.42,
  sportybet_under_odds: 2.35,
  sportybet_odds_side: "over"
});
const quotedPrice = { odds: 1.42 };
assert.ok(exactMarketEdge(positiveMarketEdgeNegativeEV, quotedPrice) >= 0.02, "fixture demonstrates a >=2% edge versus de-vigged market");
assert.ok(exactMarketExpectedReturn(positiveMarketEdgeNegativeEV, quotedPrice) < 0, "same estimate has negative expected return at offered odds");
assert.equal(qualificationState(positiveMarketEdgeNegativeEV).currentPricePass, false, "a market edge cannot override negative price EV");
assert.equal(qualificationState(positiveMarketEdgeNegativeEV).reason, "CURRENT_PRICE_EV_BELOW_2_PERCENT");
assert.equal(qualifiedBestSelections([positiveMarketEdgeNegativeEV], Date.now()).rows.length, 0, "negative-EV selection must not enter Qualified Best");

const profitablePrice = row({
  probability: 0.65,
  bookmaker_odds: 1.9,
  sportybet_odds: 1.9,
  sportybet_over_odds: 1.9,
  sportybet_under_odds: 2.0,
  sportybet_odds_side: "over"
});
assert.ok(exactMarketExpectedReturn(profitablePrice, { odds: 1.9 }) >= 0.02, "positive expected-return example clears the economic threshold");
assert.equal(qualificationState(profitablePrice).currentPricePass, true, "selection must pass both value gates");

// A flag or candidate label must not override an explicit watch/not-qualified status.
const watchOnly = row({
  qualification_status: "TENNIS_FORWARD_WATCH_NOT_QUALIFIED",
  candidate_status: "BETTING_QUALIFIED_PAPER",
  betting_qualified: true,
  qualified_for_builder: true
});
assert.equal(qualificationState(watchOnly).modelQualified, false, "watch status vetoes model qualification");
assert.equal(qualificationState(watchOnly).currentPricePass, false, "watch status cannot enter the qualified list");
assert.equal(qualificationState(watchOnly).reason, "EXPLICIT_QUALIFICATION_VETO");

// Long ordinary status strings must not trigger catastrophic backtracking in the veto detector.
const longHarmlessStatus = row({
  qualification_status: "BETTING_QUALIFIED_PAPER",
  candidate_status: "CANDIDATE_".repeat(80) + "READY",
  betting_qualified: true,
  qualified_for_builder: true
});
assert.equal(qualificationState(longHarmlessStatus).modelQualified, true, "long non-pending status text must not veto a genuinely qualified model row");

// A qualified row without candidate_status must not become "MODEL_RESEARCH"
 // simply because its candidate_group describes research provenance.
assert.equal(
  virtualCandidateStatus({
    candidate_group: "efootball_exact_research",
    qualification_status: "BETTING_QUALIFIED_PAPER",
    betting_qualified: true
  }),
  "BETTING_QUALIFIED_PAPER",
  "a qualified status beats a group/provenance label when candidate_status is absent"
);
assert.equal(
  virtualCandidateStatus({
    candidate_status: "MODEL_RESEARCH",
    qualification_status: "BETTING_QUALIFIED_PAPER",
    betting_qualified: true
  }),
  "MODEL_RESEARCH",
  "an explicit research status remains a veto even if a qualified flag conflicts"
);
assert.equal(
  virtualCandidateStatus({ qualification_status: "MODEL_RESEARCH" }),
  "MODEL_RESEARCH",
  "unqualified rows retain the conservative research fallback"
);

// Any explicit gate-pending label must veto contradictory upstream qualified booleans.
for (const pendingStatus of ["DIRECTIONAL_LINE_VALIDATION_GATE_PENDING", "MODEL_LINE_SCOPE_GATE_PENDING"]) {
  const contradictoryPending = row({
    qualification_status: pendingStatus,
    candidate_status: "BETTING_QUALIFIED_PAPER",
    prediction_status: "BETTING_QUALIFIED_PAPER",
    betting_qualified: true,
    qualified_for_builder: true
  });
  assert.equal(qualificationState(contradictoryPending).modelQualified, false, pendingStatus + " must veto conflicting qualified flags");
  assert.equal(qualificationState(contradictoryPending).currentPricePass, false, pendingStatus + " must not pass the exact-price gate");
  assert.equal(qualificationState(contradictoryPending).reason, pendingStatus, pendingStatus + " should preserve the actionable blocker label");
  assert.equal(qualifiedBestSelections([contradictoryPending], Date.now()).rows.length, 0, pendingStatus + " must never enter Qualified Best");
}

// Model estimate bands alone do not qualify a row.
const estimateOnly = row({
  qualification_status: "MODEL_90_PLUS",
  candidate_status: "MODEL_90_PLUS",
  betting_qualified: false,
  qualified_for_builder: false
});
assert.equal(qualificationState(estimateOnly).currentPricePass, false, "high probability is not the qualification gate");
assert.equal(qualificationState(estimateOnly).reason, "MODEL_GATE_NOT_PASSED");

// Quotes on a neighbouring line and stale quotes must fail closed.
const wrongLine = row({ sportybet_odds_line: 3.5 });
assert.equal(qualificationState(wrongLine).currentPricePass, false, "wrong totals line cannot qualify");
assert.equal(qualificationState(wrongLine).reason, "LINE_MISMATCH");
const stale = row({ market_odds_timestamp: new Date(Date.now() - 21 * 60 * 1000).toISOString() });
assert.equal(qualificationState(stale).currentPricePass, false, "stale SportyBet quote cannot qualify");
assert.equal(qualificationState(stale).reason, "QUOTE_STALE");

// Primary fixture display prioritizes a genuinely price-qualified exact line over a high but stale estimate.
const staleHigh = row({
  pick: "under",
  probability: 0.97,
  bookmaker_odds: 1.9,
  sportybet_odds: 1.9,
  sportybet_odds_side: "under",
  sportybet_over_odds: 2.0,
  sportybet_under_odds: 1.9,
  market_odds_timestamp: new Date(Date.now() - 21 * 60 * 1000).toISOString()
});
const passingLowerEstimate = row({ probability: 0.70 });
assert.equal(primaryPrediction([staleHigh, passingLowerEstimate]).pick, "over", "a stale high model rating must not hide a passing exact-price line");

// The shortlist contains one passing selection per fixture, uses upcoming rows only, and excludes research-only VFootball.
const best = qualifiedBestSelections([staleHigh, passingLowerEstimate], Date.now());
assert.equal(best.rows.length, 1, "one best qualified selection per fixture");
assert.equal(best.rows[0].pick, "over", "qualified shortlist selects the current-price pass");
// Qualified Best display order must follow kickoff time, not expected-return ranking.
const kickoffSortNow=Date.now();
const earlyKickoff=row({
  event_id:"kickoff-order-early",
  start_time:new Date(kickoffSortNow+20*60*1000).toISOString(),
  probability:0.65
});
const laterHighReturnKickoff=row({
  event_id:"kickoff-order-late",
  start_time:new Date(kickoffSortNow+90*60*1000).toISOString(),
  probability:0.90
});
const kickoffSorted=qualifiedBestSelections([laterHighReturnKickoff,earlyKickoff],kickoffSortNow);
assert.equal(kickoffSorted.rows.length,2,"both independently qualified fixtures remain visible");
assert.equal(kickoffSorted.rows[0].event_id,"kickoff-order-early","the earlier kickoff appears first even when the later fixture has higher expected return");
assert.ok(Date.parse(kickoffSorted.rows[0].start_time)<Date.parse(kickoffSorted.rows[1].start_time),"all Qualified Best rows are ordered by increasing kickoff time");

const past = row({ start_time: new Date(Date.now() - 60 * 1000).toISOString() });
assert.equal(qualifiedBestSelections([past], Date.now()).rows.length, 0, "past-kickoff rows never enter Qualified Best");
const vfootball = row({ sport: "virtual", product: "vfootball", event_id: "vfb-1" });
assert.equal(qualifiedBestSelections([vfootball], Date.now()).rows.length, 0, "VFootball remains outside active qualified Desk scope");
 
// Upstream-qualified eFootball rows below the 80% discovery threshold must still
// reach the exact-price gate. Model-only rows below 80% stay out of that lane.
const qualifiedSeventy = {
  ...row({
    sport: "virtual", product: "efootball_gt", probability: 0.7117,
    line: 7.5, pick: "under", event_id: "efootball-qualified-71",
    sportybet_odds_line: 7.5, sportybet_odds_side: "under",
    bookmaker_odds: 1.9, sportybet_odds: 1.9,
    sportybet_over_odds: 2.0, sportybet_under_odds: 1.9
  }),
  betting_qualified: true,
  qualified_for_builder: true,
  qualification_status: "BETTING_QUALIFIED_PAPER_DIRECTIONAL"
};
assert.equal(isVirtualDeskCandidate(qualifiedSeventy), true, "an upstream-qualified 71% eFootball candidate must reach the exact-price gate");
assert.equal(qualificationState(qualifiedSeventy).currentPricePass, true, "the sub-80% row still has to pass an exact fresh-price gate");
assert.equal(qualifiedBestSelections([qualifiedSeventy], Date.now()).rows.length, 1, "a fully price-validated sub-80% paper-qualified candidate can enter Qualified Best");
assert.equal(isVirtualDeskCandidate({ ...qualifiedSeventy, betting_qualified: false, qualified_for_builder: false, qualification_status: "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING" }), false, "a sub-80% pending research candidate is not promoted");

const overconfidentUnder = {
  ...row({ sport: "virtual", product: "efootball_gt", probability: 0.9614, line: 10.5, pick: "under", event_id: "efootball-under-105" }),
  walkforward_exact_line_n: 69,
  walkforward_exact_line_hit_rate: 0.5652173913043478
};
const calibration = probabilityCalibrationInfo(overconfidentUnder);
assert.ok(calibration, "adequately sampled exact-line walk-forward evidence enables conservative Desk blending");
assert.ok(probabilityValue(overconfidentUnder) < 0.70, "a 96% raw estimate with a 56.5% historical hit rate must not remain near-certain");
assert.ok(probabilityValue(overconfidentUnder) < rawProbabilityValue(overconfidentUnder), "poor exact-line outcomes must pull the Desk estimate down");
assert.equal(calibration.n, 69, "calibration labels retain their evidence sample size");
assert.ok(Math.abs(displayedFairOddsValue(overconfidentUnder)-(1/probabilityValue(overconfidentUnder)))<1e-9, "fair odds must agree with the calibrated Desk estimate");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, walkforward_exact_line_hit_rate: null }), null, "a null hit rate is not treated as 0% evidence");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, walkforward_exact_line_n: null }), null, "a null sample count cannot unlock calibration");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, line: null }), null, "a missing exact O/U line cannot unlock line-specific calibration");
assert.equal(probabilityCalibrationInfo({ ...overconfidentUnder, line: "" }), null, "an empty exact O/U line cannot unlock line-specific calibration");

const pendingDirectional = {
  ...overconfidentUnder,
  betting_qualified: false,
  qualified_for_builder: false,
  qualification_status: "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING"
};
assert.equal(qualificationState(pendingDirectional).currentPricePass, false, "calibration never bypasses an upstream directional validation gate");
assert.equal(qualificationState(pendingDirectional).reason, "DIRECTIONAL_LINE_VALIDATION_GATE_PENDING", "the Desk should explain the actual blocker instead of a generic model gate");

// Prefer the explicit total/line specifier: SportyBet may expose line: 9 alongside specifier: total=9.5.
assert.equal(exactVirtualMarketLine({ specifier: "total=7.5" }), 7.5, "provider total specifier is recognized");
assert.equal(exactVirtualMarketLine({ specifier: "total=7.5", line: 8.5 }), 7.5, "explicit total specifier takes precedence over a conflicting numeric line");
assert.equal(exactVirtualMarketLine({ specifier: "total=9.5", line: 9 }), 9.5, "SportyBet integer base line cannot override the actual half-goal specifier");
assert.equal(exactVirtualMarketLine({ line: 8.5 }), 8.5, "numeric market.line remains a fallback when no total specifier exists");
assert.equal(exactVirtualMarketLine({ specifier: "period=1" }), null, "unrelated specifier is not treated as a totals line");


const virtualKickoff = Date.now() + 60 * 60 * 1000;
const virtualDeskFixture = {
  event_id: "virtual-event-identity-1",
  product: "efootball_gt",
  sport: "virtual",
  start_time: new Date(virtualKickoff).toISOString(),
  participant_1: "Real Madrid (HandleA)",
  participant_2: "Liverpool (HandleB)"
};
const virtualLiveQuote = {
  event_id: "virtual-event-identity-1",
  product: "efootball_gt",
  sport: "virtual",
  start_time: new Date(virtualKickoff + 5 * 60 * 1000).toISOString(),
  participant_1: "HandleA",
  participant_2: "HandleB"
};
assert.equal(sameVirtualEvent(virtualDeskFixture, virtualLiveQuote), true, "exact event and participants tolerate five-minute kickoff drift");
assert.equal(sameVirtualEvent(virtualDeskFixture, { ...virtualLiveQuote, start_time: new Date(virtualKickoff + 16 * 60 * 1000).toISOString() }), false, "large kickoff drift cannot match quote");
assert.equal(sameVirtualEvent(virtualDeskFixture, { ...virtualLiveQuote, event_id: "different-event" }), false, "different provider event ID cannot validate quote");
assert.equal(sameVirtualEvent(virtualDeskFixture, { ...virtualLiveQuote, participant_2: "HandleC" }), false, "wrong participant cannot validate quote");
assert.equal(sameVirtualEvent(virtualDeskFixture, { ...virtualLiveQuote, product: "efootball_adriatic" }), false, "different product cannot validate quote");
assert.equal(virtualSnapshotHasCompleteFirstPage({status:"LIVE"}, 0, false, false), false, "empty snapshot does not invalidate prior quotes");
assert.equal(virtualSnapshotHasCompleteFirstPage({status:"LIVE"}, 24, false, false), true, "healthy non-empty short snapshot can be complete");
assert.equal(virtualSnapshotHasCompleteFirstPage({status:"LIVE"}, 24, true, false), false, "source errors prevent snapshot completion");

console.log("Prediction Desk gate regressions passed: explicit status veto, probability-band separation, exact line/side, 15-minute freshness, qualified-first ranking, future-only shortlist, active virtual scope, and provider specifier normalization.");
