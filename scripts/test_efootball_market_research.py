#!/usr/bin/env python3
"""Offline regression tests for isolated eFootball market research."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location("efootball_market_research",Path(__file__).with_name("efootball_market_research.py"))
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def fixture(now,offset=10):
 return {"events":[{"product":"efootball_gt","event_id":"event-1","category_id":"cat","tournament_id":"tour","competition":"GT","participant_1":"Alpha","participant_2":"Beta","start_time":(now+timedelta(minutes=offset)).isoformat(),"markets":[
  {"id":"1","name":"Match Result","outcomes":[{"id":"h","name":"1","odds":1.8,"active":True},{"id":"d","name":"X","odds":3.4,"active":True},{"id":"a","name":"2","odds":4.5,"active":True}]},
  {"id":"10","name":"Both Teams to Score","outcomes":[{"id":"y","name":"Yes","odds":2.0,"active":True},{"id":"n","name":"No","odds":1.7,"active":True}]},
  {"id":"18","name":"Total Goals","specifier":"total=3.5","outcomes":[{"name":"Over","odds":1.9},{"name":"Under","odds":1.9}]}
 ]}]}
def test_markets():
 assert mod.classify({"id":"1","name":"Match Result","outcomes":[{"name":"1"},{"name":"X"},{"name":"2"}]})=="match_winner"
 assert mod.classify({"id":"10","name":"Both Teams to Score","outcomes":[{"name":"Yes"},{"name":"No"}]})=="btts"
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
if __name__=="__main__":
 test_markets();test_capture();test_settlement_and_summary();test_legacy_missing_scope_uses_bounded_discovery();test_draw_and_append_only_merge()
 print("eFootball winner/BTTS research tests: PASS (5 groups)")
