#!/usr/bin/env python3
"""Refresh the frozen-cutoff NBA totals OOS report from current evidence only.

This deliberately does not call SportyBet, alter predictions, append quote snapshots,
or update settlement records. It re-evaluates the existing official ESPN ledger and
immutable market-225 publication snapshots so the OOS report cannot remain stale after
a settlement-only update.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from nba_totals_walk_forward import evaluate as evaluate_nba_totals

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "nba_history.json"
LEDGER = DATA / "nba_totals_ledger.json"
SNAPSHOTS = DATA / "nba_totals_publication_snapshots.json"
PREDICTIONS = DATA / "nba_predictions.json"
OUTPUT = DATA / "nba_totals_oos_value_test.json"
FROZEN_CUTOFF = "2026-11-02T02:00:00+00:00"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    history = load_json(HISTORY)
    ledger_payload = load_json(LEDGER)
    snapshots = load_json(SNAPSHOTS)
    predictions = load_json(PREDICTIONS)

    if not isinstance(history, list):
        raise TypeError("NBA history must be a JSON list.")
    if not isinstance(snapshots, list):
        raise TypeError("NBA publication snapshots must be a JSON list.")
    if not isinstance(predictions, list):
        raise TypeError("NBA predictions must be a JSON list.")
    if not isinstance(ledger_payload, dict) or not isinstance(ledger_payload.get("records"), list):
        raise TypeError("NBA totals ledger must contain a records list.")

    report = evaluate_nba_totals(
        history,
        ledger_payload["records"],
        snapshots,
        predictions,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    if report.get("paper_only") is not True or report.get("market_id") != "225":
        raise RuntimeError("OOS report failed the paper-only exact market-225 contract.")
    if report.get("holdout_protocol", {}).get("fixed_cutoff_utc") != FROZEN_CUTOFF:
        raise RuntimeError("OOS report attempted to move the frozen prospective cutoff.")

    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "generated_at": report.get("generated_at"),
        "paper_only": report.get("paper_only"),
        "market_id": report.get("market_id"),
        "fixed_cutoff_utc": report.get("holdout_protocol", {}).get("fixed_cutoff_utc"),
        "forecast_holdout_n": report.get("walk_forward", {}).get("holdout", {}).get("n"),
        "market_holdout_n": report.get("market_holdout", {}).get("n"),
        "release_decision": report.get("release_decision"),
    }, indent=2))


if __name__ == "__main__":
    main()
