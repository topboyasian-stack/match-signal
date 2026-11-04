import unittest
from pathlib import Path
from settle_nba_totals import (
    result_for, price_audit_fields, candidate_key, ledger_key,
    select_settlement_snapshot, matching_snapshot_for_ledger,
    valid_probability_snapshot, select_probability_snapshot, probability_result_for,
    PROSPECTIVE_CUTOFF_UTC,
)

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


def prospective_probability_snapshot(**overrides):
    p = prediction(
        event_id="abc",
        start_time="2026-11-03T00:00:00+00:00",
        prediction_created_at="2026-11-02T05:08:55+00:00",
        published_at="2026-11-02T05:09:07+00:00",
        expected_total=220.5,
        totals_model_version="nba-total-v5.1-pace-efficiency-calibrated",
        publication_snapshot_id="nba-total-pub:abc",
        publication_snapshot_verified=True,
        publication_snapshot_kind="immutable_sportybet_market_225_revision",
    )
    p["markets"]["total_ou"].update({
        "market_id": "225",
        "source": "SportyBet Nigeria",
        "sportybet_event_id": "sr:match:abc",
        "quote_capture_basis": "SportyBet API response observed_at",
        "quote_timestamp": "2026-11-02T05:09:06+00:00",
        "line": 220.5,
        "expected_total": 220.5,
        "over_odds": 1.91,
        "under_odds": 1.89,
        "pick": None,
    })
    p.update(overrides)
    return p


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
        self.assertTrue(audit["publication_snapshot_verified"])
        self.assertEqual(audit["sportybet_event_id"], "sr:match:abc")
        self.assertEqual(audit["quote_capture_basis"], "SportyBet API response observed_at")

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
        self.assertIn("no_verified_immutable_publication_snapshot", audit["roi_ineligibility_reasons"])

    def test_missing_exact_sportybet_event_blocks_roi(self):
        p = prediction()
        p["published_at"] = "2026-10-25T19:00:00+00:00"
        p["publication_snapshot_id"] = "nba-total-snapshot-abc"
        p["publication_snapshot_verified"] = True
        p["markets"]["total_ou"]["sportybet_event_id"] = ""
        audit = price_audit_fields(p, p["markets"]["total_ou"], parse_time_for_test(p["prediction_created_at"]))
        self.assertFalse(audit["roi_eligible"])
        self.assertIn("missing_exact_sportybet_event_id", audit["roi_ineligibility_reasons"])



    def test_first_directional_snapshot_is_selected_after_neutral_revisions(self):
        neutral = prediction()
        neutral["published_at"] = "2026-10-25T18:50:00+00:00"
        neutral["publication_snapshot_id"] = "neutral-1"
        neutral["publication_snapshot_verified"] = True
        neutral["markets"]["total_ou"]["pick"] = None
        neutral["markets"]["total_ou"]["line"] = 221.5

        first_directional = prediction()
        first_directional["published_at"] = "2026-10-25T19:00:00+00:00"
        first_directional["publication_snapshot_id"] = "under-1"
        first_directional["publication_snapshot_verified"] = True
        first_directional["markets"]["total_ou"].update({"pick": "under", "line": 220.5})

        later_directional = prediction()
        later_directional["published_at"] = "2026-10-25T19:15:00+00:00"
        later_directional["publication_snapshot_id"] = "over-2"
        later_directional["publication_snapshot_verified"] = True
        later_directional["markets"]["total_ou"].update({"pick": "over", "line": 224.5})

        chosen = select_settlement_snapshot([neutral, later_directional, first_directional])
        self.assertEqual(chosen["publication_snapshot_id"], "under-1")
        self.assertEqual(chosen["markets"]["total_ou"]["pick"], "under")

    def test_all_neutral_snapshots_remain_non_directional(self):
        first = prediction()
        first["published_at"] = "2026-10-25T18:50:00+00:00"
        first["publication_snapshot_id"] = "neutral-first"
        first["markets"]["total_ou"]["pick"] = None
        second = prediction()
        second["published_at"] = "2026-10-25T19:00:00+00:00"
        second["publication_snapshot_id"] = "neutral-second"
        second["markets"]["total_ou"]["pick"] = None
        self.assertEqual(select_settlement_snapshot([second, first])["publication_snapshot_id"], "neutral-first")



    def test_neutral_fixture_is_settled_for_probability_without_becoming_a_bet(self):
        snapshot = prospective_probability_snapshot()
        self.assertTrue(valid_probability_snapshot(snapshot))
        row = probability_result_for(snapshot, event())
        self.assertIsNotNone(row)
        self.assertEqual(row["result"], "over")
        self.assertIsNone(row["pick"])
        self.assertTrue(row["probability_validation_only"])
        self.assertEqual(row["publication_snapshot_id"], "nba-total-pub:abc")
        self.assertEqual(row["settlement_source"], "ESPN official scoreboard event ID; final score includes overtime")
        self.assertNotIn("roi_eligible", row, "Probability-only fixtures must never enter ROI accounting.")

    def test_probability_validation_uses_first_snapshot_even_if_it_is_neutral(self):
        neutral = prospective_probability_snapshot()
        later = prospective_probability_snapshot(
            published_at="2026-11-02T05:10:00+00:00",
            publication_snapshot_id="nba-total-pub:later",
        )
        later["markets"]["total_ou"]["pick"] = "under"
        chosen = select_probability_snapshot([later, neutral])
        self.assertEqual(chosen["publication_snapshot_id"], "nba-total-pub:abc")
        self.assertIsNone(chosen["markets"]["total_ou"]["pick"])

    def test_probability_fixture_requires_fresh_exact_market_225_prices(self):
        stale = prospective_probability_snapshot()
        stale["markets"]["total_ou"]["quote_timestamp"] = "2026-11-02T04:50:00+00:00"
        self.assertFalse(valid_probability_snapshot(stale))
        after_publication = prospective_probability_snapshot()
        after_publication["markets"]["total_ou"]["quote_timestamp"] = "2026-11-02T05:10:00+00:00"
        self.assertFalse(valid_probability_snapshot(after_publication))
        wrong_market = prospective_probability_snapshot()
        wrong_market["markets"]["total_ou"]["market_id"] = "18"
        self.assertFalse(valid_probability_snapshot(wrong_market))
        no_under_price = prospective_probability_snapshot()
        no_under_price["markets"]["total_ou"].pop("under_odds")
        self.assertFalse(valid_probability_snapshot(no_under_price))
        unverified = prospective_probability_snapshot(publication_snapshot_verified=False)
        self.assertFalse(valid_probability_snapshot(unverified))

    def test_probability_fixture_obeys_frozen_cutoff_and_exact_espn_event(self):
        self.assertEqual(PROSPECTIVE_CUTOFF_UTC.isoformat(), "2026-11-02T02:00:00+00:00")
        before_cutoff = prospective_probability_snapshot(
            published_at="2026-11-02T01:59:59+00:00"
        )
        before_cutoff["markets"]["total_ou"]["quote_timestamp"] = "2026-11-02T01:59:58+00:00"
        self.assertFalse(valid_probability_snapshot(before_cutoff))
        self.assertIsNone(probability_result_for(prospective_probability_snapshot(), event(id="other")))
        unfinished = event(status={"type": {"completed": False, "state": "in"}})
        self.assertIsNone(probability_result_for(prospective_probability_snapshot(), unfinished))

    def test_probability_settlement_artifact_is_persisted_separately_from_bet_ledger(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/nba-totals-settlement.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("data/nba_totals_probability_settlements.json", workflow)
        self.assertIn("git add data/nba_totals_ledger.json data/nba_totals_probability_settlements.json", workflow)
        self.assertIn("requests pandas", workflow, "Settlement CI must install pandas required by the import chain.")
        push_paths = workflow.split("  push:", 1)[1].split("permissions:", 1)[0]
        self.assertNotIn(
            "data/nba_totals_probability_settlements.json",
            push_paths,
            "Settlement output commits must not retrigger the settlement workflow through push paths.",
        )

    def test_legacy_ledger_cannot_borrow_v5_publication_snapshot(self):
        legacy_key = ("abc", "legacy")
        snapshots = {
            ("abc", "nba-total-v5-pace-efficiency-calibrated"): {
                "event_id": "abc",
                "totals_model_version": "nba-total-v5-pace-efficiency-calibrated",
                "publication_snapshot_verified": True,
                "publication_snapshot_id": "v5-snapshot",
            }
        }
        self.assertIsNone(matching_snapshot_for_ledger(snapshots, legacy_key))
        self.assertIs(
            matching_snapshot_for_ledger(
                snapshots, ("abc", "nba-total-v5-pace-efficiency-calibrated")
            ),
            snapshots[("abc", "nba-total-v5-pace-efficiency-calibrated")],
        )

    def test_same_fixture_can_settle_separate_model_versions(self):
        v3 = prediction()
        v3["totals_model_version"] = "nba-total-v3-matchup-recent-team-total"
        v3["publication_snapshot_id"] = "snapshot-v3"
        v4 = prediction()
        v4["totals_model_version"] = "nba-total-v4-pace-efficiency-calibrated"
        v4["publication_snapshot_id"] = "snapshot-v4"
        self.assertNotEqual(candidate_key(v3), candidate_key(v4))
        row_v3 = result_for(v3, event())
        row_v4 = result_for(v4, event())
        self.assertNotEqual(row_v3["ledger_id"], row_v4["ledger_id"])
        self.assertNotEqual(ledger_key(row_v3), ledger_key(row_v4))
        self.assertEqual(row_v3["event_id"], row_v4["event_id"])
        self.assertEqual(row_v3["result"], row_v4["result"])

if __name__ == "__main__":
    unittest.main()
