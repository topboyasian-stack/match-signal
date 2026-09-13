"""Attach descriptive behavior context to predictions without changing probabilities."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FOOTBALL_LEAGUES = {"EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Champions League", "MLS", "Primeira Liga"}


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    profiles = load("behavior_profiles.json", {})
    teams = profiles.get("teams", {})
    predictions = load("predictions.json", [])
    matched = 0
    for row in predictions:
        league = row.get("league") or "global"
        sport = row.get("sport")
        contexts = {}
        for side, name in (("p1", row.get("player_1")), ("p2", row.get("player_2"))):
            if not name:
                continue
            p = teams.get(f"{league}|{name}")
            if p:
                contexts[side] = p
        row["behavior_context"] = {
            "version": profiles.get("version"),
            "matched": bool(contexts),
            "teams": contexts,
            "source": "behavior_profiles.json",
            "use": "context_only_unvalidated",
            "probability_adjustment_applied": False,
        }
        if contexts:
            matched += 1
        if sport == "tennis":
            row.setdefault("individual_behavior_context", {})
            for side, name in (("p1", row.get("player_1")), ("p2", row.get("player_2"))):
                if name and name in profiles.get("individuals", {}):
                    row["individual_behavior_context"][side] = profiles["individuals"][name]
    (DATA / "predictions.json").write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "predictions": len(predictions), "behavior_matches": matched, "probability_adjustment_applied": False}, indent=2))


if __name__ == "__main__":
    main()
