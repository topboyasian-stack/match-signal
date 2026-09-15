"""Private-facing ML probability primitives for Match Signal.
No credentials, vendor payloads, raw odds, or frontend logic belong here.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

def clamp_probability(p: float, eps: float = 1e-6) -> float:
    return max(eps, min(1.0 - eps, float(p)))

def brier_binary(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    if not y_true: return 0.0
    return sum((float(p)-int(y))**2 for y,p in zip(y_true,probabilities))/len(y_true)

def log_loss_binary(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    if not y_true: return 0.0
    total=0.0
    for y,p in zip(y_true,probabilities):
        p=clamp_probability(p)
        total += -(int(y)*math.log(p)+(1-int(y))*math.log(1-p))
    return total/len(y_true)

def chronological_split(rows: Sequence[dict], holdout_fraction: float=0.2):
    ordered=sorted(rows,key=lambda r:str(r.get('start_time') or r.get('calculated_at') or ''))
    cut=max(1,int(len(ordered)*(1-holdout_fraction))) if ordered else 0
    return ordered[:cut],ordered[cut:]

@dataclass(frozen=True)
class ModelProbability:
    probability: float
    source: str
    sample_size: int=0
    calibrated: bool=False

def ensemble_probability(models: Iterable[ModelProbability], weights: Iterable[float]|None=None)->float:
    items=list(models)
    if not items: raise ValueError('at least one probability model is required')
    ws=list(weights) if weights is not None else [1.0]*len(items)
    if len(ws)!=len(items): raise ValueError('weights must match models')
    total=sum(max(0.0,float(w)) for w in ws)
    if total<=0: total=float(len(items)); ws=[1.0]*len(items)
    return clamp_probability(sum(clamp_probability(m.probability)*max(0.0,float(w)) for m,w in zip(items,ws))/total)

def disagreement(models: Iterable[ModelProbability])->float:
    values=[clamp_probability(m.probability) for m in models]
    return max(values)-min(values) if values else 0.0

def calibration_bucket(probability: float)->str:
    p=clamp_probability(probability)
    return 'low' if p<.55 else 'moderate' if p<.65 else 'strong' if p<.75 else 'high'

def evaluate_binary(rows: Sequence[dict])->dict:
    y=[];p=[]
    for row in rows:
        if not row.get('settled'): continue
        actual=row.get('actual'); probs=row.get('probabilities') or {}
        if actual not in {'p1','p2'} or probs.get(actual) is None: continue
        y.append(1); p.append(float(probs[actual]))
    return {'sample_size':len(p),'brier':round(brier_binary(y,p),6) if p else None,'log_loss':round(log_loss_binary(y,p),6) if p else None}
