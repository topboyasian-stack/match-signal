#!/usr/bin/env python3
"""Static contract checks for the single cross-sport SportyBet ticket builder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    css_version = "ticket-drawer.css?v=20261102-single-ticket1"
    js_version = "ticket-drawer.js?v=20261102-single-ticket1"
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
    api = (ROOT / "functions" / "api" / "sportybet-booking.js").read_text(encoding="utf-8")

    require('data-sport="basketball"' in basketball, "Basketball page lost its sport identity")
    require('data-sport="football"' in football, "Football page lost its sport identity")
    require('data-sport="tennis"' in tennis, "Tennis page lost its sport identity")
    require("function ticketAddMarkup" in hub and "Add prediction to ticket" in hub,
            "Football/Tennis prediction cards must expose a selectable ticket action")
    require("ticketAddMarkup(x)" in hub and "ticketAddMarkup(p)" in hub,
            "Upcoming and league prediction rows must both connect to the ticket")
    require("data-ms-ticket-add" in hub and 'data-ticket-market="total"' in hub and "row?.analytics||{}).total_games" in hub and "(sport==='football'?'18':'189')" in hub,
            "Football/Tennis winner and Over/Under predictions must submit structured selections")
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
    require("manual_selections" in drawer and "./api/sportybet-booking" in drawer,
            "The shared ticket must submit all selections through the common revalidation API")
    require("market==='total'?line:null" in drawer and "item.market==='total'" in drawer,
            "Football, Tennis and Basketball total legs must retain their exact line and side")
    require("data-ms-ticket-remove" in drawer and "data-ms-ticket-clear" in drawer,
            "Selections must be removable individually and as a full ticket")
    require("data-ticket-market-id" in drawer and "model_qualified" in drawer,
            "Basketball market identity and release status must travel with each ticket leg")
    require("ms-ticket-builder" in css and "ms-pred-ticket-action" in css,
            "The shared builder and prediction actions need their styles")

    require("data-ms-ticket-add" in nba and 'data-ticket-market="total"' in nba,
            "NBA current totals must be selectable into the same ticket")
    require("nbaTotalsReleaseQualified(S.totalsOos)" in nba and "nbaTotalRowQualified(p,S.totalsOos)" in nba,
            "NBA ticket generation must retain the independent release and per-row gates")
    require("market === 'total' && ['football','tennis'].includes(sport)" in api and "leg.market === 'total'" in api and "leg.market_id !== requiredMarketId" in api,
            "Football/Tennis total selections must revalidate against exact SportyBet full-match O/U market IDs")
    require("function collectBasketballEvents" in api and "function findBasketballSelection" in api,
            "The common booking API must resolve and revalidate NBA total markets")
    require("const basketballIds" in api and "collectBasketballEvents(context, basketballIds)" in api,
            "Mixed-sport tickets must fetch the current SportyBet Basketball event")
    require("leg.model_qualified !== true" in api and "leg.market_id !== '225'" in api,
            "The booking endpoint must reject research-only or non-225 NBA selections")
    require("new Set(ids).size !== ids.length" in api,
            "The booking endpoint must reject duplicate fixtures")
    require("Participant identity changed in SportyBet current catalogue." in api,
            "Football/Tennis participants must be matched to current SportyBet event identity")
    require("function canonicalParticipant(value)" in api and ".normalize('NFD')" in api,
            "Participant matching must normalize accented player names")
    require("function sameParticipantPair(first, event)" in api and
            "sameParticipantPair([first, second], event)" in api,
            "Current Tennis event matching must accept the same two players in either order")
    require("function participantNameMatches(first, second)" in api and
            "tokens[1].length === 1" in api and "tokens.reverse()" in api,
            "Tennis player matching must handle trailing initials such as Surname A.")
    require("actual half-point total" in api and "explicitLine" in api,
            "Exact SportyBet total specifiers must override integer base lines")
    require("specifierText.match(/(?:^|[,\\s;|&])(?:total|line)" in api,
            "Exact total specifier parsing must use whitespace-aware matching")
    require("selectedIsHome" in api and "selectedIsAway" in api and
            "The exact current SportyBet winner market or selected player outcome" in api,
            "Tennis winner mapping must preserve the selected player after SportyBet reverses participant order")
    require("function validationFailure(leg, reason)" in api and "validationFailure(leg," in api,
            "Booking failures must identify the exact selection and validation reason")
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
