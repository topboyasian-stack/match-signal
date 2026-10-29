"""Regression checks for the accelerated Virtual Lab line-ladder fit."""
from virtual_lab_model_eval import evaluate_participant_feature_gate,fit_lambda,poisson_over,holdout_prediction_rows,normalize_selection,build_events,selection_line_key,rows_with_selection_line_key

def reference_fit(points):
    if not points:return None
    best=(5.0,float("inf"))
    for i in range(25,2001):
        lam=i/100
        loss=sum((poisson_over(lam,line)-prob)**2 for line,prob in points)/len(points)
        if loss<best[1]:best=(lam,loss)
    return best[0]

assert normalize_selection("Under 6.5") == "under"
assert normalize_selection("UNDER") == "under"
assert normalize_selection("Over 4.5") == "over"
assert normalize_selection("O 1.5") == "over"
assert normalize_selection("") is None
assert normalize_selection("unknown side") is None


def test_legacy_settled_history_timestamp_is_scheduled_kickoff():
    kickoff = "2026-10-20T10:00:00+00:00"
    capture = "2026-10-20T08:15:00+00:00"
    events = build_events([{
        "market": "ou",
        "win": True,
        "event_id": "legacy-event-1",
        "timestamp": kickoff,
        # Legacy Virtual Lab settled rows have no explicit start_time; timestamp
        # is the scheduled kickoff and captured_at stores the earlier quote time.
        "captured_at": capture,
        "product": "efootball_gt",
        "competition": "GT",
        "participant_1": "Alpha (alpha)",
        "participant_2": "Beta (beta)",
        "line": 4.5,
        "selection": "Under 5.5",
        "model_prob": 0.62,
        "score": "3:2",
    }])
    assert len(events) == 1
    assert events[0]["start_time"] == kickoff
    assert events[0]["timestamp"] == kickoff


test_legacy_settled_history_timestamp_is_scheduled_kickoff()


CASES=[
 [(1.5,.90),(2.5,.77),(3.5,.56),(4.5,.31),(5.5,.15)],
 [(1.5,.69),(2.5,.47),(3.5,.28),(4.5,.13)],
 [(2.5,.94),(3.5,.81),(4.5,.64),(5.5,.44),(6.5,.25)],
 [(0.5,.99),(1.5,.96),(2.5,.87),(3.5,.62),(4.5,.29)],
 [(7.5,.92),(8.5,.80),(9.5,.61),(10.5,.38),(11.5,.19)],
]
for idx,points in enumerate(CASES,1):
    fast=fit_lambda(points);old=reference_fit(points)
    assert fast is not None and old is not None
    assert abs(fast-old)<=0.02,(idx,fast,old)
assert fit_lambda([]) is None
print("Virtual Lab line-ladder fit regression passed:",len(CASES),"cases")


def metric(n,brier,log_loss,ece):
    return {"n":n,"brier":brier,"log_loss":log_loss,"ece":ece}


def test_participant_gate_rejects_feature_that_only_beats_market():
    # Reproduces the failure mode in the current production report: participant
    # recurrence beats the market baseline but loses to the untouched Poisson base.
    metrics_by_variant = {
        "market": metric(600,.33,.94,.22),
        "poisson": metric(600,.194,.561,.010),
        "poisson_prior": metric(600,.195,.563,.019),
        "efootball_shape": metric(600,.198,.569,.037),
        "participant_model": metric(600,.197,.567,.035),
    }
    gate = evaluate_participant_feature_gate(metrics_by_variant, 600, 560)
    assert not gate["pass"], gate
    assert gate["baseline_variant"] == "poisson", gate
    assert "strongest base variant" in gate["reason"], gate


def test_participant_gate_passes_only_when_both_losses_improve():
    metrics_by_variant = {
        "market": metric(600,.33,.94,.22),
        "poisson": metric(600,.194,.561,.010),
        "poisson_prior": metric(600,.195,.563,.019),
        "efootball_shape": metric(600,.198,.569,.037),
        "participant_model": metric(600,.180,.520,.025),
    }
    gate = evaluate_participant_feature_gate(metrics_by_variant, 600, 560)
    assert gate["pass"], gate
    assert gate["baseline_variant"] == "poisson", gate


