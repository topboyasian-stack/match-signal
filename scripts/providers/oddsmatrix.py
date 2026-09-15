"""Optional OddsMatrix adapter boundary.

No endpoint, token or bookmaker credentials are hard-coded. Production access
must be injected by private runtime configuration. If unavailable, Match Signal
must return NO_CURRENT_ODDS rather than invent prices.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


def configured() -> bool:
    return bool(os.getenv("ODDSMATRIX_API_URL") and os.getenv("ODDSMATRIX_API_KEY"))


def fetch(path: str = "", params: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    if not configured():
        return None
    base = os.environ["ODDSMATRIX_API_URL"].rstrip("/")
    url = f"{base}/{path.lstrip('/')}" if path else base
    response = requests.get(url, params=params, headers={"Authorization": f"Bearer {os.environ['ODDSMATRIX_API_KEY']}"}, timeout=20)
    response.raise_for_status()
    return response.json()
