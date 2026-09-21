# Match Signal — Engine Protection Boundary

**Public owner identity:** Diddy  
**Build marker:** MS-V6-IP-2026.09.21

## Current state
The repository is currently public. Therefore source under the scripts directory, workflows, and other repository paths must be considered publicly inspectable.

## Target state

### Public layer
- HTML/CSS presentation
- client-safe UI code
- non-sensitive generated results
- public provenance metadata
- third-party attribution

### Protected layer
- proprietary model implementations
- calibration parameters and internal thresholds
- SportyBet matching and market intelligence implementation
- Odds Builder qualification internals
- private data-processing logic
- credentials and operational endpoints

The protected layer should run in a private repository or server-side runtime and expose only the minimum API/result surface required by the public application.

## Migration rule
Do not delete or rewrite the working V6 engines merely to create the boundary. First establish a protected execution target, verify equivalent outputs against the frozen V5/V6 baseline, then switch the public application to the protected endpoint. Keep the existing system recoverable until parity is demonstrated.

## Release fingerprint
Every protected release should publish a non-secret build identifier such as MS-V6-IP-2026.09.21 and preserve the corresponding Git commit in the release record.

This document describes the technical boundary; it is not legal advice.