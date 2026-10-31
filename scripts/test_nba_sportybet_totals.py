import json
import sys
import tempfile
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
# Forecasts can refresh before tip-off, but must freeze once the game starts.
fresh_snapshot = {"generated_at": (now-timedelta(hours=2)).isoformat(), "totals_model_version": pipeline.NBA_TOTALS_MODEL_VERSION}
stale_snapshot = {"generated_at": (now-timedelta(hours=7)).isoformat(), "totals_model_version": pipeline.NBA_TOTALS_MODEL_VERSION}
legacy_snapshot = {"generated_at": (now-timedelta(hours=1)).isoformat(), "totals_model_version": "nba-total-v1"}
assert pipeline.should_refresh_nba_prediction(fresh_snapshot, start, now) is False
assert pipeline.should_refresh_nba_prediction(stale_snapshot, start, now) is True
assert pipeline.should_refresh_nba_prediction(stale_snapshot, now-timedelta(minutes=1), now) is False
assert pipeline.should_refresh_nba_prediction({}, start, now) is True
assert pipeline.should_refresh_nba_prediction(legacy_snapshot, start, now) is True, "pregame forecasts from old totals logic must refresh into the versioned model"

market = pipeline.sportybet_total_for_fixture(fixture, feed)
assert market and market["market_id"] == "225" and market["line"] == 228.5
assert market["settlement"] == "Official final score including overtime"
assert market["source"] == "SportyBet Nigeria"
assert market["quote_capture_basis"] == "SportyBet API response observed_at"

# The source may return several specifiers for market 225. Select a complete,
# balanced main pair instead of blindly taking the first one.
multi_line_feed = [dict(feed[0], markets=[
    dict(feed[0]["markets"][0], specifier="total=208.5", outcomes=[
        {"name": "Over", "odds": 1.25, "active": True},
        {"name": "Under", "odds": 4.10, "active": True},
    ]),
    dict(feed[0]["markets"][0], specifier="total=228.5", outcomes=[
        {"name": "Over", "odds": 1.91, "active": True},
        {"name": "Under", "odds": 1.89, "active": True},
    ]),
    dict(feed[0]["markets"][0], specifier="total=238.5", outcomes=[
        {"name": "Over", "odds": 3.80, "active": True},
        {"name": "Under", "odds": 1.28, "active": True},
    ]),
])]
selected_line = pipeline.sportybet_total_for_fixture(fixture, multi_line_feed, expected_total=235.0)
assert selected_line and selected_line["line"] == 228.5
assert selected_line["over_odds"] == 1.91 and selected_line["under_odds"] == 1.89
assert selected_line["quote_capture_basis"] == "SportyBet API response observed_at"


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

# First qualified totals publication is frozen once per event and cannot be overwritten.
snapshot_prediction = {
    "sport": "basketball", "league": "NBA", "event_id": "espn:test-snapshot",
    "start_time": start.isoformat(), "player_1": fixture["home"], "player_2": fixture["away"],
    "prediction_created_at": now.isoformat(), "generated_at": now.isoformat(),
    "totals_model_version": pipeline.NBA_TOTALS_MODEL_VERSION,
    "expected_total": 235.0, "markets": attached["markets"],
}
snapshot = pipeline.nba_total_publication_snapshot(snapshot_prediction, now.isoformat())
assert snapshot and snapshot["publication_snapshot_verified"] is True
assert snapshot["totals_model_version"] == pipeline.NBA_TOTALS_MODEL_VERSION
assert snapshot["publication_snapshot_id"].startswith("nba-total-pub:")
assert snapshot["markets"]["total_ou"]["over_odds"] == 1.91
assert snapshot["markets"]["total_ou"]["under_odds"] == 1.89
# Price provenance is frozen for every prediction with a valid current SportyBet
# pair, even when the model has no directional lean. No-lean rows never enter ROI.
no_lean_prediction = json.loads(json.dumps(snapshot_prediction))
no_lean_prediction["event_id"] = "espn:test-no-lean"
no_lean_prediction["markets"]["total_ou"]["pick"] = None
no_lean_prediction["markets"]["total_ou"]["lean"] = "NO_CLEAR_LEAN"
no_lean_snapshot = pipeline.nba_total_publication_snapshot(no_lean_prediction, now.isoformat())
assert no_lean_snapshot and no_lean_snapshot["publication_snapshot_verified"] is True
assert no_lean_snapshot["markets"]["total_ou"]["line"] == 228.5
assert no_lean_snapshot["markets"]["total_ou"]["over_odds"] == 1.91
assert no_lean_snapshot["markets"]["total_ou"]["under_odds"] == 1.89


with tempfile.TemporaryDirectory() as tmp:
    snapshot_path = Path(tmp) / "nba_totals_publication_snapshots.json"
    first = pipeline.append_nba_totals_publication_snapshots([snapshot_prediction], snapshot_path, now.isoformat())
    assert first == {"added": 1, "total": 1}
    changed = json.loads(json.dumps(snapshot_prediction))
    changed["markets"]["total_ou"]["line"] = 231.5
    second = pipeline.append_nba_totals_publication_snapshots([changed], snapshot_path, (now + timedelta(minutes=30)).isoformat())
    saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert second == {"added": 0, "total": 1}, "a later desk refresh must not overwrite the first published selection"
    assert saved[0]["markets"]["total_ou"]["line"] == 228.5

stale_prediction = json.loads(json.dumps(snapshot_prediction))
stale_prediction["markets"]["total_ou"]["quote_timestamp"] = (now - timedelta(minutes=20)).isoformat()
assert pipeline.nba_total_publication_snapshot(stale_prediction, now.isoformat()) is None, "stale prices must not be published into the eligible snapshot cohort"

settlement = (ROOT / "scripts" / "settle_expansion.py").read_text(encoding="utf-8")
assert "total_ou_final_points" in settlement and "Official final score including overtime" in settlement
assert 'final_total = float(hg) + float(ag)' in settlement
print("NBA SportyBet total tests passed: exact fixture/time, market 225 incl. OT, fresh quotes, market-blind model and OT-aware settlement.")
