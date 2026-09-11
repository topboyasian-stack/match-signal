"""OddsPapi runner for Match Signal basketball.

Uses one tournament/fixture discovery call and fetches detailed odds only for
the nearest two BBL fixtures, keeping the free API quota practical while still
refreshing current markets. The existing basketball_hybrid prediction and
settlement logic remains the single source of truth.
"""
from datetime import datetime, timezone
import os

import basketball_hybrid as bh


def oddspapi_markets(fixtures):
    key = os.getenv("ODDSPAPI_API_KEY", "").strip()
    if not key:
        return {}, "not_configured"

    tournament_id, tournament_status = bh.oddspapi_tournament_id()
    if not tournament_id:
        return {}, tournament_status

    data, status = bh.get_json(
        bh.ODDSPAPI_BASE,
        "/v4/fixtures",
        {
            "tournamentId": str(tournament_id),
            "statusId": 0,
            "hasOdds": "true",
            "language": "en",
        },
        key,
    )
    if status != "ok" or not isinstance(data, list):
        return {}, status

    candidates = []
    for row in data:
        if not isinstance(row, dict):
            continue
        rh = row.get("participant1Name") or ""
        ra = row.get("participant2Name") or ""
        if not rh or not ra:
            continue
        for fixture in fixtures:
            if bh.name_match(rh, fixture["home"]) and bh.name_match(ra, fixture["away"]):
                candidates.append((fixture, row))
                break

    candidates.sort(key=lambda item: item[0]["start_time"])
    markets = {}
    # Two detailed odds calls per pipeline run keeps the free quota usable
    # while ensuring the next/current BBL games get refreshed markets.
    for fixture, row in candidates[:2]:
        fixture_id = row.get("fixtureId")
        if not fixture_id:
            continue
        payload, odds_status = bh.get_json(
            bh.ODDSPAPI_BASE,
            "/v4/odds",
            {"fixtureId": str(fixture_id), "language": "en", "verbosity": 3, "oddsFormat": "decimal"},
            key,
        )
        if odds_status != "ok" or not isinstance(payload, dict):
            continue
        parsed = bh.parse_oddspapi_markets(payload, fixture["home"], fixture["away"])
        parsed["fixture_id"] = fixture_id
        parsed["provider"] = "OddsPapi"
        if parsed:
            markets[fixture["event_id"]] = parsed

    if not candidates:
        return {}, "no_matching_fixtures"
    return markets, "ok" if markets else "matching_fixtures_no_markets"


bh.oddspapi_markets = oddspapi_markets

if __name__ == "__main__":
    bh.main()
