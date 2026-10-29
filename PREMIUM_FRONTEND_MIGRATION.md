# Match Signal — Public and Premium Front-End Boundary

Status: architecture plan only. No production routes, prediction logic, or live deployment are changed by this document.

## Goal

Keep two distinct user experiences while reusing one protected source of truth:

- **Public front end:** selected public predictions, a transparent settled-results ledger, and carefully defined accuracy statistics.
- **Premium front end:** subscriber-only predictions, deeper analysis, premium reports and filters.
- **Protected engine:** model implementations, calibration, SportyBet matching, market qualification rules, internal thresholds, credentials and operational controls must not be shipped to a browser or included in a public static asset directory.

## Findings from the current repository

- The default branch is `main`.
- `index.html` currently presents a broad prediction desk with links to multiple sports and research workspaces.
- The repository contains many model and data-processing scripts under `scripts/`, GitHub workflows under `.github/workflows/`, and static data files under `data/`.
- `functions/api/v1/predictions.js` and `functions/api/v1/performance.js` currently require a server-side `MATCH_SIGNAL_API_KEY`. That is suitable for a private machine-to-machine API, not a browser-facing subscriber API: never put that shared key into public JavaScript.
- `MONETIZATION_ROADMAP.md` describes the verified tip ledger and the existing read-only API direction.
- The repository's own `IP-ENGINE-BOUNDARY.md` says to preserve working engines, establish protected execution, compare outputs against a frozen baseline, and switch the public interface only after parity is demonstrated.

## Required architecture

1. **Public static build:** deploy only an explicit allowlist of public HTML/CSS/JS assets and approved public data. Do not use the repository root as an unfiltered public asset directory once the build is migrated.
2. **Protected engine:** move proprietary scripts and internal workflows to a private repository or keep them in a genuinely protected server-side runtime. Merely hiding navigation or changing repository visibility is insufficient if the files are still deployed publicly.
3. **Shared, minimum-data API:** return only approved fields. Public endpoints may serve the public prediction subset and settled public statistics. Premium endpoints must authenticate the individual subscriber server-side and verify current entitlement on every protected request.
4. **Separate front ends:** public marketing/results pages and a premium application can have separate routes or deployments. They should consume the same governed API; they must not duplicate the model engine.
5. **Payments:** inspect the current payment account and supported webhooks before implementing checkout. A successful redirect alone is not proof of payment. Store only the minimum entitlement state needed and never commit payment secrets.
6. **Truthful performance:** freeze each prediction at publication time; settle using authoritative outcomes; show sample sizes, unresolved/void/push treatment, timestamp and price provenance. Do not advertise profitability or a broad accuracy claim without support.

## Zero-upfront-cost migration sequence

### Phase A — Inventory and safety (no production changes)
- Record current Cloudflare Pages project, branch, build command and output directory.
- Enumerate browser-loaded scripts, public JSON, Pages Functions, GitHub Actions and scheduled workflows.
- Inspect repository history and deployed asset paths for exposed secrets or proprietary scripts. Rotate any exposed secret before cleanup.
- Save baseline output samples and current production URLs.

### Phase B — Protect the engine
- Establish a private source location for proprietary engine files and workflows.
- Keep only approved build artifacts in the public deployment.
- Use server-side secrets for protected functions.
- Confirm public requests cannot retrieve engine source, internal workflows, model parameters or private datasets.

### Phase C — Define public and premium contracts
- Public schema: fixture identity, published selection, publication time, status, settlement and aggregate performance fields only.
- Premium schema: entitled predictions and permitted analysis fields; no model source, internal thresholds or credentials.
- Add server-side per-user entitlement checks; do not rely on front-end route hiding.
- Preserve existing prediction and settlement logic unless a separate verified defect requires a change.

### Phase D — Build the second front end
- Reuse existing design system and shared components where safe.
- Public front end: concise landing page, selected samples, public settled ledger, methodology/limitations, and subscribe CTA.
- Premium front end: sign-in, subscription status, protected prediction desk and account/logout controls.
- Do not expose premium data in static JSON or client-side bundles.

