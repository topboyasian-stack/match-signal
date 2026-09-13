import json
import math
from pathlib import Path

from independent_football_model import independent_prediction
from value_decision import edge_and_ev, decision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


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


def row_to_event(row):
    return {
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"displayName": row.get("player_1") or "Home"}},
                {"homeAway": "away", "team": {"displayName": row.get("player_2") or "Away"}},
            ]
        }]
    }


def valid_market(row):
    probs = row.get("market_probabilities")
    odds = row.get("market_odds")
    if not isinstance(probs, dict) or not isinstance(odds, list) or len(odds) != 3:
        return None
    try:
        values = [float(probs["p1"]), float(probs["draw"]), float(probs["p2"])]
        if abs(sum(values) - 1.0) > 0.02 or any(not (0 < v < 1) for v in values):
            return None
        if any(o is None for o in odds):
            return None
        return {"p1": values[0], "draw": values[1], "p2": values[2], "odds": odds}
    except (TypeError, ValueError, KeyError):
        return None


def main():
    pred_path = DATA / "predictions.json"
    history_path = DATA / "prediction_history.json"
    calibration_path = DATA / "calibration.json"
    team_history_path = DATA / "football_team_history.json"
    predictions = load(pred_path, [])
    history = load(history_path, [])
    external_team_history = load(team_history_path, [])
    calibration = load(calibration_path, {})
    model_history = history + external_team_history

    upgraded = 0
    warnings = 0
    paper_value = 0
    no_history = 0
    no_market = 0

    for row in predictions:
        if row.get("sport") != "football":
            row.setdefault("architecture", "independent statistical + market benchmark + calibration + value")
            row.setdefault("decision", "PAPER ONLY")
            continue

        try:
            independent = independent_prediction(
                row_to_event(row),
                row.get("league") or "global",
                model_history,
                cutoff=row.get("calculated_at") or row.get("start_time"),
            )
            if not independent:
                warnings += 1
                row.setdefault("upgrade_warnings", []).append("independent model returned no prediction")
                continue

            if independent.get("sample_home", 0) < 2 or independent.get("sample_away", 0) < 2:
                no_history += 1

            raw = [independent["p1"], independent["draw"], independent["p2"]]
            calibrated = softmax_temperature(raw, calibration_temperature(calibration, "football"))
            market = valid_market(row)

            row["independent_probabilities"] = {"p1": independent["p1"], "draw": independent["draw"], "p2": independent["p2"]}
            row["calibrated_probabilities"] = {"p1": round(calibrated[0], 4), "draw": round(calibrated[1], 4), "p2": round(calibrated[2], 4)}
            row["probabilities"] = {"p1": round(calibrated[0], 4), "draw": round(calibrated[1], 4), "p2": round(calibrated[2], 4)}
            row["pick"] = ["p1", "draw", "p2"][calibrated.index(max(calibrated))]
            row["confidence"] = round(max(calibrated), 4)
            row["expected_goals"] = {"p1": independent["xg_home"], "p2": independent["xg_away"], "total": round(independent["xg_home"] + independent["xg_away"], 4)}
            row["architecture"] = "independent statistical + market benchmark + calibration + value"
            row["model"] = independent["method"]
            row["model_version"] = "4.3-recency-weighted-365d"
            row["calibration_version"] = calibration.get("version")
            row["live_eligible"] = False
            row["testing_mode"] = "paper"

            if market:
                row["market_probabilities"] = {"p1": round(market["p1"], 4), "draw": round(market["draw"], 4), "p2": round(market["p2"], 4)}
                row["market_odds"] = market["odds"]
                row["market_source"] = row.get("market_source") or "stored contemporaneous market"
                pick_idx = calibrated.index(max(calibrated))
                edge, ev = edge_and_ev(calibrated[pick_idx], market["odds"][pick_idx])
                row["edge"] = edge
                row["value"] = {"expected_value": ev, "odds": market["odds"][pick_idx], "market_implied": market[["p1", "draw", "p2"][pick_idx]]}
                dec = decision(calibrated[pick_idx], market["odds"][pick_idx], sample_ok=False)
                row["decision"] = dec["decision"]
                row["decision_reason"] = dec["reason"]
                if edge is not None and edge >= 0.035 and ev is not None and ev >= 0.05:
                    paper_value += 1
            else:
                no_market += 1
                row["market_probabilities"] = None
                row["market_odds"] = None
                row["market_source"] = None
                row["edge"] = None
                row["value"] = {"expected_value": None, "odds": None, "market_implied": None}
                row["decision"] = "PAPER ONLY"
                row["decision_reason"] = "no_contemporaneous_market_data"

            row["independent_diagnostics"] = {
                "sample_home": independent.get("sample_home", 0),
                "sample_away": independent.get("sample_away", 0),
                "history_sufficient": independent.get("sample_home", 0) >= 2 and independent.get("sample_away", 0) >= 2,
                "history_source": "ESPN completed scoreboards + settled paper ledger",
                "recency_half_life_days": 120,
                "market_available": bool(market),
            }
            upgraded += 1
        except Exception as exc:
            warnings += 1
            row.setdefault("upgrade_warnings", []).append(str(exc)[:180])

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "football_upgraded": upgraded,
        "positive_edge_paper_candidates": paper_value,
        "warnings": warnings,
        "football_without_sufficient_team_history": no_history,
        "football_without_contemporaneous_market": no_market,
        "external_team_history_rows": len(external_team_history),
    }, indent=2))


if __name__ == "__main__":
    main()
