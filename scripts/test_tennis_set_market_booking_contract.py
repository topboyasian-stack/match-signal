"""Static end-to-end contract tests for tennis Player-to-Win-a-Set."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


api = (ROOT / "functions" / "api" / "sportybet-booking.js").read_text(encoding="utf-8")
drawer = (ROOT / "ticket-drawer.js").read_text(encoding="utf-8")
builder = (ROOT / "expansion-odds-builder.js").read_text(encoding="utf-8")
adapter = (ROOT / "scripts" / "tennis_set_market_reassessment.py").read_text(encoding="utf-8")
tracker = (ROOT / "scripts" / "odds_ticket_tracker.py").read_text(encoding="utf-8")
model = (ROOT / "scripts" / "tennis_set_market_model.py").read_text(encoding="utf-8")

require("function findPlayerToWinSetSelection(leg, event)" in api,
        "Booking API must resolve the exact current tennis player-set market.")
require("marketId !== requestedMarketId || specifier !== requestedSpecifier" in api,
        "Booking must match the exact market ID and exact specifier.")
require("yes.id !== requestedOutcomeId" in api,
        "Booking must reject a changed Yes outcome ID.")
require("if (!yes || !no) continue" in api,
        "Booking must require a complete active Yes/No pair.")
require("sport === 'tennis' && market === 'player_to_win_set'" in api,
        "Tennis set-market legs must route through the dedicated exact mapper.")
require("Math.abs(Number(selection?.odds) - quotedOdds) <= 0.01" in api,
        "Manual booking must reject a changed Yes price.")
require("MANUAL_TICKET_REJECTED_PARTIAL" in api,
        "Any invalid set-market leg must preserve all-or-nothing manual ticket rejection.")

require("item.market==='player_to_win_set'" in drawer,
        "Shared ticket persistence must whitelist only the supported tennis set market.")
require("outcome_id:market==='player_to_win_set'?outcomeId:null" in drawer and "market_quote_timestamp:market==='player_to_win_set'?quoteTimestamp:null" in drawer,
        "Shared ticket must preserve outcome identity and original quote timestamp.")
require("sportybet_outcome_id:item.outcome_id" in drawer and "market_quote_timestamp:item.market_quote_timestamp" in drawer,
        "Booking request must carry the exact outcome and quote snapshot.")
require("data-ticket-market-specifier" in drawer and "data-ticket-outcome-id" in drawer,
        "Ticket drawer must ingest exact market specifier and outcome identity from the UI.")

require("function manualTennisSetTicketButton(leg)" in builder,
        "Odds Builder must expose the independently-qualified tennis set-market lane.")
require("detail.status!=='QUALIFIED_PAPER_RESEARCH'" in builder and "x.builder_eligible!==true" in builder,
        "Only the independent set-market gate and ordinary leg gate may expose a Builder ticket action.")
require('data-ticket-market="player_to_win_set"' in builder and "data-ticket-outcome-id" in builder,
        "Builder ticket action must pass the exact market and outcome identities.")

require('"pick": str(detail.get("player_side") or "").lower()' in adapter,
        "Set market candidate must keep the named participant side machine-readable.")
require('"sportybet_outcome_id": row.get("sportybet_outcome_id")' in adapter,
        "Set market candidate must preserve SportyBet outcome identity.")
require('"selection_label": f"{player} to win at least one set"' in adapter,
        "Set market candidate must preserve a user-facing selection label.")

require('"player_to_win_set"' in tracker and '"sets_won_p1" if side == "p1" else "sets_won_p2"' in tracker,
        "Ticket history must settle the exact selected player's set-win proposition from actual set counts.")
require("MIN_WALK_FORWARD_MATCHES = 60" in model and "MIN_WALK_FORWARD_OBSERVATIONS = 100" in model,
        "Set-market qualification must retain its independent walk-forward sample requirements.")

print("Tennis Player-to-Win-a-Set end-to-end contract: PASS")
