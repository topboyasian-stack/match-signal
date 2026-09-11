"""Free public-web basketball collector.

Source strategy (deliberately independent of SofaScore):
- SportPesa's public basketball board for current fixtures/competition labels.
- 1xBet public basketball line pages when a matching event page can be resolved for
  market context. No account, API key, or private endpoint is used.
- When a published total line is unavailable, the dashboard keeps the fixture and
  produces a model-estimated total from recent public results rather than inventing
  bookmaker odds. Such picks are explicitly labelled model_total.

This collector targets Germany BBL-Pokal and International Club Friendly Games.
"""
import html, json, math, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from html.parser import HTMLParser
from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SPORTPESA_URLS = [
    "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/upcoming-games/",
    "https://www.sportpesa.co.tz/en/sports-betting/basketball-2/",
]
ONE_XBET_URL = "https://1xbet.com/en/line/basketball"
TARGETS = {
    "Germany - BBL-Pokal": "German Basketball Cup",
    "Germany - BBL Pokal": "German Basketball Cup",
    "International - Club Friendly Games": "International Club Friendly",
    "International - Club Friendlies": "International Club Friendly",
}

S = requests.Session(impersonate="chrome")
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def norm_name(s):
    s = html.unescape(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    replacements = {"rostockseawolves": "rostock", "hamburgtowers": "hamburg"}
    return replacements.get(s, s)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            text = " ".join(self._text).strip()
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def fetch(url):
    r = S.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_sportpesa(html_text):
    # The public page renders event blocks server-side. Keep the parser deliberately
    # text-oriented so minor markup changes do not break fixture discovery.
    text = html.unescape(re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html_text, flags=re.I))
    text = re.sub(r"<[^>]+>", "\n", text)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    games = []
    i = 0
    while i < len(lines):
        league = lines[i]
        if league not in TARGETS:
            i += 1
            continue
        window = lines[i:i+16]
        gid = next((re.search(r"(?:Game ID|ID:)\s*(\d+)", x, re.I).group(1)
                    for x in window if re.search(r"(?:Game ID|ID:)\s*(\d+)", x, re.I)), None)
        if not gid:
            i += 1
            continue
        # Find the first two plausible team-name lines after the ID/date block.
        pos = next((j for j, x in enumerate(window) if re.search(r"(?:Game ID|ID:)\s*\d+", x, re.I)), 0)
        tail = window[pos+1:]
        teams = []
        for x in tail:
            if re.match(r"^\d{1,2}:\d{2}$", x) or re.match(r"^\d{1,2}/\d{2}/\d{2}$", x):
                continue
            if x.lower() in {"2 way - ot incl.", "1", "2", "o", "u"}:
                continue
            if x.startswith("Game ID") or x.startswith("ID:"):
                continue
            if len(x) > 2 and not re.search(r"odds|betslip|show odds", x, re.I):
                teams.append(x)
            if len(teams) == 2:
                break
        if len(teams) == 2:
            games.append({
                "event_id": str(gid),
                "league_source": league,
                "league": TARGETS[league],
                "home": teams[0],
                "away": teams[1],
            })
        i += 1
    # Deduplicate by event id.
    out, seen = [], set()
    for g in games:
        if g["event_id"] not in seen:
            out.append(g); seen.add(g["event_id"])
    return out


def one_xbet_links(html_text):
    p = LinkParser(); p.feed(html_text)
    return [(urljoin(ONE_XBET_URL, href), text) for href, text in p.links
            if href and "/line/basketball/" in href and text]


def resolve_market_page(home, away, links):
    nh, na = norm_name(home), norm_name(away)
    candidates = []
    for url, text in links:
        nt = norm_name(text)
        score = 0
        if nh and nh in nt: score += 2
        if na and na in nt: score += 2
        if score >= 4: candidates.append((score, url, text))
    if not candidates:
        # Also allow either team when the bookmaker abbreviates one side.
        for url, text in links:
            nt = norm_name(text)
            score = int(bool(nh and nh in nt)) + int(bool(na and na in nt))
            if score >= 1: candidates.append((score, url, text))
    return max(candidates, default=(0, None, None))[1:]


def parse_market_text(text):
    # Extract a published combined total when the event page exposes it in text.
    clean = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    total = None
    patterns = [
        r"(?:total|over\s*/\s*under)[^\d]{0,80}(\d{2,3}(?:\.5)?)",
        r"(?:O|U)\s*(\d{2,3}(?:\.5)?)",
    ]
    for pat in patterns:
        m = re.search(pat, clean, re.I)
        if m:
            try:
                v = float(m.group(1))
                if 100 <= v <= 260:
                    total = v; break
            except ValueError:
                pass
    return {"line": total, "source": "1xBet public event page" if total else None}


def get_market(home, away, links):
    url, label = resolve_market_page(home, away, links)
    if not url:
        return {"moneyline": None, "total": None, "market_url": None}
    try:
        body = fetch(url)
        market = parse_market_text(body)
        return {"moneyline": None, "total": market, "market_url": url}
    except Exception:
        return {"moneyline": None, "total": None, "market_url": url}


def recent_public_scores(teams, one_xbet_html):
    # Pull score-like rows from the public 1xBet basketball line page when available.
    # This is intentionally conservative; malformed or unrelated rows are ignored.
    result = {norm_name(t): [] for t in teams}
    clean = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", one_xbet_html)))
    for team in teams:
        n = norm_name(team)
        # Typical result snippets contain Team A Team B 87 81. We only use them if
        # both numeric values are plausible basketball scores.
        pat = re.compile(re.escape(team) + r".{0,180}?(\d{2,3})\s+(\d{2,3})", re.I)
        for m in pat.finditer(clean):
            a, b = int(m.group(1)), int(m.group(2))
            if 40 <= a <= 180 and 40 <= b <= 180:
                result[n].append(a + b)
    return result


