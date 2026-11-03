import json
import math
from pathlib import Path

from independent_football_model import independent_prediction
from value_decision import edge_and_ev, decision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_VERSION = "4.5-ucl-dual-competition"


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
    sporty = row.get("sportybet_winner_odds") or {}
    sporty_odds = [sporty.get("p1"), sporty.get("draw"), sporty.get("p2")]
    if all(o is not None for o in sporty_odds):
        try:
            values = [1.0/float(o) for o in sporty_odds]
            total = sum(values)
            if total > 0 and all(v > 0 for v in values):
                probs = [v/total for v in values]
                return {
                    "p1": probs[0],
                    "draw": probs[1],
                    "p2": probs[2],
                    "odds": sporty_odds,
                    "source": "SportyBet NG de-vig current market"
                }
        except (TypeError, ValueError, ZeroDivisionError):
            pass

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
        return {"p1": values[0], "draw": values[1], "p2": values[2], "odds": odds, "source": row.get("market_source")}
    except (TypeError, ValueError, KeyError):
        return None


def _apply_independent_probability_fields(row, independent, calibrated, calibration):
    """Replace legacy probability metadata with values from the current model pass."""
    keys = ("p1", "draw", "p2")
    raw = {key: round(float(independent[key]), 4) for key in keys}
    calibrated_values = {key: round(float(value), 4) for key, value in zip(keys, calibrated)}
    row["independent_probabilities"] = {
        key: round(float(independent[key]), 6) for key in keys
    }
    row["raw_probabilities"] = raw
    row["raw_confidence"] = round(max(raw.values()), 4)
    row["calibrated_probabilities"] = calibrated_values
    row["probabilities"] = calibrated_values.copy()
    row["pick"] = max(keys, key=lambda key: calibrated_values[key])
    row["confidence"] = round(max(calibrated_values.values()), 4)
    row["calibrated_confidence"] = row["confidence"]
    temperature = calibration_temperature(calibration, "football")
    row["calibration"] = {
        "market": "football:1x2",
        "method": "softmax_temperature",
        "temperature": round(float(temperature), 4),
        "raw": row["raw_confidence"],
        "calibrated": row["calibrated_confidence"],
        "version": calibration.get("version"),
    }



