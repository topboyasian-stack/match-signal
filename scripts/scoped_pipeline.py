"""Authoritative Match Signal production pipeline entrypoint.

The canonical Football + ATP/WTA engine is wrapped transactionally so a
transient provider failure cannot erase another sport or an experimental
competition from the public feed.
PAPER ONLY.
"""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    print("Production scope: canonical FOOTBALL_LEAGUES + ATP/WTA from predict_today.py")
    print("Publication scope: transactional; preserve active experimental leagues")
    runpy.run_path(str(ROOT / "scripts" / "production_pipeline.py"), run_name="__main__")
