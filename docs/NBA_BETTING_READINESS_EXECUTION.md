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
2. [ ] Freeze the prospective evaluation cutoff at **2026-11-02 02:00:00 UTC**. Forecast games and market bets published before this cutoff belong to development; only games/bets at or after it count as prospective holdout. The cutoff must never roll forward.
3. [ ] Produce the exact per-fixture failure audit: model projection, SportyBet line, projection edge, chosen side, both saved prices, quote age, final total including overtime, projection error, result, and selected-side ROI. Count each ESPN event once.
4. [ ] Run the fixed-cutoff walk-forward and price-capture regression suite in GitHub Actions. Regenerate the live evaluation JSON from the current production data and verify the fixed cutoff is present. If this run fails, fix it before proceeding.
5. [ ] Diagnose SportyBet coverage gaps by exact fixture and time. Distinguish not listed, time mismatch, stale/missing quote, market 225 unavailable, and unusable odds pair. Inspect the live proxy/feed response before changing query parameters. Preserve exact market, event, price, and freshness contracts.

### P0 — build a stronger score model using historical development data only

6. [ ] Build v6 as a separately versioned candidate; do not silently modify or relabel v5.
7. [ ] Backtest candidate features individually and in combinations against the same pre-cutoff historical development set: opponent-adjusted pace, home/away offense and defense splits, rest days/back-to-backs/schedule density, recent offense and defense form, and turnover/rebound/possession profiles where the historical data is complete.
8. [ ] Use player availability/starting-lineup information only if a free, reliable, timestamped pregame source is available and its historical availability can be reproduced. Otherwise omit it; do not use post-tip information.
9. [ ] Compare every candidate against v5 and the rolling 90-day baseline using chronological splits. Retain a feature only when it produces repeatable out-of-time improvement. Do not use SportyBet prices as model projection inputs.
10. [ ] Preserve the frozen prospective cutoff for the final test. Any candidate tuning after looking at prospective outcomes invalidates that holdout and requires a new, explicitly registered future cutoff.

### P1 — replace point-edge picks with probability and value decisions

11. [ ] Estimate a calibrated total-score uncertainty distribution from development residuals and derive calibrated P(Over) and P(Under), including half-point and integer-line push treatment.
12. [ ] Convert the exact fresh SportyBet Over/Under pair to no-vig market probabilities. Compare model probabilities with those market probabilities and calculate expected value using the saved selected-side price.
13. [ ] Require a predeclared probability/value margin that survives calibration uncertainty. The output must be OVER VALUE, UNDER VALUE, or NO BET; a fixed ±3-point projection gap alone is not a betting signal.
14. [ ] Check probability calibration, Brier score/log loss, side-specific performance, line/edge buckets, and closing-line value. All analysis must use pregame snapshots and unique fixtures.

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

## Current implementation checkpoint

The current code changes in progress are:

- scripts/nba_totals_walk_forward.py: replace rolling 80/20 splits with the frozen prospective UTC cutoff; deduplicate settled evidence by ESPN event ID; add per-fixture audit rows; replace the normal-approximation ROI lower bound with a deterministic 4,000-resample fixture-level bootstrap.
- scripts/test_nba_totals_walk_forward.py: regression tests for the fixed cutoff, event deduplication, per-fixture audit, and bootstrap metric.
- .github/workflows/nba-totals-price-capture.yml: run the walk-forward tests and compile checks before the scheduled capture/evaluation.

**Next action on resume:** inspect the GitHub Actions run triggered by the latest workflow change. Do not mark priorities 2–5 complete until the run passes and the regenerated JSON is checked.
