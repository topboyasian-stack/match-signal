"""Chronological football model experiment inspired by public statistical methods.

Compares the published forecast with a leakage-safe Dixon-Coles model, a
competition-specific Elo model, and a development-fitted probability blend.
This is an offline experiment only: it never rewrites predictions or gates.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from independent_football_model import (
    _canonical_competition,
    _team_key,
    independent_prediction,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_KEYS = ("published", "dixon_coles", "elo", "dixon_elo_blend", "fitted_blend")
SCOPE_MIN_DEVELOPMENT = 30
SCOPE_MIN_HOLDOUT = 20
SCOPE_MIN_BRIER_LIFT = 0.005
SCOPE_MAX_ACCURACY_REGRESSION = 0.01
MIN_DEVELOPMENT_ROWS = 30
HOLDOUT_FRACTION = 0.30
BLEND_STEP = 0.10
ELO_K = 22.0
ELO_HOME_ADVANTAGE = 55.0


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def actual_from_row(row):
    actual = row.get("actual")
    if actual in {"p1", "draw", "p2"}:
        return actual
    score = row.get("final_score")
    try:
        home, away = float(score[0]), float(score[1])
    except (TypeError, ValueError, IndexError):
        return None
    return "p1" if home > away else "p2" if away > home else "draw"


def event_from_row(row):
    return {
        "id": str(row.get("event_id") or ""),
        "date": row.get("start_time"),
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"displayName": row.get("player_1") or "Home"}},
                {"homeAway": "away", "team": {"displayName": row.get("player_2") or "Away"}},
            ]
        }],
    }


def normalize_probs(probs):
    values = [max(1e-9, float(probs.get(key, 0.0))) for key in ("p1", "draw", "p2")]
    total = sum(values)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Probability vector must have a positive finite sum")
    return {"p1": values[0] / total, "draw": values[1] / total, "p2": values[2] / total}


def blend_probs(probability_sets, weights):
    keys = ("p1", "draw", "p2")
    combined = {
        key: sum(float(weight) * float(probabilities[key]) for weight, probabilities in zip(weights, probability_sets))
        for key in keys
    }
    return normalize_probs(combined)


def one_hot(actual):
    return {key: 1.0 if key == actual else 0.0 for key in ("p1", "draw", "p2")}


def brier(probs, actual):
    target = one_hot(actual)
    return sum((float(probs[key]) - target[key]) ** 2 for key in target)


def log_loss(probs, actual):
    return -math.log(max(1e-12, min(1.0, float(probs[actual]))))


def ranked_probability_score(probs, actual):
    target = one_hot(actual)
    predicted_cumulative = (probs["p1"], probs["p1"] + probs["draw"])
    target_cumulative = (target["p1"], target["p1"] + target["draw"])
    return sum((p - y) ** 2 for p, y in zip(predicted_cumulative, target_cumulative))


def pick_from_probs(probs):
    return max(("p1", "draw", "p2"), key=lambda key: float(probs[key]))


def _empty_counts():
    return {"n": 0, "draws": 0}


class CompetitionElo:
    """Sequential Elo state; callers must advance it strictly before kickoff."""

    def __init__(self, history):
        seen = set()
        rows = []
        for row in history or []:
            if not isinstance(row, dict) or row.get("sport") != "football":
                continue
            if not row.get("settled") or not row.get("final_score"):
                continue
            kickoff = parse_dt(row.get("start_time"))
            if kickoff is None:
                continue
            home = _team_key(row.get("player_1"))
            away = _team_key(row.get("player_2"))
            if not home or not away:
                continue
            try:
                hg, ag = float(row["final_score"][0]), float(row["final_score"][1])
            except (TypeError, ValueError, IndexError):
                continue
            competition = _canonical_competition(row.get("league") or "global")
            event_id = str(row.get("event_id") or "")
            identity = (competition, event_id) if event_id else (
                competition, home, away, kickoff.isoformat()
            )
            if identity in seen:
                continue
            seen.add(identity)
            rows.append((kickoff, competition, home, away, hg, ag))
        self.rows = sorted(rows, key=lambda item: item[0])
        self.ratings = defaultdict(lambda: 1500.0)
        self.competition_counts = defaultdict(_empty_counts)
        self.global_counts = _empty_counts()
        self.last_time = {}
        self.index = 0
        self._prediction_cutoff = datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _expected(home_rating, away_rating):
        difference = home_rating + ELO_HOME_ADVANTAGE - away_rating
        return 1.0 / (1.0 + 10.0 ** (-difference / 400.0))

    def _decay_team_to(self, key, cutoff):
        previous = self.last_time.get(key)
        if previous is not None and cutoff > previous:
            elapsed_days = (cutoff - previous).total_seconds() / 86400.0
            factor = math.exp(-math.log(2.0) * elapsed_days / 540.0)
            self.ratings[key] = 1500.0 + (self.ratings[key] - 1500.0) * factor
        self.last_time[key] = cutoff

    def _apply(self, item):
        kickoff, competition, home, away, hg, ag = item
        home_key, away_key = (competition, home), (competition, away)
        self._decay_team_to(home_key, kickoff)
        self._decay_team_to(away_key, kickoff)
        home_rating, away_rating = self.ratings[home_key], self.ratings[away_key]
        expected = self._expected(home_rating, away_rating)
        actual = 1.0 if hg > ag else 0.0 if hg < ag else 0.5
        margin_factor = 1.0 + 0.15 * min(3.0, max(0.0, abs(hg - ag) - 1.0))
        change = ELO_K * margin_factor * (actual - expected)
        self.ratings[home_key] = home_rating + change
        self.ratings[away_key] = away_rating - change
        self.last_time[home_key] = kickoff
        self.last_time[away_key] = kickoff
        counts = self.competition_counts[competition]
        counts["n"] += 1
        counts["draws"] += int(hg == ag)
        self.global_counts["n"] += 1
        self.global_counts["draws"] += int(hg == ag)

    def advance_before(self, cutoff):
        """Apply only completed fixtures with kickoff strictly before cutoff."""
        cutoff_dt = parse_dt(cutoff)
        if cutoff_dt is None:
            raise ValueError("A valid forecast cutoff is required")
        if cutoff_dt < self._prediction_cutoff:
            raise ValueError("Elo state cannot move backwards in time")
        self._prediction_cutoff = cutoff_dt
        while self.index < len(self.rows) and self.rows[self.index][0] < cutoff_dt:
            self._apply(self.rows[self.index])
            self.index += 1

    def predict(self, league, home_name, away_name):
        competition = _canonical_competition(league or "global")
        home = _team_key(home_name)
        away = _team_key(away_name)
        if not home or not away:
            return {"p1": 1/3, "draw": 1/3, "p2": 1/3}
        cutoff_dt = parse_dt(self._prediction_cutoff)
        self._decay_team_to((competition, home), cutoff_dt)
        self._decay_team_to((competition, away), cutoff_dt)
        home_rating = self.ratings[(competition, home)]
        away_rating = self.ratings[(competition, away)]
        difference = home_rating + ELO_HOME_ADVANTAGE - away_rating
        expected_home_score = self._expected(home_rating, away_rating)
        counts = self.competition_counts[competition]
        if counts["n"] >= 15:
            draw_rate = counts["draws"] / counts["n"]
        elif self.global_counts["n"] >= 30:
            draw_rate = self.global_counts["draws"] / self.global_counts["n"]
        else:
            draw_rate = 0.26
        draw_probability = max(0.10, min(0.34, draw_rate * math.exp(-abs(difference) / 700.0)))
        home_probability = expected_home_score - draw_probability / 2.0
        away_probability = 1.0 - expected_home_score - draw_probability / 2.0
        return normalize_probs({
            "p1": max(0.005, home_probability),
            "draw": draw_probability,
            "p2": max(0.005, away_probability),
        })


def _published_probabilities(row):
    raw = row.get("calibrated_probabilities") or row.get("probabilities")
    if not isinstance(raw, dict) or not all(key in raw for key in ("p1", "draw", "p2")):
        return None
    try:
        return normalize_probs(raw)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def build_evaluation_rows(prediction_history, team_history):
    """Create pre-kickoff rows; all model features are based on prior results."""
    elo = CompetitionElo(team_history)
    source_history = [
        row for row in (team_history or [])
        if isinstance(row, dict) and row.get("sport") == "football"
        and row.get("settled") and row.get("final_score")
    ]
    predictions = sorted(
        [
            row for row in (prediction_history or [])
            if isinstance(row, dict) and row.get("sport") == "football"
            and row.get("settled") and row.get("final_score")
        ],
        key=lambda row: parse_dt(row.get("start_time")) or datetime.max.replace(tzinfo=timezone.utc),
    )

    rows = []
    exclusions = defaultdict(int)
    seen = set()
    for row in predictions:
        kickoff = parse_dt(row.get("start_time"))
        forecast_at = parse_dt(row.get("calculated_at") or row.get("created_at") or row.get("prediction_timestamp"))
        if kickoff is None:
            exclusions["missing_kickoff"] += 1
            continue
        if forecast_at is None:
            exclusions["missing_forecast_timestamp"] += 1
            continue
        if forecast_at > kickoff:
            exclusions["forecast_created_after_kickoff"] += 1
            continue
        actual = actual_from_row(row)
        published = _published_probabilities(row)
        if actual is None or published is None:
            exclusions["missing_outcome_or_probabilities"] += 1
            continue
        competition = _canonical_competition(row.get("league") or "global")
        event_id = str(row.get("event_id") or "")
        identity = (competition, event_id) if event_id else (
            competition, _team_key(row.get("player_1")), _team_key(row.get("player_2")), kickoff.isoformat()
        )
        if identity in seen:
            exclusions["duplicate_fixture"] += 1
            continue
        seen.add(identity)

        elo.advance_before(kickoff)
        event = event_from_row(row)
        dixon = independent_prediction(
            event,
            row.get("league") or "global",
            source_history,
            cutoff=kickoff,
        )
        if not dixon:
            exclusions["dixon_coles_unavailable"] += 1
            continue
        try:
            dixon_probs = normalize_probs(dixon)
        except (TypeError, ValueError, ZeroDivisionError):
            exclusions["invalid_dixon_coles_probabilities"] += 1
            continue
        elo_probs = elo.predict(row.get("league"), row.get("player_1"), row.get("player_2"))
        rows.append({
            "league": str(row.get("league") or "Unknown"),
            "event_id": event_id,
            "start_time": kickoff.isoformat(),
            "forecast_at": forecast_at.isoformat(),
            "actual": actual,
            "published": published,
            "dixon_coles": dixon_probs,
            "elo": elo_probs,
            "dixon_elo_blend": blend_probs([dixon_probs, elo_probs], [0.5, 0.5]),
        })
    return rows, dict(exclusions)


def _score_rows(rows, model_name):
    if not rows:
        return {"n": 0, "accuracy": None, "brier": None, "log_loss": None, "rps": None}
    briers, losses, rps, hits = [], [], [], []
    for row in rows:
        probs = row[model_name]
        actual = row["actual"]
        briers.append(brier(probs, actual))
        losses.append(log_loss(probs, actual))
        rps.append(ranked_probability_score(probs, actual))
        hits.append(pick_from_probs(probs) == actual)
    return {
        "n": len(rows),
        "accuracy": round(sum(hits) / len(hits), 4),
        "brier": round(sum(briers) / len(briers), 5),
        "log_loss": round(sum(losses) / len(losses), 5),
        "rps": round(sum(rps) / len(rps), 5),
    }


def fit_development_blend(rows):
    """Fit non-negative model weights on development rows only."""
    if len(rows) < MIN_DEVELOPMENT_ROWS:
        return {"weights": [1.0, 0.0, 0.0], "development_n": len(rows), "reason": "insufficient_development_sample"}
    candidates = []
    steps = round(1.0 / BLEND_STEP)
    for published_step in range(steps + 1):
        for dixon_step in range(steps - published_step + 1):
            elo_step = steps - published_step - dixon_step
            weights = [published_step / steps, dixon_step / steps, elo_step / steps]
            scores = []
            for row in rows:
                combined = blend_probs(
                    [row["published"], row["dixon_coles"], row["elo"]],
                    weights,
                )
                scores.append(brier(combined, row["actual"]))
            candidates.append({
                "weights": weights,
                "mean_brier": sum(scores) / len(scores),
            })
    # Stable tie-break: prefer the simpler published-model-heavy blend.
    best = min(
        candidates,
        key=lambda item: (
            item["mean_brier"],
            -item["weights"][0],
            -item["weights"][1],
        ),
    )
    return {
        "weights": best["weights"],
        "development_n": len(rows),
        "development_brier": round(best["mean_brier"], 5),
        "candidate_count": len(candidates),
        "objective": "minimum multiclass Brier on the chronological development window",
    }


def apply_blend(row, weights):
    return blend_probs(
        [row["published"], row["dixon_coles"], row["elo"]],
        weights,
    )


def _model_name_for_development(rows):
    """Choose a challenger using development observations only."""
    names = ("published", "dixon_coles", "elo", "dixon_elo_blend", "fitted_blend")
    metrics = {name: _score_rows(rows, name) for name in names}
    # Published is the deterministic tie-breaker; a challenger must earn the
    # switch by reducing the development Brier score.
    selected = min(
        names,
        key=lambda name: (
            metrics[name]["brier"] if metrics[name]["brier"] is not None else float("inf"),
            names.index(name),
        ),
    )
    return selected, metrics


def build_report(prediction_history, team_history):
    rows, exclusions = build_evaluation_rows(prediction_history, team_history)
    if len(rows) < 2:
        return {
            "mode": "PAPER_RESEARCH_ONLY",
            "status": "INSUFFICIENT_DATA",
            "evaluated": len(rows),
            "exclusions": exclusions,
            "promotion_allowed": False,
            "validated_competition_scopes": {},
        }

    split = int(len(rows) * (1.0 - HOLDOUT_FRACTION))
    split = max(1, min(len(rows) - 1, split))
    development, holdout = rows[:split], rows[split:]
    fit = fit_development_blend(development)
    weights = fit["weights"]

    # The global blend is fitted only on the development window.
    development_enriched = []
    for row in development:
        enriched = dict(row)
        enriched["fitted_blend"] = apply_blend(row, weights)
        development_enriched.append(enriched)

    holdout_enriched = []
    for row in holdout:
        enriched = dict(row)
        enriched["fitted_blend"] = apply_blend(row, weights)
        holdout_enriched.append(enriched)

    metrics = {
        name: _score_rows(holdout_enriched, name)
        for name in ("published", "dixon_coles", "elo", "dixon_elo_blend", "fitted_blend")
    }

    dev_by_competition = defaultdict(list)
    holdout_by_competition = defaultdict(list)
    for row in development_enriched:
        dev_by_competition[_canonical_competition(row["league"])].append(row)
    for row in holdout_enriched:
        holdout_by_competition[_canonical_competition(row["league"])].append(row)

    development_by_league = {}
    holdout_by_league = {}
    validated_scopes = {}
    for competition in sorted(set(dev_by_competition) | set(holdout_by_competition)):
        dev_rows = dev_by_competition.get(competition, [])
        test_rows = holdout_by_competition.get(competition, [])
        if dev_rows:
            selected_model, dev_metrics = _model_name_for_development(dev_rows)
            development_by_league[competition] = {
                "development_n": len(dev_rows),
                "selected_model": selected_model,
                "candidate_metrics": dev_metrics,
            }
        else:
            selected_model = "published"
            dev_metrics = {}
            development_by_league[competition] = {
                "development_n": 0,
                "selected_model": "published",
                "candidate_metrics": {},
            }

        if not test_rows:
            continue
        test_metrics = {
            name: _score_rows(test_rows, name)
            for name in ("published", "dixon_coles", "elo", "dixon_elo_blend", "fitted_blend")
        }
        selected_metrics = test_metrics[selected_model]
        published_metrics = test_metrics["published"]
        enough_development = len(dev_rows) >= SCOPE_MIN_DEVELOPMENT
        enough_holdout = len(test_rows) >= SCOPE_MIN_HOLDOUT
        brier_improved = (
            selected_metrics["brier"] is not None
            and published_metrics["brier"] is not None
            and selected_metrics["brier"] <= published_metrics["brier"] - SCOPE_MIN_BRIER_LIFT
        )
        log_loss_not_worse = (
            selected_metrics["log_loss"] is not None
            and published_metrics["log_loss"] is not None
            and selected_metrics["log_loss"] <= published_metrics["log_loss"]
        )
        accuracy_preserved = (
            selected_metrics["accuracy"] is not None
            and published_metrics["accuracy"] is not None
            and selected_metrics["accuracy"] >= published_metrics["accuracy"] - SCOPE_MAX_ACCURACY_REGRESSION
        )
        passed = bool(
            enough_development and enough_holdout and selected_model != "published"
            and brier_improved and log_loss_not_worse and accuracy_preserved
        )
        holdout_by_league[competition] = {
            "holdout_n": len(test_rows),
            "selected_development_model": selected_model,
            "selected_model_metrics": selected_metrics,
            "published_metrics": published_metrics,
            "candidate_metrics": test_metrics,
            "gate": {
                "minimum_development": SCOPE_MIN_DEVELOPMENT,
                "minimum_holdout": SCOPE_MIN_HOLDOUT,
                "minimum_brier_improvement": SCOPE_MIN_BRIER_LIFT,
                "maximum_accuracy_regression": SCOPE_MAX_ACCURACY_REGRESSION,
                "development_sample_passed": enough_development,
                "holdout_sample_passed": enough_holdout,
                "brier_passed": brier_improved,
                "log_loss_passed": log_loss_not_worse,
                "accuracy_passed": accuracy_preserved,
            },
            "status": "RESEARCH_SCOPE_VALIDATED" if passed else "RESEARCH_ONLY",
        }
        if passed:
            validated_scopes[competition] = {
                "selected_model": selected_model,
                "development_n": len(dev_rows),
                "holdout_n": len(test_rows),
                "development_metrics": dev_metrics.get(selected_model),
                "holdout_metrics": selected_metrics,
                "published_holdout_metrics": published_metrics,
                "evidence": "development-selected model passed untouched chronological holdout",
            }

    published = metrics["published"]
    fitted = metrics["fitted_blend"]
    global_holdout_minimum = 60
    promotion_allowed = bool(
        len(holdout_enriched) >= global_holdout_minimum
        and published["brier"] is not None
        and fitted["brier"] is not None
        and fitted["brier"] <= published["brier"] - 0.005
        and fitted["log_loss"] <= published["log_loss"]
        and fitted["accuracy"] >= published["accuracy"] - 0.01
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_RESEARCH_ONLY",
        "status": "EVALUATED",
        "method": "published forecast + time-decayed competition-specific Dixon-Coles + chronological competition Elo",
        "market_independent": True,
        "forecast_timestamp_required": True,
        "strict_pre_kickoff_cutoff": True,
        "total_eligible": len(rows),
        "development_n": len(development_enriched),
        "holdout_n": len(holdout_enriched),
        "holdout_fraction": HOLDOUT_FRACTION,
        "exclusions": exclusions,
        "development_fit": fit,
        "development_by_league": development_by_league,
        "holdout_metrics": metrics,
        "holdout_by_league": holdout_by_league,
        "validated_competition_scopes": validated_scopes,
        "holdout_latest_50": [
            {
                "league": row["league"],
                "event_id": row["event_id"],
                "start_time": row["start_time"],
                "actual": row["actual"],
                "published_pick": pick_from_probs(row["published"]),
                "fitted_blend_pick": pick_from_probs(row["fitted_blend"]),
                "published_probabilities": row["published"],
                "fitted_blend_probabilities": row["fitted_blend"],
            }
            for row in holdout_enriched[-50:]
        ],
        "promotion_allowed": promotion_allowed,
        "promotion_policy": (
            f"Global fitted blend requires untouched chronological holdout n>={global_holdout_minimum}; "
            "Brier improvement >=0.005, log loss not worse, and accuracy within one percentage point. "
            f"Competition scopes require development n>={SCOPE_MIN_DEVELOPMENT}, holdout n>={SCOPE_MIN_HOLDOUT}, "
            "development-only model selection, holdout Brier improvement >=0.005, non-worse log loss, "
            "and accuracy within one percentage point. All approvals are research-model scope approvals, "
            "not live-money or Builder approval."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default=str(DATA / "prediction_history.json"))
    parser.add_argument("--team-history", default=str(DATA / "football_team_history.json"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    prediction_history = json.loads(Path(args.history).read_text(encoding="utf-8"))
    team_history = json.loads(Path(args.team_history).read_text(encoding="utf-8"))
    report = build_report(prediction_history, team_history)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report.get("status"),
        "eligible": report.get("total_eligible", report.get("evaluated")),
        "development_n": report.get("development_n"),
        "holdout_n": report.get("holdout_n"),
        "metrics": report.get("holdout_metrics"),
        "selected_weights": (report.get("development_fit") or {}).get("weights"),
        "promotion_allowed": report.get("promotion_allowed"),
        "exclusions": report.get("exclusions"),
    }, indent=2))


if __name__ == "__main__":
    main()
