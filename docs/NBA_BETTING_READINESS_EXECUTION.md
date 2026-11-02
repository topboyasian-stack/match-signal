# NBA totals betting-readiness execution priority

**Project:** Match Signal — topboyasian-stack/match-signal
**Production site:** https://match-signal.pages.dev
**Scope:** NBA full-game totals, SportyBet Nigeria market 225 (Over/Under including overtime)
**Mode:** Paper/research only. No auto-betting. No paid services.

> Resume rule: when work continues in a new chat, read this file first and begin at the first unchecked priority. Do not ask the user to repeat the repository, deployment, constraints, or goals. Make changes in this repository only; do not mix this work with Deriv Signal Desk.

## Non-negotiable rules

- Do not label Basketball betting-ready or unlock its ticket legs until every release gate below passes.
- Use only exact SportyBet Nigeria market 225 event/line/Over odds/Under odds with a quote observed no more than 15 minutes before publication.
- Never substitute another bookmaker, infer a line, borrow a neighbouring event, or reuse stale odds.
- Keep the model projection independent of bookmaker prices. Prices may be used only after projection to calculate value.
- Treat one ESPN event ID as one independent settled fixture for ROI and confidence calculations. Repeated quote snapshots are not extra bets.
- Freeze model versions and evaluation dates. Do not move the holdout boundary after seeing outcomes.
- Keep the Basketball leg release gate. No manual-only bypass and no generated booking codes for unqualified NBA legs.

## Verified baseline at the start of this work

Latest inspected artifacts were generated around **2026-11-02 02:00 UTC**:

- NBA totals v5 had **5** verified settled market-225 selections: **1 win, 4 losses**, **20% accuracy**, **-3.05 units**, **-61% ROI**. This is the relevant v5 betting cohort. The 60 legacy records (all Over) are not evidence for v5 accuracy.
- The five v5 outcomes:
  - Charlotte Hornets–Philadelphia 76ers: projection 209.12, SportyBet 212.5, Under @1.88; final 213 — loss.
  - New Orleans Pelicans–Atlanta Hawks: projection 235.24, line 240.5, Under @1.95; final 220 — win.
  - San Antonio Spurs–Minnesota Timberwolves: projection 225.30, line 228.5, Under @1.95; final 232 — loss.
  - Houston Rockets–Oklahoma City Thunder: projection 223.11, line 219.5, Over @1.93; final 217 — loss.
  - Orlando Magic–Boston Celtics: projection 229.11, line 223.5, Over @1.89; final 205 — loss.
- The previously reported rolling historical forecast holdout was 238 games (MAE 15.2178 vs 16.2885 baseline), but its end boundary moved as new games arrived. It is not a frozen prospective betting test and does not prove positive betting value.
- Price capture checked 54 upcoming v5 fixtures: 11 exact fresh market-225 matches, 41 fixtures absent from the SportyBet feed, and 2 start-time mismatches over 45 minutes. The feed returned 11 events, all with market 225, without a source error. Missing prices are a real coverage limitation, not permission to guess.
- Current release status is **RESEARCH_ONLY**.

## Ordered execution list

### P0 — establish valid evidence before changing pick logic

1. [x] Recover the actual main repository state and audit the v5 verified settled cohort and current SportyBet price-coverage counts.
2. [x] Freeze the prospective evaluation cutoff at **2026-11-02 02:00:00 UTC**. Forecast games and market bets published before this cutoff belong to development; only games/bets at or after it count as prospective holdout. The cutoff must never roll forward.
3. [x] Produce the exact per-fixture failure audit: model projection, SportyBet line, projection edge, chosen side, both saved prices, quote age, final total including overtime, projection error, result, and selected-side ROI. Count each ESPN event once.
4. [x] Run the fixed-cutoff walk-forward and price-capture regression suite in GitHub Actions. Regenerate the live evaluation JSON from the current production data and verify the fixed cutoff is present. If this run fails, fix it before proceeding.
5. [x] Diagnose SportyBet coverage gaps by exact fixture and time. Distinguish not listed, time mismatch, stale/missing quote, market 225 unavailable, and unusable odds pair. Inspect the live proxy/feed response before changing query parameters. Preserve exact market, event, price, and freshness contracts.

