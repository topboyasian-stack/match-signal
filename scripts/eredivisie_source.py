"""Resilient free Eredivisie 2026/27 source.

Primary source for the live-expansion pipeline is the public openfootball
current-season dataset. FixtureDownload JSON is used for the near-term
schedule when available. Team names are normalized to Match Signal's
canonical names.
"""
import json
import re
from datetime import datetime, timezone, timedelta
import requests

OPENFOOTBALL = "https://raw.githubusercontent.com/openfootball/europe/master/netherlands/2026-27_nl1.txt"
FIXTURE_JSON = "https://fixturedownload.azurewebsites.net/feed/json/eredivisie-2026"
S = requests.Session()
S.headers.update({"User-Agent": "MatchSignal/1.0 (+https://github.com/topboyasian-stack/match-signal)"})

ALIASES = {
    "AFC Ajax": "Ajax", "Ajax Amsterdam": "Ajax", "SBV Excelsior": "Excelsior",
    "Excelsior Rotterdam": "Excelsior", "SC Cambuur-Leeuwarden": "SC Cambuur",
    "SC Cambuur": "SC Cambuur", "NEC": "NEC", "NEC Nijmegen": "NEC",
    "N.E.C. Nijmegen": "NEC", "N.E.C.": "NEC", "PSV Eindhoven": "PSV",
    "Feyenoord Rotterdam": "Feyenoord", "FC Twente '65": "FC Twente",
    "FC Twente": "FC Twente", "SC Heerenveen": "sc Heerenveen",
    "Heerenveen": "sc Heerenveen", "Telstar 1963": "Telstar",
    "Willem II Tilburg": "Willem II", "PEC Zwolle": "PEC Zwolle",
    "FC Groningen": "FC Groningen", "FC Utrecht": "FC Utrecht",
    "AZ Alkmaar": "AZ", "AZ": "AZ", "ADO Den Haag": "ADO Den Haag",
    "Fortuna Sittard": "Fortuna Sittard", "Go Ahead Eagles": "Go Ahead Eagles",
    "Sparta Rotterdam": "Sparta Rotterdam",
}


def norm_team(name):
    name = " ".join(str(name or "").replace("  ", " ").split()).strip()
    return ALIASES.get(name, name)


def parse_dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def openfootball():
    r = S.get(OPENFOOTBALL, timeout=45)
    r.raise_for_status()
    text = r.text
    current_date = None
    results = []
    fixtures = []
    date_re = re.compile(r"^\s*(?:[A-Z][a-z]{2}\s+)?([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?$")
    match_re = re.compile(r"^\s*(?:(\d{2}:\d{2})\s+)?(.+?)\s+v\s+(.+?)(?:\s+(\d+)-(\d+)(?:\s+\([^)]*\))?)?\s*$")
    months = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#") or line.lstrip().startswith("▪"):
            continue
        # Match lines such as "Fri Sep 18 2026" or "Sat Aug 8".
        dm = re.match(r"^\s*(?:[A-Z][a-z]{2}\s+)?([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))\s*$", line)
        if dm:
            mon, day, year = dm.groups()
            year = int(year) if year else (current_date.year if current_date else 2026)
            current_date = datetime(year, months[mon], int(day), tzinfo=timezone.utc)
            continue
        m = match_re.match(line)
        if not m or not current_date:
            continue
        tm, home, away, hg, ag = m.groups()
        home, away = norm_team(home), norm_team(away)
        if not home or not away or home.lower() == "cancelled":
            continue
        hour, minute = (map(int, tm.split(":")) if tm else (12, 0))
        start = current_date.replace(hour=hour, minute=minute)
        eid = f"of|2627|{start.date()}|{home}|{away}"
        row = {"event_id": eid, "date": start.isoformat(), "home": home, "away": away,
               "home_id": "", "away_id": "", "markets": {}, "source": OPENFOOTBALL}
        if hg is not None and ag is not None:
            row["home_score"] = float(hg); row["away_score"] = float(ag)
            results.append(row)
        else:
            fixtures.append(row)
    return results, fixtures


def fixture_json(now=None):
    now = now or datetime.now(timezone.utc)
    try:
        r = S.get(FIXTURE_JSON, timeout=45)
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return []
    out = []
    for x in payload:
        try: d = parse_dt(x.get("DateUtc"))
        except Exception: continue
        if d < now - timedelta(hours=2) or d > now + timedelta(days=14):
            continue
        if x.get("HomeTeamScore") not in (None, "") or x.get("AwayTeamScore") not in (None, ""):
            continue
        h, a = norm_team(x.get("HomeTeam")), norm_team(x.get("AwayTeam"))
        if not h or not a: continue
        out.append({"event_id": f"fdl|2627|{d.date()}|{h}|{a}", "date": d.isoformat(),
                    "home": h, "away": a, "home_id": "", "away_id": "", "markets": {},
                    "source": FIXTURE_JSON})
    return sorted(out, key=lambda z: z["date"])


def current_fixtures(now=None):
    now = now or datetime.now(timezone.utc)
    fj = fixture_json(now)
    if fj:
        return fj
    _, of = openfootball()
    return [x for x in of if now - timedelta(hours=2) <= parse_dt(x["date"]) <= now + timedelta(days=14)]


def current_results():
    results, _ = openfootball()
    now = datetime.now(timezone.utc)
    return [x for x in results if parse_dt(x["date"]) <= now]
