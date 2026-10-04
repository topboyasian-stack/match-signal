# Match Signal ticket layer: final go/no-go report (paper / research only)

Audited: `topboyasian-stack/match-signal` @ `ee92b83` (branch cut from a later `main`; `scripts/` unchanged between them).
Not a profitability claim. Nothing on `main`, no data, archive, settlement record, gate or threshold was changed.

## DECISION
**ACCUMULATOR OBJECTIVE NOT VALIDATED.**
Recommendation: freeze the accumulator layer; do not change gates; re-run `scripts/vfootball_walkforward_audit.py` after more settled data accumulates.

## 1. What was wrong (file / function)
1. `scripts/odds_builder.py`, VFootball event-holdout lane: `calibrated_probability = max(float(prob), evidence_probability)`; the mixed lane uses `evidence.get("posterior_rate") or prob`. `evidence_probability` is the exact line's long-run hit rate, which is identical for every event, so the leg probability ignores the price.
   - 183 unique settled VFootball tracker legs: median |builder probability - evidence hit rate| = 0.004; builder 0.936 vs de-vigged market 0.849 vs realised 0.869; Brier 0.1072 (builder) vs 0.0944 (market).
   - Example: a live Under 3.5 priced at 1.62 (market ~0.59) shown as 0.806.
2. "Edge" = base rate minus price is adverse selection. Time-safe history, rows with base rate - de-vigged price >= 0.05: hit 64.9% vs market 65.2% vs base rate 73.3%; flat ROI -4.1%. Cells at edge >= 0.10 / 0.15 that look positive have n=30 / n=3 or 48 and are noise.
3. The 0.80 / 0.90 per-leg gates therefore admit legs the market prices much lower (pending VFootball legs: builder 0.863, market 0.667, mean odds 1.50).
4. `scripts/virtual_lab_model_eval.py` inverts the stored probability for Under rows (Brier 0.603 vs 0.126), so the 37% "market baseline" in the benchmark is not a fair comparison. The "Poisson" model is fitted to the same event's bookmaker ladder, so on the VFootball holdout it equals the true market (Brier 0.1238 vs 0.1243, 3,112 rows).
5. `MATCH_SIGNAL_BENCHMARK.md` ticket counts (43 / 19) are stale vs HEAD (40 / 24).
6. NOT the cause: correlation. Cross-event pairs within 60 min (808,703 pairs): observed joint / product of marginals = 1.044 (day-jackknife SE 0.018). The 0.91 per-pair decay points the wrong way.

## 2. What was changed
Repository, in PR #34 (draft): added `scripts/vfootball_walkforward_audit.py`, `TICKET_LAYER_AUDIT.md`, this report, and `patches/0001-vfootball-price-conditional-cap.patch`.
The patch (NOT applied) adds `PRICE_CONDITIONAL_CAP_VFOOTBALL=True` and, in `make_leg`, caps a VFootball leg's probability at the de-vigged SportyBet probability. Unit-tested with synthetic inputs only; the full Builder was not run with it.

## 3. Historical evidence: current strategy (HEAD, settled tickets)
| Set | Settled | Won | Accuracy |
|---|---|---|---|
| All | 40 | 13 | 32.5% |
| 2-4 leg family | 24 | 8 | 33.3% |
| 2-leg / 3-leg / 4-leg | 8 / 3 / 13 | 4 / 0 / 4 | 50% / 0% / 30.8% |

2-4 leg model-implied probability 66.7% vs realised 33.3%; ticket Brier 0.272 vs 0.154 for the bookmaker-implied baseline. Small samples; shows the layer is not validated, not future performance.

## 4. VFootball (time-safe walk-forward, 1,659 events, 85 hourly windows, combined odds >= 2.70)
Windows where a 2.70+ ticket existed from legs at or above the tier:
| Per-leg tier | 2 legs | 3 legs | 4 legs |
|---|---|---|---|
| >= 0.90 (production) | 0/85 | 0/85 | 0/85 |
| >= 0.80 (production) | 0/85 | 0/85 | 0/85 for Poisson probability (1 ticket under the calibrated variant) |
| >= 0.70 (diagnostic only) | 0/85 | 0/85 | 84/85 |
| >= 0.60 (diagnostic only) | 0/85 | 84/85 | 84/85 |

