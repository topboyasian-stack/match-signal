#!/usr/bin/env python3
"""Restore/persist cross-sport evidence using the authenticated private Cloudflare KV API.

Raw probabilities, quotes, market identifiers and the rolling settlement ledger are
never committed to the public repository or served as static files. Missing secrets
or unavailable private storage are warnings rather than Builder-fatal errors, but
they mean durable multi-run evidence collection is not available for that run.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "data" / "calibration_private"
HISTORY_PATH = PRIVATE_DIR / "cross_sport_market_reassessment_history.json"
REVISION_PATH = PRIVATE_DIR / ".cross_sport_market_reassessment_revision"
DEFAULT_URL = "https://match-signal.pages.dev/api/analyst/market-evidence"
MAX_BYTES = 12 * 1024 * 1024


def _warning(message: str) -> None:
    print(f"::warning::{message}")


def _default_document() -> dict[str, Any]:
    return {
        "record_type": "cross_sport_market_reassessment",
        "generated_at": None,
        "mode": "PAPER_ONLY",
        "record_count": 0,
        "records": [],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _request(method: str, body: dict[str, Any] | None = None, revision: str | None = None) -> dict[str, Any]:
    token = os.environ.get("MATCH_SIGNAL_ANALYST_TOKEN", "").strip()
    url = os.environ.get("MATCH_SIGNAL_PRIVATE_EVIDENCE_URL", DEFAULT_URL).strip()
    if not token:
        raise RuntimeError("GitHub Actions secret MATCH_SIGNAL_ANALYST_TOKEN is not configured")
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "Cache-Control": "no-store",
    }
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise RuntimeError("private evidence ledger exceeds the 12 MiB request cap")
        headers["Content-Type"] = "application/json"
    if revision is not None:
        headers["If-Match"] = revision
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("private evidence response exceeds the 12 MiB response cap")
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("private evidence API returned a non-object response")
            return parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        if exc.code == 401:
            raise RuntimeError("private evidence API rejected the token (401)") from exc
        if exc.code == 503:
            raise RuntimeError("private evidence API or its KV binding is not configured (503)") from exc
        if exc.code == 409:
            raise RuntimeError("private evidence revision conflict (409); next scheduled run will reload the current ledger") from exc
        raise RuntimeError(f"private evidence API returned HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"private evidence API request failed: {str(exc)[:240]}") from exc


def restore() -> int:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = _request("GET")
        document = response.get("document")
        revision = str(response.get("revision") or "none")
        if document is None:
            document = _default_document()
        if (
            not isinstance(document, dict)
            or document.get("record_type") != "cross_sport_market_reassessment"
            or not isinstance(document.get("records"), list)
        ):
            raise RuntimeError("private evidence API returned an invalid ledger shape")
        _write_json(HISTORY_PATH, document)
        REVISION_PATH.write_text(revision + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PRIVATE_EVIDENCE_RESTORED",
            "revision": revision,
            "record_count": len(document.get("records", [])),
        }))
        return 0
    except Exception as exc:
        # Never fall back to a public ledger. An unavailable store must not make
        # the regular paper Builder fail, but its evidence won't persist this run.
        if not HISTORY_PATH.exists():
            _write_json(HISTORY_PATH, _default_document())
        REVISION_PATH.write_text("unavailable\n", encoding="utf-8")
        _warning(f"Private cross-sport evidence could not be restored: {exc}. No raw evidence will be published publicly; durable accumulation is unavailable for this run.")
        print("PRIVATE_EVIDENCE_RESTORE_UNAVAILABLE")
        return 0


def publish() -> int:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        revision = REVISION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        revision = "unavailable"
    if not revision or revision == "unavailable":
        _warning("Private evidence was not restored, so this run cannot safely persist or overwrite the private ledger.")
        print("PRIVATE_EVIDENCE_NOT_PERSISTED")
        return 0
    try:
        document = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("records"), list):
            raise RuntimeError("local private evidence ledger has an invalid shape")
        document["record_type"] = "cross_sport_market_reassessment"
        document["mode"] = "PAPER_ONLY"
        document["record_count"] = len(document["records"])
        response = _request("PUT", document, revision=revision)
        if response.get("status") != "SAVED" or not response.get("revision"):
            raise RuntimeError("private evidence API did not confirm persistence")
        document["updated_at"] = response["revision"]
        _write_json(HISTORY_PATH, document)
        REVISION_PATH.write_text(str(response["revision"]) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PRIVATE_EVIDENCE_SAVED",
            "revision": response["revision"],
            "record_count": response.get("record_count", len(document["records"])),
        }))
        return 0
    except Exception as exc:
        _warning(f"Private cross-sport evidence was not persisted: {exc}. The raw ledger remains runner-local and will not be added to public Git.")
        print("PRIVATE_EVIDENCE_SAVE_UNAVAILABLE")
        return 0


def main(argv: list[str]) -> int:
    if argv == ["restore"]:
        return restore()
    if argv == ["publish"]:
        return publish()
    print("Usage: sync_cross_sport_private_evidence.py restore|publish")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
