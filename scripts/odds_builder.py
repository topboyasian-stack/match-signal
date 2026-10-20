"""Stable entry point for Match Signal Odds Builder."""
import sys
import odds_builder_core as _core

def _upcoming_desk_recent_result_guard(product, line, side, tracker=None, min_loss_streak=4):
    try:
        line_key = f"{float(line):g}"
    except (TypeError, ValueError):
        return {"blocked": False, "reason": "invalid_line", "sample_n": 0, "loss_streak": 0, "recent_results": []}
    index = _core._upcoming_desk_settled_result_index(tracker)
    rows = index.get((str(product or "").lower(), line_key, str(side or "").lower()), [])
    streak = 0
    for row in rows:
        if row.get("status") == "LOST":
            streak += 1
        else:
            break
    decisive = [row for row in rows if row.get("status") in {"WON", "LOST"}]
    latest10, latest20 = decisive[:10], decisive[:20]
    wins10 = sum(row.get("status") == "WON" for row in latest10)
    wins20 = sum(row.get("status") == "WON" for row in latest20)
    rate10 = wins10 / len(latest10) if latest10 else None
    rate20 = wins20 / len(latest20) if latest20 else None
    threshold = max(1, int(min_loss_streak or 4))
    block_streak = streak >= threshold
    block10 = len(latest10) >= 10 and rate10 < 0.50
    block20 = len(latest20) >= 20 and rate20 < 0.55
    blocked = block_streak or block10 or block20
    reason = ("recent_settled_line_side_loss_streak" if block_streak else
              "recent_settled_line_side_last10_below_0_50" if block10 else
              "recent_settled_line_side_last20_below_0_55" if block20 else None)
    recent = [{"event_id": row.get("event_id"), "status": row.get("status"),
               "settled_at": row.get("settled_at"), "source": row.get("source")} for row in rows[:5]]
    last3, last5 = rows[:3], rows[:5]
    return {
        "blocked": blocked, "reason": reason, "product": str(product or "").lower(),
        "line": line_key, "side": str(side or "").lower(), "sample_n": len(rows),
        "decisive_sample_n": len(decisive), "consecutive_losses": streak,
        "latest_three_n": len(last3), "latest_three_losses": sum(r.get("status") == "LOST" for r in last3),
        "latest_five_n": len(last5), "latest_five_losses": sum(r.get("status") == "LOST" for r in last5),
        "latest_five_loss_rate": round(sum(r.get("status") == "LOST" for r in last5) / len(last5), 4) if last5 else 0.0,
        "latest10_n": len(latest10), "latest10_wins": wins10,
        "latest10_hit_rate": round(rate10, 4) if rate10 is not None else None,
        "latest20_n": len(latest20), "latest20_wins": wins20,
        "latest20_hit_rate": round(rate20, 4) if rate20 is not None else None,
        "threshold": threshold, "latest10_hit_rate_floor": 0.50, "latest20_hit_rate_floor": 0.55,
        "recent_results": recent,
    }

_core._upcoming_desk_recent_result_guard = _upcoming_desk_recent_result_guard
if __name__ == "__main__":
    raise SystemExit(_core.main())
else:
    sys.modules[__name__] = _core
