#!/usr/bin/env python3
"""Guard the SportyBet pregame capture workflow against unsafe scope changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sportybet-pregame-capture.yml"
SCRIPT = ROOT / "scripts" / "capture_sportybet_pregame_snapshots.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")
WORKFLOW_SOURCE = WORKFLOW.read_text(encoding="utf-8")

assert "push:" in WORKFLOW_SOURCE
assert "' .github/workflows/sportybet-pregame-capture.yml'" not in WORKFLOW_SOURCE
assert "'.github/workflows/sportybet-pregame-capture.yml'" in WORKFLOW_SOURCE
assert "'scripts/capture_sportybet_pregame_snapshots.py'" in WORKFLOW_SOURCE
assert "'scripts/merge_sportybet_pregame_snapshots.py'" in WORKFLOW_SOURCE
assert "*/10 * * * *" in WORKFLOW_SOURCE
assert "group: match-signal-data-publish" in WORKFLOW_SOURCE
assert "cancel-in-progress: false" in WORKFLOW_SOURCE
# The market scan runs once; publication retries only merge its cached result.
assert WORKFLOW_SOURCE.count("python scripts/capture_sportybet_pregame_snapshots.py") == 1
assert "cp data/sportybet_pregame_snapshots.json /tmp/sportybet_pregame_captured.json" in WORKFLOW_SOURCE
assert "scripts/merge_sportybet_pregame_snapshots.py" in WORKFLOW_SOURCE
assert "for attempt in 1 2 3 4 5; do" in WORKFLOW_SOURCE
assert "git fetch origin main" in WORKFLOW_SOURCE
assert "git reset --hard origin/main" in WORKFLOW_SOURCE
assert "/tmp/sportybet_pregame_captured.json" in WORKFLOW_SOURCE
assert "sleep $((attempt * 2))" in WORKFLOW_SOURCE
assert "python scripts/model_guard.py" in WORKFLOW_SOURCE
assert "data/sportybet_pregame_snapshots.json" in WORKFLOW_SOURCE
assert "data/risk_gate.json" in WORKFLOW_SOURCE
assert "data/value_trial_ledger.json" in WORKFLOW_SOURCE

# Capture logic must stay append-only and leave the public feed and ticket
# state untouched. It may read predictions but must not write predictions.json.
assert 'PREDICTIONS_PATH = DATA / "predictions.json"' in SOURCE
assert 'LEDGER_PATH = DATA / "sportybet_pregame_snapshots.json"' in SOURCE
assert 'LEDGER_PATH.write_text(' in SOURCE
assert 'PREDICTIONS_PATH.write_text(' not in SOURCE
assert '"football": "1"' in SOURCE
assert '"tennis": "186"' in SOURCE
assert 'ACTIVE_TENNIS_TOUR = "ATP"' in SOURCE
assert "is_fresh_pregame_snapshot(fetched_at, start_time)" in SOURCE
assert "append_snapshots" in SOURCE
assert "existing.add(key)" in SOURCE

print("SportyBet pregame capture workflow contract passed.")