### Phase E — Verify before launch
- Regression-test model output and settlement parity.
- Test unauthenticated, expired, cancelled and active subscriber access.
- Attempt direct API calls and static-file guesses as an unauthenticated visitor.
- Check that public accuracy totals reconcile with the ledger.
- Test mobile layout and the existing public production pages.
- Deploy to a preview first; switch production only after the checks pass.

## Explicit non-goals

- No automatic betting or staking.
- No paid tools or new infrastructure unless a free option proves insufficient.
- No rebuilding working prediction engines.
- No claims that the public repository or a copyright notice protects source confidentiality.
- No production switch before preview verification.


## Verified baseline audit (2026-10-29)

The current generated ledger on `main` reports:
- 1,152 published records; 754 settled; 374 correct; aggregate settled accuracy 49.6%.
- Real-bookmaker-price ROI observations: 0; measured ROI is unavailable, not zero.
- Sport breakdown: football 219/434 settled correct (50.46%); tennis 155/320 (48.44%).
- The ledger status is `PAPER_TRACKED_NOT_LIVE_MONETIZED`; these are paper-research records, not evidence of profitable betting.
- The ledger currently includes row-level model probabilities, fair odds, Brier scores, and other fields. A future public feed should explicitly allowlist fields rather than return raw ledger rows.

Existing `/api/v1/predictions`, `/api/v1/performance`, and `/api/v1/accumulator` endpoints use one shared `MATCH_SIGNAL_API_KEY`. They are not a safe browser login or subscriber-entitlement system. Never embed that key in either front end.

## Deployment workflow caution

The existing Cloudflare Pages workflow builds from a broad repository-root copy and runs many validation steps from `scripts/`. Excluding `scripts/` from that workflow before completing a dependency and output audit could break the build or change what gets published. Do not merge a broad exclusion into the production workflow as a first step. Keep deployment unchanged until an explicit public asset manifest and preview-only audit are in place.

## Go/no-go status

**Not ready to sell a performance claim or enable paid access yet.** First protect source and internal datasets, define a minimal public output, reconcile the settled ledger, and implement real per-user entitlements. Any initial offer should be described honestly as paper research, with the current sample size and missing ROI evidence visible.


## Market-selection decision (2026-10-29)

Use a narrow, evidence-led launch scope while all other sports and markets continue in shadow evaluation. These are **paper-research candidates**, not validated profitable products.

### Launch candidate: football pre-match, with strict qualification

- Prioritize Champions League fixtures for the first monitored cohort: the current football performance artifact reports 30 correct from 46 settled (65.22%). The sample is still modest and accuracy alone does not establish value.
- Across the football confidence buckets, picks at 70%+ report 46 correct from 64 settled (71.88%). This is the strongest reported confidence bucket, but the source artifact and cohort definitions must be audited for selection bias and publication-time integrity before using it in a paid product.
- Use other major-league football only as secondary/shadow cohorts until each league has its own minimum-sample, calibration, and market-price evidence.
- Only qualify an individual pick when the event is not started, the SportyBet fixture match is exact, the required market quote is current (no older than 15 minutes), and the model-versus-market value calculation passes its gate. Missing or stale quotes mean no qualified selection; never substitute a historical line.
- The initial paid-facing page should be framed as a **limited paper-research pilot**, not a proven tipster or profitable service, until genuine bookmaker prices have been captured at publication and a frozen cohort demonstrates positive, reproducible out-of-sample returns after settlement.

### Do not lead with these markets yet

- Tennis match winner: 209/434 correct (48.16%) in the latest tennis artifact.
- Tennis totals: 166/384 decisions correct (43.23%).
- Overall football 1X2: 225/442 correct (50.90%) in the latest football artifact.
- **Basketball full-game totals: include as a separate candidate cohort, not exclude with all basketball.** If the user's totals results outperform the other basketball markets, preserve and evaluate that specific market in parallel with the football pilot. Keep it in a controlled paper-research/shadow pilot until its totals-only sample is reconciled against the settled ledger, publication-time SportyBet quotes are verified, and calibration plus bookmaker-relative returns can be computed for the same cohort. Do not generalize totals performance to basketball moneyline/spread or the whole sport. The historical strict basketball holdout (59.01% accuracy versus a 63.98% market baseline and -17.08% ROI over 161 games) is an overall/previous cohort and does not by itself disprove a better-performing totals submarket; current basketball settlement reconciliation remains incomplete.
- Do not select accumulators as the flagship product based on combined model probabilities alone. Evaluate individual leg calibration, exact current bookmaker prices, and settled accumulator-level ROI separately.

