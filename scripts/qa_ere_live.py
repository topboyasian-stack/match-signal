"""Sanity-check live Eredivisie predictions before publication."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main():
    preds = load("ere_divisie_predictions.json")
    history = load("ere_divisie_history.json")
    now = datetime.now(timezone.utc)
    errors = []
    warnings = []
    seen = set()

    for p in preds:
        eid = p.get("event_id")
        if not eid or eid in seen:
            errors.append(f"duplicate/missing event_id: {eid}")
        seen.add(eid)
        probs = p.get("probabilities", {})
        vals = [float(probs.get("p1", -1)), float(probs.get("draw", -1)), float(probs.get("p2", -1))]
        if any(v < 0 or v > 1 for v in vals) or abs(sum(vals) - 1.0) > 0.002:
            errors.append(f"probability sum/range failure: {eid} -> {vals}")
        try:
            start = datetime.fromisoformat(str(p["start_time"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start <= now - __import__("datetime").timedelta(hours=2):
                errors.append(f"published fixture is already past: {eid} {start.isoformat()}")
        except Exception:
            errors.append(f"invalid start_time: {eid}")
        eg = p.get("expected_goals", {})
        if any(float(eg.get(k, -1)) < 0.2 or float(eg.get(k, 99)) > 4.8 for k in ("p1", "p2")):
            errors.append(f"xG outside safety bounds: {eid}")
        m = p.get("markets", {})
        ou = m.get("over_under", {})
        bt = m.get("btts", {})
        if abs(float(ou.get("over", 0)) + float(ou.get("under", 0)) - 1) > 0.002:
            errors.append(f"O/U probabilities invalid: {eid}")
        if abs(float(bt.get("yes", 0)) + float(bt.get("no", 0)) - 1) > 0.002:
            errors.append(f"BTTS probabilities invalid: {eid}")
        if not p.get("live_experimental") or p.get("prediction_status") != "live_experimental":
            errors.append(f"not marked live_experimental: {eid}")
        q = p.get("signal_quality", {})
        if float(q.get("effective_sample") or 0) < 1:
            warnings.append(f"very sparse effective sample: {eid} ({q.get('effective_sample')})")
        if p.get("market", {}).get("status") == "NO_FREE_CURRENT_ODDS_SOURCE":
            warnings.append(f"no current free odds benchmark: {eid}")

    if not preds:
        errors.append("no Eredivisie predictions published")
    if len(history) < 50:
        errors.append(f"history unexpectedly small: {len(history)}")

    result = {
        "checked_at": now.isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "prediction_count": len(preds),
        "history_count": len(history),
        "errors": errors,
        "warnings": warnings,
    }
    (DATA / "ere_divisie_qa.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
