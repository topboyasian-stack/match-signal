#!/usr/bin/env python3
"""Static contract checks for the single cross-sport SportyBet ticket builder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    css_version = "ticket-drawer.css?v=20261102-single-ticket1"
    js_version = "ticket-drawer.js?v=20261102-split-event-identifiers1"
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
    alternatives_script = "qualified-alternatives.js?v=20261107-qualified-picks4"
    for page, source in (("football.html", football), ("tennis.html", tennis), ("basketball.html", basketball)):
        require(alternatives_script in source, f"{page} does not load the live qualified-alternatives selector")
    require("../qualified-alternatives.js?v=20261107-qualified-picks5" in lab_html, "Virtual Lab must load the product-aware qualified-alternatives selector")
    require('data-ticket-model-qualified="true"' in (ROOT / "qualified-alternatives.js").read_text(encoding="utf-8"), "Builder-gated alternatives must retain their qualification state when added to the shared ticket")
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
    require("manual_selections" in drawer and "/api/sportybet-booking" in drawer,
            "The shared ticket must submit all selections through the root-relative common revalidation API")
    require("AbortSignal.timeout(26000)" in drawer and "Your ticket is still saved; no code is assumed to exist." in drawer,
            "Manual ticket network timeouts must preserve the slip and avoid implying a code was created")
    require("manualDeadlineAt = manualMode ? Date.now() + 22000 : null" in api and "requestTimeoutMs: manualMode ? 3500 : 6000" in api and "deadlineAt: manualDeadlineAt, timeoutMs: manualMode ? 6500 : 12000" in api,
            "Manual multi-leg revalidation and share requests must have a bounded request budget")
    require("market==='total'?line:null" in drawer and "item.market==='total'" in drawer,
            "Football, Tennis and Basketball total legs must retain their exact line and side")
    require("data-ms-ticket-remove" in drawer and "data-ms-ticket-clear" in drawer,
            "Selections must be removable individually and as a full ticket")
    require("data-ticket-market-id" in drawer and "model_qualified" in drawer and "sportybet_event_id" in drawer,
            "Basketball market identity and release status must travel with each ticket leg")
    require("product:item.product||null" in drawer and "product:target.getAttribute('data-ticket-product')" in drawer,
            "Product-specific eFootball identity must survive add-to-ticket and server submission")
    require("efootball_gt" in drawer and "efootball_adriatic" in drawer and "item.sport==='efootball'" in drawer,
            "Only the two supported eFootball product lanes may be restored into the shared ticket")
    require("ms-ticket-builder" in css and "ms-pred-ticket-action" in css,
            "The shared builder and prediction actions need their styles")

    require("data-ms-ticket-add" in nba and 'data-ticket-market="total"' in nba and "data-ticket-sportybet-event" in nba and "predictionId=String(p.event_id||'')" in nba and "sportybetId=String(event.event_id||'')" in nba,
            "NBA current totals must be selectable into the same ticket")
    require("nbaTotalsReleaseQualified(S.totalsOos,S.totalsProbability)" in nba and "nbaTotalRowQualified(p,S.totalsOos,S.totalsProbability,S.totalSnapshots,fresh)" in nba,
            "NBA ticket generation must retain the independent release and per-row gates")
    require("../ticket-drawer.css?v=20261102-efootball-shared-ticket1" in lab_html and "../ticket-drawer.js?v=20261102-efootball-shared-ticket1" in lab_html,
            "Virtual Lab must load the shared floating ticket from its nested route")
    require("data-ms-ticket-add" in lab_app and 'data-ticket-sport="efootball"' in lab_app and "data-ticket-product" in lab_app and "efootballTicketReady" in lab_app,
            "Only qualified eFootball GT/eAdriatic exact-line prediction cards may add to the shared ticket")
    require("QUALIFIED_BASE_EVIDENCE" in lab_app and "QUALIFIED_PARTICIPANT_ENHANCED" in lab_app and "p.primary.marketType==='ou'" in lab_app,
            "eFootball ticket actions must keep the existing product/model qualification gates and totals-only boundary")
    require("market === 'total' && ['football','tennis'].includes(sport)" in api and "leg.market === 'total'" in api and "leg.market_id !== requiredMarketId" in api,
            "Football/Tennis total selections must revalidate against exact SportyBet full-match O/U market IDs")
    require("if (leg.sport === 'efootball')" in api and "productForLeg(leg) !== 'efootball'" in api and
            "!['efootball_gt', 'efootball_adriatic'].includes(leg.product)" in api and
            "if (hasEfootballLeg && preExcluded.length > 0)" in api,
            "Manual eFootball O/U legs must be product-tagged and still fail closed when live SportyBet validation rejects any leg")
    require("const requiredMarketId = sport === 'football' ? '18' : sport === 'tennis' ? '189' : sport === 'efootball' ? String(leg?.market_id || '')" in api,
            "eFootball booking must revalidate the exact market ID passed by Virtual Lab")
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
            "const shareResult = await requestSportyBetShare(selections, { deadlineAt: manualDeadlineAt, timeoutMs: manualMode ? 6500 : 12000 })" in api,
            "Share-code creation must try both SportyBet sources within the manual request deadline and return JSON failures")
    require("const lookupLegs = manualMode ? legs.filter" in api and "const basketballLegs = lookupLegs.filter" in api and
            "flatMap(l => [l.sportybet_event_id, l.event_id])" in api and
            "collectBasketballEvents(context, basketballIds, catalogueTimeline, basketballLegs)" in api and
            "targetBasketballFixtureMatches" in api and "directProvider = sportybetId ? found.get(sportybetId) : null" in api,
            "Mixed-sport tickets must fetch current Basketball fixtures by provider ID or verified participants and kickoff, while excluding started legs from upcoming lookup")
    require("const footballIds = new Set(footballLegs.map" in api and
            "const tennisIds = new Set(tennisLegs.map" in api and
            "}, footballIds, footballLegs);" in api and "}, tennisIds, tennisLegs);" in api,
            "Football and Tennis catalogue scans must pass current legs for participant/time recovery")
    require("leg?.model_qualified!==true" in api and "leg?.market_id!=='225'" in api and
            "!leg.sportybet_event_id" in api and "NBA_RELEASE_GATE_LOCKED" in api and
            "nbaTotalTicketLegQualified" in api and "if (hasBasketballLeg && !manualMode)" in api,
            "Automated NBA batches must keep the release and snapshot gate while manual slips use live quote revalidation")
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
    tennis_resolver = api.split("if (tennisIds.size) {", 1)[1].split("if (basketballIds.size)", 1)[0]
    require("fallbackPath: '/api/ng/factsCenter/wapConfigurableUpcomingEvents'" in tennis_resolver,
            "Tennis fixtures must be retried against SportyBet's alternate WAP upcoming catalogue")
    require("diff <= 45 * 60 * 1000" in api,
            "Fixture participant fallback must use the same 45-minute tolerance as manual ticket revalidation")
    require("Participant identity changed in SportyBet current catalogue." in api,
            "Football/Tennis participants must be matched to current SportyBet event identity")
    require("function canonicalParticipant(value)" in api and ".normalize('NFD')" in api,
            "Participant matching must normalize accented player names")
    require("function sameParticipantPair(first, event)" in api and
            "sameParticipantPair([first, second], event)" in api,
            "Current Tennis event matching must accept the same two players in either order")
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
