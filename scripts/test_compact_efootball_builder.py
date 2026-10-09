#!/usr/bin/env python3
"""Regression tests for the compact, exact-evidence eFootball ticket lane."""
from datetime import datetime, timedelta, timezone
import math
import unittest
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

    def tearDown(self):
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

    def test_under_80_percent_leg_is_never_used_to_reach_two_x(self):
        rows=[leg(i,odds=1.10,probability=0.90) for i in range(4)]
        rows.append(leg(4,odds=1.60,probability=0.79))
        selected,diag=builder._construct_efootball_compact_batch(rows)
        self.assertEqual(selected,[])
        self.assertEqual(diag["reason"],"no_compact_combination_passed_all_gates")

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


if __name__=="__main__":
    unittest.main()
