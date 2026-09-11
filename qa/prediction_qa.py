"""Static QA gate/report for Match Signal generated prediction data."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "qa" / "report.json"


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def ok_prob(v):
    try:
        return 0 <= float(v) <= 1
    except Exception:
        return False


def valid_market_probs(probabilities, sport):
    """Football is 3-way (1X2); tennis/basketball are 2-way."""
    if sport == "football":
        values = [probabilities.get("p1"), probabilities.get("draw"), probabilities.get("p2")]
    else:
        values = [probabilities.get("p1"), probabilities.get("p2")]
    if not all(ok_prob(v) for v in values):
        return False
    return abs(sum(float(v) for v in values) - 1.0) <= 0.02


def check(rows, label):
    issues = []
    seen = set()
    for i, p in enumerate(rows):
        sport = str(p.get("sport", "")).lower()
        key = (str(p.get("event_id")), str(p.get("player_1")), str(p.get("player_2")))
        if key in seen:
            issues.append(f"{label}: duplicate fixture at index {i}")
        seen.add(key)
        if not p.get("player_1") or not p.get("player_2"):
            issues.append(f"{label}: missing name at index {i}")
        q = p.get("probabilities") or {}
        if not valid_market_probs(q, sport):
            issues.append(f"{label}: invalid probabilities at index {i}")
        if not ok_prob(p.get("confidence")):
            issues.append(f"{label}: invalid confidence at index {i}")
        if "Player 1" in str(p.get("player_1")) or "Player 2" in str(p.get("player_2")):
            issues.append(f"{label}: placeholder name at index {i}")
    return issues


def main():
    fb = load("predictions.json", [])
    bb = load("basketball_predictions.json", [])
    status = load("pipeline_status.json", {})
    acc = load("accuracy.json", {})
    bba = load("basketball_accuracy.json", {})
    issues = check(fb, "football/tennis") + check(bb, "basketball")
    sources = status.get("basketball_sources") or []
    warnings = [f"No accepted events for {s.get('competition', 'unknown')}" for s in sources if s.get("events", 0) == 0]
    settled = (acc.get("summary") or {}).get("settled", 0) + bba.get("settled", 0)
    empirical = "available" if settled else "not_yet_available"
    score = max(0, 100 - min(60, len(issues) * 5) - min(20, len(warnings) * 10) - (20 if not settled else 0))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not issues else "FAIL",
        "qa_score": score,
        "empirical_evaluation": empirical,
        "prediction_counts": {"football_tennis": len(fb), "basketball": len(bb), "settled_total": settled},
        "issues": issues[:100],
        "warnings": warnings,
        "checks": {
            "probabilities_valid": not any("invalid probabilities" in x for x in issues),
            "confidence_valid": not any("invalid confidence" in x for x in issues),
            "duplicates_checked": True,
            "placeholder_names_checked": True,
            "basketball_source_coverage_checked": True,
            "settlement_sample_present": bool(settled),
        },
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
