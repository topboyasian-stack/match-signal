#!/usr/bin/env python3
"""Regression tests for Cloudflare Pages NBA snapshot archive staging."""
from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_nba_pages_snapshot_archive import stage_snapshot_archive


class SnapshotArchiveStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "canonical" / "nba_totals_publication_snapshots.json"
        self.staging = self.root / "staging" / "data"
        self.source.parent.mkdir(parents=True)
        self.staging.mkdir(parents=True)
        self.payload = [
            {
                "snapshot_id": f"snapshot-{index:04d}",
                "event_id": str(401900000 + index),
                "market_id": "225",
                "line": 225.5,
                "over_odds": 1.91,
                "under_odds": 1.93,
                "quote_timestamp": "2026-11-02T01:45:00+00:00",
            }
            for index in range(100)
        ]
        self.source_bytes = (json.dumps(self.payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.source.write_bytes(self.source_bytes)
        shutil.copyfile(self.source, self.staging / self.source.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_compressed_asset_is_exact_and_canonical_source_is_untouched(self):
        result = stage_snapshot_archive(self.source, self.staging, max_bytes=1024 * 1024)
        gzip_path = self.staging / (self.source.name + ".gz")
        raw_path = self.staging / self.source.name

        self.assertEqual(result["record_count"], 100)
        self.assertEqual(result["source_bytes"], len(self.source_bytes))
        self.assertTrue(result["canonical_source_unchanged"])
        self.assertTrue(result["raw_browser_asset_removed"])
        self.assertTrue(result["gzip_round_trip_exact"])
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertFalse(raw_path.exists())
        self.assertTrue(gzip_path.is_file())
        self.assertEqual(gzip.decompress(gzip_path.read_bytes()), self.source_bytes)
        self.assertLess(gzip_path.stat().st_size, 1024 * 1024)

    def test_oversized_compressed_asset_fails_closed_and_keeps_raw_copy(self):
        with self.assertRaisesRegex(ValueError, "exceed the Pages per-file limit"):
            stage_snapshot_archive(self.source, self.staging, max_bytes=1)
        self.assertTrue((self.staging / self.source.name).is_file())
        self.assertFalse((self.staging / (self.source.name + ".gz")).exists())
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_non_array_archive_is_rejected_without_deleting_staged_source(self):
        invalid = b'{"not":"an array"}\n'
        self.source.write_bytes(invalid)
        (self.staging / self.source.name).write_bytes(invalid)
        with self.assertRaisesRegex(ValueError, "must be a JSON array"):
            stage_snapshot_archive(self.source, self.staging, max_bytes=1024)
        self.assertTrue((self.staging / self.source.name).exists())

    def test_staging_source_mismatch_is_rejected(self):
        (self.staging / self.source.name).write_bytes(b"[]\n")
        with self.assertRaisesRegex(ValueError, "differs from the canonical Git source"):
            stage_snapshot_archive(self.source, self.staging, max_bytes=1024 * 1024)
        self.assertTrue((self.staging / self.source.name).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
