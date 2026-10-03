# Match Signal Benchmark — 2026-10-03

This is a frozen diagnostic benchmark. It does **not** change Odds Builder selection rules or promote a new betting batch.

## What the evidence says

The underlying chronological holdout model is materially stronger than the current ticket construction on VFootball. On the untouched VFootball holdout, the Poisson model hit **81.73%** across 3,295 O/U rows, while the participant model reached **82.12%**. The SportyBet market baseline was **37.45%** on the same population.

eFootball GT is much weaker in the same holdout: Poisson **58.55%**, participant model **54.37%**, versus market **51.77%**. That means eFootball cannot currently be treated as an automatic accuracy booster merely because it is a different product.

The failure is concentrated in the ticket layer. Across 43 settled tickets, only **15 won and 28 lost (34.88%)**. For the active 2–4-leg family, there were 19 settled tickets: **7 won, 12 lost (36.84%)**.

Worse, the 2–4-leg tickets had an average model-implied joint probability of **70.59%**, while the realized hit rate was **36.84%**. The model probability Brier score was **0.282**, versus **0.149** for the simple bookmaker-implied baseline on those same tickets. The ticket layer is therefore overconfident and not merely suffering from a small sample of unlucky results.

### Construction shapes

| Shape | Settled | Won | Lost | Accuracy | Avg odds | Break-even | Unit ROI |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 legs | 7 | 4 | 3 | 57.14% | 1.696 | 58.95% | -35.44% |
| 3 legs | 1 | 0 | 1 | 0% | 5.28 | 18.94% | -100% |
| 4 legs | 11 | 3 | 8 | 27.27% | 3.376 | 29.62% | -24.33% |

The 2-leg sample is not large enough to establish a durable edge, and its average odds were far below the 2.80 target. The 4-leg sample is larger but currently fails both realized accuracy and ROI.

## Benchmark decision

**The project is not a dead end at the event-model level.** There is measurable walk-forward signal in VFootball.

**The current accumulator construction is not validated.** The benchmark shows a calibration/construction failure between strong individual-event probabilities and the combined ticket probability.

The next technical target is therefore not another generic gate or another arbitrary odds adjustment. It is to replace the current overconfident ticket probability layer with the time-safe calibrated event probabilities, then test 2–4-leg combinations against the same frozen historical rules before allowing them into production.

No claim of future profitability is made by this benchmark.
