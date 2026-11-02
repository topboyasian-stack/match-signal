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

## Verified prospective probability scoring and snapshot-linkage checkpoint — 2026-11-02

- Commit `d7a78cc9027f8df2ed79816464efdf75a0ef19c4` passed probability/value workflow run `41379322954`, including compile, all probability/value regression tests, report generation, fixed-cutoff/paper-only assertions, and publication.
- The refreshed historical synthetic-line report evaluates 239 unique validation games across 1,652 non-push game/line observations. A 4,000-resample game-clustered bootstrap reports model-minus-coinflip Brier difference `-0.011014` (95% CI `[-0.017559, -0.004461]`) and log-loss difference `-0.022337` (95% CI `[-0.035958, -0.008706]`). Repeated synthetic lines are treated as measurements within each game, not independent games. This remains a historical synthetic-line test, not a SportyBet market backtest.
- The report now separately audits post-cutoff records against the exact immutable `data/nba_totals_publication_snapshots.json` entry, matching event ID, snapshot ID, publication/start/quote times, SportyBet event ID, market 225, line and both prices. It emits separate prospective probability scores only for uniquely settled records whose exact snapshot linkage passes.
- First refreshed report (generated `2026-11-02T02:45:21Z`) showed **7 prospective fresh market-225 snapshot records across 7 unique fixtures**, all passing snapshot verification; **0** prospective settled market selections and **0** post-cutoff probability-scored fixtures. The 30-fixture minimum is not met; this is correct, not a workflow failure.
- The probability/value workflow is scheduled hourly to refresh prospective coverage as the free quote-capture and settlement jobs run.
- Follow-up commit `af3f2bf5c51484fb98f2b024ecc4610bd6c04a05` normalizes Over/Under probability comparisons conditional on no push; EV continues to treat a push as zero profit. Its first workflow run `41379497595` caught a test assertion comparing the deliberately rounded `0.3333` output to full-precision `1/3`. The test was corrected to a rounding tolerance in commit `81a7741e217c6c881b02e0b870b50ca937c3d1cc`; workflow run `41379598381` then **passed every step** (compile, 12 regression groups, report generation, cutoff/snapshot/paper-only assertions, and report publication).
- Refreshed report generated `2026-11-02T02:48:09Z`: the fixed cutoff remains `2026-11-02T02:00:00+00:00`; all 7 post-cutoff snapshot records across 7 unique fixtures still pass exact fresh SportyBet market-225 snapshot checks, but there are 0 prospective settled market selections and 0 exact-snapshot-linked settled observations. The 30-fixture probability-validation minimum remains unmet; the prospective Brier/log-loss fields are null as they should be. The five older v5 rows still show model Brier `0.309877` vs market `0.251600` and model log-loss `0.816446` vs market `0.696347` and remain a warning only.
- Latest published historical synthetic-line diagnostics continue to show game-clustered improvement over coin-flip (239 unique games; Brier difference 95% CI `[-0.017559, -0.004461]`, log-loss difference 95% CI `[-0.035958, -0.008706]`). These are not actual SportyBet-market calibration metrics.
- The exact-linkage audit was further tightened in commits `c7d9530571d388c6ff7a107b25b55ef218db2170` and `b843e82afbe7960168ebc47d015afbc56d0f5302`: a scored settlement must match the V5 model version, a unique immutable snapshot ID, event/start/publication/quote times, SportyBet event ID and market 225, the selected Over/Under side, both the top-level frozen projection and market-attached projection, the exact line, and both odds. Regression cases reject altered price, side, or projection. The final workflow run `41379870128` passed all steps, including regression tests, report generation, fixed-cutoff/paper-only checks, and publication.
- That run's report was generated at `2026-11-02T02:51:31Z` and remains `RESEARCH_ONLY`: 7 verified post-cutoff snapshots across 7 fixtures, zero settled prospective market selections, and zero prospective probability-scored fixtures. The 30-fixture threshold is still unmet.
- A subsequent price-capture run `41379932409` passed every step and refreshed `data/nba_totals_price_capture_status.json` at `2026-11-02T02:52:00.969Z`: no feed error and 11 exact fresh matches among 54 upcoming V5 predictions. This capture completed after the 02:51 probability report, so the next probability report should be checked against the newest snapshot file rather than assuming the previous report already includes it.
- Settlement ledger run `41380021200` completed successfully at `2026-11-02T02:53:01Z`, including settlement tests, reconciliation, and ledger persistence. The latest ledger has `updated_at=2026-11-02T02:52:55.017688Z`, 68 total records / 68 settled records across all cohorts, but still only 5 settled V5 records and 0 settled prospective V5 records. Its event was `workflow_dispatch`, so it proves the settlement code and ledger write path work; it does not, by itself, prove the declared 15-minute `schedule` trigger is firing.

