# Match Signal — Protected V6 Runtime Contract

**Public owner:** Diddy  
**Copyright:** © 2026 Diddy. All rights reserved.  
**Build:** MS-V6-IP-2026.09.21

## Runtime boundary

`Browser → /api/match-signal-engine → protected V6 runtime → SportyBet / sports data`

The browser must receive only the minimum result payload needed to render the application. It must never receive:

- V6 proprietary model source;
- calibration internals or private thresholds;
- SportyBet credentials or private provider credentials;
- private operational endpoints;
- internal market-matching implementation;
- Odds Builder qualification internals that are not required by the UI.

## Request contract

The public adapter sends a JSON request describing the required analysis context. The protected runtime decides which internal data sources, models, calibration, market matching, uncertainty penalties, correlation rules, and eligibility gates are executed.

Example request shape:

```json
{
  "engine": "V6",
  "build": "MS-V6-IP-2026.09.21",
  "sport": "tennis",
  "event_id": "provider-event-id",
  "markets": ["winner", "total_games"],
  "mode": "PAPER_ONLY"
}
```

## Response contract

The protected runtime returns only safe, presentation-ready results, for example:

- event identity;
- market;
- selection;
- model probability;
- model fair odds;
- verified bookmaker price;
- de-vig probability;
- model edge / EV;
- price freshness;
- data quality;
- uncertainty;
- eligibility/status;
- reason codes;
- engine/build identifier.

It must not return source code, credentials, private provider URLs, or implementation details.

## Fail-closed rule

If the protected runtime is unavailable or not configured, the public adapter returns `503 PROTECTED_RUNTIME_REQUIRED`. The public application must not silently fall back to shipping proprietary V6 execution logic to the browser.

## Migration rule

The existing V6 pipeline remains unchanged until an equivalent protected runtime has been validated against a frozen baseline. After validation:

1. deploy the protected runtime;
2. run shadow comparison against current V6 outputs;
3. require equivalence within defined tolerances;
4. switch the browser to the boundary;
5. only then retire public execution copies.

This contract is an engineering/IP protection boundary, not legal advice.
