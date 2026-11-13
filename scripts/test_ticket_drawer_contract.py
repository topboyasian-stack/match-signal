#!/usr/bin/env python3
"""Static contract checks for the single cross-sport SportyBet ticket builder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    css_version = "ticket-drawer.css?v=20261102-single-ticket1"
    js_version = "ticket-drawer.js?v=20261110-tennis-set-winner2"
    pages = ("basketball.html", "football.html", "tennis.html", "league.html", "index.html", "upcoming.html", "qualified-best.html")
    for page in pages:
        source = (ROOT / page).read_text(encoding="utf-8")
        require(css_version in source, f"{page} does not load the current shared ticket stylesheet")
        require(js_version in source, f"{page} does not load the current shared ticket script")

    basketball = (ROOT / "basketball.html").read_text(encoding="utf-8")
    football = (ROOT / "football.html").read_text(encoding="utf-8")
    tennis = (ROOT / "tennis.html").read_text(encoding="utf-8")
    drawer = (ROOT / "ticket-drawer.js").read_text(encoding="utf-8")
    css = (ROOT / "ticket-drawer.css").read_text(encoding="utf-8")
    hub = (ROOT / "sport-hubs.js").read_text(encoding="utf-8")
    nba = (ROOT / "basketball-live.js").read_text(encoding="utf-8")
    lab_html = (ROOT / "virtual-lab" / "index.html").read_text(encoding="utf-8")
    lab_app = (ROOT / "virtual-lab-app.js").read_text(encoding="utf-8")
    api = (ROOT / "functions" / "api" / "sportybet-booking.js").read_text(encoding="utf-8")

    require('data-sport="basketball"' in basketball, "Basketball page lost its sport identity")
    require('data-sport="football"' in football, "Football page lost its sport identity")
    require('data-sport="tennis"' in tennis, "Tennis page lost its sport identity")
    alternatives_script = "qualified-alternatives.js?v=20261110-tennis-set-winner2"
    for page in pages:
        source = (ROOT / page).read_text(encoding="utf-8")
        require(alternatives_script in source, f"{page} does not load the live qualified-alternatives selector")
    require("../qualified-alternatives.js?v=20261110-tennis-set-winner2" in lab_html, "Virtual Lab must load the product-aware qualified-alternatives selector")
    selector = (ROOT / "qualified-alternatives.js").read_text(encoding="utf-8")
    require("querySelectorAll('[data-ms-fixture-id]')" in selector and "x.event_id===event&&x.sport===sport" in selector,
            "Qualified alternatives must attach to the exact fixture card and sport, never a different event")
    require("data-ticket-model-qualified=\"'+String(x.builder_qualified===true)+'\"" in selector and "String(x.builder_qualified===true)" in selector and "model_qualified:target.getAttribute('data-ticket-model-qualified')==='true'" in drawer,
            "Builder-gated alternatives must retain their qualification state when added to the shared ticket")
    require('data-ticket-event="' in selector and 'data-ticket-sportybet-event="' in selector and 'data-ticket-market-id="' in selector and 'data-ticket-start="' in selector,
            "Qualified alternatives must pass the exact fixture, provider event, market ID and kickoff into the shared ticket")
    unified_row = hub.split("function unifiedRow(group){", 1)[1].split("async function renderUnifiedBoard", 1)[0]
    qualified_best_row = hub.split("function qualifiedBestRow(x){", 1)[1].split("// VFOOTBALL", 1)[0]
    require("data-ms-fixture-id" in unified_row and "alternativeFixtureSport(x)" in unified_row,
            "Upcoming rows must expose canonical sport identity so eFootball alternatives can mount")
    require("data-ms-fixture-id" in qualified_best_row and "alternativeFixtureSport(x)" in qualified_best_row,
            "Qualified Best rows must expose canonical sport identity so eFootball alternatives can mount")
    require("function alternativeFixtureSport(x)" in hub and 'return "efootball"' in hub,
            "Active eFootball product cards must use the same efootball key returned by the public alternatives API")
    require("function ticketAddMarkup" in hub and "Add prediction to ticket" in hub,
            "Football/Tennis prediction cards must expose a selectable ticket action")
    require("ticketAddMarkup(x)" in hub and "ticketAddMarkup(p)" in hub,
            "Upcoming and league prediction rows must both connect to the ticket")
    require("data-ms-ticket-add" in hub and 'data-ticket-market="total"' in hub and "row?.analytics||{}).total_games" in hub and "(sport==='football'?'18':'189')" in hub,
            "Football/Tennis winner and Over/Under predictions must submit structured selections")
    require("sportybetEventId=String(row?.sportybet_event_id||" in hub and hub.count("data-ticket-sportybet-event") >= 2,
            "Football/Tennis winner and total actions must carry a separate SportyBet provider event ID when available")
    require("sportybet_event_id:sportybetEventId||null" in drawer,
            "The shared ticket must retain separate provider IDs for Football/Tennis as well as Basketball")
    require("window.MatchSignalTicket" in drawer and "function addSelection(raw)" in drawer,
            "The shared ticket selection API is missing")
    require("match-signal:sportybet-manual-ticket:v2" in drawer,
            "Selections must persist when navigating between sport pages")
    require("MAX_LEGS=8" in drawer and "function builderMarkup()" in drawer,
            "The builder must be one compact ticket with a maximum of eight selections")
    require("builder_slot" not in drawer and "builderOnly" not in drawer and "iframe" not in drawer,
            "The floating ticket must not contain nested or multiple builders")
    require("data-ms-ticket-gate" in drawer and "generate.disabled=bookingBusy" in drawer,
            "The Generate button must remain clickable while showing the exact requirement/release blocker")
    require("data-ms-ticket-generate]').addEventListener('click',generateCode)" in drawer,
            "The Generate button must have a direct click handler")
    require("generate.disabled=bookingBusy||Boolean(lockReason())" not in drawer,
            "Ticket requirements must not make the Generate button appear dead")
    require(api.count("MANUAL_TICKET_REJECTED_PARTIAL") >= 2 and
            "if (manualMode && preExcluded.length > 0)" in api and
            "if (manualMode && (" in api,
            "Every manual sport must use the same all-or-nothing pre-validation and provider-acceptance contract")
    require("MANUAL PICK — model qualification not claimed; live recheck required" in drawer,
            "Research-only model status must not be misrepresented as a manual-ticket booking prohibition")
    require("manual_selections" in drawer and "/api/sportybet-booking" in drawer,
            "The shared ticket must submit all selections through the root-relative common revalidation API")
    require("AbortSignal.timeout(26000)" in drawer and "Your ticket is still saved; no code is assumed to exist." in drawer,
            "Manual ticket network timeouts must preserve the slip and avoid implying a code was created")
    require("requestDeadlineAt = Date.now() + 22000" in api and
            "catalogueDeadlineAt = Date.now() + 13000" in api and
            "requestTimeoutMs: manualMode ? 3000 : 6000" in api and
            "deadlineAt: requestDeadlineAt, timeoutMs: manualMode ? 6500 : 9000" in api and
            "loadNbaReleaseContext(requestDeadlineAt)" in api,
            "Builder and manual revalidation, NBA evidence loading and share requests must have bounded request budgets")
    require("market==='total'?line:null" in drawer and "item.market==='total'" in drawer,
            "Football, Tennis and Basketball total legs must retain their exact line and side")
    require("data-ms-ticket-remove" in drawer and "data-ms-ticket-clear" in drawer,
            "Selections must be removable individually and as a full ticket")
    require("data-ticket-market-id" in drawer and "model_qualified" in drawer and "sportybet_event_id" in drawer,
            "Basketball market identity and release status must travel with each ticket leg")
    require("item.market==='set_winner'" in drawer and "set_number:item.set_number" in drawer and "data-ticket-set-number" in drawer,
            "Tennis Set 1/Set 2 scope must persist through the shared ticket and manual booking request")
    require("function findSetWinnerSelection(leg, event)" in api and
            "marketId: '202'" in api and "specifier," in api and "leg.market_id !== '202'" in api,
            "Tennis set winners must be revalidated against exact SportyBet market 202 and its literal setnr specifier")
    require("data-ticket-set-number" in selector and "MARKET_SCOPE_NOT_COMPARABLE" in selector,
            "Set-winner alternatives must display their set number and avoid comparing set probabilities to match probabilities")
    require("product:item.product||null" in drawer and "product:target.getAttribute('data-ticket-product')" in drawer,
            "Product-specific eFootball identity must survive add-to-ticket and server submission")
    require("efootball_gt" in drawer and "efootball_adriatic" in drawer and "item.sport==='efootball'" in drawer,
            "Only the two supported eFootball product lanes may be restored into the shared ticket")
    require("ms-ticket-builder" in css and "ms-pred-ticket-action" in css,
            "The shared builder and prediction actions need their styles")

    require("data-ms-ticket-add" in nba and 'data-ticket-market="total"' in nba and "data-ticket-sportybet-event" in nba and "predictionId=String(p.event_id||'')" in nba and "sportybetId=String(event.event_id||'')" in nba,
            "NBA current totals must be selectable into the same ticket")
    require("function nbaTotalsReleaseQualified(evidence,probability,ledger,captureStatus)" in nba and
            "function nbaTotalRowQualified(prediction,evidence,probability,snapshots,currentMarket,ledger,captureStatus)" in nba and
            "nbaTotalsReleaseQualified(S.totalsOos,S.totalsProbability,S.totalLedger,S.priceCaptureStatus)" in nba and
            "nbaTotalRowQualified(p,S.totalsOos,S.totalsProbability,S.totalSnapshots,fresh,S.totalLedger,S.priceCaptureStatus)" in nba,
            "NBA ticket generation must retain independent release/per-row gates and live ledger/capture freshness evidence")
    require("../ticket-drawer.css?v=20261102-efootball-shared-ticket1" in lab_html and "../ticket-drawer.js?v=20261110-tennis-set-winner2" in lab_html,
            "Virtual Lab must load the shared floating ticket from its nested route")
    require("data-ms-ticket-add" in lab_app and 'data-ticket-sport="efootball"' in lab_app and "data-ticket-product" in lab_app and "efootballTicketReady" in lab_app,
            "Only qualified eFootball GT/eAdriatic exact-line prediction cards may add to the shared ticket")
    require("QUALIFIED_BASE_EVIDENCE" in lab_app and "QUALIFIED_PARTICIPANT_ENHANCED" in lab_app and "p.primary.marketType==='ou'" in lab_app,
            "eFootball ticket actions must keep the existing product/model qualification gates and totals-only boundary")
    require("market === 'total' && ['football','tennis'].includes(sport)" in api and "leg.market === 'total'" in api and "leg.market_id !== requiredMarketId" in api,
            "Football/Tennis total selections must revalidate against exact SportyBet full-match O/U market IDs")
    require("const isEfootballLeg = leg.sport === 'efootball' ||" in api and
            "(leg.sport === 'virtual' && productForLeg(leg) === 'efootball' && leg.market === 'virtual_total')" in api and
            "productForLeg(leg) !== 'efootball'" in api and
            "!['efootball_gt', 'efootball_adriatic'].includes(leg.product)" in api and
            "!['total', 'virtual_total'].includes(leg.market)" in api and
            "if (hasEfootballLeg && preExcluded.length > 0)" in api,
            "Manual eFootball O/U legs must be product-tagged and still fail closed when live SportyBet validation rejects any leg")
    require("const efootballProduct = productForLeg(leg) === 'efootball' || sport === 'efootball'" in api and
            "const requiredMarketId = sport === 'football' ? '18' : sport === 'tennis' ? '189' : efootballProduct ? String(leg?.market_id || '')" in api and
            "market === 'virtual_total'" in api and "['vfootball', 'efootball'].includes(product)" in api,
            "eFootball booking must recognize Virtual Lab's virtual_total shape and revalidate its exact provider market ID")
    require("map(l => String(l.sportybet_event_id || l.event_id || '')).filter(Boolean)" in api and "const hasEfootballLeg" in api and "EFOOTBALL_SLIP_REJECTED_PARTIAL" in api,
            "eFootball revalidation must use the SportyBet provider ID and reject partial mixed slips")
    require("function collectBasketballEvents" in api and "function findBasketballSelection" in api,
            "The common booking API must resolve and revalidate NBA total markets")
    require("import { onRequestGet as getSportyBetBasketballFeed } from './sportybet-basketball.js';" in api and "getSportyBetBasketballFeed({request:feedRequest" in api,
            "NBA revalidation must invoke the sibling SportyBet feed function directly instead of self-fetching its Pages URL")
    basketball_collector = api.split("export async function collectBasketballEvents", 1)[1].split("function findBasketballSelection", 1)[0]
    require("await fetch(url.toString()" not in basketball_collector and "response.json()" not in basketball_collector and "returned non-JSON content" in basketball_collector,
            "NBA feed revalidation must handle non-JSON responses explicitly and avoid same-origin HTML fallbacks")
    require("export async function upstream(path, params, { timeoutMs = 6000, deadlineAt = null } = {})" in api and "SPORTYBET_PROXY_ORIGIN" in api and "returned HTML instead of JSON" in api,
            "Shared SportyBet catalogue lookup must keep proxy recovery while exposing bounded request deadlines")
    require("export async function collectEvents" in api and "maxPages = 5" in api,
            "Shared ticket catalogue scans must stop at the regional proxy's supported fifth page")
    require("export async function requestSportyBetShare" in api and
            "for (const origin of [SPORTYBET_PROXY_ORIGIN, ORIGIN])" in api and
            "const shareResult = await requestSportyBetShare(selections, { deadlineAt: requestDeadlineAt, timeoutMs: manualMode ? 6500 : 9000 })" in api,
            "Share-code creation must try both SportyBet sources within the manual request deadline and return JSON failures")
    require("async function collectCurrentEventsById(legs, deadlineAt = null, sharedMatchedLegs = null)" in api and
            "upstream('/api/ng/factsCenter/event'" in api and
            "const directEvents = await collectCurrentEventsById(lookupLegs, catalogueDeadlineAt, sharedMatchedLegs)" in api and
            "const unresolvedLegs = lookupLegs.filter(leg => !sharedMatchedLegs.has(leg))" in api,
            "Manual booking must try SportyBet single-event details by current provider ID first, then catalogue-scan only unresolved aliases")
    require("const lookupLegs = manualMode ? legs.filter" in api and "const basketballLegs = lookupLegs.filter" in api and
            "const unresolvedBasketballLegs = unresolvedLegs.filter" in api and
            "unresolvedBasketballLegs.flatMap(leg => [leg.sportybet_event_id, leg.event_id])" in api and
            "collectBasketballEvents(context, unresolvedBasketballIds, catalogueTimeline, unresolvedBasketballLegs, catalogueDeadlineAt)" in api and
            "targetBasketballFixtureMatches" in api and "directProvider = sportybetId ? found.get(sportybetId) : null" in api,
            "Mixed-sport tickets must try direct SportyBet event details first, then resolve only unmatched Basketball fixtures by provider ID or verified participants and kickoff, while excluding started legs")
    require("const unresolvedFootballLegs = unresolvedLegs.filter" in api and
            "const unresolvedTennisLegs = unresolvedLegs.filter" in api and
            "}, unresolvedFootballIds, unresolvedFootballLegs)" in api and
            "}, unresolvedTennisIds, unresolvedTennisLegs)" in api and
            "const [liveFeedEvents, footballEvents, tennisEvents, basketballEvents] = await Promise.all" in api and
            "const [vfootballEvents, efootballEvents] = await Promise.all" in api and
            "const remainingVirtualLegs = unresolvedVirtualLegs.filter(leg => !sharedMatchedLegs.has(leg))" in api and
            "const remainingEfootballLegs = unresolvedEfootballLegs.filter(leg => !sharedMatchedLegs.has(leg))" in api,
            "Parallel Football and Tennis alias scans must only process legs not resolved by the direct event-details lookup")
    require("leg?.model_qualified!==true" in api and "leg?.market_id!=='225'" in api and
            "leg.market === 'winner'" in api and "leg.market_id !== '219'" in api and
            "!leg.sportybet_event_id" in api and "NBA_RELEASE_GATE_LOCKED" in api and
            "nbaTotalTicketLegQualified" in api and "if (hasBasketballLeg && !manualMode)" in api and
            "if (basketballLeg && !manualMode)" in api and
            "const expectedMarket = isWinner ? '219' : '225'" in api and
            "15 * 60 * 1000" in api,
            "Automated NBA totals Builder batches must retain the strict model-release gate; manual market-219 winner and market-225 total picks must pass exact fresh quote validation")
    require("prospective_probability_fixture_coverage" in api and
            "valid_unique_settled_fixtures" in api and "binary_scored_unique_fixtures" in api and
            "snapshot_linkage_failure_count" in api and
            "Number(c.prospective_settled_selections_with_exact_snapshot_match)>=100" in api and
            "prospective_settled_selections_with_exact_snapshot_match)>=30" not in api,
            "The backend must validate 30 unique settled fixtures separately from the 100 selected market bets")
    require("prospective_probability_fixture_coverage" in nba and
            "valid_unique_settled_fixtures" in nba and "binary_scored_unique_fixtures" in nba and
            "Number(c.prospective_settled_selections_with_exact_snapshot_match)>=100" in nba and
            "prospective_settled_selections_with_exact_snapshot_match)>=30" not in nba,
            "The Basketball UI must use the same fixture-level probability sample as the backend")
    require("v=20261104-nba-probability-cohort1" in basketball,
            "The Basketball UI must bust its cache when the probability-sample gate changes")
    require("hasBasketballLeg && preExcluded.length > 0" in api and "BASKETBALL_SLIP_REJECTED_PARTIAL" in api,
            "An NBA-containing slip must be rejected whole if any leg fails live validation or SportyBet removes a selection")
    require("new Set(ids).size !== ids.length" in api,
            "The booking endpoint must reject duplicate fixtures")
    tennis_resolver = api.split("unresolvedTennisLegs.length", 1)[1].split("unresolvedBasketballLegs.length", 1)[0]
    require("fallbackPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents'" in tennis_resolver,
            "Tennis fixtures must be retried against SportyBet's alternate WAP upcoming catalogue")
    require("diff <= 45 * 60 * 1000" in api,
            "Fixture participant fallback must use the same 45-minute tolerance as manual ticket revalidation")
    require("Participant identity changed in SportyBet current catalogue." in api,
            "Football/Tennis participants must be matched to current SportyBet event identity")
    require("function canonicalParticipant(value)" in api and ".normalize('NFD')" in api,
            "Participant matching must normalize accented player names")
    require("function sameParticipantPair(first, event, sport = '')" in api and
            "teamNameMatches(a, home, sport) && teamNameMatches(b, away, sport)" in api and
            "teamNameMatches(a, away, sport) && teamNameMatches(b, home, sport)" in api and
            "sameParticipantPair(participants, event, aliasSport)" in api,
            "Current Tennis and team-sport event matching must accept both participant orders with sport-scoped aliases")
    require("function participantNameMatches(first, second)" in api and
            "tokens[1].length === 1" in api and "tokens.reverse()" in api and
            "left[0] === right[1] && left[1] === right[0]" in api,
            "Tennis player matching must handle trailing initials and reversed full-name order")
    require("leftSurname === rightSurname" in api and
            "leftFirst[0] === rightFirst[0]" in api,
            "Abbreviated player matches must agree on both surname and first initial")
    require("actual half-point total" in api and "explicitLine" in api,
            "Exact SportyBet total specifiers must override integer base lines")
    require("specifierText.match(/(?:^|[,\\s;|&])(?:total|line)" in api,
            "Exact total specifier parsing must use whitespace-aware matching")
    require("selectedIsHome" in api and "selectedIsAway" in api and
            "The exact current SportyBet winner market or selected player outcome" in api,
            "Tennis winner mapping must preserve the selected player after SportyBet reverses participant order")
    require("function validationFailure(leg, reason)" in api and "validationFailure(leg," in api,
            "Booking failures must identify the exact selection and validation reason")
    require("canonicalParticipant(leg.player_1) === canonicalParticipant(leg.player_2)" in api and
            "canon(leg.player_1)" not in api,
            "Manual participant validation must not call a removed canon helper")
    require("errors.length?errors.join(' | ')" in drawer,
            "The ticket drawer must display leg-specific validation before the generic API error")
    require("isOpenEvent(event)" in api and "buildSelection(leg, event)" in api,
            "Every selection must be revalidated for current event state and market/outcome IDs")
    require('id="basketball-builders"' not in basketball and "4 Odds Builders" not in basketball,
            "Basketball must not retain a separate four-builder section")
    require("Math.random()" not in drawer and "crypto.randomUUID" not in drawer,
            "The client must never fabricate SportyBet booking codes")
    print("single cross-sport ticket contract: PASS")


if __name__ == "__main__":
    main()