- No release gate has been relaxed: status stays `RESEARCH_ONLY`, the Basketball ticket gate remains locked, and priority 14 remains unchecked until a minimum 30 uniquely settled prospective market-225 fixtures can be scored against exact immutable opening snapshots. The separate 100-bet/200-target ROI and forecast holdout requirements still apply.
- Release is still `RESEARCH_ONLY`; Basketball ticket selection/code generation remains locked. Do not treat historical synthetic-line metrics or fresh but unsettled snapshots as betting proof.

## Next execution priorities

15. [ ] Collect at least 100 unique prospective settled market-225 selections; target 200. Every bet needs a fresh exact snapshot and official ESPN result.
16. [ ] Require positive ROI, positive bootstrapped 95% lower bound, ROI above the market-favourite baseline, and positive closing-line value where a later real quote exists.
17. [ ] Require at least 100 post-cutoff forecast games with lower MAE than the development baseline and absolute bias no greater than 3 points.
18. [ ] Keep `RESEARCH_ONLY` until every forecast and market gate passes.
19. [ ] Run Basketball page, live feed, settled results, odds display, and ticket-builder regression tests against latest main.
20. [ ] Revalidate every NBA ticket leg against exact fresh SportyBet 225 event/line/side/price immediately before code generation; reject the whole slip if any leg is invalid.
21. [ ] Unlock NBA ticket selection/code generation only after all prospective gates and production smoke tests pass.

**## Latest verified continuation checkpoint — 2026-11-02 03:58 UTC

This checkpoint supersedes the earlier “Next action on resume” paragraph. The frozen prospective cutoff remains 2026-11-02T02:00:00+00:00. No release threshold was relaxed.

### First unchecked priority: 14 — prospective sample

