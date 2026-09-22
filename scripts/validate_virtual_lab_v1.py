#!/usr/bin/env python3
"""Deterministic Virtual Lab v1 repository contract checks.

This validator is intentionally local/static: it catches cross-product contamination,
legacy renderer references, missing preservation artifacts and traceability regressions
before a deployment is promoted.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SUPPORTED = {"efootball_gt", "efootball_adriatic", "vfootball", "zoom"}

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    failures = []

    required = [
        ROOT / "virtual-lab/index.html",
        ROOT / "virtual-lab-app.js",
        ROOT / "virtual-lab-confirmed-watch.js",
        ROOT / "_redirects",
        ROOT / "VIRTUAL-LAB-REBUILD-ARCHITECTURE.md",
        DATA / "virtual_lab_history.json",
        DATA / "virtual_lab_pending.json",
        DATA / "virtual_lab_participant_profiles.json",
        DATA / "virtual_lab_model_eval.json",
        DATA / "virtual_lab_participants/efootball_confirmed_watch.json",
        DATA / "virtual_lab_participants/tennis_archive.json",
        DATA / "virtual_lab_participants/registry.json",
        DATA / "virtual_lab_archive/2026-09-22/participant-watch-original.json",
        DATA / "virtual_lab_archive/2026-09-22/settled-history-baseline.json",
    ]
    for path in required:
        if not path.exists() or path.stat().st_size == 0:
            failures.append(f"missing/empty: {path.relative_to(ROOT)}")

    history = load(DATA / "virtual_lab_history.json")
    if not isinstance(history, list):
        failures.append("virtual_lab_history.json is not a list")
    else:
        products = {str(r.get("product") or "") for r in history if isinstance(r, dict)}
        bad = sorted(products - SUPPORTED)
        if bad:
            failures.append("history contains unsupported products: " + ", ".join(bad))
        trace_missing = []
        for r in history:
            if not isinstance(r, dict) or r.get("win") is None:
                continue
            for field in ("record_id", "trace_id", "event_id", "schema_version", "pipeline_version", "settlement_source"):
                if not r.get(field):
                    trace_missing.append(field)
        if trace_missing:
            failures.append("settled history rows missing trace fields: " + ", ".join(sorted(set(trace_missing))))

    watch = load(DATA / "virtual_lab_participants/efootball_confirmed_watch.json")
    participants = watch.get("participants", [])
    products = {str(x.get("product") or "") for x in participants}
    if products != {"efootball_gt"}:
        failures.append(f"confirmed eFootball watch contamination: {sorted(products)}")
    if len(participants) != 9:
        failures.append(f"confirmed eFootball watch count changed: {len(participants)}")

    tennis = load(DATA / "virtual_lab_participants/tennis_archive.json").get("participants", [])
    tennis_names = set(tennis)
    watch_names = {str(x.get("participant") or "") for x in participants}
    leaked = sorted(tennis_names & watch_names)
    if leaked:
        failures.append("tennis identities leaked into eFootball watch: " + ", ".join(leaked))

    page = (ROOT / "virtual-lab/index.html").read_text(encoding="utf-8")
    for marker in ("virtual-lab-app.js", "virtual-lab-confirmed-watch.js", "VL-V1-20260922", "/virtual-lab/"):
        if marker not in page:
            failures.append("Virtual Lab page missing marker: " + marker)
    for legacy in ("virtual-lab-live-override.js", "confirmed-participant-watch.js?v=", "virtual-lab-live-v4.js"):
        if legacy in page:
            failures.append("Virtual Lab page still references legacy renderer: " + legacy)

    redirects = (ROOT / "_redirects").read_text(encoding="utf-8")
    if "/research.html /virtual-lab/ 301" not in redirects:
        failures.append("missing /research.html canonical redirect")
    if "/virtual-lab.html /virtual-lab/ 301" not in redirects:
        failures.append("missing /virtual-lab.html canonical redirect")

    app = (ROOT / "virtual-lab-app.js").read_text(encoding="utf-8")
    if "2-minute time window" in app:
        failures.append("browser renderer still contains retired 2-minute cutoff wording")
    if "const LIVE_API=location.origin+'/api/sportybet-virtual';" not in app:
        failures.append("live API is not same-origin in Virtual Lab v1")
    if "window.__MATCH_SIGNAL_VIRTUAL_LAB_APP__='VL-V1'" not in app:
        failures.append("Virtual Lab v1 renderer marker missing")

    collector = (ROOT / "scripts/virtual_lab_collector.py").read_text(encoding="utf-8")
    if "SUPPORTED_PRODUCTS={'efootball_gt','efootball_adriatic','vfootball','zoom'}" not in collector.replace(" ", ""):
        failures.append("collector supported-product contract missing/changed")
    if "row.setdefault(\"trace_id\"" not in collector:
        failures.append("collector does not assign trace_id")
    if '"sr:sport:1"' in (ROOT / "scripts/virtual_lab_sync.py").read_text(encoding="utf-8"):
        failures.append("sync script still targets core football sportId sr:sport:1")
    if "srl" in (ROOT / "scripts/virtual_lab_sync.py").read_text(encoding="utf-8").lower():
        failures.append("sync script still contains legacy SRL")

    if failures:
        for item in failures:
            print("FAIL:", item)
        raise SystemExit(1)

    print("Virtual Lab v1 contract: PASS")
    print("history rows:", len(history))
    print("confirmed eFootball participants:", len(participants))
    print("tennis archive participants:", len(tennis))
    print("supported products:", sorted(SUPPORTED))

if __name__ == "__main__":
    main()
