"""Build Match Signal's auditable paper tip ledger and monetization exports.
This layer does not change prediction engines or place bets. PAPER/RESEARCH ONLY.
"""
import csv, json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def load(name, default):
    try:
        with open(DATA / name, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

def save(name, value):
    with open(DATA / name, "w", encoding="utf-8") as f: json.dump(value, f, indent=2, ensure_ascii=False)

def dt(v):
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception: return None

def market_name(p):
    a = p.get("analytics") or {}
    if (a.get("total_games") or {}).get("pick") in {"over", "under"}: return "tennis_total_games"
    if p.get("sport") == "football": return "match_winner_1x2"
    return "match_winner"

def price(p):
    for obj in (p.get("bookmaker_odds"), p.get("odds"), (p.get("markets") or {}).get("odds")):
        if isinstance(obj, dict):
            for key in (p.get("pick"), "decimal", "price"):
                try:
                    value = float(obj.get(key))
                    if value > 1.0: return value
                except (TypeError, ValueError): pass
    return None

def row_from_prediction(p):
    start, calculated = dt(p.get("start_time")), dt(p.get("calculated_at"))
    if not start or not calculated or calculated >= start: return None
    probs, pick = p.get("probabilities") or {}, p.get("pick")
    try: prob = float(probs.get(pick, p.get("confidence")))
    except (TypeError, ValueError): return None
    odds, points_pl = price(p), None
    if odds is not None and p.get("settled"):
        points_pl = round(odds - 1.0, 6) if p.get("correct") is True else (-1.0 if p.get("correct") is False else None)
    return {
        "publication_id": f"{p.get('sport','')}-{p.get('league','')}-{p.get('event_id','')}-{market_name(p)}-{pick}",
        "published_at": calculated.isoformat(), "event_id": str(p.get("event_id")), "start_time": start.isoformat(),
        "sport": p.get("sport"), "competition": p.get("league"),
        "event": f"{p.get('player_1','')} vs {p.get('player_2','')}", "market": market_name(p), "selection": pick,
        "model_probability": round(prob, 6), "model_fair_odds": round(1.0 / prob, 4) if prob > 0 else None,
        "bookmaker_odds": odds, "odds_source": "source_record" if odds is not None else None,
        "edge": round(prob - (1.0 / odds), 6) if odds else None, "settled": bool(p.get("settled")),
        "result": p.get("actual"), "correct": p.get("correct"), "brier": p.get("brier"), "points_pl": points_pl,
        "roi": points_pl, "roi_status": "MEASURED" if points_pl is not None else "PENDING_REAL_BOOKMAKER_ODDS",
        "publication_status": "PAPER_TRACKED", "decision": p.get("decision", "PAPER ONLY")
    }

def aggregate(items):
    settled = [x for x in items if x["settled"]]
    measured = [x for x in settled if x["roi"] is not None]
    return {
        "published": len(items), "settled": len(settled), "correct": sum(x["correct"] is True for x in settled),
        "accuracy": round(sum(x["correct"] is True for x in settled) / len(settled), 4) if settled else 0.0,
        "measured_roi": round(sum(float(x["roi"]) for x in measured) / len(measured), 4) if measured else None,
        "roi_observations": len(measured)
    }

def main():
    merged = {}
    for p in load("prediction_history.json", []) + load("predictions.json", []):
        row = row_from_prediction(p)
        if row: merged[row["publication_id"]] = row
    rows = sorted(merged.values(), key=lambda x: x["published_at"])
    by_sport = {s: aggregate([r for r in rows if r["sport"] == s]) for s in sorted({r["sport"] for r in rows})}
    by_market = {m: aggregate([r for r in rows if r["market"] == m]) for m in sorted({r["market"] for r in rows})}
    by_conf = {}
    for lo, hi in ((.50,.60),(.60,.65),(.65,.70),(.70,.80),(.80,1.01)):
        by_conf[f"{lo:.2f}-{hi:.2f}"] = aggregate([r for r in rows if lo <= r["model_probability"] < hi])
    payload = {
        "version":"verified-tip-ledger-v1", "updated_at":datetime.now(timezone.utc).isoformat(),
        "status":"PAPER_TRACKED_NOT_LIVE_MONETIZED",
        "methodology":{"publication_rule":"calculated_at must precede start_time","settlement_source":"prediction_history.json","roi_rule":"ROI only when a real bookmaker decimal price exists","no_retroactive_publication":True},
        "summary":aggregate(rows), "by_sport":by_sport, "by_market":by_market, "by_confidence":by_conf, "rows":rows
    }
    save("verified_tip_ledger.json", payload)
    save("tippingsports_export.json", {"version":"tippingsports-prep-v1","status":"EXPORT_READY_MANUAL_SUBMISSION","note":"External platform eligibility/submission remains separate; this is a structured paper-tip export.","tips":[{k:r.get(k) for k in ("published_at","sport","competition","event","market","selection","model_probability","bookmaker_odds","points_pl","roi")} for r in rows]})
    with open(DATA / "tippingsports_export.csv", "w", newline="", encoding="utf-8") as f:
        fields=["published_at","sport","competition","event","market","selection","model_probability","bookmaker_odds","points_pl","roi"]
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
    print(f"Verified ledger: {len(rows)} published paper rows")
if __name__ == "__main__": main()
