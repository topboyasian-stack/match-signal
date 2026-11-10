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

def test_collection_prefers_pace_gamelogs_and_preserves_fallback_diagnostics():
    old_source,old_collect,old_elo=p.nba_duckdb_fallback,p.collect_espn,p.nba_elo_fallback
    try:
        p.nba_duckdb_fallback=lambda:[{"event_id":"duckdb"}]
        p.collect_espn=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("ESPN should not be needed when v2 pace gamelogs are valid"))
        rows,errors=p.collect("NBA")
        assert rows==[{"event_id":"duckdb"}] and errors==[],(rows,errors)
        def fail_source():raise ValueError("public catalog unavailable")
        p.nba_duckdb_fallback=fail_source
        p.collect_espn=lambda *args,**kwargs:([],["ESPN daily scoreboard failed"])
        p.nba_elo_fallback=lambda:[{"event_id":"elo"}]
        rows,errors=p.collect("NBA")
        assert rows==[{"event_id":"elo"}],rows
        assert errors==["nba_data_v2_team_game_logs: public catalog unavailable","ESPN daily scoreboard failed"],errors
    finally:
        p.nba_duckdb_fallback,p.collect_espn,p.nba_elo_fallback=old_source,old_collect,old_elo


def test_v4_uses_strictly_prior_scores_pace_and_efficiency():
    old_now=p.NOW
    try:
        p.NOW=datetime(2026,10,31,12,tzinfo=UTC)
        base=[]
        for i in range(14):
            stamp=p.NOW-__import__("datetime").timedelta(days=14-i)
            base.append({"event_id":f"home-prior-{i}","date":stamp.isoformat(),
                         "home":"Home Team","away":f"Opponent {i}",
                         "home_score":100.0+i,"away_score":100.0,
                         "home_pace":100,"away_pace":100,
                         "home_off_rating":112,"away_off_rating":111,
                         "home_def_rating":110,"away_def_rating":109,
                         "home_possessions":98,"away_possessions":99})
            base.append({"event_id":f"away-prior-{i}","date":stamp.isoformat(),
                         "home":f"Other {i}","away":"Away Team",
                         "home_score":100.0,"away_score":100.0+i,
                         "home_pace":100,"away_pace":100,
                         "home_off_rating":111,"away_off_rating":112,
                         "home_def_rating":109,"away_def_rating":110,
                         "home_possessions":99,"away_possessions":98})
        fixture={"event_id":"upcoming","date":(p.NOW+__import__("datetime").timedelta(days=1)).isoformat(),
                 "home":"Home Team","away":"Away Team"}
        forecast=p.nba_predict(fixture,base,pace_blend_weight=.5,bias_adjustment=1.25)
        assert forecast["totals_model_version"]==p.NBA_TOTALS_MODEL_VERSION
        assert forecast["model"]==p.NBA_WINNER_MODEL_LABEL
        assert forecast["totals_model"]==p.NBA_TOTALS_MODEL_LABEL
        assert forecast["total_model_features"]["recency_half_life_days"]==30
        assert forecast["total_model_features"]["recent_team_total_window"]==12
        assert forecast["total_model_features"]["pace_efficiency_available"] is True
        assert forecast["total_model_features"]["pace_blend_weight"]==.5
        assert forecast["total_model_features"]["bias_correction_points"]==1.25
        assert abs(forecast["expected_total"]-(forecast["expected_score"]["home"]+forecast["expected_score"]["away"]))<1e-8
        weighted=p.weights(base,p.dt(fixture["date"]),30)
        assert len(weighted["Home Team"]["recent_totals"])==12
        assert len(weighted["Away Team"]["recent_totals"])==12
        future=base+[{"event_id":"future","date":(p.NOW+__import__("datetime").timedelta(days=2)).isoformat(),
                      "home":"Home Team","away":"Away Team","home_score":300.0,"away_score":300.0,
                      "home_pace":111,"away_pace":111,"home_off_rating":140,"away_off_rating":140,
                      "home_def_rating":140,"away_def_rating":140}]
        after=p.nba_predict(fixture,future,pace_blend_weight=.5,bias_adjustment=1.25)
        assert after["expected_total"]==forecast["expected_total"], "future games must not enter a pregame forecast"
    finally:
        p.NOW=old_now