def test_participant_gate_fails_closed_on_small_untouched_sample():
    metrics_by_variant = {
        "market": metric(20,.33,.94,.22),
        "poisson": metric(20,.194,.561,.010),
        "poisson_prior": metric(20,.195,.563,.019),
        "efootball_shape": metric(20,.198,.569,.037),
        "participant_model": metric(20,.180,.520,.025),
    }
    gate = evaluate_participant_feature_gate(metrics_by_variant, 20, 10)
    assert not gate["pass"], gate
    assert "insufficient" in gate["reason"], gate


test_participant_gate_rejects_feature_that_only_beats_market()
test_participant_gate_passes_only_when_both_losses_improve()
test_participant_gate_fails_closed_on_small_untouched_sample()
print("Participant feature promotion-gate regression checks passed")


def test_holdout_prediction_export_is_efootball_only_and_never_includes_training_rows():
    scored = [
        {
            "event_key": "e1|t1", "event_id": "e1", "timestamp": "2026-10-20T08:00:00+00:00",
            "start_time": "2026-10-20T10:00:00+00:00",
            "product": "efootball_gt", "competition": "GT", "selection": "under",
            "line": 6.5, "y": 1, "market": 0.51, "poisson": 0.58,
            "poisson_prior": 0.57, "efootball_shape": 0.56, "participant_model": 0.55,
        },
        {
            "event_key": "e2|t2", "event_id": "e2", "timestamp": "2026-10-20T10:10:00+00:00",
            "product": "vfootball", "competition": "VF", "selection": "over",
            "line": 5.5, "y": 0, "market": 0.49, "poisson": 0.48,
            "poisson_prior": 0.47, "efootball_shape": 0.46, "participant_model": 0.45,
        },
        {
            "event_key": "e3|t3", "event_id": "e3", "timestamp": "2026-10-19T10:00:00+00:00",
            "product": "efootball_adriatic", "competition": "Adriatic", "selection": "over",
            "line": 4.5, "y": 0, "market": 0.52, "poisson": 0.53,
            "poisson_prior": 0.54, "efootball_shape": 0.55, "participant_model": 0.56,
        },
    ]
    exported = holdout_prediction_rows(scored, {"e1|t1"})
    assert len(exported) == 1
    assert exported[0]["event_id"] == "e1"
    assert exported[0]["product"] == "efootball_gt"
    assert exported[0]["line"] == 6.5
    assert exported[0]["selection"] == "under"
    assert exported[0]["start_time"] == "2026-10-20T10:00:00+00:00"
    assert exported[0]["timestamp"] == "2026-10-20T08:00:00+00:00"
    assert exported[0]["poisson"] == 0.58
    assert all(row["event_key"] in {"e1|t1"} for row in exported)


test_holdout_prediction_export_is_efootball_only_and_never_includes_training_rows()
print("Same-fixture Poisson holdout export regression passed")

def test_product_selection_line_keys_are_exact_and_directional():
    rows = [
        {"product": "efootball_gt", "selection": "under", "line": 4.5, "y": 1},
        {"product": "efootball_gt", "selection": "over", "line": 4.5, "y": 0},
        {"product": "efootball_gt", "selection": "under", "line": 7.5, "y": 1},
        {"product": "efootball_gt", "selection": "draw", "line": 4.5, "y": 1},
    ]
    assert [selection_line_key(row) for row in rows] == ["u4.5", "o4.5", "u7.5", None]
    exported = rows_with_selection_line_key(rows)
    assert [row["selection_line"] for row in exported] == ["u4.5", "o4.5", "u7.5"]
    assert len(exported) == 3
    assert "selection_line" not in rows[0], "helper must not mutate canonical scored rows"


test_product_selection_line_keys_are_exact_and_directional()
print("Product-side-line evidence-key regression passed")
