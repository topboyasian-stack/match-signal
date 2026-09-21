# Virtual Lab — Prediction Engine Specification

**Public owner:** Diddy  
**Build family:** MS-VIRTUAL-LAB  
**Status:** research architecture; no live wagering

## Why the engine must be stronger than a win-rate counter

A high historical hit rate can occur by chance, selection bias, low sample size, or a rule fitted to the same observations used to evaluate it. The engine therefore separates:

- prediction;
- probability calibration;
- market-price comparison;
- uncertainty;
- temporal validation;
- replication.

A candidate does not become a research signal merely because it crossed an 80% historical hit rate.

## Model stack

### Layer 1 — empirical baseline

For each product/market/selection:

- observed frequency;
- recency-weighted frequency;
- Wilson confidence interval;
- score/total distribution;
- participant-conditioned frequencies where repeated identifiers exist.

### Layer 2 — market baseline

When decimal odds exist:

`implied_probability = 1 / odds`

For complete markets, compare the candidate against the normalized/de-vig market probability. Preserve bookmaker price and model probability as separate values.

### Layer 3 — feature model

After enough history exists, test a small set of legitimate, observable features:

- product/provider;
- competition;
- participant pair;
- participant-specific historical rates;
- score distribution;
- market type;
- price;
- time-of-day/session position;
- event interval/cadence;
- recent observed sequence features.

Do not include a feature if it was only available after the bet cutoff.

### Layer 4 — calibrated probability

Candidate models should be calibrated on a separate validation period using methods such as isotonic regression or Platt/logistic scaling when appropriate. Track Brier score and log loss in addition to hit rate.

### Layer 5 — ensemble

Only models that beat the relevant baseline on untouched data can enter the ensemble. The ensemble should combine probabilities, not majority-vote labels.

Example:

`final_probability = weighted_mean(empirical, market_baseline_adjustment, feature_model)`

Weights are learned only from historical training data and then frozen for the following test window.

## Validation protocol

Use chronological walk-forward validation:

1. train on an early window;
2. freeze the model;
3. predict the next unseen window;
4. record probability, price and outcome;
5. advance the window;
6. repeat.

Maintain a second untouched holdout that is never used for model selection.

This avoids look-ahead bias and makes the reported performance closer to deployment conditions.

## Anti-overfitting controls

- minimum sample sizes per candidate;
- Wilson lower-bound threshold;
- separate discovery/validation/test windows;
- parameter stability checks;
- feature ablation;
- sensitivity to small parameter changes;
- second-period replication;
- correction/penalty when many candidate rules are searched.

Do not keep tuning against the final holdout.

## Qualification

A candidate can reach `RESEARCH-QUALIFIED` only when all configured gates pass:

- adequate discovery sample;
- adequate unseen sample;
- out-of-sample hit rate ≥ research threshold;
- lower confidence bound above the minimum robustness floor;
- positive out-of-sample paper ROI;
- acceptable calibration;
- no material degradation across walk-forward windows;
- replicated result on another untouched period.

## What the player sees

For a qualified paper signal, the UI should state:

- exact product;
- exact market;
- exact selection;
- minimum acceptable price;
- model probability;
- market/de-vig probability where available;
- estimated edge;
- validation sample;
- out-of-sample hit rate;
- out-of-sample ROI;
- robustness status;
- reason codes.

If any required field is missing, the instruction is `NO SIGNAL`.

## Research target

The desired outcome is not “predict every round.” The desired outcome is to determine whether any particular virtual product exposes a **persistent, observable, out-of-sample statistical advantage**.

If the data shows no such advantage, the correct engine output remains `NO SIGNAL`.
