#!/usr/bin/env python3
"""Chronological ATP-only walk-forward model regressions."""
from datetime import datetime, timedelta, timezone
import copy
import runpy

MODEL = runpy.run_path("scripts/tennis_model_v2.py")


def fixture(index, *, tour="ATP", actual=None):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    actual = actual or ("p1" if index % 2 == 0 else "p2")
    return {
        "sport": "tennis",
        "league": tour,
        "event_id": f"{tour}-{index}",
        "start_time": start.isoformat(),
        "player_1": f"Player {index % 9} A",
        "player_2": f"Player {(index + 2) % 9} B",
        "settled": True,
        "actual": actual,
        "probabilities": {"p1": 0.62 if index % 3 else 0.42, "p2": 0.38 if index % 3 else 0.58},
        "pick": "p1" if index % 3 else "p2",
        "confidence": 0.62 if index % 3 else 0.58,
    }


def test_weight_selection_uses_only_prior_rows():
    records = [fixture(i) for i in range(36)]
    observed = []
    namespace = MODEL["build_prequential_walkforward"].__globals__
    original = namespace["choose_elo_weight"]

    def fake_choose(prior):
        observed.append([row["event_id"] for row in prior])
        return 0.25, {"selected": {"elo_weight": 0.25}}

    namespace["choose_elo_weight"] = fake_choose
    try:
        scored, _, _, choices = MODEL["build_prequential_walkforward"](records)
    finally:
        namespace["choose_elo_weight"] = original

    assert len(scored) == len(records)
    assert all(item["elo_weight"] == 0.0 for item in choices[:30])
    assert choices[30]["prior_records"] == 30
    assert observed[0] == [row["event_id"] for row in records[:30]]
    assert records[30]["event_id"] not in observed[0]
    assert choices[30]["elo_weight"] == 0.25


def test_current_fixture_outcome_cannot_change_its_own_forecast():
    records_a = [fixture(i) for i in range(36)]
    records_b = copy.deepcopy(records_a)
    records_b[-1]["actual"] = "p2" if records_a[-1]["actual"] == "p1" else "p1"

    namespace = MODEL["build_prequential_walkforward"].__globals__
    original = namespace["choose_elo_weight"]
    namespace["choose_elo_weight"] = lambda prior: (0.5, {"selected": {"elo_weight": 0.5}})
    try:
        scored_a, _, _, _ = MODEL["build_prequential_walkforward"](records_a)
        scored_b, _, _, _ = MODEL["build_prequential_walkforward"](records_b)
    finally:
        namespace["choose_elo_weight"] = original

    assert scored_a[-1][1] == scored_b[-1][1]
    assert scored_a[-1][3] == scored_b[-1][3]


def test_future_outcomes_do_not_rewrite_earlier_forecasts():
    records = [fixture(i) for i in range(40)]
    changed = copy.deepcopy(records)
    for row in changed[35:]:
        row["actual"] = "p2" if row["actual"] == "p1" else "p1"

    namespace = MODEL["build_prequential_walkforward"].__globals__
    original = namespace["choose_elo_weight"]
    namespace["choose_elo_weight"] = lambda prior: (0.5, {"selected": {"elo_weight": 0.5}})
    try:
        a, _, _, _ = MODEL["build_prequential_walkforward"](records)
        b, _, _, _ = MODEL["build_prequential_walkforward"](changed)
    finally:
        namespace["choose_elo_weight"] = original

    for index in range(35):
        assert a[index][1] == b[index][1]
        assert a[index][3] == b[index][3]


def test_wta_history_is_not_pooled_into_active_atp_training():
    atp = [fixture(i, tour="ATP") for i in range(36)]
    wta = [fixture(i, tour="WTA", actual="p1" if i % 2 else "p2") for i in range(60)]
    active_a = MODEL["active_tour_records"](atp, "ATP")
    active_b = MODEL["active_tour_records"](atp + wta, "ATP")
    assert [x["event_id"] for x in active_a] == [x["event_id"] for x in active_b]

    namespace = MODEL["build_prequential_walkforward"].__globals__
    original = namespace["choose_elo_weight"]
    namespace["choose_elo_weight"] = lambda prior: (0.25, {"selected": {"elo_weight": 0.25}})
    try:
        a, _, _, _ = MODEL["build_prequential_walkforward"](active_a)
        b, _, _, _ = MODEL["build_prequential_walkforward"](active_b)
    finally:
        namespace["choose_elo_weight"] = original
    assert [x[1] for x in a] == [x[1] for x in b]


def test_elo_weight_selection_includes_unmodified_base_model():
    records = [fixture(i) for i in range(40)]
    _, diagnostic = MODEL["choose_elo_weight"](records)
    weights = {row["elo_weight"] for row in diagnostic["candidates"]}
    assert weights == {0.0, 0.25, 0.5, 0.75}
    assert diagnostic["objective"].startswith("minimum chronological-window Brier")


def test_apply_model_changes_atp_but_leaves_wta_untouched():
    atp = fixture(1, tour="ATP")
    wta = fixture(2, tour="WTA")
    atp["settled"] = False
    wta["settled"] = False
    before_wta = copy.deepcopy(wta)
    predictions = [atp, wta]
    changed, _ = MODEL["apply_model"](
        predictions,
        ratings={"player 1 a": 1600.0},
        elo_weight=0.75,
        current_rankings={"player 1 a": 4, "player 3 b": 50},
        calibration=[],
    )
    assert changed == 1
    assert predictions[0]["model_version"] == MODEL["V2_VERSION"]
    assert predictions[1] == before_wta


test_weight_selection_uses_only_prior_rows()
test_current_fixture_outcome_cannot_change_its_own_forecast()
test_future_outcomes_do_not_rewrite_earlier_forecasts()
test_wta_history_is_not_pooled_into_active_atp_training()
test_elo_weight_selection_includes_unmodified_base_model()
test_apply_model_changes_atp_but_leaves_wta_untouched()

print("ATP prequential walk-forward and tour-isolation regressions passed.")
