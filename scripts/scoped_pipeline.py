"""Run Match Signal with a deliberately narrow football scope.

Football production scope is limited to EPL, Bundesliga and UEFA Champions League.
The wrapper patches the legacy league constants in the working tree before running
 the existing pipeline, so every downstream history/model step uses the same scope.
PAPER ONLY.
"""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "Champions League": "uefa.champions",
}


def replace_block(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Football scope block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_scope() -> None:
    predict = ROOT / "scripts" / "predict_today.py"
    replace_block(
        predict,
        'FOOTBALL_LEAGUES = {\n    "EPL": "eng.1",\n    "La Liga": "esp.1",\n    "Bundesliga": "ger.1",\n    "Serie A": "ita.1",\n    "Ligue 1": "fra.1",\n    "Champions League": "uefa.champions",\n    "MLS": "usa.1",\n    "Primeira Liga": "por.1",\n}',
        'FOOTBALL_LEAGUES = {\n    "EPL": "eng.1",\n    "Bundesliga": "ger.1",\n    "Champions League": "uefa.champions",\n}',
    )

    history = ROOT / "scripts" / "build_football_team_history.py"
    replace_block(
        history,
        'FOOTBALL_LEAGUES = {\n    "EPL": "eng.1",\n    "La Liga": "esp.1",\n    "Bundesliga": "ger.1",\n    "Serie A": "ita.1",\n    "Ligue 1": "fra.1",\n    "Champions League": "uefa.champions",\n    "MLS": "usa.1",\n    "Primeira Liga": "por.1",\n}',
        'FOOTBALL_LEAGUES = {\n    "EPL": "eng.1",\n    "Bundesliga": "ger.1",\n    "Champions League": "uefa.champions",\n}',
    )

    behavior = ROOT / "scripts" / "build_behavior_profiles.py"
    replace_block(
        behavior,
        'FOOTBALL_SLUGS = {\n    "EPL": "eng.1", "La Liga": "esp.1", "Bundesliga": "ger.1", "Serie A": "ita.1",\n    "Ligue 1": "fra.1", "Champions League": "uefa.champions", "MLS": "usa.1", "Primeira Liga": "por.1",\n}',
        'FOOTBALL_SLUGS = {\n    "EPL": "eng.1", "Bundesliga": "ger.1", "Champions League": "uefa.champions",\n}',
    )

    print({"football_scope": list(ALLOWED), "scope_mode": "NARROW_PRODUCTION_SCOPE"})


if __name__ == "__main__":
    apply_scope()
    runpy.run_path(str(ROOT / "scripts" / "run_pipeline.py"), run_name="__main__")
