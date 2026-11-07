#!/usr/bin/env python3
"""Regression tests for fresh core-sport fallback in the Odds Builder."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import odds_builder_core as core
UTC = timezone.utc


class BuilderLiveCoreFallbackTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)

    def test_stale_canonical_feed_uses_only_fresh_unified_core_rows(self):
        future = (self.now + timedelta(hours=2)).isoformat()
        old = (self.now - timedelta(minutes=20)).isoformat()
        rows = [
            {"event_id": "fresh-football", "sport": "football", "source_engine": "unified_live_refresh",
             "start_time": future, "pick": "p1", "confidence": 0.66, "probabilities": {"p1": 0.66, "draw": 0.2, "p2": 0.14}},
            {"event_id": "fresh-tennis", "sport": "tennis", "source_engine": "unified_live_refresh",
             "start_time": future, "pick": "p1", "confidence": 0.68, "probabilities": {"p1": 0.68, "p2": 0.32}},
            {"event_id": "tennis-watch", "sport": "tennis", "source_engine": "unified_live_refresh",
             "start_time": future, "pick": "p1", "confidence": 0.78, "probabilities": {"p1": 0.78, "p2": 0.22},
             "prediction_status": "watch_projection", "qualification_status": "TENNIS_FORWARD_WATCH_NOT_QUALIFIED"},
            {"event_id": "old-core", "sport": "football", "source_engine": "core_prediction_engine",
             "start_time": future, "pick": "p1", "confidence": 0.8, "probabilities": {"p1": 0.8, "draw": 0.1, "p2": 0.1}},
        ]
        original_load = core.load
        def fake_load(path, default):
            name = str(path)
            if name.endswith("predictions.json"):
                return [{"event_id": "expired", "sport": "football", "start_time": old}]
            if name.endswith("pipeline_status.json"):
                return {"updated_at": (self.now - timedelta(hours=5)).isoformat()}
            if name.endswith("unified_upcoming.json"):
                return {"events": rows}
            return default
        core.load = fake_load
        try:
            result, source = core._builder_prediction_source(self.now)
        finally:
            core.load = original_load
        self.assertEqual(source, "unified_live_refresh_fallback")
        self.assertEqual({row["event_id"] for row in result}, {"fresh-football", "fresh-tennis"})

    def test_fresh_tennis_does_not_block_live_football_fallback(self):
        future = (self.now + timedelta(hours=2)).isoformat()
        canonical_tennis = {
            "event_id": "canonical-tennis", "sport": "tennis", "start_time": future,
            "pick": "p1", "probabilities": {"p1": 0.64, "p2": 0.36},
        }
        live_rows = [
            {"event_id": "live-football", "sport": "football", "source_engine": "unified_live_refresh", "start_time": future},
            {"event_id": "live-tennis", "sport": "tennis", "source_engine": "unified_live_refresh", "start_time": future},
            {"event_id": "watch-tennis", "sport": "tennis", "source_engine": "unified_live_refresh", "start_time": future,
             "prediction_status": "watch_projection", "qualification_status": "TENNIS_FORWARD_WATCH_NOT_QUALIFIED"},
        ]
        original_load = core.load
        def fake_load(path, default):
            name = str(path)
            if name.endswith("predictions.json"):
                return [canonical_tennis]
            if name.endswith("pipeline_status.json"):
                return {"updated_at": (self.now - timedelta(minutes=20)).isoformat()}
            if name.endswith("unified_upcoming.json"):
                return {"events": live_rows}
            return default
        core.load = fake_load
        try:
            result, source = core._builder_prediction_source(self.now)
        finally:
            core.load = original_load
        self.assertEqual(source, "mixed_canonical_unified_fallback")
        self.assertEqual({row["event_id"] for row in result}, {"canonical-tennis", "live-football"})

    def test_stale_canonical_rows_are_not_reused_when_no_live_fallback_exists(self):
        original_load = core.load
        def fake_load(path, default):
            name = str(path)
            if name.endswith("predictions.json"):
                return [{"event_id": "stale-tennis", "sport": "tennis",
                         "start_time": (self.now + timedelta(hours=1)).isoformat()}]
            if name.endswith("pipeline_status.json"):
                return {"updated_at": (self.now - timedelta(hours=5)).isoformat()}
            if name.endswith("unified_upcoming.json"):
                return {"events": []}
            return default
        core.load = fake_load
        try:
            result, source = core._builder_prediction_source(self.now)
        finally:
            core.load = original_load
        self.assertEqual(result, [])
        self.assertEqual(source, "stale_canonical_no_live_fallback")

    def test_builder_candidates_use_active_fallback_but_never_tennis_watch_rows(self):
        future = (self.now + timedelta(hours=1)).isoformat()
        core.ACTIVE_PREDICTION_ROWS = [
            {"event_id": "football-fallback", "sport": "football", "start_time": future,
             "pick": "p1", "confidence": 0.64, "probabilities": {"p1": 0.64, "draw": 0.2, "p2": 0.16}},
            {"event_id": "tennis-fallback", "sport": "tennis", "start_time": future,
             "pick": "p1", "confidence": 0.66, "probabilities": {"p1": 0.66, "p2": 0.34}},
            {"event_id": "tennis-watch", "sport": "tennis", "start_time": future,
             "pick": "p1", "confidence": 0.80, "probabilities": {"p1": 0.80, "p2": 0.20},
             "prediction_status": "watch_projection", "qualification_status": "TENNIS_FORWARD_WATCH_NOT_QUALIFIED"},
        ]
        try:
            football = core.football_candidates(self.now)
            tennis = core.tennis_candidates(self.now)
        finally:
            core.ACTIVE_PREDICTION_ROWS = None
        self.assertEqual([row["event_id"] for row in football], ["football-fallback"])
        self.assertEqual([row["event_id"] for row in tennis], ["tennis-fallback"])


if __name__ == "__main__":
    unittest.main()
