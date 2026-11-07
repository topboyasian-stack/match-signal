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
14. [x] Reach the minimum prospective probability-validation cohort and publish exact snapshot-linked probability/CLV diagnostics. As of 2026-11-06 07:25 UTC, 31 unique settled market-225 fixtures (17 directional, 14 neutral/no-bet) pass exact immutable snapshot linkage. Descriptive scores remain worse than market no-vig (model Brier 0.256303 vs 0.250404; model log-loss 0.706401 vs 0.693956). Genuine later-quote CLV remains negative (17 observations; mean probability CLV -0.002649; mean line CLV -0.4706 points). This completes the minimum-sample/report task only; it does not qualify the model for betting or tickets.

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

- No release gate has been relaxed: `RESEARCH_ONLY` and the Basketball ticket gate remain locked. Priority 14's minimum 30-fixture probability sample is met (40 uniquely settled prospective market-225 fixtures); Priority 15 is first unchecked until at least 100 unique prospective settled market-225 selections are available (target 200), each with exact immutable snapshot linkage and official ESPN settlement.
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

## Latest continuation checkpoint — 2026-11-02 13:46 UTC — shared ticket SportyBet proxy failure fixed

The active NBA readiness priority is still **Priority 14: prospective probability validation**. The frozen prospective cutoff remains `2026-11-02T02:00:00+00:00`. This ticket-code-generation repair does not qualify NBA for betting and does not change any sample, ROI, CLV, forecast, or freshness threshold.

### Code-generation error and root cause

- The user-facing error combined `HTTP 400 (application/json)` from `match-signal-sportybet-proxy.topboyasian.workers.dev/api/ng/factsCenter/pcUpcomingEvents` with an HTML `HTTP 200` from direct SportyBet.
- Root cause confirmed in `sportybet-worker/src/index.js`: the regional proxy allowlist allowed `sr:sport:2` (basketball), `sr:sport:137`, and virtual feeds, but rejected the standard shared-ticket revalidation sport IDs `sr:sport:1` (football) and `sr:sport:5` (tennis). The existing ticket handler also asks the football/tennis catalogue for market IDs `16,45,47,203,188,187`, which were absent from its market allowlist. The Worker returned a validation HTTP 400 before reaching SportyBet; the handler then fell through to direct SportyBet, which returned HTML and caused the JSON parse error.
- The allowlist was extended only to cover the existing shared-ticket sports and explicit market IDs; unsupported sports and market IDs remain rejected. The booking handler also now preserves structured proxy `error/detail/message` text in its diagnostics.
- Added Worker regressions for exact football and tennis catalogue requests, parameter forwarding, and continued rejection of unknown sports/market IDs. Extended the Worker deployment smoke test to probe football, tennis, and NBA market 225 on the real Worker.

### Verified code/deployment evidence