### P0 — build a stronger score model using historical development data only

6. [x] Screen v6 separately from v5. The experiment has not found an upgrade that passes the robustness gate; production remains v5.
7. [x] Backtest venue splits, rest, schedule density, recent team scoring/defense form, recent pace/efficiency, and recent possession/efficiency individually and in combinations. No candidate passed the robustness gate. The archive has no turnover or rebound fields.
8. [x] Omit injury and starting-lineup features from this experiment: the existing historical archive has no timestamped player-availability or lineup fields, so those features cannot be reproduced from it.
9. [x] Compare candidates against v5 and the 90-day baseline using the fixed historical window, four chronological blocks, and paired bootstrap. No candidate passed; no feature retained.
10. [x] Preserve the frozen prospective cutoff. All v6 experiments exclude games at or after 2026-11-02 02:00 UTC.

### P1 — replace point-edge picks with probability and value decisions

11. [x] Implement an empirical residual score distribution with Over/Under probabilities and integer-line push handling as a research experiment. Score-interval coverage passed; market-probability calibration is not established.
12. [x] Implement exact fresh SportyBet market-225 no-vig probability comparisons and expected-value calculations in the research report only. There are no historic odds in the archived NBA game log.
13. [x] Add predeclared probability-edge and EV thresholds with a bootstrap lower bound. These classifications are diagnostic only and cannot authorize betting or tickets.
14. [ ] Finish probability validation. Descriptive model-vs-market Brier/log-loss is now emitted, but the five-record v5 comparison is too small and favours market no-vig prices (model Brier 0.309877 vs 0.251600; model log-loss 0.816446 vs 0.696347). A real-snapshot CLV audit is also emitted: only 2/5 had a quote within 45 minutes of tip, 1/2 had positive no-vig probability CLV, and 0/2 had positive line CLV. Continue collecting at least 30 unique market-settled fixtures before interpreting market probability calibration; never call the last captured quote an official bookmaker close.

### P1 — prospective validation and release gate

15. [ ] Collect at least **100 unique settled prospective market-225 selections**; target **200** before release. Every record must have an immutable pregame snapshot, fresh exact SportyBet prices, both sides, timestamp, line, selected side, and official ESPN settlement.
16. [ ] Require positive flat-stake ROI after actual selected-side odds, a positive bootstrapped 95% lower confidence bound, and ROI greater than the market-favourite benchmark.
17. [ ] Require positive closing-line value where a genuine later SportyBet quote is available. Never reconstruct closing prices.
18. [ ] Require at least **100 post-cutoff forecast games** with lower MAE than the development baseline and absolute bias no greater than 3 points.
19. [ ] Keep the release decision RESEARCH_ONLY until all forecast and market requirements pass. No shortening sample thresholds to force qualification.

### P2 — production and ticket release

20. [ ] Re-run Basketball page, live feed, settled results, odds display, and ticket-builder regression tests against the latest main.
21. [ ] Verify each NBA ticket leg against a fresh exact SportyBet 225 event/line/side/price immediately before code generation. Reject the whole slip if any leg is missing, stale, changed, started, or not model-qualified.
22. [ ] Unlock NBA ticket selection/code generation only after the model passes the prospective gates and the production smoke tests pass. Keep paper/research-only controls visible until then.

## Verified completion checkpoint — 2026-11-02

- Priorities **1–5 complete**. Fixed prospective cutoff is 2026-11-02T02:00:00+00:00; it is a constant in the evaluator and is asserted by CI.
- Run `41376360070` passed every step: compile, six walk-forward test groups, price-capture tests, live capture, fixed-cutoff report verification, and publication.
- A later run on commit `9c9a5e1` also passed all steps and published the expanded per-fixture audit with both Over/Under prices, selected-side profit, and favourite-benchmark profit.
- The current evaluation JSON reports 1,188 pre-cutoff forecast development games, zero post-cutoff completed forecast games, five verified v5 market selections (one win/four losses), and zero prospective settled market bets. Release remains `RESEARCH_ONLY`.
- Latest live price capture classified 54 upcoming predictions as 11 exact market-225 matches, 40 fixtures not listed in SportyBet's feed, one matched fixture with market 225 not offered, and two start-time mismatches over 45 minutes. The feed returned 12 events, 11 with market 225, without a provider error. These remain unpriced rather than guessed.

