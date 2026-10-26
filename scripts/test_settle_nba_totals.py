import unittest
from scripts.settle_nba_totals import result_for

def prediction(**overrides):
    p = {"event_id":"abc","start_time":"2026-10-25T20:00:00+00:00",
         "prediction_created_at":"2026-10-25T19:00:00+00:00",
         "player_1":"Home Team","player_2":"Away Team","expected_total":220.5,
         "model":"test","markets":{"total_ou":{"market_id":"225","line":220.5,"pick":"over","source":"SportyBet Nigeria"}}}
    p.update(overrides)
    return p

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
        p["markets"]["total_ou"].update({"line":225.5,"pick":"under"})
        self.assertEqual(result_for(p, event())["result"], "under")
        self.assertNotEqual(result_for(p, event())["pick"], "under")
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

if __name__ == "__main__":
    unittest.main()
