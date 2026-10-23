import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import live_expansion_pipeline as pipeline

now = datetime.now(timezone.utc)
start = now + timedelta(hours=3)
quote_time = now.isoformat()
fixture = {"home": "Los Angeles Lakers", "away": "Boston Celtics", "date": start.isoformat()}
feed = [{
    "event_id": "sr:match:test123",
    "home": "LA Lakers", "away": "Boston Celtics",
    "start_time": start.isoformat(), "fetched_at": quote_time,
    "markets": [{
        "id": "225", "name": "Over/Under incl. overtime", "specifier": "total=228.5",
        "outcomes": [
            {"id": "12", "name": "Over", "odds": 1.91, "active": True},
            {"id": "13", "name": "Under", "odds": 1.89, "active": True},
        ],
    }],
}]
market = pipeline.sportybet_total_for_fixture(fixture, feed)
assert market and market["market_id"] == "225" and market["line"] == 228.5
assert market["settlement"] == "Official final score including overtime"
assert market["source"] == "SportyBet Nigeria"

wrong_team = [dict(feed[0], home="Chicago Bulls")]
assert pipeline.sportybet_total_for_fixture(fixture, wrong_team) is None, "never match odds to a different game"
wrong_market = [dict(feed[0], markets=[dict(feed[0]["markets"][0], id="18")])]
assert pipeline.sportybet_total_for_fixture(fixture, wrong_market) is None, "standard O/U must not masquerade as the explicit incl-OT market"
suspended_market = [dict(feed[0], markets=[dict(feed[0]["markets"][0], status="suspended")])]
assert pipeline.sportybet_total_for_fixture(fixture, suspended_market) is None, "suspended SportyBet totals must not be used"
stale = [dict(feed[0], fetched_at=(now-timedelta(minutes=20)).isoformat())]
assert pipeline.sportybet_total_for_fixture(fixture, stale) is None, "stale quotes must not be used as current prices"

prediction = {
    "start_time": start.isoformat(), "expected_total": 235.0,
    "markets": {"moneyline": {"home": 0.6, "away": 0.4}},
}
attached = pipeline.apply_sportybet_total_snapshot(prediction, fixture, feed)
total = attached["markets"]["total_ou"]
assert total["pick"] == "over" and total["lean"] == "OVER"
assert total["projection_edge_points"] == 6.5
assert total["model_is_market_blind"] is True
assert attached["markets"]["moneyline"]["home"] == 0.6, "SportyBet prices must not alter independent winner probabilities"

settlement = (ROOT / "scripts" / "settle_expansion.py").read_text(encoding="utf-8")
assert "total_ou_final_points" in settlement and "Official final score including overtime" in settlement
assert 'final_total = float(hg) + float(ag)' in settlement
print("NBA SportyBet total tests passed: exact fixture/time, market 225 incl. OT, fresh quotes, market-blind model and OT-aware settlement.")
