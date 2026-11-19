# Match Signal — QA Test-Case Matrix

This matrix summarises representative automated assertions already present in the repository. It is a portfolio guide to the source tests, not a substitute for a fresh execution report.

## Public alternatives API

| ID | Scenario | Expected result | Source |
|---|---|---|---|
| ALT-01 | Valid future alternative with a fresh exact quote | Valid JSON response; public schema and qualification fields are consistent | tests/public-market-alternatives.test.mjs |
| ALT-02 | Candidate contains private model detail and raw probability vector | Private fields are absent from the public alternative | tests/public-market-alternatives.test.mjs |
| ALT-03 | Private evidence key is empty | Stable empty state and empty alternatives array | tests/public-market-alternatives.test.mjs |
| ALT-04 | Quote is older than the 15-minute freshness window | Row may remain research-visible but cannot be Builder-qualified | tests/public-market-alternatives.test.mjs |
| ALT-05 | Exact side price is missing | No price is fabricated; the row is not treated as freshly quoted | tests/public-market-alternatives.test.mjs |
| ALT-06 | Provider event or market mapping is absent | Research row remains visible but is not ticket-selectable | tests/public-market-alternatives.test.mjs |
| ALT-07 | Unsupported BTTS or double-chance ticket market | Research visibility is retained; unsupported ticket controls remain unavailable | tests/public-market-alternatives.test.mjs |
| ALT-08 | Alternative repeats the primary market pick or is less likely than a known primary | Duplicate or weaker candidate is rejected | tests/public-market-alternatives.test.mjs |
| ALT-09 | Several alternatives are proposed for one fixture | No more than two options are returned for that fixture | tests/public-market-alternatives.test.mjs |
| ALT-10 | Tennis Set 1 / Set 2 winner markets use set-specific specifiers | Sets remain distinct; mismatched set specifier is not ticket-selectable | tests/public-market-alternatives.test.mjs |
| ALT-11 | Private KV value is gzip-compressed | Reader requests an ArrayBuffer and returns a valid alternatives response | tests/public-market-alternatives.test.mjs |
| ALT-12 | KV binding, read, JSON, or decompression failure | Public diagnostic is safe and stable; private exception details are not exposed | tests/public-market-alternatives.test.mjs |

## Provider and ticket workflow

| ID | Scenario | Expected result | Source |
|---|---|---|---|
| BOOK-01 | Provider returns HTTP 200 with HTML instead of JSON | Do not parse HTML as JSON; try the alternate configured source with the same query | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-02 | Manual ticket contains zero selections | Return HTTP 422 and no booking code | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-03 | Provider event ID has changed | Resolve the fixture using participant names and kickoff time where the match is unambiguous | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-04 | Fixture is found deeper in the upcoming catalogue | Continue scanning within the configured page limit and resolve the matching fixture | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-05 | Fixture kickoff time has already passed | Reject the selection before catalogue lookup or share request | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-06 | Provider share response omits outcome prices | Calculate displayed combined odds from exact revalidated selection prices, not a fabricated default of 1 | scripts/test_sportybet_booking_resilience.mjs |
| BOOK-07 | Ticket combines supported football and NBA winner selections | Mocked integration returns the expected six selections and one share request | scripts/test_sportybet_booking_resilience.mjs |
| NBA-01 | NBA totals release evidence is missing or invalid | Global market-225 release check fails closed | scripts/test_nba_ticket_guard.mjs |
| NBA-02 | An evidence row points to the wrong immutable snapshot or price pair | Release qualification is rejected | scripts/test_nba_ticket_guard.mjs |
| NBA-03 | Evidence source changes after the report fingerprint was generated | Source freshness check fails; release qualification is rejected | scripts/test_nba_ticket_guard.mjs |

## Exploratory checks to perform before a release

These are useful manual follow-up checks and should only be marked complete after recording the date, environment, steps, and observed result:

- Open the live application on a narrow mobile viewport and a desktop viewport; check navigation, overflow, loading, and empty states.
- Reload a page after a data refresh; verify that old information is not presented as current.
- Use browser developer tools to inspect failed API requests and confirm the UI presents a useful state rather than a broken JSON/error dump.
- Check keyboard navigation and visible focus on interactive controls.
- Compare one fixture's displayed participants, kickoff, market, line, and price against the source response observed at test time.

## Evidence log template

| Field | Value |
|---|---|
| Test ID | |
| Date and time (UTC) | |
| Environment / URL | |
| Build or commit | |
| Preconditions | |
| Steps performed | |
| Expected result | |
| Actual result | |
| Pass / fail / blocked | |
| Screenshot or log reference | |
| Issue / follow-up | |
