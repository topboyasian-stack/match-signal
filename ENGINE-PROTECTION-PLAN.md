# Match Signal V6 — Protected Engine Migration

Public owner: Diddy  
Copyright: © 2026 Diddy. All rights reserved.  
Production: https://match-signal.pages.dev

## Objective
Move proprietary V6 analytics and market-intelligence logic out of the public presentation layer without changing validated V6 behavior.

## Protected components
- prediction/model implementations
- probability calibration and internal parameters
- SportyBet matching and market intelligence
- Odds Builder qualification and correlation logic
- proprietary data-processing and settlement logic
- private operational endpoints and credentials

## Public components
- HTML/CSS/client-safe UI
- provenance and ownership markers
- non-sensitive generated results
- public documentation and third-party attribution

## Migration rule
Do not delete or rewrite the working V6 engine first. Establish the protected execution target, freeze a comparison baseline, verify equivalent outputs, then switch production.

## Required boundary
Browser → protected API → V6 engine → data/providers

The browser must never receive credentials or proprietary source needed to reconstruct the protected engine.

## Release verification
Every protected release should retain:
- Match Signal identity
- Diddy ownership marker
- build fingerprint
- model/version identifier
- reproducible comparison against the previous approved V6 baseline

## Current status
This branch establishes the migration boundary and documentation. The repository is still public until repository visibility is changed separately.