## Verified v6 feature-experiment checkpoint — 2026-11-02

- V3 workflow run `41377733780` passed, including its regression suite and report publication.
- Fixed historical blocks: 949 training games (2025-11-08 through 2026-03-25) and 239 validation games (2026-03-26 through 2026-11-01). The prospective cutoff at 2026-11-02 02:00 UTC was not used.
- V5 validation: MAE 15.2774, RMSE 19.8615, bias -1.3826. Best candidate remained seven-day schedule density (MAE 15.2590; gain 0.0184), but paired 95% CI was -0.0391 to 0.0747 and it improved only 2/4 chronological blocks.
- Recent possessions/efficiency also failed to improve validation (MAE 15.3060; RMSE 19.9486). Overall decision: `KEEP_V5_BASELINE_NO_FEATURE_UPGRADE`. Do not promote v6.
- Latest artifact: `data/nba_totals_v6_feature_experiment.json`.

## Verified snapshot CLV and descriptive probability score checkpoint — 2026-11-02

- The CLV-capable probability report workflow run `41378184275` passed all steps. The audit starts from each bet's exact immutable opening publication snapshot and considers only later exact SportyBet market-225 quotes observed before tip-off.
- Only **2 of 5** v5 settled fixtures had a later observation within 45 minutes of start. One of those two had positive selected-side no-vig probability movement; **zero of two** had favourable selected-side line movement. This is not an official bookmaker closing line; it is the latest captured pregame quote within a defined 45-minute window.
- The five-record descriptive comparison returned model Brier **0.309877** vs market no-vig **0.251600**, and model log-loss **0.816446** vs market no-vig **0.696347**. Sample size is 5, so this is a warning only, not a calibrated conclusion.

## Verified probability/value research checkpoint — 2026-11-02

- Probability/value workflow run `41377767053` passed its tests, experiment, safety checks, and report publication.
- Empirical residual calibration used 658 training games, 291 calibration residuals, and 239 later validation games. Observed validation coverage was 51.05% for nominal 50%, 77.82% for nominal 80%, and 85.36% for nominal 90%. This checks score-residual intervals only; it does not prove market probability calibration.
- On the five verified v5 settled market-225 records, the research layer issued two value classifications; both lost. The other three were `NO BET`. Treat this as adverse but very small evidence, not a performance estimate.
- The archived 1,228-game history has empty market objects on all rows: no historical SportyBet lines or odds exist for a meaningful historical ROI or CLV backtest. Current work must build prospective immutable evidence instead.
- The research report checked 11 exact fresh market-225 upcoming pairs; 43 of 54 upcoming predictions remained without an exact fresh pair. It never authorizes betting or ticket generation.
- Latest report: `data/nba_totals_probability_value_experiment.json`. Production remains v5, Basketball ticket gate remains locked, and release remains `RESEARCH_ONLY`.

## Next execution priorities

15. [ ] Collect at least 100 unique prospective settled market-225 selections; target 200. Every bet needs a fresh exact snapshot and official ESPN result.
16. [ ] Require positive ROI, positive bootstrapped 95% lower bound, ROI above the market-favourite baseline, and positive closing-line value where a later real quote exists.
17. [ ] Require at least 100 post-cutoff forecast games with lower MAE than the development baseline and absolute bias no greater than 3 points.
18. [ ] Keep `RESEARCH_ONLY` until every forecast and market gate passes.
19. [ ] Run Basketball page, live feed, settled results, odds display, and ticket-builder regression tests against latest main.
20. [ ] Revalidate every NBA ticket leg against exact fresh SportyBet 225 event/line/side/price immediately before code generation; reject the whole slip if any leg is invalid.
21. [ ] Unlock NBA ticket selection/code generation only after all prospective gates and production smoke tests pass.

**Next action on resume:** inspect probability/value workflow run `41378471896` and the historical synthetic-line probability validation it publishes. Then continue priority 14 with prospective probability scoring and actual pregame snapshot coverage. Never promote a value classification to a betting recommendation from these research artifacts.
