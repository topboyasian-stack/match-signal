# Match Signal AI Analyst and Evidence Upgrade

## Goal

Add an accountable analysis layer that can explain Match Signal from its real records, detect operational/data-quality problems, compare the original Prediction Desk line with the line a user actually selected, and recommend model changes only after controlled evaluation.

This work must build on the current architecture. It must not replace the football, tennis, eFootball, or VFootball engines, combine their histories indiscriminately, lower qualification gates to force tickets, or write user-provided bets into model-training history.

## Audit baseline

The initial audit of main on 2026-10-09 found:

- The scheduled paper-ticket tracker records generated Builder batches and settles the exact generated legs. It does not provide a complete representation of tickets a user manually created or changed.
- User-supplied ticket evidence already exists in a separate Virtual Lab evidence file and is explicitly excluded from automatic model history to avoid selection leakage. Preserve that separation.
- The latest results-first report contained 100 tracked automated paper tickets: 33 settled, 5 won, 28 lost, and 37 lost legs. Those results describe the Builder's tracked sample, not the user's independent SportyBet slips.
- The same report distinguished exact-line individual-leg history from tickets containing those legs. For example, an exact line may have a respectable individual hit rate while tickets containing it frequently lose on another or the same leg. These denominators must never be merged.
- The latest published system-health snapshot was DEGRADED: no current tennis predictions were published, and the selected-candidate layer had zero qualified selections without weakening its evidence gate.
- The latest core pipeline status recorded 120 football predictions and 0 tennis predictions; the feed reported source HTTP 403 errors for some La Liga collection attempts and a market-data match coverage value of 0.4833. These are operational/data-quality issues the analyst should surface, not interpret as model losses.
- The latest Builder artifact contained a four-leg VFootball batch rated 37.99/100 despite a much higher average per-leg probability claim. The separate ticket-layer audit has already documented concerns about price-conditional calibration. That concern requires fresh tests; it must not be treated as resolved by the existence of a chatbot.

These are dated repository artifacts, not fresh guarantees about the live site. The next phases must refresh and timestamp every diagnostic before answering production questions.

## Data boundary: desk snapshot versus actual ticket

Each captured Over/Under leg must preserve two independent facts:

1. The original desk snapshot, exactly as it was displayed at decision time: prediction ID if available, product/competition, event identity, kickoff, selected side, exact line, quoted odds, displayed model probability, model version, and snapshot time.
2. The actual user selection: exact side, line and odds the user placed, plus the result/final score when settled.

A user may lower an Over line (for example, Over 2.5 to Over 1.5), raise an Under line (for example, Under 8.5 to Under 9.5), keep the same line, or change the side. Store the original and selected lines without overwriting either. The reviewer derives whether the user's line was easier or harder for that side.

The same final score can then be used to calculate two distinct outcomes: what happened to the desk selection and what happened to the actual selection. This is a descriptive counterfactual for that fixture, not proof that the user's adjustment has a long-run predictive edge. Only broader, chronological, selection-aware evaluation can establish that.

## Privacy and storage rules

- Never commit actual user slips, ticket IDs/verification codes, private authentication tokens, API keys, or user betting records to this public repository.
- The schema and audit utility in this branch are code/contracts only. Input evidence is supplied explicitly as a private local file and is not written or modified by the audit tool.
- Before production capture is enabled, use a private, authenticated store such as Cloudflare KV or D1 with access control and a documented retention/export/delete policy. Do not expose ticket records through public static JSON assets.
- The AI API credential must remain a Cloudflare secret. It must never be embedded in frontend JavaScript or committed to Git.
- The assistant should return evidence date, sample size, definitions and source status. If evidence is absent, it must say so instead of inventing an answer.
- The assistant is advisory and read-only. It must not place bets, generate real-money instructions, silently alter selection rules, or directly deploy model changes.

## Proposed components

### A. Evidence and evaluation (this branch starts here)

- Versioned JSON contract for private user-ticket review records.
- Standard-library audit utility that validates records and compares exact desk vs actual Over/Under selections from the same final score.
- Automated unit tests for lower/higher line adjustments, pushes, missing desk snapshots, invalid prices, and counterfactual outcome differences.
- Aggregate-only default output: no fixture names, personal ticket references, or full private slip is emitted.

### B. Operational monitor

Build a compact diagnostic service from current public artifacts and workflow runs. Inspect source freshness, expected-sport presence, event/market matching, data coverage, settlement queues, stale upcoming rows, Worker errors, Builder qualification, and calibration reports. Give warnings and failures a timestamp and exact source path. Do not equate "no qualified batch" with a failed engine, or "workflow green" with accurate predictions.

### C. Conversational analyst

Add the UI only after the protected data source and inference provider are chosen. The server must fetch only the relevant aggregates, redact private values, enforce limits, and ask the model to answer from supplied evidence. Example questions:

- Why did my ticket lose when the other legs won?
- What was the desk line, and what line did I actually select?
- For my changed lines, how often did the changed selection win while the desk line lost, and how many comparable settled legs are there?
- Is the data feed current? Which engine, market, or settlement process is degraded?
- Are model probabilities calibrated against the exact SportyBet price for the same line and side?
- Which proposed fix passed a chronological holdout, and which remains experimental?

The response format should distinguish fact, interpretation, uncertainty and recommendation. It must not declare a model is "learning" merely because its history counter increased.

### D. Controlled improvement loop

1. Ingest and verify new settled records.
2. Produce time-safe aggregates and calibration/return diagnostics by sport, product, market, exact line, side, price band and model version.
3. Identify a specific failure mode.
4. Propose a versioned change in an isolated research lane.
5. Compare against a baseline on an untouched chronological holdout and then on prospective paper predictions.
6. Promote only when minimum sample size, calibration, benchmark and safety requirements pass.
7. Retain old artifacts and provide rollback.

User-selected legs are selection-biased evidence. Track them as a distinct cohort and do not use them as if they were a random or complete sample of all desk predictions.

## Acceptance criteria before production rollout

- Every user-selected leg preserves both the original desk line and actual selected line when the former is available.
- Tests prove Over and Under line-change direction is handled correctly and integer-line pushes are not counted as wins or losses.
- No private betting records are committed to public GitHub or published as a static asset.
- Answers cite timestamped data sources and show n for every performance statement.
- Desk-level accuracy, actual-selection accuracy, ticket win rate, individual-leg hit rate, calibration and ROI remain distinct metrics.
- New model versions must outperform a fair market benchmark on a chronological holdout, with uncertainty reported. A better hit rate on its own is not sufficient.
- The existing sport-engine boundaries, evidence archives, paper-only mode and no-forced-ticket rules remain intact.
- Deployment is not complete until the affected Cloudflare production endpoint and visible feature are verified.

## Scope of this first patch

This is a non-production foundation. It adds a private-data contract, an aggregate-only O/U audit utility, tests, and a targeted CI workflow. It does not change predictions, qualification gates, ticket construction, settlement records, production pages, or Cloudflare bindings. It does not add an LLM API until private storage, authentication and provider configuration have been reviewed.
