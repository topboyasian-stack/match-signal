"""Regression tests for safe PDL source-failure handling."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("pdl_pipeline", Path(__file__).with_name("pdl_pipeline.py"))
pdl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pdl)


class PDLSourceFailureTests(unittest.TestCase):
    def test_provider_failure_preserves_last_good_predictions_and_marks_status_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "pdl_predictions.json"
            status = root / "pdl_status.json"
            original = '[{"event_id":"last-good","paper_only":true}]\n'
            predictions.write_text(original, encoding="utf-8")
            status.write_text(json.dumps({"updated_at":"2026-10-24T09:41:33+00:00","status":"CURRENT","historical_rows":61}), encoding="utf-8")
            with patch.object(pdl, "DATA", root), patch.object(pdl, "history", side_effect=RuntimeError("HTTP 403 provider blocked")), contextlib.redirect_stdout(io.StringIO()):
                pdl.main()
            self.assertEqual(predictions.read_text(encoding="utf-8"), original)
            result = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "STALE_SOURCE_UNAVAILABLE")
            self.assertEqual(result["last_successful_update_at"], "2026-10-24T09:41:33+00:00")
            self.assertIn("HTTP 403", result["last_error"])
            self.assertTrue(result["preserved_last_known_good_predictions"])

    def test_missing_fixture_source_does_not_publish_empty_current_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "pdl_predictions.json"
            status = root / "pdl_status.json"
            original = '[{"event_id":"last-good","paper_only":true}]\n'
            predictions.write_text(original, encoding="utf-8")
            status.write_text(json.dumps({"updated_at":"2026-10-24T09:41:33+00:00","status":"CURRENT"}), encoding="utf-8")
            hist = [{"home_score":1,"away_score":0,"start_time":"2026-10-20T12:00:00+00:00","home":"Home","away":"Away"}]
            with patch.object(pdl, "DATA", root), patch.object(pdl, "history", return_value=(hist, "test")), patch.object(pdl, "upcoming", return_value=([], "none")), contextlib.redirect_stdout(io.StringIO()):
                pdl.main()
            self.assertEqual(predictions.read_text(encoding="utf-8"), original)
            result = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "STALE_SOURCE_UNAVAILABLE")
            self.assertIn("fixture sources are unavailable", result["last_error"])

    def test_success_marks_feed_current_and_writes_new_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "pdl_predictions.json"
            status = root / "pdl_status.json"
            hist = [{"home_score":1,"away_score":0,"start_time":"2026-10-20T12:00:00+00:00","home":"Home","away":"Away"}]
            future = [{"event_id":"fresh-fixture","start_time":"2026-10-30T12:00:00+00:00","home":"Home","away":"Away"}]
            with patch.object(pdl, "DATA", root), patch.object(pdl, "history", return_value=(hist, "test-history")), patch.object(pdl, "upcoming", return_value=(future, "test-fixtures")), contextlib.redirect_stdout(io.StringIO()):
                pdl.main()
            result = json.loads(status.read_text(encoding="utf-8"))
            rows = json.loads(predictions.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "CURRENT")
            self.assertEqual(result["current_upcoming"], 1)
            self.assertEqual(rows[0]["event_id"], "fresh-fixture")


if __name__ == "__main__":
    unittest.main()
