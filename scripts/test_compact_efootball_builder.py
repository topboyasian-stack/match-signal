#!/usr/bin/env python3
"""Regression tests for the compact, exact-evidence eFootball ticket lane."""
from datetime import datetime, timedelta, timezone
import math
import unittest
from unittest.mock import patch
import odds_builder as builder


def leg(index, *, odds=1.15, probability=0.90, product="efootball_gt",
        expected_value=0.10, builder_eligible=True, lane="efootball_exact_evidence_value",
        event_id=None, participant_a=None, participant_b=None, minute=None):
    start=datetime(2026,10,10,10,0,tzinfo=timezone.utc)+timedelta(minutes=minute if minute is not None else index*3)
    a=participant_a or f"player-{index}-a"
    b=participant_b or f"player-{index}-b"
    return {
        "sport":"virtual","product":product,"qualification_lane":lane,
        "builder_eligible":builder_eligible,"model_probability":probability,
        "expected_value":expected_value,"bookmaker_odds":odds,"model_edge":0.04,
        "evidence_score":0.9,"event_id":event_id or f"event-{index}",
        "start_time":start.isoformat(),"match":f"Team A ({a}) vs Team B ({b})"
    }


class CompactEfootballBuilderTests(unittest.TestCase):
    def setUp(self):
        self.original_span=builder.COMPACT_EFOOTBALL_MAX_KICKOFF_SPAN_MINUTES
        builder.COMPACT_EFOOTBALL_MAX_KICKOFF_SPAN_MINUTES=60
        self.calibration_patch=patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value={
            "gamma":1.0,"sample":40,"settled_lane_ticket_count":40,
            "missing_raw_joint_probability_count":0,"trained":True,
            "oos_sample":20,"raw_oos_brier":0.25,"calibrated_oos_brier":0.24,
            "oos_brier_improved":True,"promotion_allowed":True
        })
        self.calibration_patch.start()

    def tearDown(self):
        self.calibration_patch.stop()
        builder.COMPACT_EFOOTBALL_MAX_KICKOFF_SPAN_MINUTES=self.original_span

    def test_five_short_price_legs_can_reach_two_x_without_weakening_leg_floor(self):
        rows=[leg(i,odds=1.15,probability=0.90) for i in range(5)]
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(len(selected),5)
        odds=math.prod(x["bookmaker_odds"] for x in selected)
        self.assertGreaterEqual(odds,2.00)
        self.assertTrue(all(x["model_probability"]>=0.80 for x in selected))
        self.assertTrue(all(x["qualification_lane"]=="efootball_exact_evidence_value" for x in selected))
        self.assertGreaterEqual(math.prod(x["model_probability"] for x in selected)*odds-1,0.02)
        self.assertEqual(diag["reason"],"qualified_compact_efootball_combination")

    def test_four_leg_combo_can_qualify_when_its_product_reaches_two_x(self):
        rows=[leg(i,odds=1.20,probability=0.90) for i in range(4)]
        selected,_=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(len(selected),4)
        self.assertGreaterEqual(math.prod(x["bookmaker_odds"] for x in selected),2.00)

    def test_below_65_percent_leg_is_never_used_to_reach_two_x(self):
        rows=[leg(i,odds=1.10,probability=0.90) for i in range(4)]
        rows.append(leg(4,odds=1.60,probability=0.64))
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["candidate_count"],4, "the 64% leg is below the exact-evidence lane floor")
        self.assertEqual(diag["reason"],"no_compact_combination_passed_all_gates")

    def test_65_to_79_percent_exact_evidence_legs_are_evaluated_but_ticket_roi_still_applies(self):
        rows=[leg(i,odds=1.25,probability=0.70) for i in range(4)]
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["candidate_count"],4, "70% exact-evidence legs must reach the constructor")
        self.assertEqual(diag["combinations_checked"],1)
        self.assertGreater(diag["rejected_expected_roi"],0, "low joint probability must still fail whole-ticket ROI")

    def test_exact_evidence_value_constructor_accepts_70_percent_pair_when_all_gates_pass(self):
        rows=[
            leg(0,odds=2.35,probability=0.70,expected_value=0.645,minute=0),
            leg(1,odds=2.35,probability=0.70,expected_value=0.645,minute=5)
        ]
        selected,diag=builder._construct_efootball_value_batch(rows,min_odds=2.70,max_legs=4)
        self.assertEqual(len(selected),2)
        self.assertEqual(diag["candidate_count"],2)
        self.assertGreaterEqual(diag["combined_odds"],2.70)
        self.assertGreaterEqual(diag["roi"],0.02)
        self.assertEqual(selected[0]["qualification_lane"],"efootball_exact_evidence_value")

    def test_exact_evidence_value_constructor_rejects_below_65_percent_pair(self):
        rows=[
            leg(0,odds=2.35,probability=0.64,expected_value=0.50,minute=0),
            leg(1,odds=2.35,probability=0.64,expected_value=0.50,minute=5)
        ]
        selected,diag=builder._construct_efootball_value_batch(rows,min_odds=2.70,max_legs=4)
        self.assertEqual(selected,[])
        self.assertEqual(diag["candidate_count"],0)

    def test_ticket_must_retain_two_percent_expected_roi(self):
        rows=[leg(i,odds=1.20,probability=0.80) for i in range(4)]
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertGreater(diag["rejected_expected_roi"],0)

    def test_same_event_and_reused_participant_are_rejected(self):
        rows=[
            leg(0,odds=1.25,probability=0.95),
            leg(1,odds=1.25,probability=0.95,event_id="event-0"),
            leg(2,odds=1.25,probability=0.95),
            leg(3,odds=1.25,probability=0.95),
            leg(4,odds=1.25,probability=0.95)
        ]
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertTrue(selected)
        ids=[x["event_id"] for x in selected]
        self.assertEqual(len(ids),len(set(ids)))
        participants=[p for x in selected for p in builder._participants(x)]
        self.assertEqual(len(participants),len(set(participants)))
        self.assertGreater(diag["rejected_correlated"],0)

    def test_vfootball_zoom_unqualified_lane_and_unknown_products_are_excluded(self):
        rows=[
            leg(0,odds=1.30,probability=0.95,product="vfootball"),
            leg(1,odds=1.30,probability=0.95,product="zoom"),
            leg(2,odds=1.30,probability=0.95,product="unknown"),
            leg(3,odds=1.30,probability=0.95,lane="model_first_value"),
            leg(4,odds=1.30,probability=0.95,builder_eligible=False)
        ]
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["candidate_count"],0)

    def test_legs_must_fit_price_floor_and_kickoff_span(self):
        low_price=[leg(i,odds=1.10,probability=0.95) for i in range(5)]
        selected,_=builder._construct_efootball_compact_batch(low_price)
        self.assertEqual(selected,[])
        far_apart=[leg(i,odds=1.15,probability=0.95,minute=i*30) for i in range(5)]
        selected,diag=builder._construct_efootball_compact_batch(far_apart)
        self.assertEqual(selected,[])
        self.assertGreater(diag["rejected_kickoff_span"],0)


    def test_chronological_ticket_calibration_must_improve_future_brier(self):
        origin=datetime(2026,1,1,tzinfo=timezone.utc)
        rows=[
            ((origin+timedelta(days=i)).isoformat(),0.56,1.0 if i%4==0 else 0.0)
            for i in range(60)
        ]
        result=builder._fit_efootball_ticket_gamma(rows)
        self.assertTrue(result["trained"])
        self.assertTrue(result["promotion_allowed"])
        self.assertGreaterEqual(result["oos_sample"],12)
        self.assertLess(result["calibrated_oos_brier"],result["raw_oos_brier"])

    def test_chronological_ticket_calibration_stays_held_when_raw_is_calibrated(self):
        origin=datetime(2026,1,1,tzinfo=timezone.utc)
        rows=[
            ((origin+timedelta(days=i)).isoformat(),0.50,1.0 if i%2==0 else 0.0)
            for i in range(60)
        ]
        result=builder._fit_efootball_ticket_gamma(rows)
        self.assertFalse(result["trained"])
        self.assertFalse(result["promotion_allowed"])
        self.assertFalse(result["oos_brier_improved"])
        self.assertAlmostEqual(result["raw_oos_brier"],result["calibrated_oos_brier"])


    def test_batch_metrics_uses_lane_specific_chronological_gamma(self):
        lane_result={
            "gamma":2.0,"sample":40,"settled_lane_ticket_count":40,
            "missing_raw_joint_probability_count":0,"trained":True,
            "oos_sample":20,"raw_oos_brier":0.25,"calibrated_oos_brier":0.23,
            "oos_brier_improved":True,"promotion_allowed":True
        }
        rows=[leg(0,odds=2.0,probability=0.70),leg(1,odds=2.0,probability=0.70)]
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=lane_result), patch.object(builder,"_ticket_calibration_gamma",return_value={"gamma":4.0}):
            metrics=builder._batch_metrics(rows)
        self.assertEqual(metrics["ticket_calibration_mode"],"efootball_exact_evidence_chronological_gamma")
        self.assertEqual(metrics["ticket_calibration_gamma"],2.0)
        self.assertAlmostEqual(metrics["raw_combined_model_probability"],0.49)
        self.assertAlmostEqual(metrics["combined_model_probability"],0.49**2,places=5)
        self.assertTrue(metrics["ticket_calibration_ready"])


    def test_efootball_pair_constructor_holds_without_validated_lane_calibration(self):
        rows=[
            leg(0,odds=2.35,probability=0.70,expected_value=0.645,minute=0),
            leg(1,odds=2.35,probability=0.70,expected_value=0.645,minute=5)
        ]
        held={"trained":False,"promotion_allowed":False,"sample":40,"oos_sample":16,
              "raw_oos_brier":0.24,"calibrated_oos_brier":0.25,"oos_brier_improved":False}
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held):
            selected,diag=builder._construct_efootball_value_batch(rows,min_odds=2.70,max_legs=4)
        self.assertEqual(selected,[])
        self.assertEqual(diag["reason"],"efootball_ticket_calibration_did_not_beat_raw_oos_baseline")
        self.assertEqual(diag["candidate_count"],2)

    def test_compact_efootball_constructor_holds_without_validated_lane_calibration(self):
        rows=[leg(i,odds=1.20,probability=0.90) for i in range(4)]
        held={"trained":False,"promotion_allowed":False,"sample":40,"oos_sample":16,
              "raw_oos_brier":0.24,"calibrated_oos_brier":0.25,"oos_brier_improved":False}
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held):
            selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["reason"],"efootball_ticket_calibration_did_not_beat_raw_oos_baseline")
        self.assertEqual(diag["candidate_count"],4)


if __name__=="__main__":
    unittest.main()
