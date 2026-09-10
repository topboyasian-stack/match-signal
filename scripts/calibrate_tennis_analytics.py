"""Refine secondary tennis analytics so weak signals do not imply false precision."""
import json
from pathlib import Path

DATA = Path("data")


def shrink(value, strength):
    return round(0.5 + strength * (float(value) - 0.5), 4)


def main():
    path = DATA / "predictions.json"
    predictions = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for prediction in predictions:
        if prediction.get("sport") != "tennis":
            continue
        quality = int((prediction.get("signal_quality") or {}).get("components", 0))
        analytics = prediction.get("analytics") or {}
        games = analytics.get("total_games") or {}
        if games:
            if quality < 3:
                games["over"] = 0.5
                games["under"] = 0.5
                games["pick"] = None
            else:
                strength = min(1.0, 0.65 + 0.10 * (quality - 3))
                games["over"] = shrink(games.get("over", 0.5), strength)
                games["under"] = round(1 - games["over"], 4)
                games["pick"] = "over" if games["over"] >= 0.5 else "under"
        handicap = analytics.get("games_handicap") or {}
        if handicap:
            margin = float(handicap.get("estimated_margin_p1", 0) or 0)
            if quality < 3:
                handicap["estimated_margin_p1"] = 0.0
                handicap["pick"] = None
            else:
                strength = min(1.0, 0.65 + 0.10 * (quality - 3))
                handicap["estimated_margin_p1"] = round(margin * strength, 2)
                handicap["pick"] = "p1" if handicap["estimated_margin_p1"] >= 0 else "p2"
        prediction["analytics"] = analytics
        quality_data = prediction.setdefault("signal_quality", {})
        quality_data["secondary_analytics_calibrated"] = True
        changed += 1
    path.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    print(f"Refined secondary tennis analytics: {changed}")


if __name__ == "__main__":
    main()
