"""Run the leakage-safe V5.1 tennis Total Games walk-forward backtest."""
from pathlib import Path
import json
from tennis_total_model import walk_forward_backtest

ROOT = Path(__file__).resolve().parents[1]
history = json.loads((ROOT / "data" / "prediction_history.json").read_text(encoding="utf-8"))
result = walk_forward_backtest(history)
print(json.dumps(result, indent=2, sort_keys=True))
if result.get("status") != "ok":
    raise SystemExit(1)
if result["v51_brier"] >= result["baseline_brier"]:
    raise SystemExit("V5.1 failed to improve Brier score over the legacy baseline")
