#!/usr/bin/env python3
"""Offline checks for ESPN history ranges and NBA season isolation."""
from datetime import datetime, timedelta, timezone
import expansion_pipeline as p

UTC=timezone.utc
def event(event_id,stamp,home="Home Team",away="Away Team"):
    return {"id":event_id,"date":stamp.isoformat(),
      "status":{"type":{"completed":True}},
      "competitions":[{"competitors":[
        {"homeAway":"home","team":{"id":"H","displayName":home},"score":"112"},
        {"homeAway":"away","team":{"id":"A","displayName":away},"score":"104"}
      ]}]}

def test_history_windows_and_preseason_exclusion():
    old_now,old_evs=p.NOW,p.evs
    now=datetime(2026,10,11,9,tzinfo=UTC)
    p.NOW=now
    preseason=datetime(2025,10,19,23,tzinfo=UTC)
    opener=datetime(2025,10,21,23,tzinfo=UTC)
    regular=datetime(2026,2,1,1,tzinfo=UTC)
    records=[event("preseason-2025",preseason),event("opener-2025",opener),event("regular-2026",regular)]
    calls=[]
    def fake_evs(slug,start,end):
        calls.append((slug,start,end))
        return [x for x in records if start.date() <= datetime.fromisoformat(x["date"].replace("Z","+00:00")).date() <= end.date()]
    p.evs=fake_evs
    try:
        rows,errors=p.collect_espn("basketball/nba")
        assert rows and {r["event_id"] for r in rows}=={"opener-2025","regular-2026"},[r["event_id"] for r in rows]
        assert not errors,errors
        assert len(calls)>=50,len(calls)
        assert all((end.date()-start.date()).days<=6 for _,start,end in calls),calls
        assert all(r.get("source")=="ESPN" for r in rows)
        assert not p.is_nba_regular_season_date("2026-10-19T23:00:00Z")
        assert p.is_nba_regular_season_date("2026-10-20T23:00:00Z")
    finally:
        p.NOW,p.evs=old_now,old_evs

def test_regular_season_fixture_gate():
    old_now,old_evs=p.NOW,p.evs
    preseason=event("preseason",datetime(2026,10,18,23,tzinfo=UTC))
    regular=event("opening-night",datetime(2026,10,21,0,tzinfo=UTC))
    calls=[]
    def fake_evs(slug,start,end):
        calls.append((slug,start,end))
        return [preseason,regular]
    try:
        p.NOW=datetime(2026,10,19,12,tzinfo=UTC)
        p.evs=fake_evs
        assert p.current("NBA")==[]
        assert calls==[]
        p.NOW=datetime(2026,10,20,1,tzinfo=UTC)
        rows=p.current("NBA")
        assert [r["event_id"] for r in rows]==["opening-night"],rows
        assert calls and calls[0][1]>=p.NBA_START
        assert (calls[0][2].date()-calls[0][1].date()).days<=6
    finally:
        p.NOW,p.evs=old_now,old_evs

def test_primary_and_fallback_errors_are_retained():
    old_collect,old_fallback=p.collect_espn,p.nba_fallback
    p.collect_espn=lambda slug:([],["ESPN scoreboard failed"])
    p.nba_fallback=lambda:([{"event_id":"fallback"}],["parquet unavailable"])
    try:
        rows,errors=p.collect("NBA")
        assert rows==[{"event_id":"fallback"}]
        assert errors==["ESPN scoreboard failed","parquet unavailable"],errors
    finally:
        p.collect_espn,p.nba_fallback=old_collect,old_fallback

if __name__=="__main__":
    test_history_windows_and_preseason_exclusion()
    test_regular_season_fixture_gate()
    test_primary_and_fallback_errors_are_retained()
    print("NBA source regression tests: PASS (3 groups)")
