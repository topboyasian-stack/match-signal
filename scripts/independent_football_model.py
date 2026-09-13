import math
from collections import defaultdict
from datetime import datetime, timezone


def _clamp(x, lo=0.02, hi=0.96):
    return max(lo, min(hi, float(x)))


def _normalise(values):
    total = sum(max(1e-9, float(v)) for v in values)
    return [max(1e-9, float(v)) / total for v in values]


def _poisson(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def _outcome_probs(lam_home, lam_away, max_goals=10):
    hp = [_poisson(k, lam_home) for k in range(max_goals + 1)]
    ap = [_poisson(k, lam_away) for k in range(max_goals + 1)]
    out = [0.0, 0.0, 0.0]
    for i, h in enumerate(hp):
        for j, a in enumerate(ap):
            if i > j:
                out[0] += h * a
            elif i == j:
                out[1] += h * a
            else:
                out[2] += h * a
    return _normalise(out)


def _parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _team_stats(history, cutoff):
    """Build recency-weighted team scoring/conceding rates from prior settled matches.

    Only completed results before the prediction cutoff are eligible. A 120-day
    exponential half-life gives current-season form more influence while retaining
    enough prior-season data for teams with small early-season samples.
    """
    stats = defaultdict(lambda: {"gf": 0.0, "ga": 0.0, "n": 0.0})
    league = defaultdict(lambda: {"gf": 0.0, "ga": 0.0, "n": 0.0})
    cutoff_dt = _parse_dt(cutoff) or datetime.now(timezone.utc)

    for row in history or []:
        if not row.get("settled") or not row.get("final_score"):
            continue
        if row.get("sport") != "football":
            continue
        event_dt = _parse_dt(row.get("calculated_at") or row.get("start_time"))
        if not event_dt or event_dt >= cutoff_dt:
            continue
        age_days = max(0.0, (cutoff_dt - event_dt).total_seconds() / 86400.0)
        if age_days > 365:
            continue
        # Exponential decay with a 120-day half-life.
        weight = math.exp(-math.log(2.0) * age_days / 120.0)
        try:
            hg, ag = map(float, row["final_score"][:2])
        except (TypeError, ValueError):
            continue
        home = row.get("player_1")
        away = row.get("player_2")
        if not home or not away:
            continue
        stats[home]["gf"] += weight * hg
        stats[home]["ga"] += weight * ag
        stats[home]["n"] += weight
        stats[away]["gf"] += weight * ag
        stats[away]["ga"] += weight * hg
        stats[away]["n"] += weight
        lg = row.get("league") or "global"
        league[lg]["gf"] += weight * (hg + ag)
        league[lg]["ga"] += weight * (hg + ag)
        league[lg]["n"] += weight * 2.0
    return stats, league


def _league_avg(league_stats, league):
    s = league_stats.get(league)
    if s and s["n"]:
        return max(0.75, min(3.8, s["gf"] / s["n"]))
    return 1.35


def independent_prediction(event, league, history, cutoff=None):
    """Independent football model: recency-weighted team rates + home advantage + Poisson."""
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    home_name = (home.get("team") or {}).get("displayName") or "Home"
    away_name = (away.get("team") or {}).get("displayName") or "Away"
    stats, leagues = _team_stats(history, cutoff)
    avg = _league_avg(leagues, league)

    def rates(name):
        s = stats.get(name)
        if not s or s["n"] < 2:
            return 1.0, 1.0, 0
        n = s["n"]
        shrink = n / (n + 8.0)
        attack = shrink * ((s["gf"] / n) / avg) + (1 - shrink)
        defence = shrink * ((s["ga"] / n) / avg) + (1 - shrink)
        return attack, defence, round(n, 3)

    ha, hd, hn = rates(home_name)
    aa, ad, an = rates(away_name)
    home_xg = avg * ha * ad * 1.08
    away_xg = avg * aa * hd * 0.94
    home_xg = max(0.20, min(4.8, home_xg))
    away_xg = max(0.20, min(4.8, away_xg))
    probs = _outcome_probs(home_xg, away_xg)
    return {
        "p1": round(probs[0], 6), "draw": round(probs[1], 6), "p2": round(probs[2], 6),
        "xg_home": round(home_xg, 4), "xg_away": round(away_xg, 4),
        "sample_home": hn, "sample_away": an,
        "method": "independent recency-weighted team-strength + Poisson"
    }