def test_default_nba_prediction_uses_frozen_v51_calibration():
    from expansion_pipeline import NBA_TOTALS_PACE_BLEND_WEIGHT, NBA_TOTALS_BIAS_CORRECTION

    history = []
    for i in range(8):
        home, away = ("Home Team", "Away Team") if i % 2 == 0 else ("Away Team", "Home Team")
        history.append({
            "event_id": f"calibration-{i}",
            "date": f"2026-10-{10 + i:02d}T00:00:00+00:00",
            "home": home, "away": away,
            "home_score": 108 + i, "away_score": 104 + i,
            "home_pace": 99 + (i % 2), "away_pace": 100 - (i % 2),
            "home_off_rating": 112 + i, "away_off_rating": 110 + i,
            "home_def_rating": 108 + i, "away_def_rating": 109 + i,
            "home_possessions": 98, "away_possessions": 99,
        })
    fixture = {
        "event_id": "calibration-live-check",
        "date": "2026-10-31T00:00:00+00:00",
        "home": "Home Team", "away": "Away Team",
    }
    forecast = p.nba_predict(fixture, history)
    features = forecast["total_model_features"]
    assert features["pace_efficiency_available"] is True
    assert features["pace_blend_weight"] == NBA_TOTALS_PACE_BLEND_WEIGHT == 0.8
    assert features["bias_correction_points"] == NBA_TOTALS_BIAS_CORRECTION == 0.3542
    expected = (
        features["score_form_reference_total"]
        + NBA_TOTALS_PACE_BLEND_WEIGHT * (
            features["pace_efficiency_total"] - features["score_form_reference_total"]
        )
        - NBA_TOTALS_BIAS_CORRECTION
    )
    assert abs(forecast["expected_total"] - expected) < 1e-9


def test_v2_normalizer_keeps_only_valid_regular_season_pace_metrics():
    now=datetime(2026,10,31,12,tzinfo=UTC)
    rows=p.normalize_nba_duckdb_rows([
        {"event_id":"0022600001","date":"2026-10-25","game_type":"regular_season",
         "home":"Boston Celtics","away":"New York Knicks","home_score":112,"away_score":105,
         "home_pace":99.5,"away_pace":100.5,"home_off_rating":115.2,"away_off_rating":110.1,
         "home_def_rating":108.2,"away_def_rating":113.4,"home_possessions":98,"away_possessions":99},
        {"event_id":"preseason","date":"2026-10-25","game_type":"preseason",
         "home":"A","away":"B","home_score":100,"away_score":100},
        {"event_id":"future","date":"2026-11-01","game_type":"regular_season",
         "home":"A","away":"B","home_score":100,"away_score":100}
    ],now)
    assert len(rows)==1 and rows[0]["source"]=="nba_data_v2_team_game_logs"
    assert rows[0]["home_pace"]==99.5 and rows[0]["away_off_rating"]==110.1
    assert rows[0]["home_possessions"]==98
    assert rows[0]["date"]=="2026-10-26T03:59:59.999999+00:00", rows[0]["date"]


def _winner_history_row(event_id, day_key, home, away, home_score, away_score):
    # The NBA historical source stores game-day rows at the end of the
    # Eastern calendar day, represented here as 03:59:59 UTC during DST.
    return {
        "event_id": event_id,
        "date": f"{day_key}T03:59:59.999999+00:00",
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "home_pace": 100.0,
        "away_pace": 100.0,
        "home_off_rating": 112.0 + (home_score - 100.0) / 5.0,
        "away_off_rating": 112.0 + (away_score - 100.0) / 5.0,
        "home_def_rating": 108.0,
        "away_def_rating": 108.0,
    }


