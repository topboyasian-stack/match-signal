# Match Signal ticket-layer audit (paper / research only)

Audited against `topboyasian-stack/match-signal` @ `ee92b83` (branch cut from a later `main`; `scripts/` was unchanged between the two). No production data, archive or settlement record was modified.

## Verdict (provisional, pending your review)
ACCUMULATOR OBJECTIVE NOT VALIDATED for "2.70+ combined odds with 0.80+ per-leg probability" on VFootball.

## Root causes (proven from code and data)
1. **Leg probability is an unconditional base rate, not a price-conditional probability.**
   `scripts/odds_builder.py`, VFootball event-holdout lane: `calibrated_probability=max(float(prob),evidence_probability)`
   where `evidence_probability` is the exact-line posterior hit rate. The mixed lane uses `evidence.get("posterior_rate") or prob`.
   Across 183 unique settled VFootball tracker legs, median |builder probability - evidence hit rate| = 0.004.
   Builder probability averaged 0.936, de-vigged market 0.849, realised 0.869 (Brier 0.1072 vs 0.0944 for the market).
2. **"Edge" = base rate minus today's price is adverse selection.** Time-safe history (9,393 rows): rows where base rate exceeded
   de-vigged price by >= 0.05 hit 64.9%, matching the market (65.2%), not the base rate (73.3%); flat ROI -4.1%.
3. **The 0.80/0.90 gates therefore admit legs the market prices far lower.** Pending VFootball legs: mean builder probability 0.863,
   mean de-vigged 0.667, mean odds 1.50 (e.g. Under 3.5 at 1.62 shown as 0.806).
4. **Independence/correlation is not the cause.** Cross-event pair joint hit / product of marginals = 1.044 (jackknife SE 0.018, 808,703 pairs).
   The proposed 0.91 per-pair decay points the wrong way.
5. **The structure caps odds.** Median best reachable combined odds from distinct events within 60 min:
   tier >= 0.90: 1.17 / 1.26 / 1.36 (2/3/4 legs); tier >= 0.80: 1.44 / 1.70 / 1.98. 2.70 was reachable in 0 of 85 windows at 0.80+.
6. **Benchmark defects.** `virtual_lab_model_eval.py` inverts the stored probability for Under rows (Brier 0.603 vs 0.126 correct),
   so the 37% "market baseline" is not a fair comparison. The "Poisson" probability is fitted to the same event's bookmaker ladder,
   so VFootball model Brier (0.1238) equals the true market Brier (0.1243) on the holdout. `MATCH_SIGNAL_BENCHMARK.md` counts (43/19)
   are stale versus HEAD (40/24).

## Proposed change (patch included, NOT applied)
`patches/0001-vfootball-price-conditional-cap.patch`: in `make_leg`, a VFootball leg's probability may not exceed the de-vigged SportyBet
probability. Gates, thresholds and evidence requirements are unchanged. Synthetic unit tests: Under 3.5 @1.62 drops 0.806 -> 0.587 and is rejected.
Expected effect: no VFootball batches until a price-conditional model beats the price in time-safe evaluation. That is the honest
output of the evidence, not a gate change.

The patch was verified to apply cleanly to `ee92b83` (and `scripts/` is unchanged on later `main`). It is shipped as a patch because the 151 KB
`scripts/odds_builder.py` could not be safely re-uploaded through the available tooling. Apply with:
`git apply patches/0001-vfootball-price-conditional-cap.patch`

## Limits
Odds are recorded snapshots assumed bettable; history stores one side per line; holdout cells are small (~23 tickets);
diagnostic tiers 0.70/0.60 are not production eligible; booking-code and production-site checks not run.

## eFootball GT (same price-conditional test; read-only analysis)
Data: 3,936 settled O/U rows, 1,880 events, 2026-09-21 to 2026-10-04.
- Holdout (last 30%, 1,171 rows) Brier: true market 0.2410, Poisson 0.2409 (fitted to the same ladder), shape 0.2487, participant 0.2459.
- Participant model with edge >= 0.10 over the de-vigged price (participant active): n=210, hit 61.9%, market 56.7%, model claim 68.9%,
  flat ROI +0.9% (event-cluster bootstrap 95%: -10.4% to +12.2%). Hit-minus-model gap -13.8 to -0.6 points, so the model is overconfident.
- Rows with participant probability >= 0.80: n=29, hit 62.1% vs model 82.9%, ROI -19.5%.
- Chronological thirds of the >= 0.10 bucket improved (ROI -9.5%, +3.0%, +9.3%); treated as a monitor-only signal given multiple
  models/thresholds tried.
- Conclusion: no demonstrated edge over the price; do not add eFootball to tickets. Median selected odds 1.65, median model probability 0.684.
