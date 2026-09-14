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
            existing[eid] = {"event_id": eid, "league": league, "sport": p.get("sport"), "start_time": p.get("start_time"), "player_1": p.get("player_1"), "player_2": p.get("player_2"), "pick": p.get("pick"), "confidence": p.get("confidence"), "probabilities": p.get("probabilities"), "settled": True, "settled_at": datetime.now(timezone.utc).isoformat(), "final_score": [hg, ag], "outcome": outcome, "correct": bool(correct), **extra}
            changed += 1

    result = sorted(existing.values(), key=lambda x: str(x.get("start_time")))
    LEDGER.write_text(json.dumps(result, indent=2), encoding="utf-8")
    stats = {}
    for league in ("Eredivisie", "NBA"):
        rows = [x for x in result if x.get("league") == league and x.get("settled")]
        stats[league] = {"settled": len(rows), "correct": sum(bool(x.get("correct")) for x in rows), "accuracy": round(sum(bool(x.get("correct")) for x in rows)/len(rows),4) if rows else None, "avg_brier": round(sum(float(x.get("brier",0)) for x in rows)/len(rows),6) if rows else None}
    (DATA/"expansion_live_performance.json").write_text(json.dumps({"updated_at":datetime.now(timezone.utc).isoformat(),"mode":"LIVE_EXPERIMENTAL","competitions":stats},indent=2),encoding="utf-8")
    print(json.dumps({"settled_now": changed, "performance": stats}, indent=2))


if __name__ == "__main__": settle()