def test_nba_winner_model_is_independent_and_versioned():
    history = []
    for index in range(10):
        game_day = datetime(2026, 10, 10 + index, tzinfo=UTC).date()
        next_day = game_day + __import__("datetime").timedelta(days=1)
        if index % 2 == 0:
            history.append(_winner_history_row(
                f"home-form-{index}", next_day.isoformat(),
                "Home Team", f"Opponent {index}", 118 + index, 103,
            ))
        else:
            history.append(_winner_history_row(
                f"away-form-{index}", next_day.isoformat(),
                f"Opponent {index}", "Away Team", 104, 110 + index,
            ))
    fixture = {
        "event_id": "winner-model-check",
        "date": "2026-10-22T23:00:00+00:00",
        "home": "Home Team",
        "away": "Away Team",
    }
    winner = p.nba_winner_predict(fixture, history)
    assert winner["model"]["version"] == p.NBA_WINNER_MODEL_VERSION
    assert winner["model"]["market_inputs_used"] is False
    assert 0.0 < winner["moneyline"]["home"] < 1.0
    assert abs(winner["moneyline"]["home"] + winner["moneyline"]["away"] - 1.0) < 1e-12

    forecast = p.nba_predict(fixture, history)
    assert forecast["winner_model"]["version"] == p.NBA_WINNER_MODEL_VERSION
    assert forecast["totals_model_version"] == p.NBA_TOTALS_MODEL_VERSION
    assert forecast["moneyline"] == winner["moneyline"]


def test_nba_winner_forecast_excludes_same_day_and_future_results():
    prior = [
        _winner_history_row(
            "prior-home-1", "2026-10-19", "Home Team", "Opponent A", 120, 100,
        ),
        _winner_history_row(
            "prior-away-1", "2026-10-20", "Opponent B", "Away Team", 101, 117,
        ),
        _winner_history_row(
            "prior-home-2", "2026-10-21", "Home Team", "Opponent C", 116, 102,
        ),
        _winner_history_row(
            "prior-away-2", "2026-10-22", "Opponent D", "Away Team", 99, 113,
        ),
    ]
    fixture = {
        "event_id": "same-eastern-day-fixture",
        # 21:00 ET on Oct 23; the historical row for Oct 23 is still pre-tip
        # unavailable and must not enter this forecast.
        "date": "2026-10-24T01:00:00+00:00",
        "home": "Home Team",
        "away": "Away Team",
    }
    baseline = p.nba_winner_predict(fixture, prior)
    same_day = _winner_history_row(
        "same-day-result", "2026-10-24", "Home Team", "Away Team", 250, 70,
    )
    later = _winner_history_row(
        "future-result", "2026-10-25", "Home Team", "Away Team", 60, 220,
    )
    with_unavailable_results = p.nba_winner_predict(fixture, prior + [same_day, later])
    assert with_unavailable_results["moneyline"] == baseline["moneyline"]
    assert with_unavailable_results["model"]["feature_values"] == baseline["model"]["feature_values"]


def test_nba_winner_model_is_invariant_to_same_day_row_order():
    day_one = [
        _winner_history_row("same-day-a", "2026-10-20", "Home Team", "Opponent A", 115, 102),
        _winner_history_row("same-day-b", "2026-10-20", "Opponent B", "Away Team", 99, 118),
    ]
    day_two = [
        _winner_history_row("next-day-a", "2026-10-21", "Home Team", "Opponent C", 121, 105),
        _winner_history_row("next-day-b", "2026-10-21", "Opponent D", "Away Team", 104, 116),
    ]
    fixture = {
        "event_id": "post-same-day-check",
        "date": "2026-10-23T01:00:00+00:00",
        "home": "Home Team",
        "away": "Away Team",
    }
    first = p.nba_winner_predict(fixture, day_one + day_two)
    second = p.nba_winner_predict(fixture, list(reversed(day_one + day_two)))
    assert first["moneyline"] == second["moneyline"]
    assert first["model"]["feature_values"] == second["model"]["feature_values"]


if __name__=="__main__":
    test_history_windows_and_preseason_exclusion()
    test_daily_scoreboard_uses_single_dates()
    test_regular_season_fixture_gate()
    test_gamelogs_team_rows_are_joined_and_preseason_excluded()
    test_collection_prefers_pace_gamelogs_and_preserves_fallback_diagnostics()
    test_v4_uses_strictly_prior_scores_pace_and_efficiency()
    test_v2_normalizer_keeps_only_valid_regular_season_pace_metrics()
    test_nba_winner_model_is_independent_and_versioned()
    test_nba_winner_forecast_excludes_same_day_and_future_results()
    test_nba_winner_model_is_invariant_to_same_day_row_order()
    print("NBA source regression tests: PASS (10 groups)")
