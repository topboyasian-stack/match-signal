#!/usr/bin/env python3
"""Regression tests for cross-sport market reassessment."""
from __future__ import annotations

import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_sport_market_reassessment as reassessment
import sync_cross_sport_private_evidence as evidence_sync
from fixture_primary_prediction_ledger import build_fixture_ledger, merge_primary_ledger, primary_summary


class FakeCore:
    MIN_PROB = 0.60

    @staticmethod
    def load(path, default=None):
        return [] if default is None else default

    @staticmethod
    def within_builder_horizon(row, now):
        try:
            start = datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            minutes = (start.astimezone(timezone.utc) - now).total_seconds() / 60
            return 0 < minutes <= 720
        except (KeyError, TypeError, ValueError):
            return False


def sample_football(now, *, quote_age_seconds=0, include_btts=True, include_double_chance=True):
    fetched = (now - timedelta(seconds=quote_age_seconds)).isoformat()
    markets = [
        {
            "id": "1",
            "name": "1X2",
            "line": None,
            "outcomes": [
                {"id": "home-id", "name": "Home", "odds": 2.0},
                {"id": "draw-id", "name": "Draw", "odds": 3.2},
                {"id": "away-id", "name": "Away", "odds": 4.0},
            ],
        },
        {
            "id": "18",
            "name": "Total Goals",
            "line": 2.5,
            "outcomes": [
                {"id": "over-id", "name": "Over 2.5", "odds": 2.05},
                {"id": "under-id", "name": "Under 2.5", "odds": 1.75},
            ],
        },
    ]
    if include_btts:
        markets.append({
            "id": "29",
            "name": "Both Teams To Score",
            "line": None,
            "outcomes": [
                {"id": "btts-yes-id", "name": "Yes", "odds": 1.70},
                {"id": "btts-no-id", "name": "No", "odds": 2.10},
            ],
        })
    if include_double_chance:
        markets.append({
            "id": "26",
            "name": "Double Chance",
            "line": None,
            "outcomes": [
                {"id": "dc-1x-id", "name": "1X", "odds": 1.30},
                {"id": "dc-12-id", "name": "12", "odds": 1.38},
                {"id": "dc-x2-id", "name": "X2", "odds": 1.65},
            ],
        })
    return {
        "sport": "football",
        "event_id": "football-test-1",
        "start_time": (now + timedelta(hours=2)).isoformat(),
        "player_1": "Team Alpha",
        "player_2": "Team Beta",
        "league": "Test League",
        "pick": "p1",
        "probabilities": {"p1": 0.50, "draw": 0.20, "p2": 0.30},
        "expected_goals": {"p1": 1.8, "p2": 1.2, "total": 3.0},
        "markets": {
            "over_under": {"line": 2.5, "over": 0.58, "under": 0.42},
            "btts": {"yes": 0.62, "no": 0.38},
        },
        "sportybet_winner_odds": {"p1": 2.0, "draw": 3.2, "p2": 4.0, "market_id": "1"},
        "sportybet_total_games_odds": [
            {"line": 2.5, "over": 2.05, "under": 1.75, "market_id": "18"},
            {"line": 3.0, "over": 2.15, "under": 1.70, "market_id": "18"},
        ],
        "sportybet_market": {
            "available": True,
            "event_id": "sporty-event-1",
            "fetched_at": fetched,
            "winner": {"market_id": "1"},
            "markets": markets,
        },
        "market_odds_timestamp": fetched,
        "odds_timestamp": fetched,
        "data_quality": 0.9,
        "uncertainty": 0.1,
        "model": "test independent model",
    }


class CrossSportReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        reassessment._RUN_OPTIONS.clear()

    def test_fixture_primary_is_single_frozen_pick_and_alternatives_do_not_replace_it(self):
        rows = [
            {"sport": "football", "event_id": "evt-1", "pick": "p1", "probabilities": {"p1": 0.61}, "start_time": (self.now + timedelta(hours=1)).isoformat()},
            {"sport": "football", "event_id": "evt-1", "primary_market": "total_goals", "primary_pick": "over", "primary_probability": 0.72, "start_time": (self.now + timedelta(hours=1)).isoformat()},
            {"sport": "tennis", "event_id": "evt-2", "pick": "p1", "probabilities": {"p1": 0.66}, "start_time": (self.now + timedelta(hours=1)).isoformat()},
            {"sport": "virtual", "event_id": "evt-3", "pick": "over", "start_time": (self.now + timedelta(hours=1)).isoformat()},
        ]
        ledger = build_fixture_ledger(rows, self.now)
        by_event = {x["event_id"]: x for x in ledger}
        self.assertEqual(by_event["evt-1"]["primary_status"], "UNCLASSIFIED")
        self.assertEqual(by_event["evt-2"]["primary_market"], "winner")
        self.assertEqual(by_event["evt-3"]["primary_status"], "UNCLASSIFIED")
        self.assertEqual(primary_summary(ledger)["fixture_count"], 3)

    def test_primary_ledger_never_overwrites_an_existing_frozen_prediction(self):
        original = build_fixture_ledger([{"sport": "football", "event_id": "evt", "pick": "p1", "probabilities": {"p1": 0.7}}], self.now)
        changed = build_fixture_ledger([{"sport": "football", "event_id": "evt", "pick": "p2", "probabilities": {"p2": 0.8}}], self.now)
        merged = merge_primary_ledger(original, changed, lambda *_: None, {}, self.now)
        self.assertEqual(merged[0]["primary_pick"], "p1")
        self.assertEqual(merged[0]["primary_status"], "FROZEN")

    def test_raw_reassessment_artifacts_are_routed_to_ignored_private_store(self):
        private_dir = reassessment.DATA / "calibration_private"
        self.assertEqual(reassessment.OUTPUT.parent, private_dir)
        self.assertEqual(reassessment.HISTORY_OUTPUT.parent, private_dir)
        self.assertEqual(reassessment.REVISION_PATH.parent, private_dir)
        self.assertNotEqual(reassessment.OUTPUT.parent, reassessment.DATA)
        self.assertNotEqual(reassessment.HISTORY_OUTPUT.parent, reassessment.DATA)

    def test_poisson_recalculates_half_line_and_rejects_push_line(self):
        self.assertAlmostEqual(reassessment._poisson_over_probability(3.0, 2.5), 0.5768099, places=5)
        self.assertIsNone(reassessment._poisson_over_probability(3.0, 2.0))

    def test_football_evaluates_winner_totals_btts_and_double_chance_alternatives(self):
        row = sample_football(self.now)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        audit_markets = {candidate["builder_market"] for candidate in audit}
        self.assertTrue({"1X2", "total_goals", "btts", "double_chance"}.issubset(audit_markets))
        # The model is below the 0.60 floor on all winner outcomes and the 2.5 over line;
        # higher-probability BTTS/double-chance options are retained only with exact IDs.
        active_keys = {(x["builder_market"], x["builder_pick"]) for x in active}
        self.assertIn(("btts", "yes"), active_keys)
        self.assertIn(("double_chance", "1x"), active_keys)
        self.assertIn(("double_chance", "12"), active_keys)
        self.assertNotIn(("total_goals", "over"), active_keys)
        for candidate in active:
            self.assertTrue(candidate.get("sportybet_market_id"))
            self.assertTrue(candidate.get("sportybet_outcome_id"))
            self.assertTrue(candidate.get("reassessment_market_rows"))

    def test_alternative_preview_covers_24h_without_expanding_ticket_builder(self):
        row = sample_football(self.now)
        row["start_time"] = (self.now + timedelta(hours=13)).isoformat()
        self.assertTrue(reassessment._within_alternative_horizon(row, self.now))
        self.assertFalse(FakeCore.within_builder_horizon(row, self.now))

        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(active, "fresh exact-quote alternatives should be evaluated for a 13-hour fixture")
        self.assertTrue(audit)
        self.assertEqual(reassessment._builder_horizon_candidates(FakeCore(), active, self.now), [],
                         "the 12-hour accumulator Builder must not receive 13-hour candidates")

    def test_outside_builder_horizon_alt_is_published_as_alternative_only(self):
        row = sample_football(self.now)
        row["start_time"] = (self.now + timedelta(hours=13)).isoformat()
        row.update({
            "builder_market": "total_goals",
            "builder_pick": "under",
            "builder_probability": 0.72,
            "line": 2.5,
            "sportybet_market_id": "18",
            "sportybet_event_id": "sporty-event-1",
            "sportybet_outcome_id": "under-id",
            "reassessment_market_rows": [{"side": "over", "odds": 2.05}, {"side": "under", "odds": 1.75}],
            "market_reassessment": {"status": "EXACT_CURRENT_MARKET_ALTERNATIVE"},
        })

        class AuditCore(FakeCore):
            @staticmethod
            def market_rows(candidate):
                return candidate.get("reassessment_market_rows") or []

            @staticmethod
            def make_leg(candidate):
                return {"builder_eligible": True, "status": "PASS_EXISTING_BUILDER_GATES"}

        record = reassessment._make_audit_record(AuditCore(), row, self.now)
        self.assertEqual(record["candidate_status"], "ALTERNATIVE_ONLY_OUTSIDE_BUILDER_HORIZON")
        self.assertTrue(record["fresh_exact_quote"])
        self.assertTrue(record["alternative_only"])
        self.assertFalse(record["passed_builder_gates"])
        self.assertFalse(record["in_builder_pool"])
        self.assertEqual(record["primary_prediction_id"], reassessment.hashlib.sha256(b"football|football-test-1").hexdigest()[:24])

    def test_partial_1x2_price_pair_is_not_promoted_as_an_alternative(self):
        row = sample_football(self.now, include_btts=False, include_double_chance=False)
        row["sportybet_winner_odds"].pop("draw")
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(any(x["builder_market"] == "1X2" for x in audit))
        self.assertFalse(any(x["builder_market"] == "1X2" for x in active))

    def test_integer_total_lines_are_never_substituted_for_half_lines(self):
        row = sample_football(self.now)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        total_candidates = [x for x in audit if x["builder_market"] == "total_goals"]
        self.assertTrue(total_candidates)
        self.assertTrue(all(abs(float(x["line"]) - round(float(x["line"]))) > 1e-9 for x in total_candidates))

    def test_stale_quotes_are_audited_but_never_enter_the_active_candidate_pool(self):
        row = sample_football(self.now, quote_age_seconds=901)
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(audit)
        self.assertEqual(active, [])

    def test_missing_exact_outcome_identifier_blocks_booking_candidate(self):
        row = sample_football(self.now)
        for market in row["sportybet_market"]["markets"]:
            for outcome in market["outcomes"]:
                outcome["id"] = ""
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])
        self.assertTrue(audit)
        self.assertEqual(active, [])

    def test_research_alternatives_survive_missing_live_market_definitions_but_cannot_be_booked(self):
        row = sample_football(self.now)
        row["sportybet_market"]["available"] = False
        row["sportybet_market"]["markets"] = []
        # Even an apparently recent old timestamp and cached odds must not leak into
        # research-only candidates when the exact live market snapshot is unavailable.
        row["market_odds_timestamp"] = self.now.isoformat()
        row["odds_timestamp"] = self.now.isoformat()
        active, audit = reassessment._football_options(FakeCore(), self.now, [row])

        self.assertEqual(active, [], "model-only alternatives must never enter the active Builder pool")
        self.assertTrue(audit, "existing model probabilities must still yield research alternatives")
        research = [
            item for item in audit
            if (item.get("market_reassessment") or {}).get("status") == "RESEARCH_ONLY_NO_LIVE_QUOTE"
        ]
        self.assertTrue(research)
        self.assertTrue(any(item["builder_market"] == "1X2" for item in research))
        self.assertTrue(any(item["builder_market"] == "btts" and item["builder_pick"] == "yes" for item in research))
        self.assertTrue(any(item["builder_market"] == "double_chance" and item["builder_pick"] == "1x" for item in research))
        self.assertTrue(any(item["builder_market"] == "total_goals" and item.get("line") == 2.5 for item in research))
        self.assertTrue(any(item["builder_probability"] >= FakeCore.MIN_PROB for item in research))

        for item in research:
            self.assertIsNone(item.get("bookmaker_odds"))
            self.assertEqual(item.get("reassessment_market_rows"), [])
            self.assertIsNone(item.get("sportybet_event_id"))
            self.assertIsNone(item.get("sportybet_market_id"))
            self.assertIsNone(item.get("sportybet_outcome_id"))
            self.assertFalse(item.get("bookable"))
            self.assertFalse(item.get("qualification_allowed"))
            self.assertFalse(item["market_reassessment"].get("current_price_available"))

        class AuditCore(FakeCore):
            @staticmethod
            def market_rows(candidate):
                return candidate.get("reassessment_market_rows") or []

            @staticmethod
            def make_leg(candidate):
                # Deliberately simulate a permissive downstream leg builder.
                return {"builder_eligible": True, "status": "PASS_EXISTING_BUILDER_GATES"}

        supported = next(item for item in research if item["builder_probability"] >= FakeCore.MIN_PROB)
        record = reassessment._make_audit_record(AuditCore(), supported, self.now)
        self.assertEqual(record["candidate_status"], "RESEARCH_ONLY_NO_LIVE_QUOTE")
        self.assertFalse(record["fresh_exact_quote"])
        self.assertFalse(record["passed_builder_gates"])
        self.assertFalse(record["in_builder_pool"])
        self.assertFalse(record["bookable"])
        self.assertTrue(record["research_only"])

        current_rows = reassessment._current_research_candidates([record])
        self.assertEqual(len(current_rows), 1, "current model-only alternatives must be exported separately from quote history")
        current = current_rows[0]
        self.assertEqual(current["candidate_status"], "RESEARCH_ONLY_NO_LIVE_QUOTE")
        self.assertEqual(current["sport"], "football")
        self.assertFalse(current["bookable"])
        self.assertFalse(current["qualification_allowed"])
        self.assertFalse(current["fresh_exact_quote"])
        for field in (
            "bookmaker_odds", "quote_timestamp", "market_odds_timestamp", "odds_timestamp",
            "sportybet_event_id", "sportybet_market_id", "sportybet_outcome_id",
            "sportybet_outcome_name", "sportybet_specifier",
        ):
            self.assertIsNone(current[field], f"research export must strip {field}")

        synced, revision = evidence_sync._validate_current_research_artifact({
            "generated_at": self.now.isoformat(),
            "current_research_candidates_generated_at": self.now.isoformat(),
            "current_research_candidates": current_rows,
        })
        self.assertEqual(synced, current_rows)
        self.assertEqual(revision, self.now.isoformat())
        invalid = dict(current)
        invalid["bookmaker_odds"] = 1.91
        with self.assertRaisesRegex(RuntimeError, "Unsafe or malformed"):
            evidence_sync._validate_current_research_artifact({
                "generated_at": self.now.isoformat(),
                "current_research_candidates_generated_at": self.now.isoformat(),
                "current_research_candidates": [invalid],
            })

    def test_tennis_winner_alternatives_survive_missing_live_market_definitions_but_cannot_be_booked(self):
        row = {
            "sport": "tennis",
            "event_id": "tennis-test-1",
            "start_time": (self.now + timedelta(hours=2)).isoformat(),
            "player_1": "Player Alpha",
            "player_2": "Player Beta",
            "league": "Test Tournament",
            "calibrated_probabilities": {"p1": 0.72, "p2": 0.28},
            "sportybet_winner_odds": {"p1": 1.45, "p2": 2.55},
            "sportybet_market": {
                "available": False,
                "event_id": "old-provider-event-id",
                "fetched_at": self.now.isoformat(),
                "markets": [],
            },
            "sportybet_event_id": "old-provider-event-id",
            "sportybet_market_id": "186",
            "sportybet_outcome_id": "old-outcome-id",
            "market_odds_timestamp": self.now.isoformat(),
            "odds_timestamp": self.now.isoformat(),
            "model": "test independent tennis model",
        }
        active, audit = reassessment._tennis_options(FakeCore(), self.now, [row], [])
        self.assertEqual(active, [])
        research = [
            item for item in audit
            if (item.get("market_reassessment") or {}).get("status") == "RESEARCH_ONLY_NO_LIVE_QUOTE"
        ]
        self.assertEqual({item["builder_pick"] for item in research if item["builder_market"] == "winner"}, {"p1", "p2"})
        for item in research:
            self.assertIsNone(item.get("bookmaker_odds"))
            self.assertIsNone(item.get("sportybet_event_id"))
            self.assertIsNone(item.get("sportybet_market_id"))
            self.assertIsNone(item.get("sportybet_outcome_id"))
            self.assertFalse(item.get("bookable"))
            self.assertFalse(item.get("qualification_allowed"))


    def test_future_quote_timestamp_fails_closed(self):
        row = sample_football(self.now, quote_age_seconds=0)
        future = self.now + timedelta(seconds=5)
        row["market_odds_timestamp"] = future.isoformat()
        fresh, age, stamp = reassessment._fresh_quote(row, self.now)
        self.assertFalse(fresh)
        self.assertLess(age, 0)
        self.assertEqual(stamp, future.isoformat())

    def test_nba_quote_timestamp_is_supported_by_common_freshness_check(self):
        row = {
            "quote_timestamp": (self.now - timedelta(seconds=30)).isoformat(),
            "sport": "basketball",
            "market_id": "225",
            "line": 226.5,
        }
        fresh, age, stamp = reassessment._fresh_quote(row, self.now)
        self.assertTrue(fresh)
        self.assertEqual(age, 30.0)
        self.assertEqual(stamp, row["quote_timestamp"])

    def test_decorated_alternative_preserves_primary_pick_market_and_probability(self):
        row = sample_football(self.now)
        market = row["sportybet_market"]["markets"][0]
        candidate = reassessment._decorate_candidate(
            row, sport="football", market="total_goals", side="under",
            probability=0.72, market_obj=market,
            odds_rows=[{"side": "over", "odds": 2.05}, {"side": "under", "odds": 1.75}],
            line=2.5, outcome={"id": "under-id", "name": "Under 2.5", "odds": 1.75},
            model_source="test market alternative",
        )
        self.assertEqual(candidate["builder_pick"], "under")
        self.assertEqual(candidate["original_primary_pick"], "p1")
        self.assertEqual(candidate["original_primary_market"], "winner")
        self.assertEqual(candidate["original_primary_probability"], 0.50)
        self.assertEqual(candidate.get("original_primary_line"), row.get("line"))

    def test_virtual_wrapper_preserves_builder_signature_and_primary_comparison_metadata(self):
        old = reassessment._ORIGINALS.get("virtual_candidates")
        try:
            candidate = {
                "sport": "virtual", "event_id": "virtual-1",
                "builder_market": "virtual_total", "pick": "over",
                "source_model_pick": "over", "line": 8.5,
                "probabilities": {"over": 0.57, "under": 0.43},
            }
            reassessment._ORIGINALS["virtual_candidates"] = lambda now: [candidate]
            reassessment._RUN_OPTIONS.clear()
            result = reassessment._virtual_options(self.now)
            self.assertEqual(result, [candidate], "the existing Builder-facing return shape must not change")
            self.assertEqual(len(reassessment._RUN_OPTIONS), 1)
            recorded = reassessment._RUN_OPTIONS[0]
            self.assertEqual(recorded["original_primary_pick"], "over")
            self.assertEqual(recorded["original_primary_market"], "virtual_total")
            self.assertEqual(recorded["original_primary_line"], 8.5)
            self.assertEqual(recorded["original_primary_probability"], 0.57)
            self.assertEqual(candidate.get("original_primary_pick"), None, "metadata must not mutate the core candidate object")
        finally:
            if old is None:
                reassessment._ORIGINALS.pop("virtual_candidates", None)
            else:
                reassessment._ORIGINALS["virtual_candidates"] = old

    def test_private_kv_capacity_stays_below_provider_value_limit(self):
        self.assertEqual(evidence_sync.MAX_BYTES, 24 * 1024 * 1024)
        self.assertLess(evidence_sync.MAX_BYTES, 25 * 1024 * 1024)

    def test_private_evidence_restore_failure_is_fatal_and_does_not_fabricate_an_empty_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / "history.json"
            revision = root / "revision"
            namespace = root / "namespace"
            with (
                patch.object(evidence_sync, "PRIVATE_DIR", root),
                patch.object(evidence_sync, "HISTORY_PATH", history),
                patch.object(evidence_sync, "REVISION_PATH", revision),
                patch.object(evidence_sync, "NAMESPACE_PATH", namespace),
                patch.object(evidence_sync, "_resolve_namespace_id", side_effect=RuntimeError("simulated Cloudflare outage")),
            ):
                result = evidence_sync.restore()
            self.assertEqual(result, 1, "a failed remote restore must fail the scheduled refresh")
            self.assertEqual(revision.read_text(encoding="utf-8").strip(), "unavailable")
            self.assertEqual(namespace.read_text(encoding="utf-8").strip(), "unavailable")
            self.assertFalse(history.exists(), "a failed restore must not fabricate a valid-looking empty ledger")

    def test_private_evidence_publish_without_restore_is_fatal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            revision = root / "revision"
            namespace = root / "namespace"
            revision.write_text("unavailable\n", encoding="utf-8")
            namespace.write_text("unavailable\n", encoding="utf-8")
            with (
                patch.object(evidence_sync, "PRIVATE_DIR", root),
                patch.object(evidence_sync, "REVISION_PATH", revision),
                patch.object(evidence_sync, "NAMESPACE_PATH", namespace),
            ):
                self.assertEqual(evidence_sync.publish(), 1)

    def test_private_evidence_revision_conflict_is_fatal_instead_of_green(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            revision = root / "revision"
            namespace = root / "namespace"
            revision.write_text("expected-revision\n", encoding="utf-8")
            namespace.write_text("test-namespace\n", encoding="utf-8")
            with (
                patch.object(evidence_sync, "PRIVATE_DIR", root),
                patch.object(evidence_sync, "REVISION_PATH", revision),
                patch.object(evidence_sync, "NAMESPACE_PATH", namespace),
                patch.object(evidence_sync, "_kv_get", return_value={"updated_at": "newer-revision", "records": []}),
            ):
                self.assertEqual(evidence_sync.publish(), 1, "a revision conflict must fail and retry on a later scheduled run")

    def test_primary_ledger_rewrite_uses_real_newline_not_literal_backslash_n(self):
        source = (Path(reassessment.__file__)).read_text(encoding="utf-8")
        self.assertIn('HISTORY_OUTPUT.write_text(json.dumps(history_payload, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")', source)
        self.assertNotIn('HISTORY_OUTPUT.write_text(json.dumps(history_payload, indent=2, ensure_ascii=False) + "\\\\n", encoding="utf-8")', source)

    def test_fingerprint_changes_when_price_or_model_probability_changes(self):
        base = {
            "sport": "football", "event_id": "evt", "market": "total_goals", "line": 2.5,
            "pick": "over", "quote_timestamp": "2026-11-06T12:00:00+00:00",
            "bookmaker_odds": 1.9, "model_probability": 0.63, "model_source": "test",
            "sportybet_market_id": "18", "sportybet_outcome_id": "over-id",
        }
        changed_price = {**base, "bookmaker_odds": 2.0}
        changed_probability = {**base, "model_probability": 0.65}
        self.assertNotEqual(reassessment._fingerprint(base), reassessment._fingerprint(changed_price))
        self.assertNotEqual(reassessment._fingerprint(base), reassessment._fingerprint(changed_probability))
        self.assertEqual(reassessment._fingerprint(base), reassessment._fingerprint(dict(base)))

    def test_settlement_join_scores_double_chance_as_yes_or_no(self):
        base = {"sport": "football", "event_id": "evt", "market": "double_chance", "line": None, "pick": "1x"}
        by_event = {("football", "evt"): {"actual": "p1", "settled": True}}
        self.assertEqual(reassessment._settle_result(base, by_event)["settlement_result"], "yes")
        by_event = {("football", "evt"): {"actual": "p2", "settled": True}}
        self.assertEqual(reassessment._settle_result(base, by_event)["settlement_result"], "no")


if __name__ == "__main__":
    unittest.main(verbosity=2)
