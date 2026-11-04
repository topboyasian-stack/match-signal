"""Refresh-gate policy for the NBA totals probability/value report."""

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



def latest_snapshot_evidence_time(snapshots, model_version):
    """Return the newest publication or quote timestamp for this frozen model.

    A new immutable quote revision keeps its original prediction publication time.
    Considering only published_at therefore hides newer market observations from the
    CLV report refresh gate. Quote timestamps are evidence timestamps too, but they
    never create additional bets or independent fixtures.
    """
    if not isinstance(snapshots, list):
        return None
    candidates = []
    for row in snapshots:
        if not isinstance(row, dict) or row.get("totals_model_version") != model_version:
            continue
        for field in ("published_at", "quote_timestamp"):
            stamp = _utc(row.get(field))
            if stamp is not None:
                candidates.append(stamp)
    return max(candidates, default=None)


def should_refresh_report(event_name, report_time, newest_data_time, now, min_age_minutes=10):
    """Refresh immediately on new evidence events; throttle only periodic schedules.

    A workflow_run event is emitted after capture/settlement has published evidence.
    If that evidence is newer than the report, delaying it because the report itself
    is less than ten minutes old can leave the only event-driven refresh path stale.
    Concurrency serializes duplicate events; a second run sees the first run's report
    and skips because it is no longer stale.
    """
    if event_name not in {"workflow_run", "schedule"}:
        return True

    report_at = _utc(report_time)
    newest_at = _utc(newest_data_time)
    now_at = _utc(now)
    if now_at is None:
        now_at = datetime.now(timezone.utc)

    stale = report_at is None or (newest_at is not None and newest_at > report_at)
    if not stale:
        return False
    if report_at is None:
        return True
    if event_name == "workflow_run":
        return True

    age_minutes = (now_at - report_at).total_seconds() / 60
    return age_minutes >= float(min_age_minutes)
