#!/usr/bin/env python3
"""Offline checks for NBA history sources, dated gamelog mapping and season isolation."""
from datetime import datetime, timezone
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
    p.NOW=datetime(2026,10,11,9,tzinfo=UTC)
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

def test_daily_scoreboard_uses_single_dates():
    old_get=p.get
    calls=[]
    def fake_get(url,params=None):
        calls.append(params["dates"])
        return {"events":[event("same-event",datetime(2026,10,21,tzinfo=UTC))]} if params["dates"]=="20261021" else {"events":[]}
    p.get=fake_get
    try:
        rows=p.evs_daily("basketball/nba",datetime(2026,10,20,tzinfo=UTC),datetime(2026,10,22,tzinfo=UTC))
        assert calls==["20261020","20261021","20261022"],calls
        assert len(rows)==1 and rows[0]["id"]=="same-event",rows
    finally:
        p.get=old_get

def test_regular_season_fixture_gate():
    old_now,old_daily=p.NOW,p.evs_daily
    preseason=event("preseason",datetime(2026,10,18,23,tzinfo=UTC))
    regular=event("opening-night",datetime(2026,10,21,0,tzinfo=UTC))
    calls=[]
    def fake_daily(slug,start,end):
        calls.append((slug,start,end))
        return [preseason,regular]
    try:
        p.NOW=datetime(2026,10,19,12,tzinfo=UTC)
        p.evs_daily=fake_daily
        assert p.current("NBA")==[]
        assert calls==[]
        p.NOW=datetime(2026,10,20,1,tzinfo=UTC)
        rows=p.current("NBA")
        assert [r["event_id"] for r in rows]==["opening-night"],rows
        assert calls and calls[0][1]>=p.NBA_START
        assert (calls[0][2].date()-calls[0][1].date()).days<=6
    finally:
        p.NOW,p.evs_daily=old_now,old_daily

def test_gamelogs_team_rows_are_joined_and_preseason_excluded():
    old_now,old_get,old_read=p.NOW,p.S.get,p.pd.read_parquet
    p.NOW=datetime(2026,10,11,9,tzinfo=UTC)
    class Response:
        content=b"test parquet bytes"
        def raise_for_status(self): pass
    records=[
      {"game_id":"0022500001","game_date":"2025-10-22","team_name":"Boston Celtics","team_id":2,"matchup":"BOS vs. NYK","pts":112},
      {"game_id":"0022500001","game_date":"2025-10-22","team_name":"New York Knicks","team_id":3,"matchup":"NYK @ BOS","pts":104},
      {"game_id":"0022500002","game_date":"2026-02-01","team_name":"Denver Nuggets","team_id":7,"matchup":"DEN vs. LAL","pts":120},
      {"game_id":"0022500002","game_date":"2026-02-01","team_name":"Los Angeles Lakers","team_id":8,"matchup":"LAL @ DEN","pts":110},
      {"game_id":"0012500001","game_date":"2025-10-17","team_name":"Boston Celtics","team_id":2,"matchup":"BOS vs. NYK","pts":115},
      {"game_id":"0012500001","game_date":"2025-10-17","team_name":"New York Knicks","team_id":3,"matchup":"NYK @ BOS","pts":100},
    ]
    p.S.get=lambda *args,**kwargs:Response()
    p.pd.read_parquet=lambda *args,**kwargs:p.pd.DataFrame(records)
    try:
        rows=p.nba_parquet_fallback()
        assert {r["event_id"] for r in rows}=={"0022500001","0022500002"},rows
        opener=next(r for r in rows if r["event_id"]=="0022500001")
        assert opener["home"]=="Boston Celtics" and opener["away"]=="New York Knicks",opener
        assert opener["home_score"]==112 and opener["away_score"]==104,opener
        assert all(r["source"]==p.NBA_PARQUET for r in rows)
    finally:
        p.NOW,p.S.get,p.pd.read_parquet=old_now,old_get,old_read

def test_collection_prefers_gamelogs_and_preserves_fallback_diagnostics():
    old_parquet,old_collect,old_elo=p.nba_parquet_fallback,p.collect_espn,p.nba_elo_fallback
    try:
        p.nba_parquet_fallback=lambda:[{"event_id":"parquet"}]
        p.collect_espn=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("ESPN should not be needed when dated gamelogs are valid"))
        rows,errors=p.collect("NBA")
        assert rows==[{"event_id":"parquet"}] and errors==[],(rows,errors)
        def fail_parquet():raise ValueError("parquet unavailable")
        p.nba_parquet_fallback=fail_parquet
        p.collect_espn=lambda *args,**kwargs:([],["ESPN daily scoreboard failed"])
        p.nba_elo_fallback=lambda:[{"event_id":"elo"}]
        rows,errors=p.collect("NBA")
        assert rows==[{"event_id":"elo"}],rows
        assert errors==["nba_gamelogs: parquet unavailable","ESPN daily scoreboard failed"],errors
    finally:
        p.nba_parquet_fallback,p.collect_espn,p.nba_elo_fallback=old_parquet,old_collect,old_elo

if __name__=="__main__":
    test_history_windows_and_preseason_exclusion()
    test_daily_scoreboard_uses_single_dates()
    test_regular_season_fixture_gate()
    test_gamelogs_team_rows_are_joined_and_preseason_excluded()
    test_collection_prefers_gamelogs_and_preserves_fallback_diagnostics()
    print("NBA source regression tests: PASS (5 groups)")
