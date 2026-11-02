"""Freshness guard for the NBA SportyBet market-225 capture watchdog."""

from datetime import datetime, timezone


def _utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def capture_age_minutes(checked_at, now):
    checked = _utc(checked_at)
    current = _utc(now)
    if checked is None or current is None:
        return None
    return (current - checked).total_seconds() / 60


def should_dispatch_capture(checked_at, now, active_capture_runs=0, max_age_minutes=10):
    """Dispatch only when capture evidence is stale and no capture is already active."""
    age = capture_age_minutes(checked_at, now)
    if age is None or age < -2:
        stale = True
    else:
        stale = age >= float(max_age_minutes)
    try:
        active = int(active_capture_runs)
    except (TypeError, ValueError):
        active = 1
    return stale and active <= 0
