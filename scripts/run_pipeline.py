"""Pipeline entrypoint with production tennis fixture QC.

The analytical predictor remains in predict_today.py. This wrapper supplies the
correct ESPN-aware fixture validator: athlete IDs are optional on the scoreboard,
while placeholder names and doubles/team draws are rejected.
"""
import runpy

GENERIC_NAMES = {"", "player 1", "player 2", "tbd", "tba", "unknown", "unknown player", "team 1", "team 2"}
DOUBLES_MARKERS = ("double", "doubles", "mixed", "team")


def tennis_fixture_quality(event):
    draw_type = str(event.get("draw_type") or "").strip().lower()
    if any(marker in draw_type for marker in DOUBLES_MARKERS):
        return False, "non-singles draw"

    competitors = event.get("competitors", [])
    if len(competitors) != 2:
        return False, "not exactly two competitors"

    names = []
    for competitor in competitors:
        athlete = competitor.get("athlete") or {}
        name = (athlete.get("displayName") or competitor.get("displayName") or "").strip()
        lowered = name.lower()
        if lowered in GENERIC_NAMES or len(name) < 3:
            return False, "missing real player name"
        if " / " in name or " & " in name:
            return False, "non-singles competitor"
        names.append(name)

    if names[0].lower() == names[1].lower():
        return False, "duplicate player names"
    return True, None


namespace = runpy.run_path("scripts/predict_today.py")
namespace["tennis_fixture_quality"] = tennis_fixture_quality
namespace["main"]()