def _record_ucl_shadow_fields(row, independent, calibrated, market, calibration):
    """Store dual-competition UCL probabilities without replacing the published pick."""
    keys = ("p1", "draw", "p2")
    raw = {key: round(float(independent[key]), 6) for key in keys}
    shadow_calibrated = {
        key: round(float(value), 6)
        for key, value in zip(keys, calibrated)
    }
    pick = max(keys, key=lambda key: shadow_calibrated[key])
    row["independent_probabilities"] = raw
    row["independent_calibrated_probabilities"] = shadow_calibrated
    row["independent_shadow_pick"] = pick
    row["independent_shadow_confidence"] = shadow_calibrated[pick]
    row["independent_shadow_model_version"] = MODEL_VERSION
    row["independent_shadow_model_method"] = independent.get("method")
    row["independent_competition_form"] = independent.get("competition_form")
    row["independent_shadow_status"] = independent.get("competition_form_status") or "PARTIAL_HISTORY"
    row["independent_shadow_history_complete"] = row["independent_shadow_status"] == "COMPLETE"
    row["independent_shadow_use_for_tickets"] = False
    row["independent_shadow_promotion_status"] = "NOT_PROMOTED"
    row["independent_shadow_expected_goals"] = {
        "home": independent.get("xg_home"),
        "away": independent.get("xg_away"),
        "total": round(float(independent.get("xg_home") or 0) + float(independent.get("xg_away") or 0), 4),
    }
    row["independent_shadow_market"] = None
    if market:
        odds = [float(value) for value in market["odds"]]
        index = keys.index(pick)
        edge, expected_value = edge_and_ev(shadow_calibrated[pick], odds[index])
        row["independent_shadow_market"] = {
            "source": market.get("source"),
            "probabilities": {key: round(float(market[key]), 6) for key in keys},
            "odds": odds,
            "pick_edge": edge,
            "pick_expected_value": expected_value,
            "pick_odds": odds[index],
        }
    row["independent_diagnostics"] = {
        "sample_home": independent.get("sample_home", 0),
        "sample_away": independent.get("sample_away", 0),
        "effective_sample": independent.get("effective_sample", 0),
        "history_sufficient": independent.get("sample_home", 0) >= 2 and independent.get("sample_away", 0) >= 2,
        "history_source": "ESPN completed scoreboards + settled paper ledger",
        "recency_half_life_days": 120,
        "venue_aware": True,
        "dixon_coles": True,
        "dixon_coles_rho": independent.get("dixon_coles_rho"),
        "home_attack": independent.get("home_attack"),
        "home_defence": independent.get("home_defence"),
        "away_attack": independent.get("away_attack"),
        "away_defence": independent.get("away_defence"),
        "league_home_xg": independent.get("league_home_xg"),
        "league_away_xg": independent.get("league_away_xg"),
        "market_available": bool(market),
        "competition_form_status": independent.get("competition_form_status"),
        "competition_form": independent.get("competition_form"),
        "production_pick_changed": False,
        "ticket_qualification_changed": False,
    }


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
    ucl_shadowed = 0
    ucl_shadow_complete = 0
    ucl_shadow_partial = 0

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

            # The independent dual-competition model has not yet beaten the
            # published UCL model on walk-forward evidence. Keep its forecast
            # as a research shadow; never replace the active published pick,
            # probabilities, market decision, or Builder/ticket qualification.
            if str(row.get("league") or "").strip().lower() == "champions league":
                _record_ucl_shadow_fields(row, independent, calibrated, market, calibration)
                row["architecture"] = "published UCL prediction retained; domestic + Champions League model stored as paper shadow"
                row["live_eligible"] = False
                row["testing_mode"] = "paper"
                ucl_shadowed += 1
                if row["independent_shadow_history_complete"]:
                    ucl_shadow_complete += 1
                else:
                    ucl_shadow_partial += 1
                if not market:
                    no_market += 1
                upgraded += 1
                continue

            _apply_independent_probability_fields(row, independent, calibrated, calibration)
            row["expected_goals"] = {"p1": independent["xg_home"], "p2": independent["xg_away"], "total": round(independent["xg_home"] + independent["xg_away"], 4)}
            row["architecture"] = "independent statistical + market benchmark + calibration + value"
            row["model"] = independent["method"]
            row["model_version"] = MODEL_VERSION
            row["calibration_version"] = calibration.get("version")
            row["live_eligible"] = False
            row["testing_mode"] = "paper"

            if market:
                row["market_probabilities"] = {"p1": round(market["p1"], 4), "draw": round(market["draw"], 4), "p2": round(market["p2"], 4)}
                row["market_odds"] = market["odds"]
                row["market_source"] = market.get("source") or row.get("market_source") or "stored contemporaneous market"
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

            if str(row.get("league") or "").strip().lower() == "champions league":
                form_status = independent.get("competition_form_status") or "PARTIAL_HISTORY"
                row["ucl_form_gate"] = {
                    "eligible": form_status == "COMPLETE",
                    "status": form_status,
                    "reason": None if form_status == "COMPLETE" else "domestic_or_champions_league_venue_history_incomplete",
                }
                if form_status != "COMPLETE":
                    row["decision"] = "PAPER ONLY"
                    row["decision_reason"] = "ucl_dual_competition_history_incomplete"
            row["competition_form"] = independent.get("competition_form")
            row["competition_form_status"] = independent.get("competition_form_status")
            row["independent_diagnostics"] = {
                "sample_home": independent.get("sample_home", 0),
                "sample_away": independent.get("sample_away", 0),
                "effective_sample": independent.get("effective_sample", 0),
                "history_sufficient": independent.get("sample_home", 0) >= 2 and independent.get("sample_away", 0) >= 2,
                "history_source": "ESPN completed scoreboards + settled paper ledger",
                "recency_half_life_days": 120,
                "venue_aware": True,
                "dixon_coles": True,
                "dixon_coles_rho": independent.get("dixon_coles_rho"),
                "home_attack": independent.get("home_attack"),
                "home_defence": independent.get("home_defence"),
                "away_attack": independent.get("away_attack"),
                "away_defence": independent.get("away_defence"),
                "league_home_xg": independent.get("league_home_xg"),
                "league_away_xg": independent.get("league_away_xg"),
                "market_available": bool(market),
                "competition_form_status": independent.get("competition_form_status"),
                "competition_form": independent.get("competition_form"),
            }
            upgraded += 1
        except Exception as exc:
            warnings += 1
            row.setdefault("upgrade_warnings", []).append(str(exc)[:180])

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "model_version": MODEL_VERSION,
        "football_upgraded": upgraded,
        "positive_edge_paper_candidates": paper_value,
        "warnings": warnings,
        "football_without_sufficient_team_history": no_history,
        "football_without_contemporaneous_market": no_market,
        "ucl_shadow_predictions": ucl_shadowed,
        "ucl_shadow_complete_history": ucl_shadow_complete,
        "ucl_shadow_partial_history": ucl_shadow_partial,
        "ucl_shadow_policy": "research-only; published pick/probabilities/decision and ticket qualification are preserved",
        "external_team_history_rows": len(external_team_history),
    }, indent=2))


if __name__ == "__main__":
    main()
