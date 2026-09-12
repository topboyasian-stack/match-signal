import json
import math
from pathlib import Path

from independent_football_model import independent_prediction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def nll(probs, actual):
    return -math.log(max(1e-9, probs[actual]))


def fit_temperature(samples):
    if len(samples) < 20:
        return 1.0, {"status": "insufficient_sample", "n": len(samples)}
    best_t, best_loss = 1.0, float("inf")
    for i in range(51):
        t = 0.5 + i * 0.03
        loss = 0.0
        for probs, actual in samples:
            logits = [math.log(max(1e-9, p)) / t for p in probs]
            m = max(logits)
            vals = [math.exp(x - m) for x in logits]
            s = sum(vals)
            calibrated = [v / s for v in vals]
            loss += nll(calibrated, actual)
        if loss < best_loss:
            best_t, best_loss = t, loss
    return round(best_t, 4), {"status": "fit", "n": len(samples), "nll": round(best_loss / len(samples), 6)}


def main():
    history = load(DATA / "prediction_history.json", [])
    samples = []
    for row in history:
        if row.get("sport") != "football" or not row.get("settled") or not row.get("final_score"):
            continue
        try:
            actual = 0 if row["final_score"][0] > row["final_score"][1] else 1 if row["final_score"][0] == row["final_score"][1] else 2
            event = {
                "id": row.get("event_id"),
                "competitions": [{"competitors": [
                    {"homeAway": "home", "team": {"displayName": row.get("player_1")}},
                    {"homeAway": "away", "team": {"displayName": row.get("player_2")}},
                ]}],
            }
            model = independent_prediction(event, row.get("league") or "global", history, cutoff=row.get("calculated_at") or row.get("start_time"))
            if model:
                samples.append(([model["p1"], model["draw"], model["p2"]], actual))
        except Exception:
            continue
    temperature, meta = fit_temperature(samples)
    output = {"version": "4.0", "football": {"temperature": temperature, **meta}, "generated_from": "walk-forward historical settled predictions"}
    (DATA / "calibration.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
