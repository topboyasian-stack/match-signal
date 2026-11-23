#!/usr/bin/env python3
"""Stage the canonical NBA publication-snapshot archive as a bounded gzip asset.

The canonical JSON remains untouched in Git for immutable provenance and report
fingerprinting. The Basketball browser runtime reads the live predictions and
research reports, not this historical archive; Pages receives an exact gzip
copy so archive growth cannot exceed Cloudflare's per-file upload limit.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
from typing import Any


def stage_snapshot_archive(source: Path, staging_dir: Path, max_bytes: int) -> dict[str, Any]:
    source = Path(source)
    staging_dir = Path(staging_dir)
    staged_raw = staging_dir / source.name
    staged_gzip = staging_dir / (source.name + ".gz")

    if max_bytes <= 0:
        raise ValueError("Pages per-file size limit must be positive.")
    if not source.is_file():
        raise FileNotFoundError(f"Missing canonical NBA publication snapshot archive: {source}")
    if not staged_raw.is_file():
        raise FileNotFoundError(f"Missing copied NBA publication snapshot archive: {staged_raw}")

    source_bytes = source.read_bytes()
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Canonical NBA publication snapshot archive is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, list):
        raise ValueError("NBA publication snapshot archive must be a JSON array.")

    staged_bytes = staged_raw.read_bytes()
    if staged_bytes != source_bytes:
        raise ValueError("Staged NBA snapshot archive differs from the canonical Git source; refusing deployment.")

    compressed = gzip.compress(source_bytes, compresslevel=9, mtime=0)
    if len(compressed) >= max_bytes:
        raise ValueError(
            f"Compressed NBA publication snapshots still exceed the Pages per-file limit "
            f"({len(compressed)} >= {max_bytes})."
        )

    temporary = staged_gzip.with_name(staged_gzip.name + ".tmp")
    temporary.write_bytes(compressed)
    if gzip.decompress(temporary.read_bytes()) != source_bytes:
        temporary.unlink(missing_ok=True)
        raise ValueError("Compressed NBA snapshot archive failed exact-byte round-trip verification.")
    temporary.replace(staged_gzip)
    staged_raw.unlink()

    if staged_raw.exists() or not staged_gzip.is_file() or staged_gzip.stat().st_size >= max_bytes:
        raise ValueError("NBA snapshot archive staging did not satisfy the Pages asset contract.")

    return {
        "record_count": len(payload),
        "source_bytes": len(source_bytes),
        "compressed_bytes": staged_gzip.stat().st_size,
        "canonical_source_unchanged": source.read_bytes() == source_bytes,
        "raw_browser_asset_removed": not staged_raw.exists(),
        "gzip_round_trip_exact": gzip.decompress(staged_gzip.read_bytes()) == source_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/nba_totals_publication_snapshots.json")
    parser.add_argument("--staging-dir", default=".pages-deploy/data")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.environ.get("MAX_PAGES_FILE_BYTES", "26214400")),
    )
    args = parser.parse_args()
    try:
        result = stage_snapshot_archive(Path(args.source), Path(args.staging_dir), args.max_bytes)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"NBA snapshot staging failed: {exc}\n")
    print(
        "NBA immutable publication snapshots staged: "
        f"{result['record_count']} records, {result['source_bytes']} canonical bytes -> "
        f"{result['compressed_bytes']} gzip bytes; exact round-trip verified; "
        "canonical Git source unchanged; raw oversized Pages asset removed."
    )
    if not result["canonical_source_unchanged"] or not result["raw_browser_asset_removed"] or not result["gzip_round_trip_exact"]:
        parser.exit(1, "NBA snapshot staging invariants failed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
