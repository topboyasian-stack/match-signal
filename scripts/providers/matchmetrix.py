"""Optional MatchMetrix probability benchmark adapter.

This is intentionally an adapter boundary, not a scraper. Only use an
official/licensed API or data feed made available to the account. Credentials
remain in private runtime secrets.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


def configured() -> bool:
    return bool(os.getenv("MATCHMETRIX_API_URL") and os.getenv("MATCHMETRIX_API_KEY"))


def fetch(path: str = "", params: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    if not configured():
        return None
    base = os.environ["MATCHMETRIX_API_URL"].rstrip("/")
    url = f"{base}/{path.lstrip('/')}" if path else base
    response = requests.get(url, params=params, headers={"Authorization": f"Bearer {os.environ['MATCHMETRIX_API_KEY']}"}, timeout=20)
    response.raise_for_status()
    return response.json()
