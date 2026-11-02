"""Regression tests for the NBA market-225 capture freshness watchdog."""

from datetime import datetime, timezone

from nba_totals_capture_watchdog import (
    capture_age_minutes, should_dispatch_capture,
    stale_upcoming_prediction_count, should_dispatch_model_refresh,
)


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

    model_now = dt("2026-11-02T13:55:00Z")
    fresh_upcoming = [{
        "event_id": "fresh-1", "start_time": "2026-11-02T20:00:00Z",
        "generated_at": "2026-11-02T10:00:00Z"
    }]
    stale_upcoming = [{
        "event_id": "stale-1", "start_time": "2026-11-02T20:00:00Z",
        "generated_at": "2026-11-02T06:00:00Z"
    }]
    already_started = [{
        "event_id": "started-1", "start_time": "2026-11-02T12:00:00Z",
        "generated_at": "2026-11-02T04:00:00Z"
    }]
    assert stale_upcoming_prediction_count(fresh_upcoming, model_now) == 0
    assert stale_upcoming_prediction_count(stale_upcoming, model_now) == 1
    assert stale_upcoming_prediction_count(already_started, model_now) == 0, (
        "Started fixtures must retain their frozen pre-game snapshot and must not trigger a refresh."
    )
    assert should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T12:00:00Z", model_now, active_model_runs=0
    ), "A stale pre-game forecast with an old model status must trigger recovery."
    assert not should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T13:40:00Z", model_now, active_model_runs=0
    ), "A recent model refresh must suppress immediate retry loops."
    assert not should_dispatch_model_refresh(
        stale_upcoming, "2026-11-02T12:00:00Z", model_now, active_model_runs=1
    ), "An active model run must suppress duplicate recovery dispatches."
    assert not should_dispatch_model_refresh(
        fresh_upcoming, "2026-11-02T06:00:00Z", model_now, active_model_runs=0
    ), "Fresh predictions must not be rebuilt just because the status file is old."
    assert should_dispatch_model_refresh(None, None, model_now, active_model_runs=0), (
        "Missing prediction content and model status must fail safe to recovery."
    )

    print("PASS: stale/missing capture and NBA model recovery, freshness boundary, active-run suppression, and clock-skew cases.")


if __name__ == "__main__":
    run()
