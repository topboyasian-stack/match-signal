#!/usr/bin/env python3
"""Static contract checks for Match Signal's floating SportyBet ticket box."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    version_css = "ticket-drawer.css?v=20261102-sportybet-drawer2"
    version_js = "ticket-drawer.js?v=20261102-sportybet-drawer2"
    for page in ("basketball.html", "football.html", "tennis.html", "odds-builder.html"):
        source = (ROOT / page).read_text(encoding="utf-8")
        require(version_css in source, f"{page} does not load the current ticket-drawer stylesheet")
        require(version_js in source, f"{page} does not load the current ticket-drawer script")

    basketball = (ROOT / "basketball.html").read_text(encoding="utf-8")
    football = (ROOT / "football.html").read_text(encoding="utf-8")
    tennis = (ROOT / "tennis.html").read_text(encoding="utf-8")
    drawer = (ROOT / "ticket-drawer.js").read_text(encoding="utf-8")
    api = (ROOT / "functions" / "api" / "sportybet-booking.js").read_text(encoding="utf-8")
    nba_client = (ROOT / "basketball-live.js").read_text(encoding="utf-8")

    require('data-sport="basketball"' in basketball, "Basketball page lost its sport identity")
    require('data-sport="football"' in football, "Football page lost its sport identity")
    require('data-sport="tennis"' in tennis, "Tennis page lost its sport identity")
    require("builderOnly=1" in drawer and "#basketball-builders" in drawer,
            "Basketball drawer must target its native four-builder workspace")
    require("function manualBuilderMarkup" in drawer and "generateManualCode" in drawer,
            "Football/tennis manual slip UI or generation action is missing")
    require("./api/sportybet?" in drawer and "pageRequests" in drawer and "[1, 2, 3]" in drawer,
            "Manual slip must fetch current SportyBet fixture pages")
    require("localStorage" in drawer and "match-signal:sportybet-manual-ticket:v1" in drawer,
            "Manual ticket selections must persist across the football and tennis pages")
    require("manual_selections" in drawer and "'./api/sportybet-booking'" in drawer,
            "Manual slip is not connected to the existing SportyBet booking endpoint")
    require("mode: 'manual'" in drawer, "Manual slip request mode is missing")
    require("manualMode" in api and "INVALID_MANUAL_SELECTION" in api,
            "Booking endpoint is missing its manual selection validation")
    require("new Set(ids).size !== ids.length" in api,
            "Booking endpoint must reject duplicate fixtures in a slip")
    require("Participant identity changed in SportyBet current catalogue." in api,
            "Booking endpoint must recheck participants against the live catalogue")
    require("isOpenEvent(event)" in api and "buildSelection(leg, event)" in api,
            "Booking endpoint must revalidate event timing and current market/outcome IDs")
    require("nbaTotalsReleaseQualified(S.totalsOos)" in nba_client,
            "NBA totals qualification lock was unexpectedly removed")
    require("Math.random()" not in drawer and "crypto.randomUUID" not in drawer,
            "The drawer must never fabricate booking codes client-side")
    print("ticket drawer contract: PASS")


if __name__ == "__main__":
    main()