### Backend improvement loop for every non-launch market

1. Keep a timestamped, append-only record of the prediction exactly as shown before kickoff, including model/version, probability, exact market/line, verified bookmaker odds and timestamp, and quote-match confidence.
2. Settle only from authoritative results; preserve void/push handling and do not overwrite prior snapshots.
3. Report sample size, accuracy, Brier score/calibration, and ROI only where real bookmaker odds exist; compare with a de-vigged bookmaker baseline.
4. Segment results by sport, market, league/tour, confidence bucket, odds band, and quote age. Use minimum sample gates and rolling out-of-sample windows; do not promote a market from a small high-accuracy slice alone.
5. Keep challenger models in shadow mode. Promote only if they improve calibration and net performance against the frozen production baseline; retain rollback capability.
6. Publish a simple market status: `PILOT`, `SHADOW / COLLECTING EVIDENCE`, or `PAUSED / REPAIR`. No automated betting.

### Current release gate

The best current **candidate** is football pre-match with a high-confidence filter, with Champions League as the first cohort to evaluate. It is not yet a green-lit paid-picks claim: the overall verified ledger still has zero real-bookmaker-price ROI observations. Start by instrumenting this narrow cohort correctly, publish the paper record transparently, and continue improving tennis, basketball, totals, and accumulators without promoting them prematurely.

## Immediate next action
Create a non-production inventory of browser-loaded files, public JSON feeds, and Pages Functions, then build an explicit public asset manifest and run it on a preview. Do not alter the current production deploy workflow until the preview has passed.

## Basketball: explicit repair track (not dropped)

Basketball is excluded from the first commercial pilot because its current data and settlement chain is not yet trustworthy enough—not because the sport is being removed from Match Signal. Keep the Basketball page and its existing prediction engine in place while repairing and validating it in shadow mode. Do not claim it is fixed or publish performance claims until the checks below pass.

Known basketball acceptance criteria carried forward from the Basketball Prediction Status QA:

1. **Upcoming/live state:** exclude games that have already started from Upcoming; ensure live and final states reflect the event status rather than stale schedule data.
2. **Current bookmaker line integrity:** model projected totals must remain separate from SportyBet lines. A historical line (for example, the Kings–Grizzlies example showed model total 234.7 against a historical SportyBet line of 221.5) must never be represented as a current verified quote or used to generate a current lean.
3. **Alternative-line consistency:** when a SportyBet total line is changed, update the selected line, both relevant prices, model lean/value calculation, and every linked odds-builder selection together. Do not leave mixed values from different lines.
4. **Freshness gate:** a selection may qualify only against an exact matched SportyBet fixture and market with a verified quote no older than 15 minutes. If no current quote exists, show a clear unavailable/no-lean state and do not substitute historical prices.
5. **Settlement ledger:** reconcile every published basketball prediction against the authoritative final result, including full-game overtime rules and void/push cases. Store immutable publication-time snapshots and settlement evidence; do not count a displayed final score as a settled ledger result until the ledger confirms it.
6. **Performance reconciliation:** resolve the conflicting historical prediction/final counts seen in QA and reconcile the Basketball UI, prediction feed, results view, and settled ledger to one source of truth. Then calculate accuracy, calibration and bookmaker-relative ROI only for the exact same eligible cohort; do not reuse the historical 59.01% holdout figure as current performance.
7. **Builder validation:** verify the four Basketball odds-builder areas use only current, valid selections and calculate combined odds correctly; prevent missing prices or stale lines from silently producing a 1.00 combined-odds result.
8. **Release gate:** add automated regression checks for started-game filtering, line/price/lean synchronization, stale-quote rejection, settlement idempotency, and builder totals. Keep the market at `SHADOW / REPAIR` until the tests pass and the reconciled sample is independently checked.

This basketball backlog is part of the continuing backend work even while the football paper-research cohort is evaluated first. It must not be removed from navigation or silently abandoned as a side effect of narrowing the initial launch scope.
