#!/usr/bin/env python3
"""Offline regression tests for isolated eFootball market research."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location("efootball_market_research",Path(__file__).with_name("efootball_market_research.py"))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
sync_spec=importlib.util.spec_from_file_location("virtual_lab_sync",Path(__file__).with_name("virtual_lab_sync.py"))
sync=importlib.util.module_from_spec(sync_spec);sync_spec.loader.exec_module(sync)
def fixture(now,offset=10):
 return {"events":[{"product":"efootball_gt","event_id":"event-1","category_id":"cat","tournament_id":"tour","competition":"GT","participant_1":"Alpha","participant_2":"Beta","start_time":(now+timedelta(minutes=offset)).isoformat(),"markets":[
  {"id":"1","name":"Match Result","outcomes":[{"id":"h","name":"1","odds":1.8,"active":True},{"id":"d","name":"X","odds":3.4,"active":True},{"id":"a","name":"2","odds":4.5,"active":True}]},
  {"id":"10","name":"Double Chance","outcomes":[{"id":"1x","name":"1X","odds":1.2,"active":True},{"id":"12","name":"12","odds":1.3,"active":True},{"id":"x2","name":"X2","odds":1.4,"active":True}]},
  {"id":"29","name":"GG/NG","outcomes":[{"id":"y","name":"GG","odds":2.0,"active":True},{"id":"n","name":"NG","odds":1.7,"active":True}]},
  {"id":"18","name":"Total Goals","specifier":"total=3.5","outcomes":[{"name":"Over","odds":1.9},{"name":"Under","odds":1.9}]}
 ]}]}
def test_live_feed_compaction_preserves_scope_ids():
 raw={"product":"efootball_gt","event_id":"e1","category_id":"cat-1","tournament_id":"tour-1",
      "participant_1":"Alpha","participant_2":"Beta","start_time":"2026-10-11T10:00:00+00:00","markets":[]}
 row=sync.compact(raw)
 assert row["category_id"]=="cat-1" and row["tournament_id"]=="tour-1"
def test_markets():
 assert mod.classify({"id":"1","name":"Match Result","outcomes":[{"name":"1"},{"name":"X"},{"name":"2"}]})=="match_winner"
 assert mod.classify({"id":"10","name":"Double Chance","outcomes":[{"name":"1X"},{"name":"12"},{"name":"X2"}]}) is None
 assert mod.classify({"id":"29","name":"GG/NG","outcomes":[{"name":"GG"},{"name":"NG"}]})=="btts"
 assert mod.classify({"id":"55","name":"GG/NGG","outcomes":[{"name":"GG"},{"name":"NGG"}]})=="btts"
 assert mod.classify({"id":"18","name":"Total Goals","outcomes":[{"name":"Over"},{"name":"Under"}]}) is None
 assert mod.classify({"id":"1","name":"1st Half Result","outcomes":[{"name":"1"},{"name":"X"},{"name":"2"}]}) is None
 assert mod.canon("match_winner","X")=="draw" and mod.canon("btts","NGG")=="no"
def test_capture():
 now=datetime(2026,10,11,10,0,tzinfo=timezone.utc);a={"observations":[]};live=fixture(now)
 assert mod.capture(live,a,now)==2
 assert {x["market_type"] for x in a["observations"]}=={"match_winner","btts"}
 assert all(x["category_id"]=="cat" and x["tournament_id"]=="tour" for x in a["observations"])
 assert mod.capture(live,a,now+timedelta(minutes=1))==0
 assert mod.capture(fixture(now,20),{"observations":[]},now)==0
 assert mod.capture(fixture(now,-1),{"observations":[]},now)==0
 live["events"][0]["product"]="vfootball"
 assert mod.capture(live,{"observations":[]},now)==0
def test_live_market_coverage_reports_actual_btts_availability():
 now=datetime(2026,10,11,10,0,tzinfo=timezone.utc)
 live=fixture(now)
 coverage=mod.market_coverage(live,now)
 gt=coverage["products"]["efootball_gt"]
 assert gt["market_id_29_rows"]==1
 assert gt["usable_two_way_quote_rows"]["btts"]==1
 assert gt["usable_two_way_quote_rows"]["match_winner"]==1
 assert gt["near_kickoff_usable_quote_rows"]["btts"]==1
 # A source event containing market 10 Double Chance is not a BTTS observation.
 live["events"][0]["markets"]=[m for m in live["events"][0]["markets"] if m["id"]!="29"]
 coverage=mod.market_coverage(live,now)["products"]["efootball_gt"]
 assert coverage["market_id_29_rows"]==0
 assert "btts" not in coverage["usable_two_way_quote_rows"]
def test_settlement_and_summary():
 now=datetime(2026,10,11,10,0,tzinfo=timezone.utc);a={"observations":[]};mod.capture(fixture(now),a,now)
 assert mod.settle(a,[{"eventId":"event-1","homeScore":"3","awayScore":"2"}],now+timedelta(hours=1))==2
 rows={x["market_type"]:x for x in a["observations"]}
 assert rows["match_winner"]["actual_outcome"]=="home" and rows["match_winner"]["favourite_correct"] is True
 assert rows["btts"]["actual_outcome"]=="yes" and rows["btts"]["favourite_correct"] is False
 s=mod.summary(a,now);assert s["summary_by_product_market"]["efootball_gt|match_winner"]["settled"]==1
 assert s["summary_by_product_market"]["efootball_gt|btts"]["settled"]==1
 assert s["production_qualification_enabled"] is False and s["odds_builder_eligible"] is False
def test_legacy_missing_scope_uses_bounded_discovery():
 now=datetime(2026,10,11,10,30,tzinfo=timezone.utc)
 payload={"events":[{"eventId":"legacy-e","homeScore":"2","awayScore":"1"}]}
 class FakeResponse:
  def raise_for_status(self): pass
  def json(self): return payload
 with patch.object(mod.requests,"get",return_value=FakeResponse()) as get:
  events,errors=mod.fetch_results([{"event_id":"legacy-e","start_time":"2026-10-11T10:00:00+00:00"}],now)
  assert events==payload["events"] and not errors
  args,kwargs=get.call_args
  assert args[0].endswith("/api/sportybet-virtual-results")
  assert kwargs["params"]["source"]=="efootball"
  assert "categoryId" not in kwargs["params"] and "tournamentId" not in kwargs["params"]
  a={"observations":[{"event_id":"legacy-e","market_type":"match_winner","odds":{"home":1.8,"draw":3.4,"away":4.5},"market_probabilities_no_vig":{"home":.55,"draw":.29,"away":.16},"market_favourite":"home","favourite_odds":1.8,"settlement_status":"PENDING"}]}
  assert mod.settle(a,events,now)==1
  assert a["observations"][0]["actual_outcome"]=="home"
def test_draw_and_append_only_merge():
 row={"sample_id":"same","event_id":"e","market_type":"match_winner","odds":{"home":1.8,"away":2.0},"market_probabilities_no_vig":{"home":.52,"away":.48},"market_favourite":"home","favourite_odds":1.8,"settlement_status":"PENDING"}
 a={"observations":[row.copy()]}
 assert mod.settle(a,[{"eventId":"e","homeScore":1,"awayScore":1}],datetime.now(timezone.utc))==0
 assert a["observations"][0]["settlement_status"]=="UNSETTLED_DRAW_SCOPE"
 frozen={"sample_id":"same","settlement_status":"PENDING","captured_at":"2026-10-11T10:00:00+00:00","odds":{"home":1.8}}
 settled={"sample_id":"same","settlement_status":"SETTLED","settled_at":"2026-10-11T11:00:00+00:00","odds":{"home":1.8}}
 m=mod.merge({"observations":[frozen]},{"observations":[settled]})
 assert m["observations"][0]["settlement_status"]=="SETTLED" and m["odds_builder_eligible"] is False
def test_settlement_due_uses_elapsed_time_not_exact_minute():
 now=datetime(2026,10,11,10,17,tzinfo=timezone.utc)
 assert mod.settlement_due({},now) is True
 archive={"last_run":{"captured_at":(now-timedelta(minutes=1)).isoformat(),
   "settlement_checked_at":(now-timedelta(minutes=14)).isoformat()}}
 assert mod.settlement_due(archive,now) is False
 archive["last_run"]["settlement_checked_at"]=(now-timedelta(minutes=15)).isoformat()
 assert mod.settlement_due(archive,now) is True
 with patch.dict(mod.os.environ,{"EFOOTBALL_RESEARCH_FORCE_SETTLE":"1"}):
  assert mod.settlement_due(archive,now) is True

def test_scoped_result_lookup_retries_without_time_filters():
 now=datetime(2026,10,11,10,17,tzinfo=timezone.utc)
 event={"eventId":"scoped-event","homeScore":"2","awayScore":"1"}
 class FakeResponse:
  def __init__(self,payload):self.payload=payload
  def raise_for_status(self):pass
  def json(self):return self.payload
 with patch.object(mod.requests,"get",side_effect=[FakeResponse({"events":[]}),FakeResponse({"events":[event]})]) as get:
  rows,errors=mod.fetch_results([{"event_id":"scoped-event","category_id":"cat-1","tournament_id":"tour-1","start_time":"2026-10-11T10:00:00+00:00"}],now)
  assert rows==[event] and not errors,(rows,errors)
  assert get.call_count==2
  first=get.call_args_list[0].kwargs["params"]
  second=get.call_args_list[1].kwargs["params"]
  assert "startTime" in first and "endTime" in first,first
  assert "startTime" not in second and "endTime" not in second,second
  assert first["pageSize"]==5 and second["pageSize"]==5,(first,second)
  assert second["categoryId"]=="cat-1" and second["tournamentId"]=="tour-1"

def test_legacy_scope_discovery_retries_without_time_filters():
 now=datetime(2026,10,11,10,17,tzinfo=timezone.utc)
 event={"eventId":"legacy-event","homeScore":"1","awayScore":"0"}
 class FakeResponse:
  def __init__(self,payload):self.payload=payload
  def raise_for_status(self):pass
  def json(self):return self.payload
 with patch.object(mod.requests,"get",side_effect=[FakeResponse({"events":[]}),FakeResponse({"events":[event]})]) as get:
  rows,errors=mod.fetch_results([{"event_id":"legacy-event","start_time":"2026-10-11T09:30:00+00:00"}],now)
  assert rows==[event] and not errors,(rows,errors)
  assert get.call_count==2
  second=get.call_args_list[1].kwargs["params"]
  assert second["source"]=="efootball" and "startTime" not in second and "endTime" not in second,second
  assert second["pageSize"]==5,second

def test_result_proxy_upstream_errors_are_preserved():
 now=datetime(2026,10,11,10,17,tzinfo=timezone.utc)
 class FakeResponse:
  def raise_for_status(self):pass
  def json(self):return {"ok":True,"events":[],"errors":[{"page":1,"error":"upstream HTTP 503"}]}
 with patch.object(mod.requests,"get",side_effect=[FakeResponse(),FakeResponse()]) as get:
  rows,errors=mod.fetch_results([{"event_id":"legacy-event","start_time":"2026-10-11T09:30:00+00:00"}],now)
  assert rows==[],rows
  assert errors and any("upstream HTTP 503" in err for err in errors),errors
  assert get.call_count==2

if __name__=="__main__":
 test_live_feed_compaction_preserves_scope_ids();test_markets();test_capture();test_live_market_coverage_reports_actual_btts_availability();test_settlement_and_summary();test_legacy_missing_scope_uses_bounded_discovery();test_draw_and_append_only_merge();test_settlement_due_uses_elapsed_time_not_exact_minute();test_scoped_result_lookup_retries_without_time_filters();test_legacy_scope_discovery_retries_without_time_filters();test_result_proxy_upstream_errors_are_preserved()
 print("eFootball winner/BTTS research tests: PASS (11 groups)")
