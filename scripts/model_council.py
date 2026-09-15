"""Model-council coordinator.

Only derived probabilities/signals should leave this layer. External vendor
benchmarks are optional and must never silently replace Match Signal's own
model. Production credentials and calibration artifacts stay server-side.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def weighted_consensus(models: list[dict]) -> float | None:
    usable = [m for m in models if m.get("probability") is not None and m.get("weight", 0) > 0]
    if not usable:
        return None
    total = sum(float(m["weight"]) for m in usable)
    return sum(float(m["probability"]) * float(m["weight"]) for m in usable) / total


def build(event_id: str, market: str, models: list[dict]) -> dict:
    p = weighted_consensus(models)
    disagreement = None
    probs = [float(m["probability"]) for m in models if m.get("probability") is not None]
    if len(probs) > 1:
        disagreement = max(probs) - min(probs)
    return {
        "event_id": str(event_id),
        "market": market,
        "models": models,
        "consensus_probability": round(p, 6) if p is not None else None,
        "model_disagreement": round(disagreement, 6) if disagreement is not None else None,
        "status": "PAPER_RESEARCH" if p is not None else "INSUFFICIENT_MODELS",
        "real_money_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_PRIVATE_PROVIDER_DATA",
        "external_providers": {
            "matchmetrix": "disabled_until_licensed_api_configured",
            "oddsmatrix": "disabled_until_licensed_api_configured",
        },
        "client_exposure": {
            "raw_vendor_payloads": False,
            "model_features": False,
            "provider_credentials": False,
            "calibration_artifacts": False,
            "engine_parameters": "minimal_only",
        },
        "real_money_approved": False,
    }
    (DATA / "model_council_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
