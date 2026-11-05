#!/usr/bin/env python3
"""Offline regression tests for Virtual Lab exact-scope settlement recovery."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location(
    "virtual_lab_collector",Path(__file__).with_name("virtual_lab_collector.py")
)
collector=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def pending_row(event_id, kickoff, product="efootball_gt", line=3.5, selection="O3.5"):
    return {
        "observation_id":event_id+"|ou|"+str(line),
        "settled":False,
        "event_id":event_id,
        "product":product,
        "source":"efootball",
        "category_id":"cat-shared",
        "tournament_id":"tour-shared",
        "start_time_ms":int(kickoff.timestamp()*1000),
        "start_time":kickoff.isoformat(),
        "market":"ou",
        "market_id":"18",
        "line":line,
        "selection":selection,
        "selection_name":"Over",
        "odds":1.9,
        "model_prob":0.62,
        "provider":"SportyBet NG",
        "competition":"eFootball",
        "participant_1":"Alpha (AAA)",
        "participant_2":"Beta (BBB)",
        "captured_at":(kickoff-timedelta(minutes=5)).isoformat(),
    }


def test_old_fixtures_in_same_scope_are_queried_in_bounded_windows():
    now=datetime(2026,11,2,19,30,tzinfo=timezone.utc)
    old=now-timedelta(days=9)
    recent=now-timedelta(hours=4)
    pending={
        "old-a":pending_row("old-a",old,line=3.5,selection="O3.5"),
        # Multiple market decisions for one event must share the same lookup.
        "old-a-u45":pending_row("old-a",old,line=4.5,selection="U4.5"),
        "recent-b":pending_row("recent-b",recent,line=3.5,selection="O3.5"),
    }
    calls=[]

    def fake_proxy(_url,params):
        start=int(params["startTime"]); end=int(params["endTime"])
        assert 0<end-start<=3*60*60*1000,(start,end)
        assert params["categoryId"]=="cat-shared"
        assert params["tournamentId"]=="tour-shared"
        calls.append(dict(params))
        rows=[]
        for item in pending.values():
            kickoff=int(item["start_time_ms"])
            if start<=kickoff<=end:
                event_id=item["event_id"]
                if event_id not in {x["eventId"] for x in rows}:
                    rows.append({
                        "eventId":event_id,"matchStatus":"End","setScore":"3:1"
                    })
        return {"ok":True,"events":rows,"errors":[]}

    with patch.object(collector,"proxy_json",side_effect=fake_proxy), \
         patch.object(collector,"STATUS_PATH",Path("/tmp/match-signal-settlement-test-missing-status.json")), \\
         patch.object(collector.time,"time",return_value=now.timestamp()):
        settled, count, errors, meta=collector.settle(pending)

    assert not errors,errors
    assert count==3,count
    assert len(settled)==3,len(settled)
    assert len(calls)==2,len(calls)
    assert all((c["endTime"]-c["startTime"])==3*60*60*1000 for c in calls)
    assert meta["result_windows_available"]==2,meta
    assert meta["recent_windows_queried"]>=1,meta
    assert all(row["settlement_source"].startswith("SportyBet NG") for row in settled)
    assert all(row["win"] is True for row in settled)


def test_inplay_score_is_never_settled_as_a_final_result():
    now=datetime.now(timezone.utc)
    kickoff=now-timedelta(minutes=30)
    pending={"live":pending_row("live",kickoff)}
    with patch.object(
        collector,"proxy_json",
        return_value={"ok":True,"events":[
            {"eventId":"live","matchStatus":"Live","setScore":"3:1"}
        ],"errors":[]}
    ), patch.object(
        collector,"STATUS_PATH",Path("/tmp/match-signal-settlement-test-missing-status-2.json")
    ):
        settled,count,errors,meta=collector.settle(pending)
    assert not errors,errors
    assert count==0,count
    assert not settled,settled
    assert pending["live"].get("settled") is not True


if __name__=="__main__":
    test_old_fixtures_in_same_scope_are_queried_in_bounded_windows()
    test_inplay_score_is_never_settled_as_a_final_result()
    print("Virtual Lab bounded exact-scope settlement tests passed")
