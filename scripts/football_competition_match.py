"""Strict, shared competition identity checks for football market attachment.

Team-name similarity alone is not sufficient: senior and youth competitions can
contain identically named teams. A match must agree on competition, cohort, and
any explicit age-group marker before a bookmaker quote can be attached.
"""
import re
import unicodedata

_ALIASES = {
    "epl": "premier league",
    "english premier league": "premier league",
    "england premier league": "premier league",
    "la liga santander": "la liga",
    "laliga": "la liga",
    "german bundesliga": "bundesliga",
    "italy serie a": "serie a",
    "italian serie a": "serie a",
    "france ligue 1": "ligue 1",
    "french ligue 1": "ligue 1",
    "portugal primeira liga": "primeira liga",
}

_AGE_GROUP_RE = re.compile(
    r"\\b(?:u[\\s._-]?(1[5-9]|2[0-3])|under[\\s._-]?(1[5-9]|2[0-3]))\\b",
    re.IGNORECASE,
)
_YOUTH_MARKER_RE = re.compile(
    r"\\b(?:youth|junior|academy|reserves?|development league|boys|girls)\\b",
    re.IGNORECASE,
)


def competition_key(value):
    """Return a conservative normalized competition name, or an empty string."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    tokens = text.split()
    if tokens and tokens[0] == "uefa":
        tokens = tokens[1:]
    # Providers sometimes append a season or "league phase" to tournament names.
    while tokens and re.fullmatch(r"20\\d{2}", tokens[-1]):
        tokens.pop()
    if len(tokens) >= 2 and tokens[-2:] == ["league", "phase"]:
        tokens = tokens[:-2]
    text = " ".join(tokens).strip()
    return _ALIASES.get(text, text)


def same_competition(prediction_competition, market_competition):
    """True only when both feeds explicitly identify the same competition."""
    left = competition_key(prediction_competition)
    right = competition_key(market_competition)
    return bool(left and right and left == right)


def _cohort_profile(competition, category=None, teams=()):
    """Extract explicit youth/age-group identity from provider metadata and teams."""
    texts = [competition, category, *(teams or ())]
    ages = set()
    youth = False
    for value in texts:
        text = str(value or "")
        if _YOUTH_MARKER_RE.search(text):
            youth = True
        for match in _AGE_GROUP_RE.finditer(text):
            youth = True
            ages.add(match.group(1) or match.group(2))
    return youth, frozenset(ages)


def football_market_identity_matches(
    prediction_competition,
    market_competition,
    market_category=None,
    prediction_teams=(),
    market_teams=(),
):
    """Reject same-named senior/youth fixtures and conflicting age-group labels.

    Competition equality is still mandatory. The provider category and both
    teams are checked independently because some feeds reuse senior tournament
    labels for youth fixtures or omit the age marker from one team name.
    Unknown or conflicting cohorts fail closed; no quote is attached by names
    and kickoff alone.
    """
    if not same_competition(prediction_competition, market_competition):
        return False

    prediction_youth, prediction_ages = _cohort_profile(
        prediction_competition, teams=prediction_teams
    )
    market_youth, market_ages = _cohort_profile(
        market_competition, category=market_category, teams=market_teams
    )

    if prediction_youth != market_youth:
        return False
    # If either side provides an age group, require both sides to provide the
    # same explicit age group; generic "Youth" is not enough to identify U17 vs U19.
    if prediction_ages != market_ages:
        return False
    return True
