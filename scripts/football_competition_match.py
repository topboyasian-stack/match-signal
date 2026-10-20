"""Strict, shared identity checks before a football market can be attached.

Team-name similarity alone is not sufficient: senior and youth competitions can
contain identically named teams, and kickoff/competition agreement alone can
still attach one of several fixtures with the wrong opponent. This module keeps
the competition, cohort, age group, and both participant identities aligned.
"""
import re
import unicodedata
from difflib import SequenceMatcher

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
    r"\b(?:u[\s._-]?(1[5-9]|2[0-3])|under[\s._-]?(1[5-9]|2[0-3]))\b",
    re.IGNORECASE,
)
_YOUTH_MARKER_RE = re.compile(
    r"\b(?:youth|junior|academy|reserves?|development league|boys|girls)\b",
    re.IGNORECASE,
)
_TEAM_STOPWORDS = {"fc", "afc", "sc", "cf", "ac", "club", "the"}
_IDENTITY_METADATA_KEYS = {
    "league", "leaguename", "league_name",
    "competition", "competitionname", "competition_name", "competitiondisplayname",
    "tournament", "tournamentname", "tournament_name",
    "category", "categoryname", "category_name",
    "agegroup", "age_group", "agecategory", "age_category", "gender",
    "stage", "stagename", "phase", "phasename", "round", "roundname",
    "eventname", "event_name",
}
_IDENTITY_CONTAINER_KEYS = {
    "competitions", "tournaments", "categoryinfo", "leagueinfo",
    "competitioninfo", "tournamentinfo", "groups", "eventdetails", "metadata",
}
_IDENTITY_NAME_KEYS = {"name", "shortname", "displayname", "fullname", "slug", "label", "agegroup", "gender"}


def football_market_identity_metadata(event, tournament=None, category=None):
    """Extract event-specific league/cohort labels that a parent tournament can hide."""
    values = []

    def add(value):
        if value is None or isinstance(value, (dict, list, tuple, set, bool)):
            return
        value = str(value).strip()
        if value and value not in values:
            values.append(value)

    def visit(node, depth=0, identity_container=False):
        if depth > 5:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
                if normalized in _IDENTITY_METADATA_KEYS:
                    if isinstance(value, (dict, list)):
                        visit(value, depth + 1, True)
                    else:
                        add(value)
                elif normalized in _IDENTITY_CONTAINER_KEYS and isinstance(value, (dict, list)):
                    visit(value, depth + 1, True)
                elif identity_container and normalized in _IDENTITY_NAME_KEYS:
                    if isinstance(value, (dict, list)):
                        visit(value, depth + 1, True)
                    else:
                        add(value)
        elif isinstance(node, (list, tuple)):
            for value in node[:50]:
                visit(value, depth + 1, identity_container)

    add(tournament)
    add(category)
    visit(event)
    return " | ".join(values)


def competition_key(value):
    """Return a conservative normalized competition name, or an empty string."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    tokens = text.split()
    if tokens and tokens[0] == "uefa":
        tokens = tokens[1:]
    # Providers sometimes append a season or "league phase" to tournament names.
    while tokens and re.fullmatch(r"20\d{2}", tokens[-1]):
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


def _cohort_profile(competition, category=None, teams=(), metadata=None):
    """Extract explicit youth/age-group identity from all preserved provider metadata."""
    texts = [competition, category, metadata, *(teams or ())]
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


def _team_key(value):
    """Normalize participant labels while preserving meaningful team-name tokens."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(token for token in text.split() if token not in _TEAM_STOPWORDS)


def _team_similarity(left, right):
    """Conservative fuzzy score; missing participant names never match."""
    a = _team_key(left)
    b = _team_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    at = set(a.split())
    bt = set(b.split())
    overlap = len(at & bt) / max(1, len(at | bt))
    return max(ratio, 0.75 * overlap + 0.25 * ratio)


def _participants_match(prediction_teams, market_teams, minimum_similarity=0.78):
    """Require both clubs to match; one exact club cannot compensate for a wrong rival."""
    if len(prediction_teams or ()) != 2 or len(market_teams or ()) != 2:
        return False
    p1, p2 = prediction_teams
    m1, m2 = market_teams
    direct = (
        _team_similarity(p1, m1) >= minimum_similarity
        and _team_similarity(p2, m2) >= minimum_similarity
    )
    reverse = (
        _team_similarity(p1, m2) >= minimum_similarity
        and _team_similarity(p2, m1) >= minimum_similarity
    )
    return direct or reverse


def football_market_identity_matches(
    prediction_competition,
    market_competition,
    market_category=None,
    prediction_teams=(),
    market_teams=(),
    market_metadata=None,
):
    """Fail closed unless competition, cohort, age group, and both teams agree.

    Provider category and both participants are checked independently because
    some feeds reuse senior tournament labels for youth fixtures. Both team names
    must match in one orientation; a high score for only one team is not enough.
    Unknown competition, cohort conflict, missing teams, or uncertain team identity
    means no bookmaker quote is attached.
    """
    if not same_competition(prediction_competition, market_competition):
        return False

    prediction_youth, prediction_ages = _cohort_profile(
        prediction_competition, teams=prediction_teams
    )
    market_youth, market_ages = _cohort_profile(
        market_competition,
        category=market_category,
        teams=market_teams,
        metadata=market_metadata,
    )

    if prediction_youth != market_youth:
        return False
    # If either side provides an age group, require both sides to provide the
    # same explicit group; generic "Youth" alone cannot distinguish U17 from U19.
    if prediction_ages != market_ages:
        return False

    if not _participants_match(prediction_teams, market_teams):
        return False
    return True
