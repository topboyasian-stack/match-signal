# Product QA Case Study — Match Signal

**Role direction:** Junior Product QA / Software Testing / Data Quality  
**Project:** Match Signal — https://match-signal.pages.dev  
**Repository:** https://github.com/topboyasian-stack/match-signal

## Project summary

Match Signal is an independent multi-sport research application. It combines fixture data, third-party market information, prediction research, alternative selections, settlement records, and a paper-only selection workflow.

I use the project as practical evidence of product problem-solving and quality-focused development. The strongest QA examples are not generic UI checks; they involve real integration risks such as inconsistent provider responses, changed fixture IDs, stale quotes, incorrect market mapping, and accidental exposure of private evidence.

This is a project portfolio, not a claim of prior employment as a QA engineer.

## Testing focus

The repository contains automated regression coverage for:

1. **API contract and response validation** — expected status, JSON shape, fields, and diagnostics.
2. **Data freshness and correctness** — stale or missing prices cannot be treated as current.
3. **Privacy and data minimisation** — private model details and raw probability data are excluded from public responses.
4. **Third-party integration resilience** — an HTML edge response is handled without attempting to parse it as JSON, and an alternate source can be tried.
5. **Identity matching** — a fixture can be resolved using participant names and kickoff time when its provider ID has changed.
6. **Boundary and negative testing** — empty selections, started fixtures, unsupported markets, invalid evidence, and mismatched market specifiers are rejected or kept research-only.
7. **Regression protection** — test cases preserve expected behaviour after a defect is fixed.

## Two concrete defect investigations

### 1. Compressed private evidence broke the public alternatives reader

A large private evidence value could be stored in gzip-compressed form. The public alternatives endpoint needed to handle the compressed representation instead of treating it as ordinary JSON text.

The regression test supplies compressed bytes, checks that KV is read as an arrayBuffer, and asserts that the endpoint returns a valid public alternatives response. Related tests check safe diagnostic reasons for KV and decoding failures.

Evidence:
- [Merged PR #548 — compressed KV evidence fix](https://github.com/topboyasian-stack/match-signal/pull/548)
- [Public alternatives endpoint](https://github.com/topboyasian-stack/match-signal/blob/main/functions/api/public/market-alternatives.js)
- [Public alternatives regression tests](https://github.com/topboyasian-stack/match-signal/blob/main/tests/public-market-alternatives.test.mjs)

### 2. Provider responses and changed fixture IDs made ticket preparation fragile

The SportyBet integration needed to tolerate an HTML edge/challenge response, recover through an alternate source, and find fixtures whose provider IDs had changed. The test suite includes participant-and-time matching, deeper catalogue pagination, rejection of already-started fixtures, and a mocked mixed-sport response.

The test also checks that returned combined odds use the exact revalidated selection prices when the mocked provider share response omits outcome prices. This is a mocked integration assertion, not evidence that a live provider-issued share code was generated during the test.

Evidence:
- [Merged PR #549 — manual NBA market-225 share-code resilience](https://github.com/topboyasian-stack/match-signal/pull/549)
- [Booking API](https://github.com/topboyasian-stack/match-signal/blob/main/functions/api/sportybet-booking.js)
- [Booking resilience regression script](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_sportybet_booking_resilience.mjs)
- [NBA ticket guard tests](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_nba_ticket_guard.mjs)

## Example test commands

The repository package.json currently defines npm run build but does not define a single npm test script. The focused checks are invoked directly:

    node --test tests/public-market-alternatives.test.mjs
    node scripts/test_sportybet_booking_resilience.mjs
    node --test scripts/test_nba_ticket_guard.mjs
    npm run build

Run these from the repository root in an environment with the project's required Node.js version and dependencies installed.

## Evidence and verification boundaries

The repository contains the regression assertions linked above. The connected GitHub status records inspected for PR #548 and PR #549 showed successful Netlify deploy-preview checks. Those checks are evidence that preview deployments succeeded; they are not proof that every Node.js regression script ran in CI or that every live production integration was independently smoke-tested.

For that reason, this portfolio describes the checks present in source and the behaviour they assert. It does not make an unsupported claim that the entire application is defect-free or that a live SportyBet share code was generated by a mocked test.

## Skills demonstrated

- Translating production symptoms into reproducible test scenarios
- Writing positive, negative, and boundary test cases
- Validating API responses and data contracts
- Testing stale-data and identity-matching edge cases
- Reviewing integration failure paths
- Protecting private data in public responses
- Reading change history and linking defects to regression coverage
- Communicating test evidence and verification limits clearly

## Suggested next improvement

Add a dedicated CI job that runs the focused Node.js checks and publishes their results as a visible check on every pull request. This would make the test execution evidence easier for reviewers and prospective employers to verify.
