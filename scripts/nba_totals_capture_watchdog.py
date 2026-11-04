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



def should_dispatch_research_refresh(
    report_generated_at,
    now,
    active_research_runs=0,
    max_age_minutes=20,
):
    """Recover a missed/stuck scheduled research refresh without duplicate runs."""
    try:
        active = int(active_research_runs)
    except (TypeError, ValueError):
        active = 1
    if active > 0:
        return False

    age = capture_age_minutes(report_generated_at, now)
    if age is None:
        return True
    if age < -2:
        return False
    return age >= float(max_age_minutes)


def stale_upcoming_prediction_count(predictions, now, max_age_hours=6):
    """Count upcoming NBA rows the client must withhold as stale pre-game baselines.

    Started games are deliberately excluded: their frozen pre-game record must not
    be rewritten. Unknown/missing file content returns None so the caller fails safe.
    """
    current = _utc(now)
    if current is None or not isinstance(predictions, list):
        return None
    stale = 0
    max_age = float(max_age_hours) * 60 * 60
    from datetime import timedelta

    for row in predictions:
        if not isinstance(row, dict):
            continue
        start = _utc(row.get("start_time"))
        if start is None or start <= current:
            continue
        stamp = _utc(
            row.get("generated_at")
            or row.get("prediction_created_at")
            or row.get("published_at")
        )
        if (
            stamp is None
            or stamp > current + timedelta(minutes=2)
            or stamp >= start
            or (current - stamp).total_seconds() > max_age
        ):
            stale += 1
    return stale


def should_dispatch_model_refresh(
    predictions,
    last_model_refresh_at,
    now,
    active_model_runs=0,
    max_age_hours=6,
    min_retry_minutes=30,
):
    """Recover a stale model schedule without duplicate runs or immediate retry loops."""
    stale_count = stale_upcoming_prediction_count(predictions, now, max_age_hours=max_age_hours)
    stale = stale_count is None or stale_count > 0

    try:
        active = int(active_model_runs)
    except (TypeError, ValueError):
        active = 1
    if active > 0 or not stale:
        return False

    age = capture_age_minutes(last_model_refresh_at, now)
    # Missing/invalid model-refresh status fails safe to recovery. A recent/future
    # status indicates a just-completed attempt; cool down before trying again.
    if age is None:
        return True
    if age < -2:
        return False
    return age >= float(min_retry_minutes)
