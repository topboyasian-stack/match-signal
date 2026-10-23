"""Settle live-experimental NBA/Eredivisie predictions into an auditable ledger."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from expansion_pipeline import collect

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEDGER = DATA / "expansion_prediction_history.json"


def norm(v):
    return " ".join(str(v or "").lower().replace("fc", "").split())


def load(path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def settle():
    ledger = load(LEDGER, [])
    existing = {str(x.get("event_id")): x for x in ledger}
    completed = {}
    for league, key in (("Eredivisie", "football"), ("NBA", "basketball")):
        try: rows, _ = collect(league)
        except Exception: rows = []
        for r in rows:
            completed[(league, norm(r.get("home")), norm(r.get("away")), str(r.get("date"))[:10])] = r

    changed = 0
    for filename, league in (("ere_divisie_predictions.json", "Eredivisie"), ("nba_predictions.json", "NBA")):
        preds = load(DATA / filename, [])
        for p in preds:
            if not p.get("live_experimental"): continue
            # Only score forecasts saved before tip-off. A current/live guess
            # must never be backfilled as a successful pre-game prediction.
            try:
                start = datetime.fromisoformat(str(p.get("start_time") or "").replace("Z", "+00:00"))
                stamp = datetime.fromisoformat(str(p.get("generated_at") or p.get("prediction_created_at") or "").replace("Z", "+00:00"))
                if start.tzinfo is None: start = start.replace(tzinfo=timezone.utc)
                if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp >= start or p.get("accuracy_eligible") is False: continue
            except (TypeError, ValueError):
                continue
            eid = str(p.get("event_id"))
            if eid in existing and existing[eid].get("settled"): continue
            key = (league, norm(p.get("player_1")), norm(p.get("player_2")), str(p.get("start_time"))[:10])
            r = completed.get(key)
            if not r: continue
            hg, ag = r.get("home_score"), r.get("away_score")
            if hg is None or ag is None: continue
            if league == "Eredivisie":
                outcome = "p1" if hg > ag else "p2" if ag > hg else "draw"
                correct = p.get("pick") == outcome
                pr = p.get("probabilities") or {}
                brier = ((pr.get("p1",0)-(outcome=="p1"))**2 + (pr.get("draw",0)-(outcome=="draw"))**2 + (pr.get("p2",0)-(outcome=="p2"))**2) / 3
                total = hg + ag
                ou = p.get("markets",{}).get("over_under",{})
                btts = p.get("markets",{}).get("btts",{})
                ou_result = "over" if total > 2.5 else "under" if total < 2.5 else "push"
                btts_result = "yes" if hg > 0 and ag > 0 else "no"
                extra = {"over_under_result": ou_result, "btts_result": btts_result, "brier": round(brier,6)}
            else:
                outcome = "p1" if hg > ag else "p2"
                correct = p.get("pick") == outcome
                pr = p.get("probabilities") or {}
                brier = ((pr.get("p1",0)-(outcome=="p1"))**2 + (pr.get("p2",0)-(outcome=="p2"))**2) / 2
                extra = {"brier": round(brier,6)}
                # ESPN's final NBA score is the official game total and includes
                # overtime points when OT was played. Only settle a total if a
                # pre-game SportyBet market-225 snapshot was captured.
                total_market = (p.get("markets") or {}).get("total_ou") or {}
                try:
                    total_line = float(total_market.get("line"))
                    valid_total_line = 100 <= total_line <= 300
                except (TypeError, ValueError):
                    total_line, valid_total_line = None, False
                if valid_total_line:
                    final_total = float(hg) + float(ag)
                    total_result = "over" if final_total > total_line else "under" if final_total < total_line else "push"
                    total_pick = total_market.get("pick") if total_market.get("pick") in ("over", "under") else None
                    extra.update({
                        "total_ou_line": total_line,
                        "total_ou_pick": total_pick,
                        "total_ou_result": total_result,
                        "total_ou_final_points": int(final_total) if final_total.is_integer() else final_total,
                        "total_ou_correct": (total_pick == total_result) if total_pick and total_result != "push" else None,
                        "total_ou_push": total_result == "push",
                        "total_ou_source": total_market.get("source"),
                        "total_ou_market_id": str(total_market.get("market_id") or ""),
                        "total_ou_quote_timestamp": total_market.get("quote_timestamp"),
                        "total_ou_settlement_rule": "Official final score including overtime",
                    })
            existing[eid] = {"event_id": eid, "league": league, "sport": p.get("sport"), "start_time": p.get("start_time"), "player_1": p.get("player_1"), "player_2": p.get("player_2"), "pick": p.get("pick"), "confidence": p.get("confidence"), "probabilities": p.get("probabilities"), "prediction_created_at": p.get("generated_at") or p.get("prediction_created_at"), "prediction_was_pregame": True, "settled": True, "settled_at": datetime.now(timezone.utc).isoformat(), "final_score": [hg, ag], "outcome": outcome, "correct": bool(correct), **extra}
            changed += 1

    result = sorted(existing.values(), key=lambda x: str(x.get("start_time")))
    LEDGER.write_text(json.dumps(result, indent=2), encoding="utf-8")
    stats = {}
    for league in ("Eredivisie", "NBA"):
        rows = [x for x in result if x.get("league") == league and x.get("settled")]
        stats[league] = {"settled": len(rows), "correct": sum(bool(x.get("correct")) for x in rows), "accuracy": round(sum(bool(x.get("correct")) for x in rows)/len(rows),4) if rows else None, "avg_brier": round(sum(float(x.get("brier",0)) for x in rows)/len(rows),6) if rows else None}
        if league == "NBA":
            total_rows = [x for x in rows if x.get("total_ou_correct") is not None]
            total_pushes = sum(bool(x.get("total_ou_push")) for x in rows)
            stats[league].update({
                "total_ou_settled": len(total_rows),
                "total_ou_correct": sum(bool(x.get("total_ou_correct")) for x in total_rows),
                "total_ou_accuracy": round(sum(bool(x.get("total_ou_correct")) for x in total_rows)/len(total_rows),4) if total_rows else None,
                "total_ou_pushes": total_pushes,
            })
    (DATA/"expansion_live_performance.json").write_text(json.dumps({"updated_at":datetime.now(timezone.utc).isoformat(),"mode":"LIVE_EXPERIMENTAL","competitions":stats},indent=2),encoding="utf-8")
    print(json.dumps({"settled_now": changed, "performance": stats}, indent=2))


if __name__ == "__main__": settle()
