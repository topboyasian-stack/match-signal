"""Regression tests for the NBA market-225 capture freshness watchdog."""

from datetime import datetime, timezone

from nba_totals_capture_watchdog import capture_age_minutes, should_dispatch_capture


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run():
    now = dt("2026-11-02T08:25:00Z")
    assert round(capture_age_minutes("2026-11-02T08:16:39Z", now), 2) == 8.35
    assert not should_dispatch_capture("2026-11-02T08:16:39Z", now, 0), (
        "A capture under 10 minutes old must not be duplicated."
    )
    assert should_dispatch_capture("2026-11-02T08:14:59Z", now, 0, max_age_minutes=10), (
        "A capture at least 15 minutes old must trigger a recovery capture."
    )
    assert not should_dispatch_capture("2026-11-02T08:00:00Z", now, 1), (
        "An already queued/running capture must suppress a duplicate dispatch."
    )
    assert should_dispatch_capture(None, now, 0), "Missing status must fail safe to capture."
    assert should_dispatch_capture("not-a-time", now, 0), "Invalid timestamps must fail safe."
    assert not should_dispatch_capture("2026-11-02T08:26:00Z", now, 0), (
        "Small future clock skew should not trigger duplicate capture."
    )
    assert should_dispatch_capture("2026-11-02T08:29:00Z", now, 0), (
        "A timestamp more than two minutes in the future must fail safe."
    )
    print("PASS: stale/missing capture recovery, freshness boundary, active-run suppression, and clock-skew cases.")


if __name__ == "__main__":
    run()
