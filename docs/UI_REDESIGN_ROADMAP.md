# Match Signal UI Refresh Roadmap

Updated: 2026-10-11

## Product direction

Match Signal should feel like one coherent prediction and research desk with three distinct workspaces:

- **Prediction Desk:** current upcoming fixtures, exact-market prices, qualification state, settlement status, and actionable next steps.
- **Virtual Lab:** eFootball-first paper research, participant history, line/market experiments, validation, and eligibility gates.
- **Reports:** a read-only system-wide scorecard that explains sample size, calibration, results, freshness, and blockers.
- **AI Analyst:** a private, token-protected workspace for operational explanations and ticket review. It must remain `noindex`, and private records must never be included in public static artifacts.

## Phase 1 — shared workspace shell and research visibility

Implemented in the October 11, 2026 UI refresh commits:

- Shared dark dashboard style, navigation and current-workspace indicator for Virtual Lab, Reports and AI Analyst.
- Reports receives a live research summary that reads published Virtual Lab status, walk-forward evaluation, eligibility, system health and the separate eFootball Winner/GG-NG archive.
- Virtual Lab defaults to eFootball GT + eAdriatic. VFootball and Zoom remain selectable secondary lanes; no history is deleted.
- Team crests and real-player headshots use exact-name lookup. Unsupported names remain initials; gamer handles never get a guessed face.
- Virtual Lab’s expensive line-ladder model fit is accelerated, covered by a reference-fit regression test, and the collector has a longer time budget.
- No model-selection, risk or market-promotion gate is weakened by these UI changes.

### Phase 1 acceptance checks

- The collector publishes a fresh status, walk-forward evaluation and eligibility artifact.
- Cloudflare production HTTP/asset checks pass for the current main commit.
- A natural scheduled collector run is observed; a manual or push-triggered run does not count as proof of scheduled automation.
- Missing/ambiguous media falls back cleanly and does not break fixture cards.
- AI Analyst continues to require private access and its token is never placed in a URL.

## Phase 2 — full desk redesign

Create a consistent card-and-timeline visual system across Upcoming, Football, Tennis, Live and Odds Builder:

- **Fixture identity row:** verified crest/headshot, competition, local kickoff, time-to-start or live/finished state.
- **Evidence and price row:** exact quoted market, selection, line, current price timestamp, sample size, calibration and the precise qualification blocker.
- **Status vocabulary:** separate model estimate, evidence candidate, qualified paper selection, stale/volatile quote, live, and settled result.
- **Better scanning:** compact filters, kickoff-sorted groups, hide settled matches from Upcoming while retaining history, and consistent mobile layouts.
- **Research-aware summaries:** put sample size and holdout metrics beside performance claims; never promote from hit rate alone.
- **Progressive disclosure:** cards show the decision-relevant facts first; detailed model diagnostics and logs live behind a detail panel.

Acceptance: desktop/tablet/mobile screenshots, keyboard navigation and accessibility checks, existing selection/price contract tests, and production smoke tests all pass before calling the redesign complete.

## Phase 3 — shared intelligence layer

- Make Reports the concise summary of the whole system and link each metric to its owning artifact or workspace.
- Keep Virtual Lab detail and experiments in the Lab; do not duplicate Lab’s full controls in Reports.
- Make AI Analyst discoverable from shared navigation without making its private ledger public.
- Link explanations to timestamped artifacts, freshness, settled-sample counts and explicit uncertainty.

## Media and attribution contract

- Prefer a first-party team/player ID or stable provider ID where available. Until that exists, match normalized names exactly.
- Club/team name resolves to a badge; real human tennis/football player name resolves to a headshot. An eFootball gamertag is not a real-person identity.
- Cache successful and missed lookups; throttle external requests to the provider’s free rate limit.
- If the source returns no exact match, show initials. Never guess based on a similar name.
- Media artwork is provider-supplied and may be absent or subject to third-party rights. Preserve source information and respect the provider’s terms.

## Non-negotiable data boundaries

- Preserve append-only settled history, participant identities and model-evaluation artifacts.
- UI refreshes must not retrain the model, change weights, weaken qualification gates or promote Winner/GG-NG.
- eFootball Winner and GG/NG remain in their separate paper research archive until sample size, calibration versus no-vig baseline, chronological holdout, exact settlement and post-margin performance all support a promotion decision.
- The Virtual Lab can remain useful while system health is degraded, but the UI must display freshness and health separately.
