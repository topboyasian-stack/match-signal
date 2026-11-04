# Match Signal core reliability guardrails

These rules are shared contracts, not sport-specific suggestions. Changes to a model, feed, board, result ledger, Builder, or booking adapter must preserve them.

## Prediction and result integrity

- A published forecast is an immutable, timestamped decision snapshot. Later model refreshes must not rewrite the probability, market, side, line, or price that was visible before kickoff.
- Join a final result to its forecast through a stable internal fixture identity. Provider event IDs are namespaced by provider and product and are not sufficient by themselves when a provider can recycle IDs.
- A fallback match is allowed only when product/competition, normalized participant identity, and kickoff time identify exactly one fixture within the documented tolerance.
- Missing, conflicting, or ambiguous results remain explicitly unmatched. Never guess, silently discard the forecast, backdate a prediction, or use a later price to reconstruct the pre-match decision.
- Settlement runs are idempotent. Replaying the same final result cannot duplicate wins, losses, pushes, or accuracy denominators.
- Current and archived histories are merged through one canonical deduplication rule. Conflicting outcomes are excluded and diagnosed, not resolved by choosing whichever record is convenient.

## Sport and market boundaries

- Each sport/product owns its feed adapter and validation rules. Cross-sport aggregation happens only after the adapters return normalized records.
- Exact competition/product identity must survive discovery, prediction, publication, settlement, and reporting.
- An incomplete source for one fixture must not block unrelated, fully evidenced fixtures.
- Model projections, provider quotes, and settled outcomes are separate evidence classes. One must never be substituted for another.
- A quote is valid only with its provider, event, market, line/specifier, selection, price, and observed capture time. A refresh must not stamp an old quote with a new timestamp.

## Shared SportyBet ticket contract

- There is one shared manual ticket API for all supported sports.
- Manual tickets are all-or-nothing: every leg is revalidated against the current SportyBet event, participant pair, kickoff status, exact market/line/side, and current price before a share request is sent.
- If any leg fails before the share request, the whole manual ticket is rejected and no code is requested.
- If SportyBet accepts only part of a manual ticket, the whole code is withheld. Do not return a reduced ticket under a success response.
- Manual preparation and automated Builder qualification are separate paths. Supporting a manual research selection must never bypass an automated qualification gate.
- Never claim that a share code exists unless the provider returned a non-empty code for the complete requested selection set.
- A failed request must preserve the user's local ticket and return a stable JSON error contract.

## Publication and deployment

- A generated board and its reservation/settlement ledger must be published as one consistent revision when one depends on the other.
- Automated writers must rebase/re-read the latest main state before publication and must not overwrite unrelated or newer artifacts.
- A retry must be idempotent and preserve existing settlements.
- A repair PR must not dispatch prediction refreshes, Builder publication, notification, or Cloudflare production-promotion workflows.
- Regression CI must use mocked provider responses and local fixtures. It must not call SportyBet, ESPN, Cloudflare production APIs, or write production artifacts.

## Required regression coverage

Changes touching these boundaries must run the core reliability suite:

1. Shared ticket drawer contract and server booking integration (single- and mixed-sport tickets).
2. Missing manual leg rejection before share request.
3. Provider partial-acceptance rejection with no exposed code.
4. Upcoming prediction publication and settlement-retention tests.
5. Odds Builder history, settled-loss, and calibration-history tests.
6. eFootball product/line settlement reconciliation tests.

A green unit test is necessary but not sufficient for a production release. Production readiness additionally requires the affected deployed workflow and UI to be verified without changing unrelated data or bypassing freshness/evidence gates.
