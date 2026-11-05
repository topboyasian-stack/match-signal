"""Shared time checks for frozen pre-kickoff SportyBet snapshots."""
from datetime import datetime, timezone


MAX_PREGAME_QUOTE_AGE_SECONDS = 15 * 60


def parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def pregame_snapshot_age_seconds(snapshot_at, start_time):
    """Return seconds from quote to kickoff, or None for invalid timestamps."""
    quote_at = parse_utc(snapshot_at)
    start_at = parse_utc(start_time)
    if quote_at is None or start_at is None:
        return None
    return (start_at - quote_at).total_seconds()


def is_fresh_pregame_snapshot(snapshot_at, start_time, max_age_seconds=MAX_PREGAME_QUOTE_AGE_SECONDS):
    """Accept only quotes captured 0..15 minutes before the scheduled start."""
    age = pregame_snapshot_age_seconds(snapshot_at, start_time)
    return age is not None and 0 <= age <= int(max_age_seconds)
