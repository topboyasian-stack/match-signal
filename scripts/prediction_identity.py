"""Canonical, provider-scoped identity helpers for Match Signal prediction history.

The primary prediction history is sourced from ESPN. Within that ledger, a
fixture is identified by sport + competition label + ESPN event ID; event IDs
alone are not globally unique across competitions or sports.
"""
from __future__ import annotations

import re
import unicodedata


def prediction_identity_key(row):
    """Return a stable sport/competition/event key, or None if incomplete."""
    if not isinstance(row, dict):
        return None
    sport = " ".join(str(row.get("sport") or "").strip().casefold().split())
    league = " ".join(str(row.get("league") or "").strip().casefold().split())
    event_id = str(row.get("event_id") or "").strip()
    if not sport or not league or not event_id:
        return None
    return f"{sport}:{league}:{event_id}"


def participant_key(value):
    """Conservatively normalize a football club label for result identity checks."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = text.replace("&", " and ")
    tokens = re.sub(r"[^a-z0-9]+", " ", text).split()
    stopwords = {"fc", "afc", "sc", "cf", "ac", "club", "the"}
    return " ".join(token for token in tokens if token not in stopwords)


def football_result_participants_match(prediction, event):
    """Require the ESPN result home/away clubs to match the saved prediction order.

    Uncertain identity is intentionally unresolved rather than scoring a forecast
    against a different fixture that happened to share a provider event ID.
    """
    if not isinstance(prediction, dict) or not isinstance(event, dict):
        return False
    competitors = event.get("competitors")
    if not isinstance(competitors, list):
        return False
    home = next((row for row in competitors if isinstance(row, dict) and row.get("homeAway") == "home"), None)
    away = next((row for row in competitors if isinstance(row, dict) and row.get("homeAway") == "away"), None)
    if not home or not away:
        return False

    def name(row):
        return str(((row.get("team") or {}).get("displayName")) or row.get("displayName") or "").strip()

    predicted_home = participant_key(prediction.get("player_1"))
    predicted_away = participant_key(prediction.get("player_2"))
    actual_home = participant_key(name(home))
    actual_away = participant_key(name(away))
    return bool(predicted_home and predicted_away and predicted_home != predicted_away and predicted_home == actual_home and predicted_away == actual_away)


def append_new_predictions(history, predictions):
    """Append only new canonical fixtures, retaining all existing settled history."""
    if not isinstance(history, list):
        raise TypeError("prediction history must be a list")
    existing = {key for row in history if (key := prediction_identity_key(row))}
    appended = 0
    for prediction in predictions if isinstance(predictions, list) else []:
        key = prediction_identity_key(prediction)
        if not key or key in existing:
            continue
        history.append(prediction.copy())
        existing.add(key)
        appended += 1
    return appended
