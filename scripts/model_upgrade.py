import json
import math
from datetime import datetime, timezone
from pathlib import Path

from independent_football_model import independent_prediction, _canonical_competition
from football_prequential_ensemble import (
    CompetitionElo,
    build_report as build_football_validation_report,
    normalize_probs,
    probabilities_for_scope,
    safe_history_cutoff,
)
from value_decision import edge_and_ev, decision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_VERSION = "5.0-prequential-competition-validated"


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



def apply_validated_competition_probabilities(row, published, selected, scope):
    """Apply only a competition model independently selected and validated on holdout.

    This updates the forecast itself, but does not grant money, Builder, or ticket
    eligibility. All such fields are deliberately left untouched.
    """
    if not isinstance(scope, dict) or scope.get("status") != "RESEARCH_SCOPE_VALIDATED":
        return False
    if not isinstance(selected, dict) or not all(k in selected for k in ("p1", "draw", "p2")):
        return False

    selected = normalize_probs(selected)
    baseline = normalize_probs(published)
    protected = {
        key: row.get(key)
        for key in (
            "live_eligible",
            "betting_qualified",
            "qualified_for_builder",
            "builder_eligible",
            "real_money_eligible",
            "paper_only",
        )
        if key in row
    }
    row.setdefault("published_model_probabilities", {
        key: round(float(baseline[key]), 6) for key in ("p1", "draw", "p2")
    })
    row["probabilities"] = {key: round(float(selected[key]), 6) for key in ("p1", "draw", "p2")}
    row["calibrated_probabilities"] = dict(row["probabilities"])
    row["pick"] = max(("p1", "draw", "p2"), key=lambda key: row["probabilities"][key])
    row["confidence"] = round(row["probabilities"][row["pick"]], 4)
    row["calibrated_confidence"] = row["confidence"]
    row["football_model_version"] = MODEL_VERSION
    row["football_model_validation"] = {
        "status": "RESEARCH_SCOPE_VALIDATED",
        "selected_model": scope.get("selected_model"),
        "development_n": scope.get("development_n"),
        "holdout_n": scope.get("holdout_n"),
        "development_metrics": scope.get("development_metrics"),
        "holdout_metrics": scope.get("holdout_metrics"),
        "published_holdout_metrics": scope.get("published_holdout_metrics"),
        "evidence": scope.get("evidence"),
        "market_independent": True,
        "live_money_approved": False,
        "ticket_release_approved": False,
    }
    row["model"] = f"Chronological competition model: {scope.get('selected_model')}"
    row["model_version"] = MODEL_VERSION
    row["architecture"] = "development-selected competition model + untouched chronological holdout + SportyBet value benchmark"
    row["calibration"] = {
        "market": "football:1X2",
        "method": "native model probabilities; scope selected on development and passed untouched holdout",
        "temperature": None,
        "raw": row["confidence"],
        "calibrated": row["confidence"],
        "version": MODEL_VERSION,
    }
    row["live_eligible"] = False
    row["testing_mode"] = "paper"
    for key, value in protected.items():
        row[key] = value
    return True


def _competition_elo_probabilities(history, row, cache):
    # Never substitute kickoff for a missing forecast timestamp: doing so could
    # admit results that were not safely observable before the original forecast.
    cutoff = safe_history_cutoff(row.get("calculated_at"))
    if cutoff is None:
        return None
    key = cutoff.isoformat()
    if key not in cache:
        model = CompetitionElo(history)
        model.advance_before(cutoff)
        cache[key] = model
    return cache[key].predict(
        row.get("league") or "global",
        row.get("player_1") or "Home",
        row.get("player_2") or "Away",
    )



