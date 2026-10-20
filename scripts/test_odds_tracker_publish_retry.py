from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "odds-ticket-tracker.yml"
source = WORKFLOW.read_text(encoding="utf-8")

assert "'scripts/test_odds_tracker_publish_retry.py'" in source, "regression test must run on pushes touching its own file"
assert "      - name: Run ticket tracker publish-retry regression\n        run: python scripts/test_odds_tracker_publish_retry.py" in source
assert "    timeout-minutes: 15" in source, "publish retries and necessary settlement recalculation need a bounded recovery window"

publish = source.split("      - name: Publish ticket tracker", 1)[1]
for required in (
    'tracking_base="$(git rev-parse HEAD^)"',
    'tracker_snapshot="$(mktemp)"',
    'for attempt in 1 2 3 4 5 6; do',
    'git fetch --no-tags origin main',
    'git diff --quiet "$tracking_base" origin/main --',
    'cp "$tracker_snapshot" data/odds_ticket_tracker.json',
    'python scripts/odds_ticket_tracker.py',
    'tracking_base="$(git rev-parse HEAD^)"',
):
    assert required in publish, f"publish recovery is missing: {required}"

for required_input in (
    "data/odds_builder.json",
    "data/odds_ticket_tracker.json",
    "data/virtual_lab_history.json",
    "data/virtual_lab_pending.json",
    "data/virtual_lab_live.json",
    "data/prediction_history.json",
    "data/expansion_prediction_history.json",
    "data/virtual_lab_archive/settlements",
):
    assert required_input in publish, f"change detection misses tracker input: {required_input}"

assert "git push --force" not in publish and "git push -f " not in publish, "must never force-push over main"
print("Ticket tracker publish-retry contract passed: preserve validated data on unrelated commits, recalculate on relevant source changes, no force-push.")
