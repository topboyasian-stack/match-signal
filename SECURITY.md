# Match Signal Security

## Official identity
- Product: Match Signal
- Public owner identity: Diddy
- Official production: https://match-signal.pages.dev
- Build family: V6

## Reporting a vulnerability
Do not publish credentials, private endpoints, or exploitable details in a public issue. Contact the project owner through the private contact channel associated with the Match Signal project.

## Security boundaries
Match Signal is being transitioned toward a split architecture in which the public presentation layer is separated from proprietary analytics and market-processing logic. Sensitive credentials and private operational endpoints must never be embedded in browser-delivered HTML, CSS, JavaScript, JSON, or GitHub Actions logs.

## Secrets
Never commit API keys, access tokens, bookmaker credentials, Cloudflare credentials, Telegram bot tokens, database credentials, private signing keys, or session cookies. Use deployment/repository secret storage instead.

## Proprietary engine
Prediction, calibration, market intelligence, SportyBet synchronization, settlement, and Odds Builder logic are proprietary. Until the repository split is completed, assume code committed to this public repository is publicly inspectable and do not treat repository access as a confidentiality boundary.

## Incident response
If a secret is exposed, revoke or rotate it first, then remove the exposure from the active tree and assess repository history. Removing a secret from the latest commit does not invalidate copies that may already exist.

This file is operational guidance, not legal advice.