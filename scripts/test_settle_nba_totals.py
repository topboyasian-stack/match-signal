import unittest
from settle_nba_totals import result_for, price_audit_fields

def prediction(**overrides):
    p = {"event_id":"abc","start_time":"2026-10-25T20:00:00+00:00",
         "prediction_created_at":"2026-10-25T19:00:00+00:00",
         "player_1":"Home Team","player_2":"Away Team","expected_total":220.5,
         "model":"test","markets":{"total_ou":{"market_id":"225","line":220.5,"pick":"over","source":"SportyBet Nigeria", "sportybet_event_id":"sr:match:abc", "quote_capture_basis":"SportyBet API response observed_at", "quote_timestamp":"2026-10-25T18:55:00+00:00", "over_odds":1.91, "under_odds":1.89}}}
    p.update(overrides)
    return p

def parse_time_for_test(value):
    from datetime import datetime
    return datetime.fromisoformat(value)

def event(**overrides):
    e = {"id":"abc","status":{"type":{"completed":True,"state":"post"}},
         "competitions":[{"competitors":[{"homeAway":"home","score":"110"},{"homeAway":"away","score":"111"}]}]}
    e.update(overrides)
    return e

class SettlementTests(unittest.TestCase):
    def test_over_win_includes_final_points(self):
        self.assertEqual(result_for(prediction(), event())["result"], "over")
    def test_push_is_not_a_loss(self):
        p = prediction()
        p["markets"]["total_ou"]["line"] = 221
        self.assertEqual(result_for(p, event())["result"], "push")
    def test_under_loss_is_recorded(self):
        p = prediction()
        p["markets"]["total_ou"].update({"line":220.5,"pick":"under"})
        self.assertEqual(result_for(p, event())["result"], "over")
        self.assertNotEqual(result_for(p, event())["pick"], result_for(p, event())["result"])
    def test_wrong_fixture_id_rejected(self):
        self.assertIsNone(result_for(prediction(), event(id="wrong")))
    def test_missing_market_rejected(self):
        p = prediction()
        p["markets"]["total_ou"]["market_id"] = "1"
        self.assertIsNone(result_for(p, event()))
    def test_missing_final_score_rejected(self):
        self.assertIsNone(result_for(prediction(), event(competitions=[{"competitors":[]}])) )
    def test_postgame_prediction_rejected(self):
        p = prediction()
        p["prediction_created_at"] = "2026-10-25T21:00:00+00:00"
        self.assertIsNone(result_for(p, event()))
    def test_unfinished_game_rejected(self):
        self.assertIsNone(result_for(prediction(), event(status={"type":{"completed":False,"state":"in"}})))
    def test_price_pair_is_preserved_in_settlement(self):
        row = result_for(prediction(), event())
        self.assertEqual(row["over_odds"], 1.91)
        self.assertEqual(row["under_odds"], 1.89)
        self.assertTrue(row["price_pair_valid"])
        self.assertEqual(row["quote_age_minutes_at_publication"], 5.0)
        self.assertFalse(row["roi_eligible"], "a frozen publication snapshot is still required")

    def test_roi_requires_fresh_prices_and_explicit_verified_snapshot(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:00:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = True
        market = p["markets"]["total_ou"]
        audit = price_audit_fields(p, market, parse_time_for_test(p["prediction_created_at"]))
        self.assertTrue(audit["roi_eligible"])
        self.assertTrue(audit["publication_snapshot_verified"])\n        self.assertEqual(audit["sportybet_event_id"], "sr:match:abc")\n        self.assertEqual(audit["quote_capture_basis"], "SportyBet API response observed_at")\n        self.assertEqual(audit["sportybet_event_id"], "sr:match:abc")\n        self.assertEqual(audit["quote_capture_basis"], "SportyBet API response observed_at")

    def test_stale_quote_not_roi_eligible(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:20:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = True
        market = p["markets"]["total_ou"]
        audit = price_audit_fields(p, market, parse_time_for_test(p["prediction_created_at"]))
        self.assertFalse(audit["roi_eligible"])
        self.assertIn("quote_older_than_15_minutes_at_publication", audit["roi_ineligibility_reasons"])

    def test_quote_after_publication_not_roi_eligible(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:00:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = True
        p["markets"]["total_ou"]["quote_timestamp"] = "2026-10-25T19:01:00+00:00"
        audit = price_audit_fields(p, p["markets"]["total_ou"], parse_time_for_test(p["prediction_created_at"]))
        self.assertFalse(audit["roi_eligible"])
        self.assertIn("quote_not_proven_available_at_publication", audit["roi_ineligibility_reasons"])

    def test_missing_price_blocks_roi_eligibility(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:00:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = True
        p["markets"]["total_ou"].pop("under_odds")
        audit = price_audit_fields(p, p["markets"]["total_ou"], parse_time_for_test(p["prediction_created_at"]))
        self.assertFalse(audit["roi_eligible"])
        self.assertIn("missing_or_invalid_over_under_decimal_prices", audit["roi_ineligibility_reasons"])

    def test_unverified_snapshot_blocks_roi_eligibility(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:00:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = False
        audit = price_audit_fields(p, p["markets"]["total_ou"], parse_time_for_test(p["prediction_created_at"]))
        self.assertFalse(audit["roi_eligible"])
        self.assertIn("no_verified_immutable_publication_snapshot", audit["roi_ineligibility_reasons"])\n\n    def test_missing_exact_sportybet_event_blocks_roi(self):\n        p = prediction()\n        p["published_at"] = "2026-10-25T19:00:00+00:00"\n        p["publication_snapshot_id"] = "nba-total-snapshot-abc"\n        p["publication_snapshot_verified"] = True\n        p["markets"]["total_ou"]["sportybet_event_id"] = ""\n        audit = price_audit_fields(p, p["markets"]["total_ou"], parse_time_for_test(p["prediction_created_at"]))\n        self.assertFalse(audit["roi_eligible"])\n        self.assertIn("missing_exact_sportybet_event_id", audit["roi_ineligibility_reasons"])

if __name__ == "__main__":
    unittest.main()
