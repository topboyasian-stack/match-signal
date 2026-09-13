import math
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


def _team_stats(history, cutoff):
    """Build leakage-safe, recency-weighted team and league statistics.

    Improvements over the original V4 model:
    - deduplicates historical events before weighting;
    - keeps home/away splits instead of treating all venues identically;
    - estimates league-specific home and away scoring baselines;
    - applies exponential recency weighting over 365 days;
    - shrinks small samples toward the league baseline.
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
        event_dt = _parse_dt(row.get("calculated_at") or row.get("start_time"))
        if not event_dt or event_dt >= cutoff_dt:
            continue
        if (cutoff_dt - event_dt).total_seconds() > 365 * 86400:
            continue
        home = row.get("player_1")
        away = row.get("player_2")
        if not home or not away:
            continue
        event_key = str(row.get("event_id") or "")
        if not event_key:
            event_key = f"{row.get('league')}|{home}|{away}|{event_dt.isoformat()}"
        if event_key in seen:
            continue
        seen.add(event_key)
        try:
            hg, ag = map(float, row["final_score"][:2])
        except (TypeError, ValueError):
            continue
        rows.append((event_dt, row.get("league") or "global", home, away, hg, ag))

    for event_dt, lg, home, away, hg, ag in rows:
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

        ls = league[lg]
        ls["home_gf"] += weight * hg
        ls["home_ga"] += weight * ag
        ls["away_gf"] += weight * ag
        ls["away_ga"] += weight * hg
        ls["n"] += weight

    return stats, league


def _league_baseline(league_stats, league):
    s = league_stats.get(league)
    if not s or not s["n"]:
        return 1.45, 1.15
    home_attack = max(0.65, min(2.8, s["home_gf"] / s["n"]))
    away_attack = max(0.55, min(2.5, s["away_gf"] / s["n"]))
    return home_attack, away_attack


def _venue_rates(team, side, base_for, base_against):
    """Return attack/defence multipliers plus effective sample size."""
    overall_n = team.get("n", 0.0)
    if side == "home":
        gf, ga, n = team.get("home_gf", 0.0), team.get("home_ga", 0.0), team.get("home_n", 0.0)
    else:
        gf, ga, n = team.get("away_gf", 0.0), team.get("away_ga", 0.0), team.get("away_n", 0.0)

    # Venue split is informative but can be sparse. Blend it toward overall
    # team rates as the venue sample grows rather than switching abruptly.
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
    attack = (venue_weight * venue_attack + (1.0 - venue_weight) * overall_attack)
    defence = (venue_weight * venue_defence + (1.0 - venue_weight) * overall_defence)
    attack = sample_weight * attack + (1.0 - sample_weight)
    defence = sample_weight * defence + (1.0 - sample_weight)
    return _clamp(attack, 0.55, 1.65), _clamp(defence, 0.55, 1.65), round(n, 3)


def independent_prediction(event, league, history, cutoff=None):
    """Independent football model: venue-aware team strength + Poisson/Dixon-Coles.

    This model deliberately does not consume bookmaker probabilities. Market
    probabilities are handled later as a benchmark/value layer.
    """
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    home_name = (home.get("team") or {}).get("displayName") or "Home"
    away_name = (away.get("team") or {}).get("displayName") or "Away"

    stats, leagues = _team_stats(history, cutoff)
    home_base, away_base = _league_baseline(leagues, league)

    home_team = stats.get(home_name, _empty_team())
    away_team = stats.get(away_name, _empty_team())
    ha, hd, hn = _venue_rates(home_team, "home", home_base, away_base)
    aa, ad, an = _venue_rates(away_team, "away", away_base, home_base)

    # Home/away league baselines plus team attack/defence multipliers.
    home_xg = home_base * ha * ad
    away_xg = away_base * aa * hd

    # Conservative bounds prevent sparse samples from producing extreme prices.
    home_xg = max(0.20, min(4.8, home_xg))
    away_xg = max(0.20, min(4.8, away_xg))

    # Stronger samples justify the DC correction more; sparse matches remain
    # closer to plain Poisson to avoid overfitting the low-score adjustment.
    effective_n = min(hn, an)
    rho = -0.08 * min(1.0, effective_n / 8.0)
    probs = _outcome_probs(home_xg, away_xg, rho=rho)

    return {
        "p1": round(probs[0], 6),
        "draw": round(probs[1], 6),
        "p2": round(probs[2], 6),
        "xg_home": round(home_xg, 4),
        "xg_away": round(away_xg, 4),
        "sample_home": hn,
        "sample_away": an,
        "effective_sample": round(effective_n, 3),
        "home_attack": round(ha, 4),
        "home_defence": round(hd, 4),
        "away_attack": round(aa, 4),
        "away_defence": round(ad, 4),
        "league_home_xg": round(home_base, 4),
        "league_away_xg": round(away_base, 4),
        "dixon_coles_rho": round(rho, 5),
        "method": "independent venue-aware recency-weighted team-strength + Poisson/Dixon-Coles",
    }
