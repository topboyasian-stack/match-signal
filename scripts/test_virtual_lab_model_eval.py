"""Regression checks for the accelerated Virtual Lab line-ladder fit."""
from virtual_lab_model_eval import fit_lambda,poisson_over

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
