# Match Signal — Defect and Regression Case Studies

## Case 1: Compressed KV evidence was not handled by the public reader

**Area:** API / data decoding / privacy boundary  
**Change:** [PR #548](https://github.com/topboyasian-stack/match-signal/pull/548)  
**Relevant files:** functions/api/public/market-alternatives.js, tests/public-market-alternatives.test.mjs

### Observed failure mode

The private cross-sport evidence writer can store a large value in gzip-compressed form. The public alternatives endpoint previously expected a normal JSON text value. When the stored representation was compressed, the reader could not safely parse it as JSON.

### Risk

- Public alternatives could become unavailable even though evidence existed.
- A generic server error made the underlying failure difficult to diagnose.
- A careless error response could expose private implementation details.

### Corrective behaviour

The reader was updated to request an ArrayBuffer, decode supported plain or gzip content, apply a decompression-size bound, and keep the public response schema restricted to approved fields. Stable safe diagnostics identify failure classes without returning raw private exception messages.

### Regression assertions

- The KV read uses the expected key and requests arrayBuffer.
- A gzip-compressed value produces HTTP 200 and the expected public alternative.
- Private model details and raw probability vectors are absent from the response.
- Failure paths expose safe, stable reasons rather than raw exception text.

### QA lesson

Integration tests should exercise the storage representation that actually occurs in production, not only the simplest plain-text fixture. Public API tests should also check for accidental disclosure, not just status codes.

---

## Case 2: Provider catalogue instability caused false “event no longer present” failures

**Area:** Third-party API integration / identity resolution / workflow validation  
**Change:** [PR #549](https://github.com/topboyasian-stack/match-signal/pull/549)  
**Relevant files:** functions/api/sportybet-booking.js, scripts/test_sportybet_booking_resilience.mjs, scripts/test_nba_ticket_guard.mjs

### Observed failure modes represented in regression tests

- An upstream endpoint could return an HTML challenge page with HTTP 200 instead of JSON.
- A fixture's current provider event ID could differ from an older saved identifier.
- A fixture could appear beyond the first few catalogue pages.
- A started fixture could still be present in an old selection payload.
- A provider share response could omit outcome prices, creating a risk of reporting an incorrect combined price.

### Corrective behaviour and assertions

- Retry the same catalogue query against an alternate configured source when the first response is HTML.
- Resolve an unambiguous fixture using participants and kickoff time when its provider ID has changed.
- Exercise a fixture placed on catalogue page 12.
- Reject already-started selections before an upcoming-catalogue lookup or share request.
- Use the exact revalidated leg prices when the provider response omits outcome price fields.
- Return no booking code for an empty manual selection.

### QA lesson

For integrations, a successful HTTP status is not sufficient evidence of a valid response. Tests should verify content type and payload shape, identity matching, time boundaries, pagination, and the exact data used in the final response.

### Important test limitation

The mixed-ticket response and share code in the regression script are mocked. This validates the application's handling of the provider contract under test conditions; it does not prove that a live provider accepted a real ticket or issued a production share code.

---

## Case 3: Research visibility must not be confused with ticket qualification

**Area:** Business rules / data quality / negative testing  
**Relevant files:** functions/api/public/market-alternatives.js, tests/public-market-alternatives.test.mjs

### Risk

A candidate may be useful to inspect as research but still lack an exact provider mapping, a current quote, or a supported market. Treating every visible candidate as selectable would blur an important product boundary.

### Regression assertions

- Stale or unverified quotes remain distinguishable from exact fresh quotes.
- Missing prices are not fabricated.
- Unmapped candidates can remain research-visible while ticket_selectable and builder_qualified are false.
- Unsupported market buttons are not enabled.
- Alternatives that repeat the primary selection or fail the defined comparison are filtered.
- The publisher returns no more than two alternatives per fixture.

### QA lesson

A visible record, a valid record, a selectable record, and a qualified record are different states. Tests should assert each state explicitly so that a UI or API change cannot silently collapse them into one.
