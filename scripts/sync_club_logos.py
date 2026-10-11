#!/usr/bin/env python3
"""Build a permanent, license-checked local club-logo registry for Match Signal.

Only raster previews under CC0, Public Domain, CC BY, or CC BY-SA are copied.
Each saved asset retains its Wikimedia file page, license, and artist/credit metadata.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSET_DIR = ROOT / "assets" / "club-logos"
REGISTRY_PATH = DATA / "club-logo-registry.json"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "MatchSignal-ClubLogoRegistry/1.0 (https://github.com/topboyasian-stack/match-signal)"
MAX_IMAGE_BYTES = 2_000_000
MISS_RETRY_DAYS = 7

DATA_SOURCES = [
    "data/odds_builder.json",
    "data/odds_ticket_tracker.json",
    "data/virtual_lab_live.json",
    "data/virtual_lab_pending.json",
    "data/virtual_lab_history.json",
    "data/prediction_history.json",
    "data/expansion_prediction_history.json",
    "data/virtual_lab_participant_profiles.json",
]
VIRTUAL_PRODUCTS = {"efootball", "efootball_gt", "efootball_adriatic", "vfootball", "zoom", "virtual"}
FOOTBALL_PRODUCTS = VIRTUAL_PRODUCTS | {"football", "soccer"}
TEAM_FIELDS = (
    "team_1", "team_2", "homeTeamName", "awayTeamName",
    "home_team", "away_team", "homeTeam", "awayTeam",
    "participant_1", "participant_2",
)
ARTWORK_RE = re.compile(r"\b(logo|crest|badge|emblem|coat of arms)\b", re.I)
CLUB_CLUE_RE = re.compile(
    r"\b(football|soccer|club|olympique|racing|athletic|sporting|futbol|fútbol|fc|afc|sc|ac|cf)\b|"
    r"\b(?:f\.c\.|a\.f\.c\.|c\.f\.|s\.c\.|a\.c\.)\b",
    re.I,
)
ALIASES = {
    "man city": ("Manchester City",),
    "man utd": ("Manchester United",),
    "newcastle utd": ("Newcastle United",),
    "wolves": ("Wolverhampton Wanderers",),
    "spurs": ("Tottenham Hotspur",),
    "psg": ("Paris Saint-Germain",),
    "barca": ("Barcelona",),
    "bayern": ("Bayern Munich",),
    "juve": ("Juventus",),
    "inter": ("Inter Milan",),
    "atletico": ("Atletico Madrid",),
    "ath madrid": ("Atletico Madrid",),
    "sporting lisbon": ("Sporting CP",),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def plain(value) -> str:
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def clean_team_name(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" \t\r\n-–—")


def normalize_text(value) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).split())


def normalize_team(value) -> str:
    text = normalize_text(clean_team_name(value))
    text = re.sub(r"^(fc|afc|sc|ac|club)\s+", "", text)
    text = re.sub(r"\s+(football club|fc|cf|afc|sc|ac)$", "", text).strip()
    return text


def split_fixture(value):
    text = str(value or "")
    match = re.search(r"\s+(?:vs?\.?|v)\s+", text, flags=re.I)
    if not match:
        return ()
    left = clean_team_name(text[:match.start()])
    right = clean_team_name(text[match.end():])
    if normalize_team(left) and normalize_team(right):
        return left, right
    return ()


def is_football_product(value) -> bool:
    product = normalize_text(value).replace(" ", "_")
    return product in FOOTBALL_PRODUCTS or product.startswith("efootball") or product.startswith("vfootball")


def license_allowed(value) -> bool:
    lic = plain(value).lower().replace("\u00a0", " ").replace("–", "-").replace("—", "-")
    lic = re.sub(r"\s+", " ", lic).strip()
    if lic in {"cc0", "cc0 1.0", "public domain", "public domain mark", "pd"}:
        return True
    return bool(re.fullmatch(r"cc by(?:-sa)?(?:\s+\d+(?:\.\d+)?)?(?:\s+international)?", lic))


def _registry():
    try:
        raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("teams", {})
            raw.setdefault("misses", {})
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": 1, "teams": {}, "misses": {}}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_clubs():
    """Count club names in live/pending, builder, history, and settlement evidence."""
    names = {}
    frequencies = Counter()

    def add(raw, product, field="match"):
        clean = clean_team_name(raw)
        key = normalize_team(clean)
        if not key or len(key) < 3 or key in {"home", "away", "team one", "team two", "unknown"}:
            return
        if field in {"participant_1", "participant_2"} and normalize_text(product).replace(" ", "_") in VIRTUAL_PRODUCTS:
            # In virtual feeds participant fields can be gamer handles. Only accept
            # those that explicitly carry a parenthesized club label.
            if not re.search(r"\([^()]+\)\s*$", str(raw or "")):
                return
        if field == "match" and not clean:
            return
        names.setdefault(key, Counter())[clean] += 1
        frequencies[key] += 1

    def walk(node, inherited_product=""):
        if isinstance(node, list):
            for child in node:
                walk(child, inherited_product)
            return
        if not isinstance(node, dict):
            return
        product = node.get("product") or node.get("sport") or inherited_product or ""
        is_football = is_football_product(product)
        match_text = node.get("match")
        if is_football and isinstance(match_text, str):
            sides = split_fixture(match_text)
            if sides:
                add(sides[0], product)
                add(sides[1], product)
        if is_football:
            for field in TEAM_FIELDS:
                value = node.get(field)
                if isinstance(value, str) and value.strip():
                    add(value, product, field)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, product)

    for relative in DATA_SOURCES:
        path = ROOT / relative
        payload = _read_json(path)
        if payload is not None:
            walk(payload)

    archive_dir = DATA / "virtual_lab_archive" / "settlements"
    if archive_dir.exists():
        for path in sorted(archive_dir.glob("*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        try:
                            walk(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue

    # Keep the most common spelling as the display name for each normalized key.
    result = []
    for key, variants in names.items():
        display = variants.most_common(1)[0][0]
        result.append({"key": key, "name": display, "frequency": frequencies[key]})
    result.sort(key=lambda x: (-x["frequency"], x["key"]))
    return result


def _allowed_image_mime(value) -> bool:
    return str(value or "").lower().split(";", 1)[0].strip() in {
        "image/jpeg", "image/png", "image/webp", "image/gif"
    }


def _signature_ok(content: bytes, mime: str) -> bool:
    mime = mime.lower()
    if mime == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if mime == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    return False


def _source_file_url(title: str) -> str:
    filename = re.sub(r"^File:", "", str(title), flags=re.I).replace(" ", "_")
    return "https://commons.wikimedia.org/wiki/File:" + quote(filename, safe="_()'!,.-")


def _license_url(metadata) -> str:
    raw = str((metadata.get("LicenseUrl") or {}).get("value") or "")
    match = re.search(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
    return html.unescape(match.group(1)) if match else plain(raw)


def _candidate_for(name: str):
    key = normalize_team(name)
    terms = [name]
    terms.extend(ALIASES.get(key, ()))
    terms = list(dict.fromkeys(term for term in terms if term and normalize_team(term)))
    best = None

    for term in terms:
        search_key = normalize_team(term)
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f'"{term}" (logo OR crest OR badge OR emblem)',
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": 256,
            "format": "json",
            "origin": "*",
        }
        try:
            response = requests.get(
                COMMONS_API, params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=20,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(1.0)
                response = requests.get(
                    COMMONS_API, params=params,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=20,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue

        pages = (payload.get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = str(page.get("title") or "")
            title_base = re.sub(r"\.[^.]+$", "", re.sub(r"^File:", "", title, flags=re.I))
            title_key = normalize_text(title_base)
            info_rows = page.get("imageinfo") or []
            info = info_rows[0] if info_rows else {}
            metadata = info.get("extmetadata") or {}
            licence = plain((metadata.get("LicenseShortName") or {}).get("value") or (metadata.get("UsageTerms") or {}).get("value") or "")
            mime = str(info.get("thumbmime") or info.get("mime") or "").lower()
            url = str(info.get("thumburl") or "")
            if not url:
                # Original files may be enormous or SVG; require a raster preview.
                continue
            if urlparse(url).scheme != "https" or urlparse(url).hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
                continue
            if not _allowed_image_mime(mime) or not license_allowed(licence):
                continue
            if not search_key or (" " + search_key + " ") not in (" " + title_key + " "):
                continue
            if not ARTWORK_RE.search(title_base) or not CLUB_CLUE_RE.search(title_base):
                continue
            exact_bonus = 100 if title_key == search_key else 0
            crest_bonus = 12 if re.search(r"\b(crest|badge|emblem)\b", title_base, re.I) else 0
            logo_bonus = 8 if re.search(r"\blogo\b", title_base, re.I) else 0
            score = exact_bonus + crest_bonus + logo_bonus
            candidate = {
                "title": title,
                "url": url,
                "source_url": _source_file_url(title),
                "licence": licence,
                "license_url": _license_url(metadata),
                "artist": plain((metadata.get("Artist") or {}).get("value") or (metadata.get("Credit") or {}).get("value") or "")[:220],
                "mime": mime,
                "score": score,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    return best


def _download_asset(candidate):
    response = requests.get(
        candidate["url"],
        headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif"},
        timeout=25,
    )
    response.raise_for_status()
    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    content = response.content
    if len(content) < 100 or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("image preview size outside the safe 100B–2MB range")
    if not _allowed_image_mime(content_type) or not _signature_ok(content, content_type):
        raise ValueError("Commons returned an unsupported or invalid raster preview")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[content_type]
    return content, ext, content_type


def _retry_due(value, now):
    try:
        retry_after = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        return retry_after <= now
    except (TypeError, ValueError):
        return True


def sync_registry(max_new=80):
    registry = _registry()
    teams = registry.setdefault("teams", {})
    misses = registry.setdefault("misses", {})
    discoveries = collect_clubs()
    now = datetime.now(timezone.utc)
    attempts = []
    for item in discoveries:
        key = item["key"]
        entry = teams.get(key)
        if entry:
            local_path = ROOT / str(entry.get("path") or "").lstrip("/")
            if local_path.exists():
                continue
            teams.pop(key, None)
        miss = misses.get(key) or {}
        if miss and not _retry_due(miss.get("retry_after"), now):
            continue
        attempts.append(item)
        if len(attempts) >= max(1, int(max_new)):
            break

    print(f"Logo registry scan: {len(discoveries)} normalized teams; {len(attempts)} lookup attempts queued.")
    if not attempts:
        print("No new logo lookups due. Registry is already complete for discovered names or unresolved entries are in cooldown.")
        return False

    def process(item):
        try:
            candidate = _candidate_for(item["name"])
            if not candidate:
                return item, None, "No exact name-matched CC0/Public Domain/CC BY/CC BY-SA raster artwork found."
            content, ext, mime = _download_asset(candidate)
            return item, (candidate, content, ext, mime), None
        except Exception as exc:
            return item, None, str(exc)[:240]

    changes = 0
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(process, item) for item in attempts]
        for future in concurrent.futures.as_completed(futures):
            item, result, error = future.result()
            key = item["key"]
            if result:
                candidate, content, ext, mime = result
                filename = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:90] or "club"
                asset_path = ASSET_DIR / (filename + ext)
                # Avoid overwriting a different asset when an extension changes.
                asset_path.write_bytes(content)
                teams[key] = {
                    "name": item["name"],
                    "path": "/assets/club-logos/" + asset_path.name,
                    "provider": "Wikimedia Commons",
                    "source_url": candidate["source_url"],
                    "title": candidate["title"],
                    "licence": candidate["licence"],
                    "license_url": candidate["license_url"],
                    "artist": candidate["artist"],
                    "mime": mime,
                    "bytes": len(content),
                    "aliases": [item["name"]],
                    "downloaded_at": now_iso(),
                }
                misses.pop(key, None)
                changes += 1
                print(f"Saved licensed club logo: {item['name']} ({candidate['licence']})")
            else:
                misses[key] = {
                    "name": item["name"],
                    "last_attempted_at": now_iso(),
                    "retry_after": (now + timedelta(days=MISS_RETRY_DAYS)).isoformat(),
                    "reason": error or "No reusable image returned.",
                }
                print(f"Logo fallback retained for {item['name']}: {misses[key]['reason']}")

    registry["schema_version"] = 1
    registry["generated_at"] = now_iso()
    registry["source_policy"] = "Local raster assets are copied only from verified CC0, Public Domain, CC BY, or CC BY-SA Wikimedia Commons previews; source, license, and attribution metadata are retained."
    registry["scan_summary"] = {
        "discovered_teams": len(discoveries),
        "permanent_logos": len(teams),
        "unresolved_names": len(misses),
        "new_assets_this_run": changes,
        "last_scan_at": now_iso(),
    }
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Logo registry summary:", json.dumps(registry["scan_summary"], ensure_ascii=False))
    return changes > 0 or bool(attempts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new", type=int, default=80, help="Maximum new team lookups to attempt per run.")
    args = parser.parse_args()
    sync_registry(max_new=args.max_new)


if __name__ == "__main__":
    main()
