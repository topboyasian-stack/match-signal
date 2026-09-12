import json
import math
from pathlib import Path

import requests

from independent_football_model import independent_prediction
from value_decision import edge_and_ev, decision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
FOOTBALL_LEAGUES = {
    "EPL": "eng.1",
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Serie A": "ita.1",
    "Ligue 1": "fra.1",
    "Champions League": "uefa.champions",
    "MLS": "usa.1",
    "Primeira Liga": "por.1",
}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "MatchSignal/4.1 independent-model"})


def get_json(url):
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    return r.json()


def american_to_prob(odds):
    try:
        odds = float(odds)
        return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)
    except (TypeError, ValueError):
        return None


def market_1x2(event):
    try:
        market = (event.get("competitions") or [{}])[0].get("odds") or []
        market = market[0] if market else {}
        ml = market.get("moneyline") or market.get("moneyLine") or {}
        vals = []
        odds = []
        for side in ("home", "draw", "away"):
            node = ml.get(side) or {}
            close = node.get("close") or node.get("open") or {}
            o = close.get("odds")
            odds.append(o)
            vals.append(american_to_prob(o))
        if any(v is None for v in vals):
            return None
        s = sum(vals)
        return {"p1": vals[0] / s, "draw": vals[1] / s, "p2": vals[2] / s, "odds": odds}
    except Exception:
        return None


def calibration_temperature(calibration, sport):
    try:
        return float((calibration.get(sport) or {}).get("temperature", 1.0))
    except (TypeError, ValueError):
        return 1.0


def softmax_temperature(probs, temperature):
    temperature = max(0.5, min(2.5, float(temperature or 1.0)))
    logits = [math.log(max(1e-8, p)) / temperature for p in probs]
    m = max(logits)
    vals = [math.exp(x - m) for x in logits]
    s = sum(vals)
    return [v / s for v in vals]


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fetch_event(event_id, league):
    """Use the same ESPN league slug that generated the fixture; /soccer/all is unreliable for summary-by-event."""
    slug = FOOTBALL_LEAGUES.get(league, "eng.1")
    return get_json(f"{ESPN}/soccer/{slug}/summary?event={event_id}")


def main():
    pred_path = DATA / "predictions.json"
    history_path = DATA / "prediction_history.json"
    calibration_path = DATA / "calibration.json"
    predictions = load(pred_path, [])
    history = load(history_path, [])
    calibration = load(calibration_path, {})
    upgraded = 0
    warnings = 0
    paper_value = 0

    for row in predictions:
        if row.get("sport") != "football":
            row.setdefault("architecture", "market + statistical + calibration + value")
            row.setdefault("decision", "PAPER ONLY")
            continue
        event_id = row.get("event_id")
        if not event_id:
            continue
        try:
            event = fetch_event(event_id, row.get("league") or "")
            independent = independent_prediction(
                event,
                row.get("league") or "global",
                history,
                cutoff=row.get("calculated_at") or row.get("start_time"),
            )
            if not independent:
                continue
            raw = [independent["p1"], independent["draw"], independent["p2"]]
            calibrated = softmax_temperature(raw, calibration_temperature(calibration, "football"))
            market = market_1x2(event)
            row["independent_probabilities"] = {"p1": independent["p1"], "draw": independent["draw"], "p2": independent["p2"]}
            row["calibrated_probabilities"] = {"p1": round(calibrated[0], 4), "draw": round(calibrated[1], 4), "p2": round(calibrated[2], 4)}
            row["probabilities"] = {"p1": round(calibrated[0], 4), "draw": round(calibrated[1], 4), "p2": round(calibrated[2], 4)}
            row["pick"] = ["p1", "draw", "p2"][calibrated.index(max(calibrated))]
            row["confidence"] = round(max(calibrated), 4)
            row["expected_goals"] = {"p1": independent["xg_home"], "p2": independent["xg_away"], "total": round(independent["xg_home"] + independent["xg_away"], 4)}
            row["architecture"] = "independent statistical + market benchmark + calibration + value"
            row["model"] = independent["method"]
            row["market"] = market or {"available": False}
            row["market_probabilities"] = None if not market else {"p1": round(market["p1"], 4), "draw": round(market["draw"], 4), "p2": round(market["p2"], 4)}
            row["market_odds"] = None if not market else market["odds"]
            row["edge"] = None
            row["value"] = None
            row["decision"] = "PAPER ONLY"
            row["live_eligible"] = False
            row["testing_mode"] = "paper"
            if market:
                pick_idx = calibrated.index(max(calibrated))
                edge, ev = edge_and_ev(calibrated[pick_idx], market["odds"][pick_idx])
                row["edge"] = edge
                row["value"] = {"expected_value": ev, "odds": market["odds"][pick_idx], "market_implied": market[["p1", "draw", "p2"][pick_idx]]}
                dec = decision(calibrated[pick_idx], market["odds"][pick_idx], sample_ok=False)
                row["decision"] = dec["decision"]
                row["decision_reason"] = dec["reason"]
                if edge is not None and edge >= 0.035 and ev is not None and ev >= 0.05:
                    paper_value += 1
            upgraded += 1
        except Exception as exc:
            warnings += 1
            row.setdefault("upgrade_warnings", []).append(str(exc)[:180])

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "football_upgraded": upgraded, "positive_edge_paper_candidates": paper_value, "warnings": warnings}, indent=2))


if __name__ == "__main__":
    main()
