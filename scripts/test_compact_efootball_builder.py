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
        builder._EFOOTBALL_HIGH_CONFIDENCE_TICKET_CALIBRATION_CACHE=None
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
        builder._EFOOTBALL_HIGH_CONFIDENCE_TICKET_CALIBRATION_CACHE=None

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
        self.assertGreaterEqual(result["calibrated_oos_brier"],result["raw_oos_brier"])


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
              "raw_oos_brier":0.24,"calibrated_oos_brier":0.25,"oos_brier_improved":False,
              "brier_promotion_allowed":False,"profitability_promotion_allowed":False,
              "promotion_hold_reason":"chronological_oos_brier_not_improved"}
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held):
            selected,diag=builder._construct_efootball_value_batch(rows,min_odds=2.70,max_legs=4)
        self.assertEqual(selected,[])
        self.assertEqual(diag["reason"],"efootball_ticket_calibration_oos_brier_not_improved")
        self.assertEqual(diag["candidate_count"],2)

    def test_compact_efootball_constructor_holds_without_validated_lane_calibration(self):
        rows=[leg(i,odds=1.20,probability=0.90) for i in range(4)]
        held={"trained":False,"promotion_allowed":False,"sample":40,"oos_sample":16,
              "raw_oos_brier":0.24,"calibrated_oos_brier":0.25,"oos_brier_improved":False,
              "brier_promotion_allowed":False,"profitability_promotion_allowed":False,
              "promotion_hold_reason":"chronological_oos_brier_not_improved"}
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held):
            selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["reason"],"efootball_ticket_calibration_oos_brier_not_improved")
        self.assertEqual(diag["candidate_count"],4)

    def test_ticket_constructors_report_profitability_hold_when_brier_improves(self):
        held={
            "trained":True,"promotion_allowed":False,"sample":107,
            "settled_lane_ticket_count":107,"missing_raw_joint_probability_count":0,
            "gamma":1.8621,"oos_sample":99,"raw_oos_brier":0.269469,
            "calibrated_oos_brier":0.183544,"oos_brier_improved":True,
            "brier_promotion_allowed":True,"profitability_promotion_allowed":False,
            "settled_lane_profit_ticket_count":107,"settled_lane_wins":28,
            "settled_lane_losses":79,"settled_lane_net_units":-3.042,
            "settled_lane_flat_stake_roi":-0.02843,
            "profitability_minimum_settled_tickets":30,
            "promotion_hold_reason":"settled_lane_roi_not_positive"
        }
        pair=[
            leg(0,odds=2.35,probability=0.70,expected_value=0.645,minute=0),
            leg(1,odds=2.35,probability=0.70,expected_value=0.645,minute=5)
        ]
        compact=[leg(i,odds=1.20,probability=0.90) for i in range(4)]
        with patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held):
            pair_selected,pair_diag=builder._construct_efootball_value_batch(pair,min_odds=2.70,max_legs=4)
            compact_selected,compact_diag=builder._construct_efootball_compact_batch(compact)

        expected_reason="efootball_ticket_calibration_settled_roi_not_positive"
        self.assertEqual(pair_selected,[])
        self.assertEqual(compact_selected,[])
        self.assertEqual(pair_diag["reason"],expected_reason)
        self.assertEqual(compact_diag["reason"],expected_reason)
        self.assertTrue(pair_diag["ticket_calibration"]["oos_brier_improved"])
        self.assertTrue(compact_diag["ticket_calibration"]["oos_brier_improved"])
        self.assertLess(pair_diag["ticket_calibration"]["settled_lane_flat_stake_roi"],0)
        self.assertLess(compact_diag["ticket_calibration"]["settled_lane_flat_stake_roi"],0)

    def test_high_confidence_calibration_uses_only_comparable_pure_efootball_history(self):
        origin=datetime(2026,1,1,tzinfo=timezone.utc)
        def historical_ticket(index, *, product="efootball_gt", probability=0.85, legs=2, lane="high_confidence_research"):
            status="WON" if index<16 else "LOST"
            timestamp=(origin+timedelta(days=index)).isoformat()
            return {
                "ticket_id":f"high-confidence-{index}","primary_lane":lane,"status":status,
                "_calibration_stamp":timestamp,"settled_at":timestamp,
                "combined_odds":3.0,"raw_combined_model_probability":0.50,
                "legs":[{
                    "product":product,"qualification_lane":"efootball_exact_evidence_value",
                    "model_probability":probability
                } for _ in range(legs)]
            }
        history=[historical_ticket(i) for i in range(40)]
        history.extend([
            historical_ticket(40,product="vfootball"),
            historical_ticket(41,probability=0.75),
            historical_ticket(42,legs=5),
            historical_ticket(43,lane="efootball_exact_evidence_value")
        ])
        fit={
            "gamma":1.2,"sample":40,"warmup":8,"trained":True,
            "oos_sample":32,"raw_oos_brier":0.25,"calibrated_oos_brier":0.21,
            "oos_brier_improved":True,"promotion_allowed":True
        }
        with (
            patch.object(builder,"load",return_value={}),
            patch.object(builder,"settled_ticket_history",return_value=history),
            patch.object(builder,"_fit_efootball_ticket_gamma",return_value=fit),
        ):
            result=builder._efootball_high_confidence_ticket_gamma()
        self.assertTrue(result["promotion_allowed"])
        self.assertEqual(result["tagged_lane_ticket_count"],43)
        self.assertEqual(result["settled_lane_ticket_count"],40)
        self.assertEqual(result["comparable_raw_probability_sample"],40)
        self.assertEqual(result["excluded_product_scope_tickets"],1)
        self.assertEqual(result["excluded_weak_leg_tickets"],1)
        self.assertEqual(result["excluded_ticket_shapes"],1)
        self.assertEqual(result["settled_lane_wins"],16)
        self.assertEqual(result["settled_lane_losses"],24)
        self.assertAlmostEqual(result["settled_lane_flat_stake_roi"],0.20)

    def test_high_confidence_constructor_uses_its_own_calibration_not_value_lane(self):
        rows=[leg(i,odds=1.30,probability=0.90) for i in range(4)]
        high={
            "lane":"high_confidence_research","gamma":1.2,"sample":40,"trained":True,
            "tagged_lane_ticket_count":43,"settled_lane_ticket_count":40,
            "comparable_raw_probability_sample":40,"missing_raw_joint_probability_count":0,
            "oos_sample":32,"raw_oos_brier":0.25,"calibrated_oos_brier":0.21,
            "oos_brier_improved":True,"brier_promotion_allowed":True,
            "profitability_promotion_allowed":True,"settled_lane_profit_ticket_count":40,
            "settled_lane_wins":16,"settled_lane_losses":24,"settled_lane_net_units":8.0,
            "settled_lane_flat_stake_roi":0.20,"profitability_minimum_settled_tickets":30,
            "promotion_allowed":True,"promotion_hold_reason":None
        }
        blocked_value={
            "lane":"efootball_exact_evidence_value","gamma":1.8621,"trained":True,
            "promotion_allowed":False,"brier_promotion_allowed":True,
            "profitability_promotion_allowed":False,"settled_lane_profit_ticket_count":107,
            "settled_lane_flat_stake_roi":-0.02843,"profitability_minimum_settled_tickets":30,
            "promotion_hold_reason":"settled_lane_roi_not_positive"
        }
        with (
            patch.object(builder,"_efootball_high_confidence_ticket_gamma",return_value=high),
            patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=blocked_value),
        ):
            options,diag=builder._construct_high_confidence_value_batches(rows,max_batches=1,max_legs=4,min_odds=2.70)
        self.assertTrue(options)
        self.assertEqual(diag["batches_selected"],1)
        self.assertEqual(options[0]["metrics"]["ticket_calibration_mode"],"efootball_high_confidence_chronological_gamma")
        self.assertEqual(options[0]["metrics"]["ticket_calibration_lane"],"high_confidence_research")
        self.assertGreaterEqual(options[0]["odds"],2.70)
        self.assertGreaterEqual(options[0]["roi"],0.02)
        self.assertEqual(diag["ticket_calibration"]["lane"],"high_confidence_research")

    def test_high_confidence_constructor_stays_held_when_its_own_roi_is_negative(self):
        rows=[leg(i,odds=1.30,probability=0.90) for i in range(4)]
        held={
            "lane":"high_confidence_research","gamma":1.2,"sample":40,"trained":True,
            "tagged_lane_ticket_count":43,"settled_lane_ticket_count":40,
            "comparable_raw_probability_sample":40,"missing_raw_joint_probability_count":0,
            "oos_sample":32,"raw_oos_brier":0.25,"calibrated_oos_brier":0.21,
            "oos_brier_improved":True,"brier_promotion_allowed":True,
            "profitability_promotion_allowed":False,"settled_lane_profit_ticket_count":40,
            "settled_lane_wins":10,"settled_lane_losses":30,"settled_lane_net_units":-10.0,
            "settled_lane_flat_stake_roi":-0.25,"profitability_minimum_settled_tickets":30,
            "promotion_allowed":False,"promotion_hold_reason":"settled_lane_roi_not_positive"
        }
        with patch.object(builder,"_efootball_high_confidence_ticket_gamma",return_value=held):
            options,diag=builder._construct_high_confidence_value_batches(rows,max_batches=1,max_legs=4,min_odds=2.70)
        self.assertEqual(options,[])
        self.assertEqual(diag["reason"],"efootball_ticket_calibration_settled_roi_not_positive")
        self.assertTrue(diag["ticket_calibration"]["oos_brier_improved"])
        self.assertLess(diag["ticket_calibration"]["settled_lane_flat_stake_roi"],0)

    def test_high_confidence_calibration_reports_insufficient_sample_before_brier_failure(self):
        origin=datetime(2026,1,1,tzinfo=timezone.utc)
        history=[]
        for index in range(8):
            stamp=(origin+timedelta(days=index)).isoformat()
            status="WON" if index<3 else "LOST"
            history.append({
                "ticket_id":f"thin-high-confidence-{index}",
                "primary_lane":"high_confidence_research","status":status,
                "_calibration_stamp":stamp,"settled_at":stamp,
                "combined_odds":3.0,"raw_combined_model_probability":0.5,
                "legs":[{
                    "product":"efootball_gt",
                    "qualification_lane":"efootball_exact_evidence_value",
                    "model_probability":0.85
                } for _ in range(2)]
            })
        no_oos={
            "gamma":1.0,"sample":8,"warmup":8,"trained":False,
            "oos_sample":0,"raw_oos_brier":None,"calibrated_oos_brier":None,
            "oos_brier_improved":False,"promotion_allowed":False
        }
        with (
            patch.object(builder,"load",return_value={}),
            patch.object(builder,"settled_ticket_history",return_value=history),
            patch.object(builder,"_fit_efootball_ticket_gamma",return_value=no_oos),
        ):
            result=builder._efootball_high_confidence_ticket_gamma()
        self.assertFalse(result["promotion_allowed"])
        self.assertFalse(result["brier_promotion_allowed"])
        self.assertFalse(result["calibration_sample_sufficient"])
        self.assertEqual(result["promotion_hold_reason"],"insufficient_settled_lane_roi_sample")
        self.assertEqual(result["tagged_lane_ticket_count"],8)
        self.assertEqual(result["comparable_raw_probability_sample"],8)

    def test_no_bet_summary_exposes_high_confidence_hold_and_active_product_scope(self):
        high_diag={
            "eligible_legs":12,
            "candidate_combinations":0,
            "batches_selected":0,
            "ticket_calibration":{
                "lane":"high_confidence_research",
                "trained":True,
                "oos_brier_improved":True,
                "brier_promotion_allowed":True,
                "profitability_promotion_allowed":False,
                "settled_lane_flat_stake_roi":-0.08,
                "promotion_allowed":False,
                "promotion_hold_reason":"settled_lane_roi_not_positive",
            },
            "reason":"efootball_ticket_calibration_settled_roi_not_positive",
        }
        def shape_diagnostics(product,idx=None):
            return [{"product":product,"leg_count":2,"ticket_n":0,"qualifies":False}]

        with (
            patch.object(builder,"make_leg",return_value={"builder_eligible":False,"product":"efootball_gt"}),
            patch.object(builder,"construction_shape_diagnostics",side_effect=shape_diagnostics),
            patch.object(builder,"_construct_mixed_virtual_efootball_batches",return_value=([],{"reason":"no_mixed_combination_reached_all_gates"})),
            patch.object(builder,"_construct_vfootball_holdout_batches",return_value=([],{"reason":"no_vfootball_holdout_combination_reached_all_gates"})),
            patch.object(builder,"_construct_phase2_cyclical_loop_batches",return_value=([],{"reason":"no_phase2_combination_reached_all_gates"})),
            patch.object(builder,"_construct_high_confidence_value_batches",return_value=([],high_diag)),
            patch.object(builder,"_secondary_efootball_diagnostics",return_value={"pool_size":0,"pair_scan":{"fully_qualified_pairs":0},"best_pair":[]}),
            patch.object(builder,"_batch_capacity_diagnostic",return_value={"eligible_legs":0,"active_floor_reachable_with_current_gates":False}),
        ):
            batches,built,diag=builder.build_value_batches([{}])

        self.assertEqual(batches,[])
        self.assertEqual(diag["priority_product"],"active_qualified_pool")
        self.assertIn("efootball_gt",diag["active_efootball_construction_shape_diagnostics"])
        self.assertIn("efootball_adriatic",diag["active_efootball_construction_shape_diagnostics"])
        self.assertEqual(diag["construction_shape_diagnostics"][0]["product"],"efootball_gt")
        self.assertEqual(diag["high_confidence_diagnostics"]["ticket_calibration"]["promotion_hold_reason"],"settled_lane_roi_not_positive")
        self.assertEqual(diag["high_confidence_diagnostics"]["reason"],"efootball_ticket_calibration_settled_roi_not_positive")


    def test_pair_diagnostics_reports_calibration_hold_separately_from_roi_and_shows_shadow_only_pairs(self):
        rows=[
            leg(0,odds=2.35,probability=0.70,expected_value=0.645,minute=0),
            leg(1,odds=2.35,probability=0.70,expected_value=0.645,minute=5),
        ]
        rows[0]["pick"] = f'{rows[0]["match"]} — O/U over 2.5'
        rows[0]["participant_history"] = {"line": "2.5", "side": "over"}
        # The fallback must also recover the line and direction from the displayed pick.
        rows[1]["pick"] = f'{rows[1]["match"]} — O/U under 3.5'
        held={
            "trained":True,"promotion_allowed":False,"gamma":1.8701,"sample":108,
            "oos_sample":100,"raw_oos_brier":0.268647,"calibrated_oos_brier":0.181888,
            "oos_brier_improved":True,"brier_promotion_allowed":True,
            "profitability_promotion_allowed":False,"settled_lane_profit_ticket_count":108,
            "settled_lane_flat_stake_roi":-0.037426,
            "promotion_hold_reason":"settled_lane_roi_not_positive"
        }
        with (
            patch.object(builder,"_efootball_exact_evidence_ticket_gamma",return_value=held),
            patch.object(builder,"_ticket_calibration_gamma",return_value={"gamma":2.4}),
        ):
            diag=builder._secondary_efootball_diagnostics(rows,min_odds=2.70)

        scan=diag["pair_scan"]
        self.assertEqual(scan["pairs_total"],1)
        self.assertEqual(scan["odds_reach_pairs"],1)
        self.assertEqual(scan["calibration_hold_rejections"],1)
        self.assertEqual(scan["roi_rejections"],0,"a near-zero placeholder during a calibration hold is not an ROI test result")
        self.assertEqual(scan["fully_qualified_pairs"],0,"shadow pairs must never be active-qualified pairs")
        self.assertEqual(diag["best_pair"],[])
        self.assertEqual(len(diag["top_legs"]),2)
        self.assertEqual((diag["top_legs"][0]["line"],diag["top_legs"][0]["side"]),(2.5,"over"))
        self.assertEqual((diag["top_legs"][1]["line"],diag["top_legs"][1]["side"]),(3.5,"under"))
        self.assertEqual(len(diag["shadow_only_candidates"]),1)
        candidate=diag["shadow_only_candidates"][0]
        self.assertEqual((candidate["legs"][0]["line"],candidate["legs"][0]["side"]),(2.5,"over"))
        self.assertEqual((candidate["legs"][1]["line"],candidate["legs"][1]["side"]),(3.5,"under"))
        self.assertEqual(candidate["qualification_status"],"SHADOW_ONLY_NOT_QUALIFIED")
        self.assertFalse(candidate["ticket_calibration_ready"])
        self.assertEqual(candidate["blocking_reason"],"settled_lane_roi_not_positive")
        self.assertGreaterEqual(candidate["raw_independence_expected_roi"],0.02)
        self.assertIn("Diagnostic-only",diag["shadow_only_policy"])


if __name__=="__main__":
    unittest.main()