- Regional Worker deployment [run 41455605359](https://github.com/topboyasian-stack/match-signal/actions/runs/41455605359) **passed**. Live post-deploy probes returned HTTP 200 and JSON from SportyBet for football (`sr:sport:1`, 976 source events), tennis (`sr:sport:5`, 354 source events), and NBA (`sr:sport:2`, market 225). The regional diagnostics also returned JSON with `bizCode: 10000`.
- Worker source/test workflow [run 41455605332](https://github.com/topboyasian-stack/match-signal/actions/runs/41455605332) **passed**.
- Shared Ticket Drawer Contract [run 41455583886](https://github.com/topboyasian-stack/match-signal/actions/runs/41455583886) **passed**, including the live invalid-ticket POST check, which verified an HTTP 422 JSON response with no booking code.
- NBA ticket fail-closed tests [run 41455583890](https://github.com/topboyasian-stack/match-signal/actions/runs/41455583890) **passed**. Whole-slip rejection and the research-only NBA ticket lock remain enforced.
- Cloudflare Pages deployment [run 41455583821](https://github.com/topboyasian-stack/match-signal/actions/runs/41455583821) deployed its Pages artifact successfully. Its separate production HTTP/asset smoke step was still running at the last observed check; recheck it and the persisted verification record before claiming the full Pages verification passed.
- Relevant changes: proxy allowlist and market list in `sportybet-worker/src/index.js`; worker contract in `scripts/test_sportybet_region_worker.mjs`; live deploy probes in `.github/workflows/deploy-sportybet-worker.yml`; structured error details in `functions/api/sportybet-booking.js`.

### Current NBA release evidence — remain RESEARCH_ONLY

- Current probability/value report `data/nba_totals_probability_value_experiment.json` (blob `6f6a44a4184f8efaf837ef8ad5a591867c740b42`) was generated at `2026-11-02T11:55:07.142190+00:00` and remains `RESEARCH_ONLY`. It records 420 prospective exact-fresh market-225 snapshot observations over 15 unique fixtures, zero settled prospective selections, zero exact-snapshot-linked settled selections, zero probability-scored fixtures, zero near-close CLV observations, and no linkage failures. Repeated quotes are not independent selections.
- Current fixed-cutoff OOS report `data/nba_totals_oos_value_test.json` (blob `7ee7c9310b3a08fb1dc0580341653a0c0838a47c`) was generated at `2026-11-02T11:32:09.774076+00:00`: post-cutoff forecast holdout n=4, model MAE 26.7875 versus baseline MAE 24.75, absolute bias 6.4637, and zero settled market-holdout selections. The 100-game forecast condition fails; ROI, ROI 95% lower bound, favourite benchmark and CLV remain unproven.
- Settlement ledger `data/nba_totals_ledger.json` (blob `75734552a681a52ca241a6877318dabe2fe6e203`) has 70 settled historical records, but the current prospective report has zero post-cutoff settled selections. That historical count does not satisfy the prospective thresholds.
- The most recently persisted `DEPLOY-VERIFY-CLOUDFLARE.json` is still `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE` (source `8b56a1cfd340d9267e426b15241697e91882f126`) and says the generic booking POST check is `NO_FUTURE_BATCH`; do not treat it as evidence that a real valid multi-leg SportyBet share-code creation was verified.

### Next action on resume

1. Recheck run 41455583821's final production HTTP/asset smoke result and the newest production verification JSON.
2. Verify a real, nonempty shared ticket is revalidated against the current provider catalogue immediately before code generation; the Worker now serves valid football and tennis catalogues, but no actual user-selected multi-leg share code was requested or fabricated by these tests.
3. Continue **Priority 14** from exact SportyBet Nigeria market-225 snapshots with official ESPN settlements and immutable linkage. Preserve cutoff `2026-11-02T02:00:00+00:00`; do not count duplicate quotes as independent bets.
4. Keep NBA `RESEARCH_ONLY` and the Basketball ticket gate locked until every prospective sample, ROI/confidence-bound/favourite-benchmark, genuine later-quote CLV, forecast MAE/bias, and production regression condition independently passes. No auto-betting.


## Latest continuation checkpoint — 2026-11-02 14:00 UTC — NBA model freshness recovered

This checkpoint updates production freshness and workflow evidence only. The frozen prospective cutoff remains `2026-11-02T02:00:00+00:00`. First unchecked research priority remains **14 — prospective probability validation**; no release threshold was lowered.

### NBA pre-game stale-publication incident — corrected and verified

- Root cause: `data/nba_predictions.json` retained 54 upcoming projections with generation timestamps older than the Basketball UI's six-hour limit. The quote-capture workflow was freshening prices but was not itself the full model/fixture rebuild. The Live Expansion cron was not running regularly.
- Re-armed `.github/workflows/live-expansion.yml` at cron `14,44 * * * *` and added a fail-closed publication check that rejects missing, future-dated, post-tip, or greater-than-six-hour upcoming NBA prediction timestamps. A model refresh with stale output cannot pass publication.
- The model/fixture refresh workflow [run 41457363124](https://github.com/topboyasian-stack/match-signal/actions/runs/41457363124) completed **successfully**. Model generation, freshness guard, settlement, fixed-cutoff evaluation, and artifact publication all passed.
- Post-publication `data/nba_predictions.json` has 58 rows total, 54 upcoming fixtures, and **0 stale upcoming projections**. The new upcoming model timestamps are `2026-11-02T13:57:15Z`; `data/expansion_status.json` updated at `2026-11-02T13:57:32Z`, with 58 NBA fixtures, 0 NBA collection errors and no NBA source diagnostics.
- Updated the NBA capture watchdog with stale-model detection, active-run suppression, and a 30-minute retry cooldown. It uses the existing Live Expansion workflow for recovery rather than relaxing the six-hour UI rule. Regression suite [run 41457581116](https://github.com/topboyasian-stack/match-signal/actions/runs/41457581116) passed after correcting the test import. The post-refresh watchdog event [run 41457521837](https://github.com/topboyasian-stack/match-signal/actions/runs/41457521837) passed and logged `stale_upcoming_predictions=0`, `nba_schedule_fixtures=58`, `dispatch=false`, reason `upcoming_model_projections_within_six_hour_window`. The capture branch also logged `dispatch=false` with its latest capture only 0.59 minutes old. Do not dispatch redundant model runs when projections are fresh.

### Cloudflare Pages and shared-ticket status — verified with one remaining limitation

- The earlier Pages deploy [run 41455583821](https://github.com/topboyasian-stack/match-signal/actions/runs/41455583821) uploaded its artifact but failed production smoke because the deployed Unified Upcoming board was more than 30 minutes stale; it was not a verified release.
- A later manual Pages deployment [run 41456981757](https://github.com/topboyasian-stack/match-signal/actions/runs/41456981757) completed **successfully**. The production smoke passed 20 pages, 52 assets, the NBA ESPN proxy, protected API, ticket tracker, and other required probes; the live site served a fresh Unified Upcoming board. This corrects the previous deployment verification gap.
- Worker deployment [run 41455605359](https://github.com/topboyasian-stack/match-signal/actions/runs/41455605359) and Worker tests [run 41455605332](https://github.com/topboyasian-stack/match-signal/actions/runs/41455605332) passed; football and tennis shared-ticket catalogue probes returned HTTP 200 JSON. The ticket drawer invalid-slip safety check passed via [run 41455583886](https://github.com/topboyasian-stack/match-signal/actions/runs/41455583886), returning HTTP 422 JSON for an empty invalid ticket with no code.
- Actual valid shared-ticket code generation is **not yet verified**: the successful Pages smoke explicitly skipped the booking POST because the current Builder artifact had no fully future 2+ leg batch. Do not claim an actual share code was generated or infer success from the OPTIONS check.
 
### Current model and market evidence — still RESEARCH_ONLY

- The recent market capture found 15 exact fresh SportyBet Nigeria market-225 pairs among 54 upcoming model predictions; 37 fixtures were not listed in the current feed and 2 had start-time mismatches. Keep those unmatched fixtures unpriced.
- Fixed-cutoff OOS report generated `2026-11-02T13:57:22Z`: post-cutoff forecast holdout n=4; model MAE 26.7875 versus baseline MAE 24.75; bias 6.4637 points; settled prospective market-holdout selections n=0. It does not satisfy forecast or betting-value release requirements.
- Basketball remains `RESEARCH_ONLY`. Keep the ticket release gate locked; do not create qualified NBA legs or mark betting-ready. Preserve Priority 14, immutable market-225 snapshots, official ESPN settlements and all existing frozen thresholds.
- Next action on resume: verify the user's real multi-leg ticket against current catalogue/odds at code-generation time, and continue Priority 14 evidence collection. The app should be hard-refreshed to fetch the newly published projections; if the old stale banner remains after a hard refresh, inspect the browser-visible response/source timestamp rather than weakening freshness checks.

## Production cache-alignment checkpoint — 2026-11-02 14:06 UTC

### Basketball public stale-data path — fixed and verified

- The first Pages release with the new artifact check correctly failed [run 41458000059](https://github.com/topboyasian-stack/match-signal/actions/runs/41458000059): the immutable deployment had 54 fresh NBA projections, but the mutable `match-signal.pages.dev/data/nba_predictions.json` route still returned 54 old projections. The six-hour model rule was retained; stale rows were not accepted.
- Root cause was the public cache policy gap: `_headers` explicitly disabled caching on several high-refresh JSON endpoints, but omitted `/data/nba_predictions.json` and NBA research/settlement artifacts.
- Added `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` to `/data/nba_predictions.json`, `/data/expansion_status.json`, `/data/expansion_prediction_history.json`, `/data/expansion_live_performance.json`, `/data/nba_totals_ledger.json`, `/data/nba_totals_oos_value_test.json`, `/data/nba_totals_probability_value_experiment.json`, `/data/nba_totals_publication_snapshots.json`, and `/data/nba_totals_price_capture_status.json`.
- Strengthened `.github/workflows/cloudflare-pages.yml` so the build rejects a missing/empty/stale NBA prediction artifact, the NBA JSON is part of production asset smoke tests, and both the immutable deployment and public production hostname must return fresh upcoming projections **and** the expected no-store/no-cache/max-age=0 response header.
- Corrected deployment [run 41458444673](https://github.com/topboyasian-stack/match-signal/actions/runs/41458444673) **passed**. The smoke output confirms `Immutable deployment NBA prediction artifact fresh: 54 upcoming forecasts` and `Production hostname NBA prediction artifact fresh: 54 upcoming forecasts`; the full production smoke passed 20 pages and 53 assets, including the NBA ESPN proxy. Public-route cache mismatch is resolved in the verified release.
- `data/nba_predictions.json` now holds 58 rows, 54 future fixtures, and zero predictions failing the six-hour freshness guard. The pre-game model timestamps are `2026-11-02T13:57:15.087Z`. The source schedule/model run [41457363124](https://github.com/topboyasian-stack/match-signal/actions/runs/41457363124) passed its stale-output publication gate; watchdog tests [41457581116](https://github.com/topboyasian-stack/match-signal/actions/runs/41457581116) and post-refresh watchdog [41457521837](https://github.com/topboyasian-stack/match-signal/actions/runs/41457521837) also passed, with zero stale upcoming projections.
- Latest capture status, checked at `2026-11-02T14:02:46Z`, has no feed error and reports 15 exact fresh market-225 matches/price updates among 54 upcoming predictions. Unmatched games remain unpriced.
- Latest fixed-cutoff OOS report, generated at `2026-11-02T14:02:50Z`, remains `RESEARCH_ONLY`: forecast holdout n=4; MAE 26.7875 against baseline 24.75; bias 6.4637; settled prospective market bets n=0. These evidence gates remain unmet.
- The production verification record at `2026-11-02T14:05:54Z` remains `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE`, **only because** Qualified Best has valid-zero candidates and the live booking POST is `NO_FUTURE_BATCH`; the smoke explicitly did not attempt a real code-creation POST without an eligible future 2+ leg ticket. A valid selected ticket must still be tested when available. Do not invent a booking code.

### Resume priority

Priority **14 — prospective probability validation** remains the first unchecked NBA readiness item. Preserve cutoff `2026-11-02T02:00:00+00:00`, immutable market-225 snapshots and official ESPN settlement linkage. Keep Basketball `RESEARCH_ONLY` and its ticket release gate locked. On the user's side, hard-refresh `https://match-signal.pages.dev/basketball.html`; the published data and public static fallback have now both passed the fresh six-hour checks.

## Shared ticket booking incident — 2026-11-02 14:34 UTC

This is a cross-sport shared-ticket repair; NBA release readiness remains a separate gate. The frozen prospective cutoff stays `2026-11-02T02:00:00+00:00`, and Priority 14 — prospective probability validation — remains the first unchecked NBA priority.

### Root causes corrected

- **Football catalogue HTTP 400:** `collectEvents()` scanned up to eight pages, but the regional Worker only allows `pageNum=1..5`. When a target was not found earlier, the client sent page 6 and got `INVALID_QUERY: pageNum must be an integer from 1 to 5`. Set the bounded catalogue scan default to five pages and exported it for regression testing; primary and tennis WAP-fallback scans can no longer submit page 6.
- **Tennis share response HTML:** after correctly revalidating the tennis legs, the booking handler sent `POST /api/ng/orders/share` straight to `www.sportybet.com`. When that endpoint returned an HTML edge/challenge page with HTTP 200, the handler stopped there and reported a generic malformed-response error. Added a fixed-path POST relay to the regional Worker and changed the Pages booking function to try the Worker first, use the same body on direct-origin fallback when the relay cannot return usable JSON, and return one consistent JSON diagnostic if both routes fail.
- **Worker security contract:** the share relay does not accept arbitrary target URLs. It permits only the fixed SportyBet share endpoint, POST only, 2–20 selections, allowlisted market IDs, required event/outcome IDs, and bounded specifiers. Invalid requests fail before contacting SportyBet. Existing exact-event, open-fixture, price/market revalidation remains in the Pages handler; NBA stays behind its unchanged release gate.

### Verification evidence

- Regional Worker source/tests and deployment: [Worker tests run 41462680595](https://github.com/topboyasian-stack/match-signal/actions/runs/41462680595) **passed**; live Worker deploy/probes [run 41462680715](https://github.com/topboyasian-stack/match-signal/actions/runs/41462680715) **passed**. Live football catalogue returned HTTP 200 JSON (993 catalogue events reported by SportyBet); tennis returned HTTP 200 JSON (354 reported). The new live POST probe sent only an intentionally invalid empty slip and received HTTP 422 `application/json` with `INVALID_SHARE_SELECTION_COUNT` and no upstream-status header, proving the deployed share route validates before provider access without creating a code.
- Shared ticket regression suite [run 41462836324](https://github.com/topboyasian-stack/match-signal/actions/runs/41462836324) **passed**. Its log reports `single cross-sport ticket contract: PASS` and `SportyBet booking resilience: PASS (bounded catalog paging, regional share POST fallback, JSON-safe failures, and exact market-225 pair)`. Tests check pages 1–5 only, proxy-first share request, same exact payload on direct fallback, and consistent failures when both origins return HTML.
- Cloudflare Pages deployment for handler source commit `f3ceebdfe5124bb301e9d464c8e4afae229105aa`, [run 41462432310](https://github.com/topboyasian-stack/match-signal/actions/runs/41462432310), **passed** its production HTTP and asset smoke tests (20 pages, 53 assets) and current NBA artifact checks. The live invalid-ticket contract also continues to return JSON 422 with no booking code. A follow-on Pages run is rebuilding the same checked-out source after workflow/test-only changes; that run is not a second proof of successful real code generation.
- **Still unverified:** no valid user-selected 2+ leg slip has yet completed the real SportyBet share POST and returned a booking code in this session. The production smoke intentionally skipped a share-code POST because the Builder artifact had no eligible future 2+ leg batch. Do not infer share-code success from the catalogue probes, invalid-ticket 422 probe, or local mocked regression. If both upstream share routes are blocked, the UI should now show the same explicit `SPORTYBET_SHARE_UPSTREAM_UNAVAILABLE` diagnostic for tennis and football instead of divergent generic messages; a current, future, valid selected ticket is needed for the final end-to-end confirmation.

### NBA priority retained

No model qualification, odds-freshness, settlement, or release threshold was lowered. NBA remains `RESEARCH_ONLY`; continue Priority 14 with immutable exact market-225 snapshots, official ESPN settlement linkage, and the frozen cutoff. Do not use the ticket repair as evidence of NBA betting readiness.

## Latest continuation checkpoint — 2026-11-03 07:38 UTC — forecast cutoff classification corrected

Priority **14 — prospective probability validation** remains the first unchecked readiness item. The frozen cutoff is unchanged at `2026-11-02T02:00:00+00:00`. No odds, thresholds, bookmaker sources, model versions, settlement rules, or auto-betting permissions were changed.

### Defect found and corrected

- The fixed-cutoff walk-forward evaluator used `data/nba_history.json`'s normalized `date` as its forecast cutoff timestamp. For `nba_data_v2_team_game_logs`, that field is the end of the Eastern game date, deliberately moved to the end of day to prevent same-day result leakage. Because the frozen cutoff falls during the Nov 1 Eastern game date, this could incorrectly classify pre-cutoff games as prospective. The prior `n=4` holdout was therefore not safe evidence for the frozen prospective cohort.
- Fixed in `scripts/nba_totals_walk_forward.py` at commit [`b017fb395d2ab571f6af758ccb9488e733dd7b7a`](https://github.com/topboyasian-stack/match-signal/commit/b017fb395d2ab571f6af758ccb9488e733dd7b7a): forecast chronology remains unchanged, but holdout classification now uses a separate `forecast_timestamp`; an exact `start_time` wins when present, and date-only NBA log rows are conservatively assigned the earliest possible tip time at local midnight America/New_York. A date that could contain pre-cutoff games stays in development rather than being promoted into holdout.
- Added a regression in `scripts/test_nba_totals_walk_forward.py` at commit [`73bc2c7b03cf48d7375d037dd77ff697df3b035c`](https://github.com/topboyasian-stack/match-signal/commit/73bc2c7b03cf48d7375d037dd77ff697df3b035c), covering a date-only pre-cutoff row, an exact post-cutoff start time, and a later local game date.
- The full Live Expansion run [41597246212](https://github.com/topboyasian-stack/match-signal/actions/runs/41597246212) completed successfully after syncing the new test commit; `python scripts/test_nba_totals_walk_forward.py`, the NBA source/season tests, exact SportyBet totals/settlement tests, forecast freshness guard, settlement, and fixed-cutoff report generation passed. The source/season gate also passed in [41597246516](https://github.com/topboyasian-stack/match-signal/actions/runs/41597246516).

### Current evidence — do not release

- Latest persisted fixed-cutoff OOS report [`data/nba_totals_oos_value_test.json`](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_oos_value_test.json) was generated at `2026-11-03T07:39:00Z` by research run [41597624140](https://github.com/topboyasian-stack/match-signal/actions/runs/41597624140). It correctly reports **0 prospective walk-forward forecast games** from the current date-only history source, not 4. The 1,224-game history currently ends with four Nov 1 Eastern game-date rows whose earliest possible local tip precedes the cutoff. Until exact post-cutoff forecast times or unambiguously post-cutoff game dates enter the history, MAE/bias cannot be qualified; the 100-game forecast gate fails closed. The post-capture research refresh [41597733903](https://github.com/topboyasian-stack/match-signal/actions/runs/41597733903) was still running at the last check.
- Latest probability/value report [`data/nba_totals_probability_value_experiment.json`](https://github.com/topboyasian-stack/match-signal/blob/main/data/nba_totals_probability_value_experiment.json), generated at `2026-11-03T07:40:11Z` by successful research run [41597733903](https://github.com/topboyasian-stack/match-signal/actions/runs/41597733903), remains `RESEARCH_ONLY`. There are **10 unique settled prospective v5.1 market-225 selections**, each with an exact immutable snapshot link and **zero linkage failures**; the probability-validation minimum is 30 unique settled fixtures. The archive has 19 unique prospective fixtures and 1,358 repeated snapshot revisions; those revisions are not independent bets. Follow-on research refresh [41597782119](https://github.com/topboyasian-stack/match-signal/actions/runs/41597782119) completed successfully at `2026-11-03T07:41:01Z`; it added no new independent settled fixtures, so the 10-selection sample and `RESEARCH_ONLY` decision are unchanged.
- The 10-selection market holdout is 6 wins / 4 losses, +1.36 flat-stake units (**+13.6% ROI**), but the fixture-level bootstrap 95% ROI lower bound is **−43.4%**, so the confidence-bound condition fails. ROI is above the market-favourite benchmark (market-favourite ROI −5.8%; relative difference +19.4%), but that does not compensate for the failed lower bound or inadequate sample.
- Genuine later SportyBet observations are still insufficient and negative in aggregate: 7 quotes were observed within 45 minutes of tip, only 3 showed positive probability CLV and 2 positive line CLV; mean probability CLV is −0.002271 and mean line CLV is −0.2857 points. These are later pregame captures, not an official bookmaker close; the CLV release check remains false.
- Latest completed price capture [41597656352](https://github.com/topboyasian-stack/match-signal/actions/runs/41597656352) succeeded. Capture status checked at `2026-11-03T07:38:56Z`: 4 exact fresh SportyBet Nigeria market-225 fixtures among 47 upcoming v5.1 forecasts, 4 fresh pairs, 19 unique fixtures with immutable snapshots, `capture_status=PARTIAL`, and zero unmatched fresh-price predictions; 4 new immutable quote observations were appended. Unlisted fixtures remain unpriced; no substitute book, stale quote, inferred odds, or reconstructed line is used. The next research refresh [41597733903](https://github.com/topboyasian-stack/match-signal/actions/runs/41597733903) is still in progress at checkpoint time.
- The release gate in `functions/api/sportybet-booking.js` still independently requires the fixed cutoff, at least 100 forecast games with MAE below baseline and absolute bias ≤3, at least 100 unique settled market-225 selections, positive ROI and positive bootstrap 95% lower bound, ROI above the market-favourite benchmark, at least 30 exact-snapshot-linked probability observations, and positive later-quote CLV. `functions/api/sportybet-basketball-booking.js` still revalidates each exact market-225 leg immediately before share-code creation. No gate or threshold was relaxed; keep `RESEARCH_ONLY`, with no NBA code generation and no auto-betting.

### Production and workflow evidence

- Latest completed Pages deployment at this checkpoint is [run 41597101499](https://github.com/topboyasian-stack/match-signal/actions/runs/41597101499), source commit `24fb8abbbb9734578bf89100b54a19c633262202`, immutable artifact [`52d98aa5.match-signal.pages.dev`](https://52d98aa5.match-signal.pages.dev), production alias [`match-signal.pages.dev`](https://match-signal.pages.dev). Production smoke passed **20 pages, 54 assets, and the NBA ESPN proxy**; both the immutable deployment and production hostname served 47 upcoming NBA forecasts.
- The deployed source and current main have identical blob SHAs for `basketball.html`, `basketball-live.js`, `functions/api/sportybet-basketball.js`, `functions/api/sportybet-booking.js`, `functions/api/sportybet-basketball-booking.js`, and `ticket-drawer.js`. Basketball UI and booking code are current. Both the Basketball page and release handler prefer the latest raw GitHub `main` reports for NBA evidence, so the corrected `n=0` holdout is the live gate input even though this Pages artifact predates the evaluator-only change.
- Production verification remains `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE`: generic booking POST is `NO_FUTURE_BATCH`; the smoke did not have a fully future 2+ leg batch and did not generate a code. Do not treat that skipped booking POST as ticket-code verification or NBA readiness.
- Builder Production Promotion [41597639153](https://github.com/topboyasian-stack/match-signal/actions/runs/41597639153) was cancelled while queued; replacement [41597798931](https://github.com/topboyasian-stack/match-signal/actions/runs/41597798931) was pending, and [41597225640](https://github.com/topboyasian-stack/match-signal/actions/runs/41597225640) was still in progress at the last workflow check. Recheck any resulting Pages deployment on the next run; do not claim a newer production artifact until its run and immutable URL are verified.

### Next action on resume

1. Re-read this document, then inspect the newest main SHA, reports, ledger, capture status, Actions runs, and production verification.
2. Continue Priority 14 from the first unchecked evidence gate: obtain at least 30 uniquely settled prospective market-225 fixtures with exact immutable snapshot linkage. Do not count quote revisions as fixtures.
3. Continue toward at least 100 unique prospective settled market-225 selections (target 200), while requiring positive ROI, a positive bootstrap 95% lower bound, ROI above the market-favourite benchmark, and positive genuine later-quote CLV.
4. Accumulate at least 100 valid post-cutoff forecast games using the corrected conservative timestamp rule; then require lower MAE than the development baseline and absolute bias ≤3 points. Do not use the old misclassified `n=4` as evidence.
5. Verify the latest-main Basketball page, ESPN live feed, settlement, odds display, and ticket-builder regressions and any resulting production deploy. Keep `RESEARCH_ONLY` and the Basketball ticket gate locked until every condition independently passes.

## Latest continuation checkpoint — 2026-11-07 08:02 UTC

This is the single current continuation checkpoint and supersedes the continuation notes dated 2026-11-05 and 2026-11-06. Main head inspected before this checkpoint update: `38fb9f16c38055661c71deb5260388f8bda00374`. The frozen prospective cutoff remains `2026-11-02T02:00:00+00:00`. No threshold was relaxed, no alternate bookmaker or inferred odds were used, repeated quotes were not counted as independent bets, and auto-betting remains disabled.

### First unchecked priority: 15 — collect unique prospective settled market-225 selections

- Priority 14 is met for descriptive probability validation: `data/nba_totals_probability_value_experiment.json` reports 40 uniquely settled prospective fixtures (minimum 30), 40 binary-scored fixtures, and zero immutable-snapshot linkage failures.
- Priority 15 is not met: the report contains only 27 unique prospective market-225 selections, with 15 wins and 12 losses. Exact immutable snapshot linkage is complete for 27/27 selections, with zero missing or mismatched links. The requirement remains at least 100 unique settled selections, targeting 200; repeated captures and quote revisions do not increase this count.
- The latest probability/value report was generated at `2026-11-07T08:00:54.576152+00:00`; research workflow [42353561497](https://github.com/topboyasian-stack/match-signal/actions/runs/42353561497) passed. Brier score is 0.262880 versus market no-vig 0.250489; log loss is 0.719661 versus market 0.694124, so model scores are currently worse than the market.
- The 27-selection market holdout has 15 wins, 12 losses, +1.23 flat-stake units, and +4.56% point-estimate ROI. The deterministic fixture-level bootstrap 95% ROI lower bound is -30.44%; the market-favourite benchmark ROI is +11.33%, so the candidate is 6.78 percentage points below that benchmark. The ROI, confidence-bound, and market-favourite release conditions therefore fail.
- Twenty genuine later pre-game/near-close quote observations are available, but the report explicitly says none is an official bookmaker close. Mean probability CLV is -0.002253 and mean line CLV is -0.45 points; the positive-CLV release check fails. Do not relabel these observations as official closing prices.
- The frozen-cutoff forecast holdout is n=38, MAE 12.5461 versus development-baseline MAE 13.3962, and bias +1.3942 points. The observed MAE and bias satisfy their numerical comparisons at this sample size, but the mandatory minimum of 100 post-cutoff forecast games is not met.
- The current release decision remains `RESEARCH_ONLY`.

### Latest collected data and Actions evidence

- Capture [42353504168](https://github.com/topboyasian-stack/match-signal/actions/runs/42353504168) succeeded. `data/nba_totals_price_capture_status.json` was checked at `2026-11-07T07:59:44.720887+00:00`: no feed error, 62 model predictions checked, 51 upcoming v5.1 predictions, seven exact fresh SportyBet Nigeria market-225 pairs, and seven new immutable snapshots. Forty-four of the 51 upcoming predictions still lack an exact fresh pair; the feed currently exposes only seven matching market-225 events. The report contains 3,818 verified fresh v5.1 market-225 snapshot records across 47 unique fixtures. These snapshots are evidence, not independent bets.
- Settlement run [42353573094](https://github.com/topboyasian-stack/match-signal/actions/runs/42353573094) succeeded but added no new official ESPN settlement evidence. The probability-settlement artifact remains at 40 unique settled fixtures (last updated `2026-11-07T07:31:49.538223+00:00`). The settled ledger was refreshed at `2026-11-07T07:55:14.906436+00:00`; it contains 27 v5.1 selections, still 15 wins and 12 losses.
- The latest fixed-cutoff OOS report was regenerated at `2026-11-07T07:59:51.361662+00:00`. The probability/value report at 08:00:54 is newer than the latest capture and ledger timestamps, so the current checkpoint uses the refreshed reports.
- Dedicated NBA `event=schedule` runs remain absent after the last observed scheduled NBA run at approximately 07:32 UTC, despite the re-arm workflow verifying the capture, settlement, probability and watchdog workflows as active. Re-arm/watchdog run [42353336498](https://github.com/topboyasian-stack/match-signal/actions/runs/42353336498) passed, and event-driven capture, settlement checks and report refreshes continue to run. Do **not** mark scheduled delivery fixed until a new NBA `event=schedule` run is directly observed; continue using the event-driven fallback.

### Fail-closed ticket fix and regression evidence

- Closed the manual NBA bypass in `functions/api/sportybet-booking.js`: manual and automated NBA slips now load the same global release evidence and must pass `nbaTotalTicketLegQualified` for every leg. Manual mode can no longer bypass the release decision or exact fresh snapshot/value checks. A locked response explicitly reports `booking_code_withheld: true`.
- Updated `scripts/test_nba_ticket_guard.mjs` to assert that a manual NBA ticket is blocked while the report is `RESEARCH_ONLY` and that a leg with a mismatched immutable market-225 snapshot is rejected before share-code creation. Latest-main gate regression [42353680182](https://github.com/topboyasian-stack/match-signal/actions/runs/42353680182) passed all seven Node tests, the Basketball desk contract, and the cross-sport ticket contract.
- Added schedule re-arming on relevant workflow pushes and successful pipeline completions, merged the duplicate `push` trigger, and tested the re-arm path. The workflow regression passed, but actual scheduled NBA delivery is still unproven as stated above.
- Added a production smoke probe using synthetic, non-existent market-225 event IDs. It cannot represent a real fixture or place a wager; it verifies that the deployed endpoint withholds a share code before any valid share request can be made.

### Current Cloudflare production state

- Latest successful deployment is [run 42353369793](https://github.com/topboyasian-stack/match-signal/actions/runs/42353369793), source commit `826641bc7803cd871fb1b54790d5ee1d6fbae984`, build ID `MS-UNIFIED-20261107-826641bc7803`, immutable artifact [0ad56aa2.match-signal.pages.dev](https://0ad56aa2.match-signal.pages.dev), production alias [match-signal.pages.dev](https://match-signal.pages.dev). The deployment passed the production page/asset and NBA ESPN-proxy smoke checks.
- Builder Production Promotion [42353399266](https://github.com/topboyasian-stack/match-signal/actions/runs/42353399266) remains in progress at `Refresh Unified Upcoming before rebuilding the Builder`; no later Pages deployment run has appeared as of 2026-11-07T08:05 UTC. Recheck the production record and artifact after this run resolves before treating the deployment as final.
- The new production gate probe passed against both the production alias and immutable artifact: each returned HTTP 423 `NBA_RELEASE_GATE_LOCKED`, `booking_code_withheld: true`, and no `booking_code`. The probe used synthetic non-existent fixtures and did not request a SportyBet share code.
- `DEPLOY-VERIFY-CLOUDFLARE.json` was recorded at main commit `c3793bf40a18335d18f1db751ff817278826486c`. Its status is `VERIFIED_WITH_DIAGNOSTIC_INCOMPLETE`; `nba_ticket_gate_probe_status` is `PASS`, while `booking_api_status` remains `NO_FUTURE_BATCH` because no valid future 2+ leg batch was available for a genuine share-code POST. Do not claim end-to-end booking-code generation has been verified.
- The deployed source commit's runtime file blobs match current main for `basketball.html` (`a58615bf`), `basketball-live.js` (`882a6c37`), `functions/api/sportybet-basketball.js` (`dc781e02`), `functions/api/sportybet-basketball-booking.js` (`4c544785`), `functions/api/sportybet-booking.js` (`95e583e0`), `ticket-drawer.js` (`7715d5e2`), and `_headers` (`ae811559`). The manual NBA release-gate fix is deployed and directly verified.

### Next action

1. Continue capturing only exact SportyBet Nigeria market-225 lines and both prices observed within 15 minutes before publication, and settle only from official ESPN outcomes with immutable snapshot linkage.
2. Accumulate at least 100 unique prospective settled market-225 selections (target 200); do not count repeated quote revisions or neutral fixtures as bets.
3. Accumulate at least 100 post-cutoff forecast games and re-evaluate MAE and bias against the fixed development baseline.
4. Keep investigating missing scheduled NBA workflow events while preserving the working event-driven fallback.
5. Keep `RESEARCH_ONLY` and the Basketball ticket gate locked until every sample, ROI, bootstrap, market-favourite, genuine later-quote CLV, forecast, and latest-main production regression condition independently passes.