def model_total(home, away, scores):
    h = scores.get(norm_name(home), [])[-6:]
    a = scores.get(norm_name(away), [])[-6:]
    vals = h + a
    if vals:
        return round(sum(vals) / len(vals), 1)
    return None


def predict(game, market, scores):
    home, away = game["home"], game["away"]
    expected = model_total(home, away, scores)
    line = (market.get("total") or {}).get("line")
    market_source = (market.get("total") or {}).get("source")
    if line is not None:
        # Without reliable public prices, do not fabricate probabilities. Use the
        # model-vs-market gap to express a restrained total signal.
        edge = 1 / (1 + math.exp(-(expected - line) / 7)) if expected is not None else .5
        over = max(.05, min(.95, edge)); under = 1 - over
        pick = "over" if over > under else "under"
        total_source = market_source
    else:
        # Estimated reference line is the model expectation rounded to a half point.
        # No fake bookmaker probability is shown.
        ref = round(expected * 2) / 2 if expected is not None else None
        over = under = .5
        pick = None
        line = ref
        total_source = "Model-estimated total; no published public O/U line found"
    confidence = .5
    if expected is not None:
        confidence = .5 + min(.18, abs((expected - (line or expected)) / 25))
    q = sum(bool(x) for x in [expected is not None, market_source, market.get("market_url")])
    return {
        "sport": "basketball",
        "league": game["league"],
        "source": "SportPesa public board + 1xBet public market page",
        "event_id": game["event_id"],
        "start_time": datetime.now(timezone.utc).isoformat(),
        "player_1": home,
        "player_2": away,
        "probabilities": {"p1": .5, "p2": .5},
        "pick": None,
        "confidence": round(confidence, 4),
        "markets": {
            "moneyline": None,
            "total_ou": {
                "line": line,
                "over": round(over, 4),
                "under": round(under, 4),
                "pick": pick,
                "expected_total": expected,
                "source": total_source,
                "settlement": "Official final score including overtime",
            },
            "spread": None,
        },
        "form": {"p1_total_samples": len(scores.get(norm_name(home), [])),
                 "p2_total_samples": len(scores.get(norm_name(away), []))},
        "signal_quality": {
            "components": q,
            "max_components": 3,
            "market_total_available": bool(market_source),
            "market_event_page_available": bool(market.get("market_url")),
            "recent_total_form_available": expected is not None,
        },
        "model": "Public-market total vs recent scoring form" if market_source else "Recent scoring form total estimate",
        "rules_note": "Basketball total settlement uses the official final score, including overtime.",
    }


def settle(history):
    # No private score endpoint is assumed here. Future settlement can consume the
    # public results feed once the event has a final score; until then remain unsettled.
    return history


def main():
    source_status = []
    games = []
    for url in SPORTPESA_URLS:
        try:
            parsed = parse_sportpesa(fetch(url))
            if parsed:
                games = parsed
                source_status.append({"source": url, "events": len(parsed), "status": "ok"})
                break
            source_status.append({"source": url, "events": 0, "status": "empty"})
        except Exception as exc:
            source_status.append({"source": url, "events": 0, "status": type(exc).__name__})
    try:
        xbet_html = fetch(ONE_XBET_URL)
        links = one_xbet_links(xbet_html)
        source_status.append({"source": ONE_XBET_URL, "event_links": len(links), "status": "ok"})
    except Exception as exc:
        xbet_html, links = "", []
        source_status.append({"source": ONE_XBET_URL, "event_links": 0, "status": type(exc).__name__})
    teams = [x for g in games for x in (g["home"], g["away"])]
    scores = recent_public_scores(teams, xbet_html)
    predictions = []
    for g in games:
        market = get_market(g["home"], g["away"], links)
        predictions.append(predict(g, market, scores))
    history = load(DATA / "basketball_history.json", [])
    known = {(str(x.get("event_id")), x.get("league")) for x in history}
    for p in predictions:
        if (p["event_id"], p["league"]) not in known:
            history.append(p)
    save(DATA / "basketball_predictions.json", sorted(predictions, key=lambda x: x["start_time"]))
    save(DATA / "basketball_history.json", history)
    settled = [x for x in history if x.get("settled")]
    totals = [x for x in settled if x.get("total_correct") is not None]
    correct = sum(bool(x.get("correct")) for x in settled)
    total_correct = sum(bool(x.get("total_correct")) for x in totals)
    save(DATA / "basketball_accuracy.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "settled": len(settled), "correct": correct,
        "accuracy": correct / len(settled) if settled else None,
        "total_ou_settled": len(totals), "total_ou_correct": total_correct,
        "total_ou_accuracy": total_correct / len(totals) if totals else None,
    })
    status = load(DATA / "pipeline_status.json", {})
    status.update({
        "basketball_count": len(predictions),
        "basketball_settled": len(settled),
        "basketball_sources": source_status,
        "basketball_source_status": "SportPesa public board + 1xBet public market pages; SofaScore disabled",
        "basketball_updated_at": datetime.now(timezone.utc).isoformat(),
        "basketball_rules": "Totals settle on official final score including overtime",
    })
    save(DATA / "pipeline_status.json", status)
    print(f"Public-web basketball: {len(predictions)} predictions; sources={source_status}; settled={len(settled)}")


if __name__ == "__main__":
    main()
