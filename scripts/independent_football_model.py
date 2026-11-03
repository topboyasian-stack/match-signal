import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone


def _clamp(x, lo=0.02, hi=0.96):
    return max(lo, min(hi, float(x)))


def _normalise(values):
    total = sum(max(1e-12, float(v)) for v in values)
    return [max(1e-12, float(v)) / total for v in values]


def _poisson(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def _parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _dc_tau(home_goals, away_goals, lam_home, lam_away, rho=-0.08):
    """Dixon-Coles low-score correction.

    The correction targets the scorelines most commonly mis-modeled by a
    plain independent Poisson model: 0-0, 1-0, 0-1 and 1-1.
    """
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lam_home * lam_away * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lam_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lam_home * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _outcome_probs(lam_home, lam_away, rho=-0.08, max_goals=10):
    """Independent outcome probabilities with a conservative Dixon-Coles correction."""
    matrix = []
    for i in range(max_goals + 1):
        row = []
        hp = _poisson(i, lam_home)
        for j in range(max_goals + 1):
            row.append(hp * _poisson(j, lam_away) * _dc_tau(i, j, lam_home, lam_away, rho))
        matrix.append(row)

    out = [0.0, 0.0, 0.0]
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            if i > j:
                out[0] += value
            elif i == j:
                out[1] += value
            else:
                out[2] += value
    return _normalise(out)


DOMESTIC_COMPETITIONS = frozenset({
    "La Liga",
    "Bundesliga",
    "Ligue 1",
    "Premier League",
    "Serie A",
    "Eredivisie",
    "Primeira Liga",
    "Süper Lig",
    "Belgian Pro League",
    "Austrian Bundesliga",
    "Eliteserien",
    "Czech First League",
    "Ukrainian Premier League",
    "Super League Greece",
    "Scottish Premiership",
    "Swiss Super League",
    "Danish Superliga",
    "Polish Ekstraklasa",
    "Croatian First Football League",
    "Serbian SuperLiga",
    "Slovak Super Liga",
})


def _canonical_competition(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    aliases = {
        "ucl": "Champions League",
        "uefa champions league": "Champions League",
        "champions league": "Champions League",
        "epl": "Premier League",
        "english premier league": "Premier League",
        "premier league": "Premier League",
        "serie a": "Serie A",
        "italian serie a": "Serie A",
        "la liga": "La Liga",
        "spanish la liga": "La Liga",
        "bundesliga": "Bundesliga",
        "ligue 1": "Ligue 1",
        "eredivisie": "Eredivisie",
        "primeira liga": "Primeira Liga",
        "liga portugal": "Primeira Liga",
        "super lig": "Süper Lig",
        "turkish super lig": "Süper Lig",
    }
    return aliases.get(text, str(value or "").strip())


def _team_key(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    ignored = {"fc", "afc", "cf", "sc", "club", "the", "ac", "as", "vfb", "vfl", "sk", "cp", "fk", "istanbul", "1907"}
    text = " ".join(token for token in text.split() if token not in ignored)
    aliases = {
        "internazionale": "inter",
        "inter milano": "inter",
        "bodo glimt": "bodo glimt",
        "bodoe glimt": "bodo glimt",
        "atletico de madrid": "atletico madrid",
        "real betis seville": "real betis",
        "real betis": "real betis",
        "villarreal cf": "villarreal",
        "villarreal": "villarreal",
        "psv eindhoven": "psv",
        "psv": "psv",
        "lask linz": "lask",
        "lask": "lask",
        "b dortmund": "borussia dortmund",
        "borussia dortmund": "borussia dortmund",
        "slovan bratislava": "slovan bratislava",
        "shakhtar donetsk": "shakhtar donetsk",
        "porto": "porto",
        "benfica": "benfica",
        "barcelona": "barcelona",
        "man utd": "manchester united",
        "manchester utd": "manchester united",
        "man city": "manchester city",
        "racing de lens": "lens",
        "galatasaray istanbul": "galatasaray",
    }
    return aliases.get(text, text)


def _empty_team():
    return {
        "gf": 0.0,
        "ga": 0.0,
        "n": 0.0,
        "home_gf": 0.0,
        "home_ga": 0.0,
        "home_n": 0.0,
        "away_gf": 0.0,
        "away_ga": 0.0,
        "away_n": 0.0,
    }


def _empty_league():
    return {
        "home_gf": 0.0,
        "home_ga": 0.0,
        "away_gf": 0.0,
        "away_ga": 0.0,
        "n": 0.0,
    }


def _team_stats(history, cutoff, competition_filter=None):
    """Build leakage-safe, recency-weighted team and competition stats.

    Team strength is keyed by normalized club identity, while league baselines
    remain competition-specific. Event IDs are deduplicated within competition
    so a provider ID collision cannot erase a different competition's result.
    """
    stats = defaultdict(_empty_team)
    league = defaultdict(_empty_league)
    cutoff_dt = _parse_dt(cutoff) or datetime.now(timezone.utc)
    seen = set()
    rows = []

    for row in history or []:
        if not row.get("settled") or not row.get("final_score"):
            continue
        if row.get("sport") != "football":
            continue
        competition = _canonical_competition(row.get("league") or "global")
        if competition_filter is not None and competition != competition_filter:
            continue
        event_dt = _parse_dt(row.get("calculated_at") or row.get("start_time"))
        if not event_dt or event_dt >= cutoff_dt:
            continue
        if (cutoff_dt - event_dt).total_seconds() > 365 * 86400:
            continue
        home = _team_key(row.get("player_1"))
        away = _team_key(row.get("player_2"))
        if not home or not away:
            continue
        event_id = str(row.get("event_id") or "")
        event_key = (competition, event_id) if event_id else (
            competition, home, away, event_dt.isoformat()
        )
        if event_key in seen:
            continue
        seen.add(event_key)
        try:
            hg, ag = map(float, row["final_score"][:2])
        except (TypeError, ValueError):
            continue
        rows.append((event_dt, competition, home, away, hg, ag))

    for event_dt, comp, home, away, hg, ag in rows:
        age_days = max(0.0, (cutoff_dt - event_dt).total_seconds() / 86400.0)
        weight = math.exp(-math.log(2.0) * age_days / 120.0)

        hs = stats[home]
        hs["gf"] += weight * hg
        hs["ga"] += weight * ag
        hs["n"] += weight
        hs["home_gf"] += weight * hg
        hs["home_ga"] += weight * ag
        hs["home_n"] += weight

        aws = stats[away]
        aws["gf"] += weight * ag
        aws["ga"] += weight * hg
        aws["n"] += weight
        aws["away_gf"] += weight * ag
        aws["away_ga"] += weight * hg
        aws["away_n"] += weight

        ls = league[comp]
        ls["home_gf"] += weight * hg
        ls["home_ga"] += weight * ag
        ls["away_gf"] += weight * ag
        ls["away_ga"] += weight * hg
        ls["n"] += weight

    return stats, league


def _league_baseline(league_stats, league):
    s = league_stats.get(_canonical_competition(league))
    if not s or not s["n"]:
        return 1.45, 1.15
    home_attack = max(0.65, min(2.8, s["home_gf"] / s["n"]))
    away_attack = max(0.55, min(2.5, s["away_gf"] / s["n"]))
    return home_attack, away_attack


def _venue_rates(team, side, base_for, base_against):
    """Return attack/defence multipliers plus recency-weighted venue sample."""
    overall_n = team.get("n", 0.0)
    if side == "home":
        gf, ga, n = team.get("home_gf", 0.0), team.get("home_ga", 0.0), team.get("home_n", 0.0)
    else:
        gf, ga, n = team.get("away_gf", 0.0), team.get("away_ga", 0.0), team.get("away_n", 0.0)

    if n > 0:
        venue_attack = (gf / n) / max(0.5, base_for)
        venue_defence = (ga / n) / max(0.5, base_against)
    else:
        venue_attack = venue_defence = 1.0

    if overall_n > 0:
        overall_attack = (team["gf"] / overall_n) / max(0.5, (base_for + base_against) / 2.0)
        overall_defence = (team["ga"] / overall_n) / max(0.5, (base_for + base_against) / 2.0)
    else:
        overall_attack = overall_defence = 1.0

    venue_weight = min(0.72, n / (n + 5.0))
    sample_weight = min(0.90, overall_n / (overall_n + 8.0))
    attack = venue_weight * venue_attack + (1.0 - venue_weight) * overall_attack
    defence = venue_weight * venue_defence + (1.0 - venue_weight) * overall_defence
    attack = sample_weight * attack + (1.0 - sample_weight)
    defence = sample_weight * defence + (1.0 - sample_weight)
    return _clamp(attack, 0.55, 1.65), _clamp(defence, 0.55, 1.65), round(n, 3)


def _infer_domestic_league(history, team_name, cutoff):
    """Infer a club's own domestic competition from its settled domestic fixtures."""
    cutoff_dt = _parse_dt(cutoff) or datetime.now(timezone.utc)
    key = _team_key(team_name)
    counts = defaultdict(float)
    latest = {}
    for row in history or []:
        if row.get("sport") != "football" or not row.get("settled") or not row.get("final_score"):
            continue
        competition = _canonical_competition(row.get("league"))
        if competition not in DOMESTIC_COMPETITIONS:
            continue
        event_dt = _parse_dt(row.get("calculated_at") or row.get("start_time"))
        if not event_dt or event_dt >= cutoff_dt:
            continue
        age_days = (cutoff_dt - event_dt).total_seconds() / 86400.0
        if age_days > 365:
            continue
        if key not in {_team_key(row.get("player_1")), _team_key(row.get("player_2"))}:
            continue
        counts[competition] += math.exp(-math.log(2.0) * age_days / 120.0)
        latest[competition] = max(latest.get(competition, event_dt), event_dt)
    if not counts:
        return None
    return max(counts, key=lambda comp: (counts[comp], latest[comp]))


def _ucl_blend_weight(effective_sample):
    """Reliability-weighted UCL contribution, capped to prevent tiny samples dominating."""
    n = max(0.0, float(effective_sample or 0.0))
    return min(0.30, 0.35 * n / (n + 5.0)) if n else 0.0


def _blend(domestic_value, ucl_value, ucl_weight):
    return (1.0 - ucl_weight) * domestic_value + ucl_weight * ucl_value


def independent_prediction(event, league, history, cutoff=None):
    """Competition-aware football model using domestic form plus UCL form for UCL fixtures.

    UCL and domestic performances are normalized against their own competition
    scoring baselines before blending. The UCL share grows with the available
    recency-weighted venue sample and is capped at 30%; domestic form remains
    the anchor. All inputs are strictly prior to the forecast cutoff.
    """
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    home_name = (home.get("team") or {}).get("displayName") or "Home"
    away_name = (away.get("team") or {}).get("displayName") or "Away"
    target_competition = _canonical_competition(league)
    history = history or []
    cutoff_dt = _parse_dt(cutoff) or datetime.now(timezone.utc)

    if target_competition == "Champions League":
        ucl_stats, ucl_leagues = _team_stats(history, cutoff_dt, "Champions League")
        ucl_home_base, ucl_away_base = _league_baseline(ucl_leagues, "Champions League")

        domestic_leagues = {
            home_name: _infer_domestic_league(history, home_name, cutoff_dt),
            away_name: _infer_domestic_league(history, away_name, cutoff_dt),
        }
        domestic_cache = {}
        for domestic_league in set(x for x in domestic_leagues.values() if x):
            domestic_cache[domestic_league] = _team_stats(history, cutoff_dt, domestic_league)

        def rates_for(team_name, side, competition, stats, league_stats):
            if not competition:
                return 1.0, 1.0, 0.0
            base_home, base_away = _league_baseline(league_stats, competition)
            team_stats = stats.get(_team_key(team_name), _empty_team())
            if side == "home":
                return _venue_rates(team_stats, "home", base_home, base_away)
            return _venue_rates(team_stats, "away", base_away, base_home)

        home_dom = domestic_leagues[home_name]
        away_dom = domestic_leagues[away_name]
        home_da, home_dd, home_dn = rates_for(
            home_name, "home", home_dom,
            domestic_cache.get(home_dom, ({}, {}))[0],
            domestic_cache.get(home_dom, ({}, {}))[1],
        )
        away_da, away_dd, away_dn = rates_for(
            away_name, "away", away_dom,
            domestic_cache.get(away_dom, ({}, {}))[0],
            domestic_cache.get(away_dom, ({}, {}))[1],
        )
        home_ua, home_ud, home_un = rates_for(
            home_name, "home", "Champions League", ucl_stats, ucl_leagues
        )
        away_ua, away_ud, away_un = rates_for(
            away_name, "away", "Champions League", ucl_stats, ucl_leagues
        )

        home_ucl_weight = _ucl_blend_weight(home_un)
        away_ucl_weight = _ucl_blend_weight(away_un)
        ha = _blend(home_da, home_ua, home_ucl_weight)
        hd = _blend(home_dd, home_ud, home_ucl_weight)
        aa = _blend(away_da, away_ua, away_ucl_weight)
        ad = _blend(away_dd, away_ud, away_ucl_weight)

        home_n = round(home_dn + home_un, 3)
        away_n = round(away_dn + away_un, 3)
        complete = home_dn >= 2.0 and away_dn >= 2.0 and home_un >= 1.0 and away_un >= 1.0
        competition_form = {
            "mode": "domestic_plus_champions_league",
            "status": "COMPLETE" if complete else "PARTIAL_HISTORY",
            "release_eligible": bool(complete),
            "ucl_weight_cap": 0.30,
            "home": {
                "domestic_competition": home_dom,
                "domestic_venue_sample": home_dn,
                "champions_league_venue_sample": home_un,
                "champions_league_blend_weight": round(home_ucl_weight, 4),
                "domestic_attack": round(home_da, 4),
                "champions_league_attack": round(home_ua, 4),
                "combined_attack": round(ha, 4),
                "domestic_defence": round(home_dd, 4),
                "champions_league_defence": round(home_ud, 4),
                "combined_defence": round(hd, 4),
            },
            "away": {
                "domestic_competition": away_dom,
                "domestic_venue_sample": away_dn,
                "champions_league_venue_sample": away_un,
                "champions_league_blend_weight": round(away_ucl_weight, 4),
                "domestic_attack": round(away_da, 4),
                "champions_league_attack": round(away_ua, 4),
                "combined_attack": round(aa, 4),
                "domestic_defence": round(away_dd, 4),
                "champions_league_defence": round(away_ud, 4),
                "combined_defence": round(ad, 4),
            },
            "policy": "Domestic competition form is the anchor; UCL form is normalized to the UCL scoring baseline and blended by recency-weighted same-venue sample, capped at 30%.",
        }
        home_base, away_base = ucl_home_base, ucl_away_base
        effective_n = min(home_n, away_n)
        method = "domestic + Champions League form, competition-normalized venue strength + Poisson/Dixon-Coles"
    else:
        competition_filter = target_competition if target_competition in DOMESTIC_COMPETITIONS else None
        stats, leagues = _team_stats(history, cutoff_dt, competition_filter)
        home_base, away_base = _league_baseline(leagues, target_competition)
        home_team = stats.get(_team_key(home_name), _empty_team())
        away_team = stats.get(_team_key(away_name), _empty_team())
        ha, hd, hn = _venue_rates(home_team, "home", home_base, away_base)
        aa, ad, an = _venue_rates(away_team, "away", away_base, home_base)
        home_n, away_n = hn, an
        effective_n = min(hn, an)
        method = "competition-specific venue-aware recency-weighted team strength + Poisson/Dixon-Coles"
        competition_form = {
            "mode": "single_competition",
            "status": "COMPLETE" if hn >= 2.0 and an >= 2.0 else "PARTIAL_HISTORY",
            "release_eligible": bool(hn >= 2.0 and an >= 2.0),
            "competition": target_competition,
            "home_venue_sample": hn,
            "away_venue_sample": an,
        }

    home_xg = max(0.20, min(4.8, home_base * ha * ad))
    away_xg = max(0.20, min(4.8, away_base * aa * hd))
    rho = -0.08 * min(1.0, effective_n / 8.0)
    probs = _outcome_probs(home_xg, away_xg, rho=rho)

    return {
        "p1": round(probs[0], 6),
        "draw": round(probs[1], 6),
        "p2": round(probs[2], 6),
        "xg_home": round(home_xg, 4),
        "xg_away": round(away_xg, 4),
        "sample_home": round(home_n, 3),
        "sample_away": round(away_n, 3),
        "effective_sample": round(effective_n, 3),
        "home_attack": round(ha, 4),
        "home_defence": round(hd, 4),
        "away_attack": round(aa, 4),
        "away_defence": round(ad, 4),
        "league_home_xg": round(home_base, 4),
        "league_away_xg": round(away_base, 4),
        "dixon_coles_rho": round(rho, 5),
        "competition_form": competition_form,
        "competition_form_status": competition_form["status"],
        "method": method,
    }


