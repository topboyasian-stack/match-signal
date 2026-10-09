#!/usr/bin/env python3
"""Regression tests for the shared selection-candidate artifact contract."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
gate = runpy.run_path(str(ROOT / "scripts" / "selective_prediction_gate.py"))
collector = runpy.run_path(str(ROOT / "scripts" / "selection_candidate_collector.py"))

# The high-confidence/current-value gate and the model-first Desk pool are two
# different products. They must never race to overwrite the same JSON artifact.
assert gate["SELECTED"] == ROOT / "data" / "selection_gate_selected.json"
assert collector["OUT"] == ROOT / "data" / "selection_candidates.json"
assert gate["SELECTED"] != collector["OUT"]

gate_source = (ROOT / "scripts" / "selective_prediction_gate.py").read_text(encoding="utf-8")
assert '"generated_at": datetime.now(timezone.utc).isoformat()' in gate_source
assert '"selected_artifact": "data/selection_gate_selected.json"' in gate_source
assert '"candidate_pool_artifact": "data/selection_candidates.json"' in gate_source
assert '"filtered_predictions": len(predictions) - len(selected)' in gate_source
assert '"confidence_filtered_predictions": rejected' in gate_source

collector_source = (ROOT / "scripts" / "selection_candidate_collector.py").read_text(encoding="utf-8")
assert 'OUT = DATA / "selection_candidates.json"' in collector_source
assert '"purpose": "model-first current candidate pool; independent from Odds Builder value/results qualification"' in collector_source

print("Selection Gate artifact separation and summary contract passed.")