- The probability/value report was regenerated at 2026-11-02T03:55:44.621470+00:00 by workflow run [41385591647](https://github.com/topboyasian-stack/match-signal/actions/runs/41385591647), which completed successfully. Its release decision remains RESEARCH_ONLY.
- The report contains 103 verified fresh market-225 snapshot records across only 13 unique prospective fixtures. There are 0 uniquely settled prospective market-225 selections, 0 exact-snapshot-linked settled selections, and 0 linkage failures. The minimum of 30 unique settled fixtures is not met; repeated snapshots are not independent bets.
- The latest fixed-cutoff OOS report was generated at 2026-11-02T03:53:36.155268+00:00. Post-cutoff forecast holdout n=0, MAE/bias and baseline comparison are unavailable, and market holdout n=0 with ROI/95% lower bound/market-favourite comparison unavailable. The 100-game forecast condition and all prospective ROI/CLV conditions remain unmet.
- Latest price capture [41385445549](https://github.com/topboyasian-stack/match-signal/actions/runs/41385445549) passed at 2026-11-02T03:53:41Z. It observed 13 exact fresh SportyBet Nigeria market-225 pairs, added 13 immutable snapshots (193 current-model snapshots / 206 total records), and reported no feed error. Only 13 of 64 model predictions had a fresh pair; 51 remain unpriced/unavailable. The 13 post-cutoff fixture IDs have repeated snapshots, not 13 independent settled bets.
- Settlement ledger last updated at 2026-11-02T03:51:04.190847+00:00: 68 settled records overall; only 5 v5 records settled, with 1 correct (20% accuracy). The current ROI-eligible v4/v5 cohort has 8 selections and −51.25% flat-stake ROI. No post-cutoff market-225 selections have settled.

### Data-pipeline fixes and evidence

- Corrected the report cadence so it runs after price capture (:07/:22/:37/:52) and settlement (:10/:25/:40/:55), at :12/:27/:42/:57. Added schedule-order assertions and a 10-minute freshness throttle. The research workflow also now listens for successful price-capture and settlement completions, so it does not depend on cron alone. The workflow/test change is in [e344c869](https://github.com/topboyasian-stack/match-signal/commit/e344c869aca42625afbc306d123aa9e7df523bb2); run [41385591647](https://github.com/topboyasian-stack/match-signal/actions/runs/41385591647) passed the schedule assertion, probability/value tests, paper-only/cutoff checks, and report publication.
- Added a successful-price-capture backup trigger to the settlement workflow, throttled when the ledger was refreshed within 10 minutes: [8930a8a](https://github.com/topboyasian-stack/match-signal/commit/8930a8a15712b66dbf0b3fd9d638440266817887). The push-triggered settlement run [41385242159](https://github.com/topboyasian-stack/match-signal/actions/runs/41385242159) passed and refreshed the ledger. The follow-on event-driven settlement run [41385493568](https://github.com/topboyasian-stack/match-signal/actions/runs/41385493568) also passed; it correctly skipped reconciliation/persistence because the ledger was still fresh.
- Added final Builder Production Promotion as a direct price-capture trigger: [606d599](https://github.com/topboyasian-stack/match-signal/commit/606d59907906989f67dc6e3152ce35d85182822a). The capture workflow ran successfully on push, but the promotion-triggered branch still needs a future run to independently verify it.
- The Actions query returned no NBA totals runs with event=schedule in the 03:00–03:58 UTC window. Event-driven capture/settlement/report paths are now configured as a backup. The capture-to-settlement backup has been exercised successfully; the new report workflow_run trigger still needs a post-change capture/settlement event to verify it, and report timestamps must remain newer than the latest price-capture and ledger timestamps.

### Production and ticket gate

- Latest completed Cloudflare production smoke-test run: [41385733921](https://github.com/topboyasian-stack/match-signal/actions/runs/41385733921), source commit e98d5f4eba068f640a8a999d567f5413e26652e3, build ID MS-UNIFIED-20261102-e98d5f4eba06, immutable deployment [ab308571.match-signal.pages.dev](https://ab308571.match-signal.pages.dev) (production alias [match-signal.pages.dev](https://match-signal.pages.dev)). The run passed 20-page, 52-asset, and NBA ESPN-proxy smoke tests.
- The persisted production verification record at main HEAD cd5072173b941bafb6cd1a29ffe79bb752cd8918 is VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE: core pages are verified, but Qualified Best has VALID_ZERO coverage with 0 model-qualified rows and the booking API POST check is NO_FUTURE_BATCH (no fully future 2+ leg batch was available, so no booking code was requested). The deployment is current for site/data source e98d5f4; the only later main changes observed so far are verification/checkpoint records. Builder Production Promotion run [41384741905](https://github.com/topboyasian-stack/match-signal/actions/runs/41384741905) completed successfully, while [41385043586](https://github.com/topboyasian-stack/match-signal/actions/runs/41385043586) remains in progress and may publish another Builder artifact. Recheck production after that run; do not treat the deployment state as final until any resulting deployment also passes smoke tests.
- Basketball release qualification and ticket-code generation remain fail-closed. No auto-betting was enabled, and no release gate was unlocked.

### Next action on resume

1. Re-read this file, current main, the latest probability/value and OOS reports, the settlement ledger, fresh market-225 snapshots, and current Actions/deployment state.
2. Confirm the queued deployment and Builder Promotion statuses; verify any subsequent capture-triggered settlement/report runs and confirm the report timestamp is newer than the latest capture and ledger timestamps.
3. Continue Priority 14 only: collect genuinely prospective, exact-market-225 selections and settle them only from official ESPN results. Do not start Priority 15 until at least 30 unique prospective market-225 fixtures have settled and every other release condition is independently proven. Keep RESEARCH_ONLY and the Basketball ticket gate locked.

## Latest verified continuation checkpoint — 2026-11-02 04:30 UTC

This checkpoint supersedes the earlier 03:58 UTC production/ticket notes above. The fixed prospective cutoff remains `2026-11-02T02:00:00+00:00`. No release threshold was relaxed.

### Production ticket identity defect fixed and deployed

- Fixed the NBA ticket identifier contract. Basketball ticket markup now sends the ESPN prediction ID in `event_id` and the exact SportyBet provider event ID separately in `sportybet_event_id`.
- The shared ticket drawer stores and submits both IDs, rejects legacy NBA ticket rows without the provider ID, and retains the ESPN ID for prediction/settlement identity.
- The server resolves current SportyBet catalogue events by `sportybet_event_id`, retains ESPN `event_id` for the unique V5 prediction lookup, confirms that the provider ID equals the immutable quote's SportyBet event ID, and rejects duplicate provider IDs in a manual NBA slip.
- Current main implementations: `basketball-live.js`, `ticket-drawer.js`, `functions/api/sportybet-booking.js`; page references use `ticket-drawer.js?v=20261102-split-event-identifiers1` and Basketball's script uses `ids=20261102-split-event-identifiers3`.
- Replaced the dedicated server guard regression cases with tests for distinct ESPN/SportyBet identifiers, whole-slip rejection when one NBA leg cannot be resolved, code withholding after partial SportyBet acceptance, and the locked `RESEARCH_ONLY` release gate.
- Regression evidence: NBA ticket fail-closed workflow [41387172963](https://github.com/topboyasian-stack/match-signal/actions/runs/41387172963) passed; shared Ticket Drawer Contract workflow [41387404347](https://github.com/topboyasian-stack/match-signal/actions/runs/41387404347) passed; deployment's Basketball desk, NBA live projection/release-gate and shared ticket checks all passed.
- Updated the Cloudflare production smoke-test markers to expect the new shared drawer asset. Used the ordered Builder Production Promotion path: pre-build board -> Builder -> post-build board -> child Builder -> Pages deploy. The child board correctly set `SKIP_PROMOTION=true` and dispatched its required Builder handoff; this was not a recursive promotion loop.
- Cloudflare production workflow [41388664157](https://github.com/topboyasian-stack/match-signal/actions/runs/41388664157) completed **successfully** at 2026-11-02T04:30:04Z. Its steps passed artifact verification, Pages deploy, production HTTP/asset smoke tests, live-source diagnostic, production verification record, and final checkout.
- Production verification file `DEPLOY-VERIFY-CLOUDFLARE.json` is `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE`: core pages verified; Qualified Best diagnostic is `VALID_ZERO` (239 candidate rows, 0 model-qualified); booking API diagnostic is `NO_FUTURE_BATCH` because no fully future 2+ leg batch was available to exercise a production POST. No live booking code was fabricated or requested.
- Important: software ticket identity/validation is fixed and deployed; successful end-to-end NBA code generation is still not production-verified because the global release gate is locked and no qualified NBA batch exists. Do not mark the NBA booking POST path fully proven.

### Model challenger result — no production promotion

- Added an isolated nonlinear residual challenger experiment, with chronological training folds and the same frozen historical validation interval. It does not use bookmaker prices, does not touch the live V5 model, and does not use the prospective holdout for tuning.
- Experiment workflow [41387639127](https://github.com/topboyasian-stack/match-signal/actions/runs/41387639127) passed. It used 949 training games and 239 historical validation games.
- V5 validation: MAE 15.2774, RMSE 19.8615, bias -1.3826. Best ExtraTrees residual candidate: MAE 15.1759, RMSE 19.7986, bias -0.985. MAE improvement was only 0.1015 points, and its paired fixture-bootstrap 95% CI for the improvement was -0.1576 to +0.3660. The confidence interval crosses zero.
- Decision: `KEEP_V5_NO_NONLINEAR_PROMOTION`. ExtraTrees is not promoted. Production remains `nba-total-v5-pace-efficiency-calibrated`; no evidence supports claiming a reliable model improvement.

### Latest prospective evidence — still not betting-ready

- Latest fixed-cutoff OOS report: generated `2026-11-02T04:25:54.902934Z`; release remains `RESEARCH_ONLY`.
  - Post-cutoff forecast holdout: 0 games; MAE, bias and baseline comparison unavailable.
  - Post-cutoff settled market holdout: 0 selections.
  - Development market cohort: 6 selections, 2 wins / 4 losses, -2.12 units, -35.33% flat-stake ROI, bootstrap lower bound -100%.
  - Publication capture summary: 64 model predictions; 13 exact fresh SportyBet market-225 pairs; 258 immutable fresh snapshots across 23 unique snapshot events; 51 predictions unpriced/unavailable; capture status PARTIAL.
- Latest probability/value report: generated `2026-11-02T04:26:49.201831Z`; release remains `RESEARCH_ONLY`.
  - 168 verified fresh prospective snapshots across 13 unique fixtures.
  - 0 prospective settled market selections; 0 exact-snapshot-linked settled selections; 0 linkage mismatches.
  - 0 prospective probability-scored fixtures; 0 near-close CLV observations.
- Latest price-capture status: `2026-11-02T04:25:48.797946Z`: 13 exact fresh matches among 54 upcoming V5 predictions, from 13 feed events with market 225. Unmatched diagnoses: 39 not listed in the current feed and 2 start-time mismatches; do not mislabel these as 41 confirmed code defects.
- The next NBA slate has not yet settled relative to the frozen cutoff. Re-running capture, settlement or report workflows cannot create settled prospective evidence before official final scores exist.

### First execution priority on resume

1. Re-read this file, latest `main`, latest OOS/probability/capture reports, settlement ledger and current Actions/Cloudflare state.
2. Preserve the new ESPN/SportyBet dual-ID ticket contract and its regression tests. Do not roll back to a single event ID.
3. Keep the release gate locked. Continue the existing exact market-225 capture and official ESPN settlement process as games become available; preserve immutable snapshots and one observation per unique ESPN fixture.
4. Continue only evidence-based model research. Do not promote V6/ExtraTrees or change V5 based on a small, statistically unstable historical improvement. Any new candidate must use timestamp-safe features, chronological validation, paired fixture-level uncertainty and no bookmaker-price leakage.
5. Do not mark betting-ready until the existing 100 prospective settled market selections, 30 unique probability scores, positive ROI/95% lower bound/market-favourite comparison, positive probability and line CLV, and 100-game post-cutoff MAE/bias gates all pass. Do not change the frozen cutoff or thresholds.


## Production calibration alignment correction — 2026-11-02

- Corrected a material model-path mismatch: live NBA predictions were calling `nba_predict()` with the uncalibrated defaults (pace blend 0.0, bias correction 0.0), while the probability experiment had been using the frozen calibrated parameters (pace blend 0.8, bias correction 0.3542). Those are different forecast models and must not share one evidence cohort.
- Introduced model identity `nba-total-v5.1-pace-efficiency-calibrated`. Live publication now defaults to the frozen 0.8 pace/efficiency blend and subtracts 0.3542 points. The fixed-cutoff evaluator and residual-probability calibration use those same frozen parameters; no parameter re-fit occurs on calibration or prospective holdout outcomes.
- Updated the Basketball client and server booking release checks to require the v5.1 model identity. Historical v5 snapshots/settlements remain historical only and are not relabelled or counted as v5.1 evidence. Fresh v5.1 SportyBet snapshots and settled fixtures form a new, auditable cohort.
- Added regressions for the live forecast defaults, fixed-cutoff evaluator parameters, residual-calibration parameter identity, and the matching client/server release model version.
- The frozen prospective cutoff remains `2026-11-02T02:00:00+00:00`; no sample-size or performance gate was relaxed. NBA remains `RESEARCH_ONLY` until the prospective model, probability, ROI, CLV, settlement and booking release gates pass.

## Latest continuation checkpoint — 2026-11-02 08:32 UTC

This is the active resume point. The frozen prospective cutoff remains `2026-11-02T02:00:00+00:00`. No sample-size, odds-freshness, ROI, CLV, forecast, or release threshold was relaxed. The latest main HEAD observed before this checkpoint edit is `4f2bccd5c711e1c33d21eae40804a7ac8fb94748`; the NBA work remains confined to `topboyasian-stack/match-signal`.

### First unchecked priority: 14 — prospective probability validation

- The current probability/value report was regenerated and published by [workflow run 41411409102](https://github.com/topboyasian-stack/match-signal/actions/runs/41411409102), successful at 2026-11-02T08:14:01Z. It includes the new report-refresh regression test, schedule-order assertions, compile/tests, report generation, paper-only/cutoff checks, and publication.
- The latest probability/value report was published by [run 41413229892](https://github.com/topboyasian-stack/match-signal/actions/runs/41413229892), successful at 08:28:52Z, and generated at `2026-11-02T08:28:31.264291+00:00` after the 08:27 capture and 08:28 settlement reconciliation. It contains **240 verified market-225 snapshot records across 15 unique fixtures**, **0 prospective settled market selections**, **0 exact-snapshot-linked settled selections**, **0 probability-scored fixtures**, **0 near-close CLV observations**, and **0 linkage failures**. These 240 are repeated price observations across 15 fixtures, not 240 bets. It reports **15 current exact-fresh-pair diagnostics** and **39 predictions without an exact fresh pair**. The report timestamp is newer than the latest capture (08:27:22Z) and ledger update (08:28:01Z).
- The latest fixed-cutoff OOS report was regenerated by the 08:27 capture at `2026-11-02T08:27:26.084770+00:00`: only **4** post-cutoff forecast games, model MAE **26.7875** versus development-baseline MAE **24.75**, and absolute bias **6.4637**. It does not beat baseline and fails the bias limit. The market holdout has **0** settled selections, so ROI, confidence bound, and favourite-benchmark comparison are unavailable. Do not tune the model to these four holdout outcomes.
- The settlement ledger remains updated at `2026-11-02T06:49:38.350315+00:00`: **70** settled records overall (60 legacy, 7 v5, 3 v4), but **0** records published at/after the frozen cutoff and **0** v5.1 prospective settled selections. Legacy/v4/v5 records do not satisfy the new v5.1 prospective gate.
- The newest capture is [run 41413103812](https://github.com/topboyasian-stack/match-signal/actions/runs/41413103812), successful at 08:27:36Z. Its status file was checked at `2026-11-02T08:27:22.895247+00:00`: 15 exact fresh SportyBet Nigeria market-225 pairs and 15 immutable snapshots were added, with no feed error; 39 predictions remain unpriced/unavailable. Settlement run [41413229866](https://github.com/topboyasian-stack/match-signal/actions/runs/41413229866) succeeded at 08:28:07Z, refreshed the ledger to `2026-11-02T08:28:01.842933+00:00`, and left it at 70 settled records with zero prospective records. Report run [41413229892](https://github.com/topboyasian-stack/match-signal/actions/runs/41413229892) succeeded at 08:28:52Z and regenerated the report from the latest data. Quotes must still be revalidated immediately before any future ticket code generation. See [capture status](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_price_capture_status.json), [probability/value report](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_probability_value_experiment.json), [fixed-cutoff OOS report](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_oos_value_test.json), and [settlement ledger](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_ledger.json).

### Workflow defect fixed and verified

- Capture run [41402742523](https://github.com/topboyasian-stack/match-signal/actions/runs/41402742523) succeeded at 06:53:41Z. The event-driven probability run [41402805150](https://github.com/topboyasian-stack/match-signal/actions/runs/41402805150) also completed successfully, but its refresh gate skipped report generation: the previous report was under 10 minutes old even though the capture had published newer snapshot/status data. Its remaining research steps were skipped, leaving the report stale.
- Added `scripts/nba_totals_report_refresh_gate.py` and `scripts/test_nba_totals_report_refresh_gate.py`; changed `.github/workflows/nba-totals-probability-value.yml` so a successful `workflow_run` refreshes immediately when capture/settlement evidence is newer, while scheduled refreshes retain the ten-minute throttle. Duplicate event-driven runs skip after the first report covers the evidence.
- Regression cases passed in [run 41411409102](https://github.com/topboyasian-stack/match-signal/actions/runs/41411409102): new evidence under ten minutes old refreshes, duplicate/fresh reports skip, scheduled throttling remains, and missing reports regenerate. The updated report was actually published; this was not merely a build/test-only claim.
- A scheduling gap remains: the latest scheduled price-capture run found is [41376829309](https://github.com/topboyasian-stack/match-signal/actions/runs/41376829309) at 02:16:27Z, and the latest scheduled settlement run found is [41369269089](https://github.com/topboyasian-stack/match-signal/actions/runs/41369269089) at 00:50:07Z. The new event-driven capture [41411803153](https://github.com/topboyasian-stack/match-signal/actions/runs/41411803153) succeeded, but the scheduled NBA capture/settlement events were still absent while other repository schedules continued.
- Added a fallback freshness watchdog: `.github/workflows/nba-totals-capture-watchdog.yml`, `scripts/nba_totals_capture_watchdog.py`, and `scripts/test_nba_totals_capture_watchdog.py`. It checks at `:12/:27/:42/:57`, counts active capture runs, and dispatches the existing capture workflow when the status is missing/invalid or at least **10 minutes** old and no capture is queued/running, leaving a five-minute buffer before the 15-minute quote-freshness cutoff. It never creates/infer odds or counts snapshots as bets. Push validation [41412744448](https://github.com/topboyasian-stack/match-signal/actions/runs/41412744448) passed with the final threshold; the later watchdog push validation [41413500510](https://github.com/topboyasian-stack/match-signal/actions/runs/41413500510) also passed at 08:30:26Z, reporting zero active captures, capture age 3.02 minutes, and `dispatch=false` because the latest capture was fresh.
- The original scheduled capture and settlement runs remain absent after [capture 41376829309](https://github.com/topboyasian-stack/match-signal/actions/runs/41376829309) at 02:16:27Z and [settlement 41369269089](https://github.com/topboyasian-stack/match-signal/actions/runs/41369269089) at 00:50:07Z. The watchdog's scheduled tick has not yet been observed. To avoid relying on cron alone, the watchdog now also triggers after successful Live Expansion, Unified Upcoming Board, and settlement completions, and after Cloudflare deploy completions. Its push validation run [41413500510](https://github.com/topboyasian-stack/match-signal/actions/runs/41413500510) passed, but the new `workflow_run` path has not yet been exercised by a post-change source-workflow completion; verify it on the next event. Do not declare the schedule gap fully resolved until a scheduled tick or stale-triggered recovery dispatch is observed.

### Production and regression evidence

- Latest completed Cloudflare deployment at this checkpoint is [run 41409803237](https://github.com/topboyasian-stack/match-signal/actions/runs/41409803237), source commit `11a3dd395e1f0aee36a2d42b364e1d03cd13bd64`, immutable artifact [dc34d7d3.match-signal.pages.dev](https://dc34d7d3.match-signal.pages.dev), production alias [match-signal.pages.dev](https://match-signal.pages.dev). The run passed its production HTTP/asset smoke tests (20 pages, 52 assets) and NBA ESPN proxy check.
- The persisted verification record is `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE`, verified at `2026-11-02T08:00:43.877095+00:00`: core pages are verified, but the generic booking POST test is `NO_FUTURE_BATCH` and Qualified Best is `VALID_ZERO` with zero qualified candidates. No booking code was requested or fabricated for an unavailable batch.
- The current main blob SHAs for `basketball.html`, `basketball-live.js`, `ticket-drawer.js`, `ticket-drawer.css`, `functions/api/sportybet-booking.js`, `functions/api/sportybet-basketball.js`, NBA settlement/capture code, and their key regressions match the source/tested commit `32cb3e24c9583caaab50650afe587adb17b707fd`. Relevant passing latest-code regression runs include [NBA source/season gates 41393209403](https://github.com/topboyasian-stack/match-signal/actions/runs/41393209403), [Ticket Drawer Contract 41393209401](https://github.com/topboyasian-stack/match-signal/actions/runs/41393209401), and [NBA ticket fail-closed 41392190523](https://github.com/topboyasian-stack/match-signal/actions/runs/41392190523). The four key production code files also have identical blob SHAs at deployed source `11a3dd395e1f0aee36a2d42b364e1d03cd13bd64) and current main.
- The capture-triggered settlement and probability workflows have both completed successfully: [41411898561](https://github.com/topboyasian-stack/match-signal/actions/runs/41411898561) and [41411898949](https://github.com/topboyasian-stack/match-signal/actions/runs/41411898949). The report is newer than the capture and ledger timestamps and remains `RESEARCH_ONLY`.
- Builder Production Promotion run [41411497799](https://github.com/topboyasian-stack/match-signal/actions/runs/41411497799) remained in progress and later promotion run [41411976023](https://github.com/topboyasian-stack/match-signal/actions/runs/41411976023) was pending at the last check. The latest completed deployment remains [run 41409803237](https://github.com/topboyasian-stack/match-signal/actions/runs/41409803237), source `11a3dd395e1f0aee36a2d42b364e1d03cd13bd64`, artifact [dc34d7d3.match-signal.pages.dev](https://dc34d7d3.match-signal.pages.dev). Recheck both promotions and any resulting deployment before treating that as the newest production state.

### Next action on resume

1. Re-read this checklist and inspect the current main SHA, reports, ledger, capture status, Actions runs, and latest production verification.
2. Recheck promotion runs 41411497799 and 41411976023 and any newer deployment/artifact.
3. Verify the next watchdog `workflow_run` trigger after a successful Board/Live Expansion/settlement event; if capture age reaches 10 minutes and no capture is active, verify the existing capture workflow is dispatched and the settlement/report chain follows. The scheduled watchdog tick and real stale-triggered dispatch remain unverified.
4. Continue collecting exact SportyBet market-225 observations and official ESPN settlements. Do not count repeated quotes as independent fixtures or selections.
4. Continue collecting exact SportyBet market-225 observations and official ESPN settlements. Do not count repeated quotes as independent fixtures or selections.
4. Continue priority 14 until at least 30 uniquely settled prospective market-225 fixtures have exact immutable snapshot linkage. Then continue the 100-selection/200-target, positive ROI/positive 95% lower bound/favourite benchmark, authentic later-quote CLV, and 100-game post-cutoff MAE/bias gates. Keep the model unchanged unless a separately preregistered development-only experiment proves an upgrade.
5. Keep `RESEARCH_ONLY` and the Basketball ticket gate locked. No auto-betting; every future NBA ticket leg must still be freshly revalidated against exact market 225 immediately before code generation.
