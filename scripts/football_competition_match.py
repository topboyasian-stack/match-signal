"""Strict, shared competition identity checks for football market attachment.

Team-name similarity alone is not sufficient: senior and youth competitions can
contain identically named teams. This module intentionally fails closed whenever
the competition label is absent or does not match.
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
