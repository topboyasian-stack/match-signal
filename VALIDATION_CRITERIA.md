# Validation criteria for un-freezing the accumulator layer (paper / research only)

Written before collecting more evidence, so the pass/fail rule cannot be bent after seeing results.
Applies per engine (VFootball, eFootball GT); engines are never pooled.

## What must be true (all of them)
1. **Price-conditional probabilities.** Every leg probability used for gating must be conditioned on the current price/ladder (see `patches/0001-vfootball-price-conditional-cap.patch`). Unconditional line hit rates are not allowed to gate a leg.
2. **Forward, append-only log.** Each decision (legs, odds snapshot, model probability, model version) is written before the result exists. No edits after settlement.
3. **Frozen model version.** The model/gates are fixed for the whole test. Any change restarts the count.
4. **Sample size.** At least 2,600 settled tickets per engine for the ROI interval to be able to exclude zero when the true edge is about 5% at roughly 2.7 odds (per-ticket SD about 1.3 units; about 50% power). 5,300 tickets gives about 80% power. Windows must be counted from collection reality: the audit data had about 7 hourly windows per day, so 2,600 tickets is roughly a year unless collection runs continuously (24/day is about 110 days).
5. **Edge over the price.** Brier score better than the de-vigged market with a day-block bootstrap 95% interval that excludes zero.
6. **Money result.** Flat-stake ROI 95% interval (day-block bootstrap) with a lower bound above zero, at the odds actually recorded.
7. **Calibration.** Predicted vs realised hit rate within the interval in every probability band with n >= 30; no band overconfident by more than 5 points.
8. **Untouched holdout.** The last 25% of the test period (chronological) is not examined until criteria 1-7 pass on the earlier 75%, then it must pass as well.
9. **Leg quality.** Per-leg safety floors (0.80 preferred 0.90) stay as they are; they are never lowered to create batches.

If any item fails, the accumulator layer stays frozen. Predictions, the Prediction Desk, the Virtual Lab and booking-code generation are unaffected by the freeze.

## Status as of this audit (everything below FAILS the criteria)
- VFootball: leg model equals the market (Brier 0.1238 vs 0.1243, holdout 3,112 rows); 2.70+ from 0.80+ legs reachable in 0/85 windows.
- eFootball GT: participant signal adds nothing beyond price. A walk-forward logistic blend of market logit and participant gap (1,030 out-of-sample rows, participant-active) fitted a participant weight of about -0.03 to -0.10 (essentially zero), Brier 0.2405 vs market 0.2399 (gain -0.0007, day-block 95% interval -0.0013 to +0.0001).
- Participant model edge >= 0.10 bucket: n=210, ROI +0.9%, 95% interval -10.4% to +12.2%; model overconfident (claims 68.9%, realised 61.9%).

## What would genuinely help
Information the price does not already contain, evaluated against the price. For eFootball that means participant-level features beyond what the market ladder reflects (recent form windows, head-to-head, fatigue/streaks), tested with the walk-forward blend above. A signal only counts when it improves out-of-sample Brier over the market.
