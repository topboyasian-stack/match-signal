# Match Signal Virtual Lab

**Public owner:** Diddy  
**Build:** MS-VIRTUAL-LAB-2026.09.21  
**Purpose:** Standalone research environment for simulated football/eFootball products.

## Scope

The lab is intentionally separate from the existing Match Signal football and tennis pages.

Initial product families:

1. eFootball — GT Sports League
2. eFootball — eAdriatic
3. Simulated Reality League (SRL)
4. Virtual Football
5. Zoom / Turbo virtuals

## Research pipeline

Observed/public data:

`event → market → selection → odds → result → settlement`

Research stages:

1. Collect completed observations.
2. Normalize product, provider, event, market and timestamps.
3. Fingerprint each product/provider separately.
4. Test distributions, repeated participants, scorelines and market behaviour.
5. Test sequence/dependence features.
6. Freeze candidate rules on a discovery period.
7. Evaluate on an untouched out-of-sample period.
8. Repeat on a second untouched period.
9. Only a reproducible result can advance to a paper signal.
10. Never force a daily signal when evidence is absent.

## 80% target

The 80% figure is a research threshold, not a guarantee.

A strategy must cross the threshold **out-of-sample**, with enough observations and replication, before it is treated as a candidate signal. High hit rate without positive expected return is not sufficient.

## Product-specific investigation

### eFootball GT
- participant identity and repeat matchup effects
- participant-specific win/draw/loss frequencies
- score and total-goal distributions
- odds movement
- same-event prices across operators where the underlying event is genuinely identical

### eAdriatic
- repeat participant patterns
- competition/round structure
- score distributions
- market-specific behaviour

### SRL
- team identity as simulation labels, not real-world match form
- repeated team pairings
- league/competition-specific distributions
- price/result relationship
- cross-bookmaker event matching

### Virtual Football
- season/table structure
- team/player attributes where legitimately disclosed
- repeat fixtures
- short-interval event behaviour
- result and score distributions

### Zoom / Turbo
- event cadence
- competition/product fingerprints
- market efficiency and outcome distributions

## Safety / integrity boundary

The lab does not:
- bypass authentication/security;
- reverse-engineer or recover secret RNG state;
- manipulate bookmaker requests;
- exploit technical faults for unauthorized payouts;
- automate wagering;
- claim that an anomaly proves manipulation.

## Architecture

`Standalone Browser UI → local/imported observed dataset → research calculations`

Future optional architecture:

`Legitimate public-data collector → normalization store → research engine → paper-only signal API → Virtual Lab UI`

The collector must use permitted/public data access or a licensed data source. No private credentials or secrets belong in this public repository.

## Separation rule

Do not add Virtual Lab navigation links or shared runtime dependencies to the existing Match Signal pages until the research module is independently validated.