def build_validation_audit(validation_report, football_upgraded, validated_updates, validated_scope_counts, warnings):
    """Build a timestamped, explicit audit of the prequential model run."""
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "PAPER_RESEARCH_ONLY",
        "model_version": MODEL_VERSION,
        "validation_report_status": validation_report.get("status"),
        "validation_total_eligible": int(validation_report.get("total_eligible", 0) or 0),
        "validation_development_n": int(validation_report.get("development_n", 0) or 0),
        "validation_holdout_n": int(validation_report.get("holdout_n", 0) or 0),
        "global_blend_promotion_allowed": bool(validation_report.get("promotion_allowed", False)),
        "validated_competition_scopes": validation_report.get("validated_competition_scopes") or {},
        "validated_scope_prediction_counts": dict(validated_scope_counts),
        "validated_model_prediction_updates": int(validated_updates),
        "football_predictions_processed": int(football_upgraded),
        "warnings": int(warnings),
        "live_money_approved": False,
        "ticket_release_approved": False,
        "release_gates_changed": False,
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

    # Re-evaluate model choice using only pre-kickoff historical predictions.
    # A competition becomes eligible for a prediction-model update only when
    # its own development-selected challenger passes its own untouched holdout.
    try:
        validation_report = build_football_validation_report(history, external_team_history)
    except Exception as exc:
        validation_report = {
            "status": "VALIDATION_ERROR",
            "validated_competition_scopes": {},
            "validation_error": str(exc)[:240],
        }
    validated_scopes = validation_report.get("validated_competition_scopes") or {}
    model_history = external_team_history
    elo_cache = {}

    upgraded = 0
    warnings = 0
    paper_value = 0
    no_history = 0
    no_market = 0
    validated_updates = 0
    validated_scope_counts = {}
    ucl_shadowed = 0
    ucl_shadow_complete = 0
    ucl_shadow_partial = 0

    for row in predictions:
        if row.get("sport") != "football":
            row.setdefault("architecture", "competition statistical model + current market benchmark + calibration + value")
            row.setdefault("decision", "PAPER ONLY")
            continue

        try:
            history_cutoff = safe_history_cutoff(row.get("calculated_at"))
            if history_cutoff is None:
                warnings += 1
                row.setdefault("upgrade_warnings", []).append(
                    "missing forecast timestamp; statistical challenger not applied"
                )
                continue
            independent = independent_prediction(
                row_to_event(row),
                row.get("league") or "global",
                model_history,
                cutoff=history_cutoff,
            )
            if not independent:
                warnings += 1
                row.setdefault("upgrade_warnings", []).append("independent model returned no prediction")
                continue

            if independent.get("sample_home", 0) < 2 or independent.get("sample_away", 0) < 2:
                no_history += 1

            dixon_probs = normalize_probs({
                "p1": independent["p1"],
                "draw": independent["draw"],
                "p2": independent["p2"],
            })
            elo_probs = _competition_elo_probabilities(model_history, row, elo_cache)
            baseline_source = (
                row.get("published_model_probabilities")
                or row.get("calibrated_probabilities")
                or row.get("probabilities")
            )
            if not isinstance(baseline_source, dict):
                raise ValueError("published football probability vector is missing")
            published_probs = normalize_probs(baseline_source)

            market = valid_market(row)
            competition = _canonical_competition(row.get("league") or "global")
            scope = validated_scopes.get(competition)
            selected_probs = None
            if scope and elo_probs:
                selected_probs = probabilities_for_scope(
                    scope,
                    published_probs,
                    dixon_probs,
                    elo_probs,
                )

            # Keep dual-competition UCL diagnostics visible, but never give them
            # ticket eligibility or bypass the competition-specific holdout.
            if competition == "Champions League":
                shadow_calibrated = softmax_temperature(
                    [dixon_probs["p1"], dixon_probs["draw"], dixon_probs["p2"]],
                    calibration_temperature(calibration, "football"),
                )
                _record_ucl_shadow_fields(
                    row,
                    independent,
                    shadow_calibrated,
                    market,
                    calibration,
                )
                ucl_shadowed += 1
                if row["independent_shadow_history_complete"]:
                    ucl_shadow_complete += 1
                else:
                    ucl_shadow_partial += 1

            row["independent_probabilities"] = {
                key: round(float(dixon_probs[key]), 6) for key in ("p1", "draw", "p2")
            }
            if elo_probs:
                row["football_elo_probabilities"] = {
                    key: round(float(elo_probs[key]), 6) for key in ("p1", "draw", "p2")
                }
            row["expected_goals"] = {
                "p1": independent["xg_home"],
                "p2": independent["xg_away"],
                "total": round(independent["xg_home"] + independent["xg_away"], 4),
            }
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

            model_applied = False
            if scope and selected_probs:
                model_applied = apply_validated_competition_probabilities(
                    row,
                    published_probs,
                    selected_probs,
                    scope,
                )
            if model_applied:
                validated_updates += 1
                validated_scope_counts[competition] = validated_scope_counts.get(competition, 0) + 1
                if competition == "Champions League":
                    row["independent_shadow_promotion_status"] = "RESEARCH_SCOPE_VALIDATED"
                    row["independent_shadow_use_for_tickets"] = False
            else:
                # Preserve the published prediction outside every validated scope.
                row["probabilities"] = {
                    key: round(float(published_probs[key]), 6) for key in ("p1", "draw", "p2")
                }
                row["calibrated_probabilities"] = dict(row["probabilities"])
                row["pick"] = max(("p1", "draw", "p2"), key=lambda key: row["probabilities"][key])
                row["confidence"] = round(row["probabilities"][row["pick"]], 4)
                row["calibrated_confidence"] = row["confidence"]
                row["football_model_validation"] = {
                    "status": "RESEARCH_ONLY",
                    "selected_model": None,
                    "reason": "no competition-specific challenger passed development-selected untouched holdout",
                    "validation_status": validation_report.get("status"),
                    "live_money_approved": False,
                    "ticket_release_approved": False,
                }
                row["live_eligible"] = False
                row["testing_mode"] = "paper"

            final_probs = row["probabilities"]
            final_vector = [final_probs["p1"], final_probs["draw"], final_probs["p2"]]
            row["calibration_version"] = calibration.get("version")
            row["model_version"] = MODEL_VERSION if model_applied else row.get("model_version", "published")
            row["architecture"] = "competition-specific validated prediction model + SportyBet value benchmark + independent research challengers"
            if not model_applied:
                row["model"] = row.get("model") or "published model retained; statistical challengers are research-only"

            # Current bookmaker prices are used only to calculate a paper value
            # signal. They cannot change any eligibility or ticket-release gate.
            if market:
                row["market_probabilities"] = {
                    "p1": round(market["p1"], 4),
                    "draw": round(market["draw"], 4),
                    "p2": round(market["p2"], 4),
                }
                row["market_odds"] = market["odds"]
                row["market_source"] = market.get("source") or row.get("market_source") or "stored contemporaneous market"
                pick_key = row["pick"]
                pick_idx = ("p1", "draw", "p2").index(pick_key)
                edge, ev = edge_and_ev(final_vector[pick_idx], market["odds"][pick_idx])
                row["edge"] = edge
                row["value"] = {
                    "expected_value": ev,
                    "odds": market["odds"][pick_idx],
                    "market_implied": market[pick_key],
                }
                dec = decision(final_vector[pick_idx], market["odds"][pick_idx], sample_ok=False)
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

            row["live_eligible"] = False
            row["testing_mode"] = "paper"
            upgraded += 1
        except Exception as exc:
            warnings += 1
            row.setdefault("upgrade_warnings", []).append(str(exc)[:180])

    pred_path.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
    audit = build_validation_audit(validation_report, upgraded, validated_updates, validated_scope_counts, warnings)
    audit_path = DATA / "football_prequential_validation.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "audit_path": str(audit_path.relative_to(ROOT)),
        "audit_generated_at_utc": audit["generated_at_utc"],
        "model_version": MODEL_VERSION,
        "football_upgraded": upgraded,
        "validated_model_prediction_updates": validated_updates,
        "validated_scope_counts": validated_scope_counts,
        "validated_competition_scopes": validated_scopes,
        "validation_report_status": validation_report.get("status"),
        "validation_total_eligible": validation_report.get("total_eligible", 0),
        "validation_development_n": validation_report.get("development_n", 0),
        "validation_holdout_n": validation_report.get("holdout_n", 0),
        "global_blend_promotion_allowed": validation_report.get("promotion_allowed", False),
        "positive_edge_paper_candidates": paper_value,
        "warnings": warnings,
        "football_without_sufficient_team_history": no_history,
        "football_without_contemporaneous_market": no_market,
        "ucl_shadow_predictions": ucl_shadowed,
        "ucl_shadow_complete_history": ucl_shadow_complete,
        "ucl_shadow_partial_history": ucl_shadow_partial,
        "ucl_shadow_policy": "research shadow remains non-ticket eligible; approved scope model update does not alter release gates",
        "external_team_history_rows": len(external_team_history),
    }, indent=2))


if __name__ == "__main__":
    main()