Median best reachable combined odds: tier 0.90 = 1.17 / 1.26 / 1.36; tier 0.80 = 1.44 / 1.70 / 1.98 (2/3/4 legs).

Diagnostic-tier tickets (84 tickets each; break-even accuracy ~36.9%; holdout = last 30%, ~23 tickets):
| Method / tier / shape | Predicted | Accuracy (Wilson 95%) | Brier | Avg odds | Flat ROI | Max drawdown (units) | Holdout acc / ROI |
|---|---|---|---|---|---|---|---|
| C 0.70 4-leg | 0.447 | 29.8% (21-40%) | 0.223 | 2.71 | -19.2% | 19.0 | 21.7% / -41.0% |
| C 0.60 3-leg | 0.455 | 32.1% (23-43%) | 0.236 | 2.73 | -12.1% | 22.8 | 26.1% / -29.3% |
| B/A 0.60 4-leg | 0.341 | 42.9% (33-54%) | 0.253 | 2.71 | +16.0% | 7.2 | 47.8% / +29.5% |
| E 0.70 4-leg (n=71) | 0.317 | 38.0% (28-50%) | 0.240 | 2.71 | +3.2% | 11.5 | 50.0% / +35.2% (n=20) |

The B and E intervals contain break-even, so these are not evidence of an edge. Methods A/B/C/D mostly change the probability label, not which ticket is picked. D91 lowers Brier only by pulling predictions toward the realised rate. Calibrated methods overpredict by ~15 points (0.45 vs 0.30), consistent with the live tracker.

## 5. eFootball GT (3,936 O/U rows, 1,880 events, 2026-09-21 to 2026-10-04)
- Holdout Brier (1,171 rows): market 0.2410, Poisson 0.2409, shape 0.2487, participant 0.2459.
- Participant model, edge >= 0.10, participant active (n=210): hit 61.9% vs market 56.7% vs model claim 68.9%; flat ROI +0.9% (event-cluster bootstrap 95% -10.4% to +12.2%). Overconfident: hit-minus-model -13.8 to -0.6 points.
- Participant probability >= 0.80 (n=29): hit 62.1% vs claim 82.9%; ROI -19.5%.
- Chronological thirds of the >= 0.10 bucket: ROI -9.5%, +3.0%, +9.3%. Monitor only; several models and thresholds were tried.
- Conclusion: no demonstrated edge; do not add eFootball to tickets. Mixed VFootball/eFootball tickets are unsupported.

## 6. Construction (2 / 3 / 4 legs)
No shape qualifies at the production tiers (0.80 and 0.90). Only at diagnostic tiers below the stated safety floor does any shape reach 2.70, and there the results are inconclusive or negative (section 4). Accuracy and 2.70+ odds cannot both be met from this data.

## 7. Production
- PR #34 (draft) is open against `main`; branch `audit/vfootball-ticket-walkforward`. GitHub checks: Netlify redirect/header rules success, "Pages changed" neutral, workflow `experiment` success. That workflow runs the **unpatched** Builder, so it does not validate the patch.
- Cloudflare deployment and production URLs (`match-signal.pages.dev`, GitHub Pages) were NOT verified: the sandbox network blocked them (`host_not_allowed`).

## 8. Booking code
NOT VERIFIED. No test batch, code generation, ticket match or UI check was run. No claim is made.

## 9. Does the proposed change survive an untouched holdout?
No ticket-layer improvement exists to hold out. The patch removes unconditional-rate "edge"; with it VFootball legs have no claimed edge over the price, so no batches qualify. That is the evidence-based result, not a gate change.

## Limits
Odds are recorded snapshots assumed bettable; history stores one side per line; holdout cells are small; VFootball rows lack participant names; method A is a proxy for the VFootball lane (Wilson bound and live evidence counters not reproduced); PR #31's calibration results (n=11 in the key subset) are supporting, not independent, evidence.

FINAL: ACCUMULATOR OBJECTIVE NOT VALIDATED
