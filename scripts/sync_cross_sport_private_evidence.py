#!/usr/bin/env python3
"""Private cross-sport evidence sync using the existing Cloudflare deployment credentials.

Raw probabilities, quotes, edges, market identifiers and settlement observations
are stored only in the existing private Cloudflare KV namespace. They are never
committed to Git or published as static assets.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "data" / "calibration_private"
HISTORY_PATH = PRIVATE_DIR / "cross_sport_market_reassessment_history.json"
CURRENT_OUTPUT_PATH = PRIVATE_DIR / "cross_sport_market_reassessment_private.json"
REVISION_PATH = PRIVATE_DIR / ".cross_sport_market_reassessment_revision"
NAMESPACE_PATH = PRIVATE_DIR / ".cross_sport_evidence_namespace_id"
EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1"
CF_API = "https://api.cloudflare.com/client/v4"
PROJECT_NAME = "match-signal"
MAX_BYTES = 24 * 1024 * 1024  # Stay below Cloudflare KV's 25 MiB per-value ceiling.


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


def _credentials() -> tuple[str, str]:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account:
        raise RuntimeError("Existing Cloudflare deployment credentials CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are unavailable")
    return token, account


def _api_json(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token, _ = _credentials()
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "Cache-Control": "no-store",
    }
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(CF_API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("Cloudflare API response exceeded the 12 MiB cap")
            value = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise RuntimeError(f"Cloudflare API returned HTTP {exc.code}: {detail[:240]}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloudflare API request failed: {str(exc)[:240]}") from exc
    if not isinstance(value, dict) or value.get("success") is not True:
        errors = (value.get("errors") if isinstance(value, dict) else None) or []
        raise RuntimeError("Cloudflare API rejected the request: " + json.dumps(errors)[:240])
    return value


def _find_binding_id(node: Any) -> str | None:
    """Find the namespace id for the exact Pages binding when project metadata exposes it."""
    binding_name = "MATCH_SIGNAL_ANALYST_STORE"
    if isinstance(node, dict):
        if binding_name in node:
            value = node[binding_name]
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for key in ("namespace_id", "namespaceId", "id"):
                    if isinstance(value.get(key), str) and value[key].strip():
                        return value[key].strip()
        binding = node.get("binding") or node.get("name")
        if binding == binding_name:
            for key in ("namespace_id", "namespaceId", "id"):
                if isinstance(node.get(key), str) and node[key].strip():
                    return node[key].strip()
        for value in node.values():
            found = _find_binding_id(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_binding_id(value)
            if found:
                return found
    return None


def _normalize(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _resolve_namespace_id() -> str:
    explicit = os.environ.get("MATCH_SIGNAL_EVIDENCE_KV_NAMESPACE_ID", "").strip()
    if explicit:
        return explicit

    _, account = _credentials()
    account_path = "/accounts/" + urllib.parse.quote(account, safe="")
    project = _api_json("GET", account_path + "/pages/projects/" + urllib.parse.quote(PROJECT_NAME, safe=""))
    project_result = project.get("result") or {}
    found = _find_binding_id(project_result.get("deployment_configs") or project_result)
    if found:
        return found

    # Some Pages API responses omit binding ids. Resolve only a unique, exact
    # namespace-title match; never select an arbitrary KV namespace.
    listed = _api_json("GET", account_path + "/storage/kv/namespaces?per_page=1000")
    namespaces = listed.get("result") or []
    exact_names = {
        "matchsignalanalyststore",
        "matchsignalprivateanalyst",
        "matchsignalanalystprivate",
    }
    exact = [
        row for row in namespaces
        if isinstance(row, dict) and _normalize(row.get("title")) in exact_names
        and isinstance(row.get("id"), str) and row["id"]
    ]
    if len(exact) == 1:
        return exact[0]["id"]
    likely = [
        row for row in namespaces
        if isinstance(row, dict)
        and "matchsignal" in _normalize(row.get("title"))
        and "analyst" in _normalize(row.get("title"))
        and isinstance(row.get("id"), str) and row["id"]
    ]
    if len(likely) == 1:
        return likely[0]["id"]
    raise RuntimeError("Could not uniquely resolve MATCH_SIGNAL_ANALYST_STORE. Give the workflow the namespace id via MATCH_SIGNAL_EVIDENCE_KV_NAMESPACE_ID or grant the existing Cloudflare API token read access to Pages bindings and KV namespaces.")


def _kv_url(namespace_id: str) -> str:
    _, account = _credentials()
    return (
        CF_API + "/accounts/" + urllib.parse.quote(account, safe="")
        + "/storage/kv/namespaces/" + urllib.parse.quote(namespace_id, safe="")
        + "/values/" + urllib.parse.quote(EVIDENCE_KEY, safe="")
    )


def _kv_get(namespace_id: str) -> dict[str, Any] | None:
    token, _ = _credentials()
    request = urllib.request.Request(
        _kv_url(namespace_id),
        headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Cache-Control": "no-store"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("private evidence record exceeded the 12 MiB cap")
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        if exc.code == 404:
            return None
        raise RuntimeError(f"Cloudflare KV read returned HTTP {exc.code}: {detail[:240]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Cloudflare KV read failed: {str(exc)[:240]}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("private KV document is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("record_type") != "cross_sport_market_reassessment" or not isinstance(value.get("records"), list):
        raise RuntimeError("private KV document has an invalid shape")
    return value



def _validate_current_research_artifact(artifact: Any) -> tuple[list[dict[str, Any]], str]:
    """Validate the generated unpriced research lane without mixing it into quote history."""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("current_research_candidates"), list):
        raise RuntimeError("Current research artifact is missing the replace-on-refresh current_research_candidates array")
    generated_at = str(artifact.get("current_research_candidates_generated_at") or artifact.get("generated_at") or "").strip()
    if not generated_at:
        raise RuntimeError("Current research candidate array has no generation timestamp")

    allowed_markets = {"1X2", "winner", "total_goals", "total_games", "btts", "double_chance", "set_winner"}
    price_fields = (
        "bookmaker_odds", "quote_timestamp", "market_odds_timestamp", "odds_timestamp",
        "sportybet_event_id", "sportybet_market_id", "sportybet_outcome_id",
        "sportybet_outcome_name", "sportybet_specifier",
    )
    result: list[dict[str, Any]] = []
    for row in artifact["current_research_candidates"]:
        if not isinstance(row, dict):
            raise RuntimeError("Current research candidates contain a non-object row")
        probability = row.get("model_probability")
        try:
            p = float(probability)
        except (TypeError, ValueError):
            raise RuntimeError("Current research candidate has an invalid model probability")
        if (
            row.get("sport") not in {"football", "tennis"}
            or row.get("market") not in allowed_markets
            or (
                row.get("market") == "set_winner"
                and not (
                    row.get("sport") == "tennis"
                    and row.get("set_number") in (1, 2, "1", "2")
                    and row.get("pick") in {"p1", "p2"}
                )
            )
            or row.get("prediction_role") != "ALTERNATIVE"
            or row.get("alternative_source") != "SYSTEM_RECOMMENDED"
            or row.get("candidate_status") != "RESEARCH_ONLY_NO_LIVE_QUOTE"
            or row.get("research_only") is not True
            or row.get("bookable") is not False
            or row.get("qualification_allowed") is not False
            or row.get("passed_builder_gates") is not False
            or row.get("fresh_exact_quote") is not False
            or not str(row.get("event_id") or "").strip()
            or not str(row.get("start_time") or "").strip()
            or not str(row.get("pick") or "").strip()
            or not 0 < p < 1
            or any(row.get(field) is not None for field in price_fields)
        ):
            raise RuntimeError("Unsafe or malformed current research candidate; refusing to publish it")
        result.append(dict(row))
    if len(result) > 2000:
        raise RuntimeError("Current research candidate array exceeded its 2,000-row publication cap")
    return result, generated_at


def _load_current_research_candidates() -> tuple[list[dict[str, Any]], str]:
    try:
        artifact = json.loads(CURRENT_OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Current cross-sport research artifact is unavailable or invalid JSON") from exc
    return _validate_current_research_artifact(artifact)


def _kv_put(namespace_id: str, document: dict[str, Any]) -> None:
    token, _ = _credentials()
    data = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise RuntimeError("private evidence ledger exceeds the 12 MiB write cap")
    req = urllib.request.Request(
        _kv_url(namespace_id),
        data=data,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read(4096)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise RuntimeError(f"Cloudflare KV write returned HTTP {exc.code}: {detail[:240]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Cloudflare KV write failed: {str(exc)[:240]}") from exc


def restore() -> int:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        namespace_id = _resolve_namespace_id()
        document = _kv_get(namespace_id)
        revision = str((document or {}).get("updated_at") or "none")
        if document is None:
            document = _default_document()
        _write_json(HISTORY_PATH, document)
        REVISION_PATH.write_text(revision + "\n", encoding="utf-8")
        NAMESPACE_PATH.write_text(namespace_id + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PRIVATE_EVIDENCE_RESTORED",
            "revision": revision,
            "record_count": len(document.get("records", [])),
        }))
        return 0
    except Exception as exc:
        # Do not fabricate an empty ledger when the remote restore fails.
        REVISION_PATH.write_text("unavailable\n", encoding="utf-8")
        NAMESPACE_PATH.write_text("unavailable\n", encoding="utf-8")
        _warning(f"Private cross-sport evidence restore failed: {exc}. Failing this run so persistence outages cannot masquerade as successful refreshes.")
        print("PRIVATE_EVIDENCE_RESTORE_UNAVAILABLE")
        return 1


def publish() -> int:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        revision = REVISION_PATH.read_text(encoding="utf-8").strip()
        namespace_id = NAMESPACE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        revision, namespace_id = "unavailable", "unavailable"
    if not revision or revision == "unavailable" or not namespace_id or namespace_id == "unavailable":
        _warning("Private evidence was not restored, so this run cannot safely persist or overwrite the private ledger. Failing the refresh.")
        print("PRIVATE_EVIDENCE_NOT_PERSISTED")
        return 1
    try:
        # Re-read right before write to avoid overwriting another writer's newer ledger.
        current = _kv_get(namespace_id)
        current_revision = str((current or {}).get("updated_at") or "none")
        if current_revision != revision:
            raise RuntimeError("private evidence revision conflict; next run will reload the latest ledger")
        document = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("records"), list):
            raise RuntimeError("local private evidence ledger has an invalid shape")
        # Keep current model-only options separate from immutable, quote-backed history.
        # Replace this array on every Builder refresh so research candidates never become
        # historical price observations and never inherit stale provider/price fields.
        research_candidates, research_generated_at = _load_current_research_candidates()
        document["record_type"] = "cross_sport_market_reassessment"
        document["mode"] = "PAPER_ONLY"
        document["record_count"] = len(document["records"])
        document["current_research_candidates"] = research_candidates
        document["current_research_candidates_generated_at"] = research_generated_at
        document["current_research_candidate_count"] = len(research_candidates)
        document["updated_at"] = datetime.now(timezone.utc).isoformat()
        _kv_put(namespace_id, document)
        _write_json(HISTORY_PATH, document)
        REVISION_PATH.write_text(str(document["updated_at"]) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PRIVATE_EVIDENCE_SAVED",
            "revision": document["updated_at"],
            "record_count": len(document["records"]),
            "current_research_candidate_count": len(research_candidates),
            "current_research_candidates_generated_at": research_generated_at,
        }))
        return 0
    except Exception as exc:
        _warning(f"Private cross-sport evidence was not persisted: {exc}. The raw ledger remains runner-local and will not be added to public Git. Failing the refresh so the failure is visible.")
        print("PRIVATE_EVIDENCE_SAVE_UNAVAILABLE")
        return 1


def main(argv: list[str]) -> int:
    if argv == ["restore"]:
        return restore()
    if argv == ["publish"]:
        return publish()
    print("Usage: sync_cross_sport_private_evidence.py restore|publish")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
