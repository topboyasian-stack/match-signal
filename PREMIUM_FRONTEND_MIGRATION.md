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

## Immediate next action

Read the current Cloudflare Pages configuration and confirm whether the production output directory serves repository-root files. Then map each required asset into an explicit public build allowlist before changing the deployment.