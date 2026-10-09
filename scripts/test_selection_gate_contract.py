#!/usr/bin/env python3
"""Regression tests for the shared selection-candidate artifact contract."""
import argparse
import json
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
assert '"candidate_qualification_scope": "upstream_prediction_flags_only" if qualified else "model_estimate_only"' in collector_source
assert '"qualification_semantics": "Counts candidates carrying an upstream betting_qualified/qualified_for_builder flag; this is not the selective prediction gate count and does not override current exact-line price, value, freshness, results, or Odds Builder gates."' in collector_source

parser = argparse.ArgumentParser()
parser.add_argument("--require-generated-artifacts", action="store_true")
args = parser.parse_args()

if args.require_generated_artifacts:
    gate_status = json.loads((ROOT / "data" / "selection_gate.json").read_text(encoding="utf-8"))
    selected_path = ROOT / gate_status["selected_artifact"]
    candidate_path = ROOT / gate_status["candidate_pool_artifact"]
    assert gate_status.get("generated_at"), "selection_gate.json must be timestamped"
    assert selected_path == gate["SELECTED"]
    assert candidate_path == collector["OUT"]
    assert isinstance(json.loads(selected_path.read_text(encoding="utf-8")), list)
    assert isinstance(json.loads(candidate_path.read_text(encoding="utf-8")), list)

print("Selection Gate artifact separation and summary contract passed.")
