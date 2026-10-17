"""Regression checks for the accelerated Virtual Lab line-ladder fit."""
from virtual_lab_model_eval import evaluate_participant_feature_gate,fit_lambda,poisson_over

def reference_fit(points):
    if not points:return None
    best=(5.0,float("inf"))
    for i in range(25,2001):
        lam=i/100
        loss=sum((poisson_over(lam,line)-prob)**2 for line,prob in points)/len(points)
        if loss<best[1]:best=(lam,loss)
    return best[0]

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
