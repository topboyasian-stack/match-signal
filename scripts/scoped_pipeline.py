"""Authoritative Match Signal pipeline entrypoint.

This wrapper used to narrow production football to three competitions, which
caused the scheduled production refresh to silently remove other configured
leagues. Production now uses the canonical league scope from predict_today.py.
Special experimental competitions (Eredivisie, Saudi Pro League, NBA) keep their
own dedicated expansion workflows and are reconciled afterward.
PAPER ONLY.
"""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    print("Production scope: canonical FOOTBALL_LEAGUES + ATP/WTA from predict_today.py")
    runpy.run_path(str(ROOT / "scripts" / "run_pipeline.py"), run_name="__main__")
