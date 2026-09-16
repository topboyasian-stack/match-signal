# Match Signal Monetization Roadmap

Status: PAPER / RESEARCH ONLY. No module in this roadmap places or stakes a wager.

## Phase 1 — Verified Tip Ledger
Implemented by `scripts/build_monetization_ledger.py`.
- Records predictions published before event start.
- Preserves settlement evidence from `prediction_history.json`.
- Tracks accuracy and Brier evidence.
- Measures ROI only when a real bookmaker decimal price is present.
- Never invents historical bookmaker prices.

Outputs:
- `data/verified_tip_ledger.json`
- `data/tippingsports_export.json`
- `data/tippingsports_export.csv`

## Phase 2 — Automated performance record
The monetization workflow regenerates the ledger and market-research artifact on schedule. It is deliberately separate from the prediction engines and settlement logic.

## Phase 3 — Public proof record
The existing production performance surface can consume the verified ledger. Any public record must clearly label the dataset as paper research until real bookmaker prices and independently reproducible results are available.

## Phase 4 — TippingSports preparation
TippingSports currently requires a public, genuine and profitable tipping history, at least six months of active account history, at least 30 tips/month, and no month worse than -10 points before accepting a seller application. The platform also permits bot/system tipster accounts under its terms. Match Signal therefore prepares structured exports first; account creation, eligibility and submission remain external.

## Phase 5 — Match Signal API
Cloudflare Pages Functions expose authenticated read-only endpoints:
- `/api/v1/predictions`
- `/api/v1/performance`
- `/api/v1/accumulator`

Set the production Cloudflare Pages secret `MATCH_SIGNAL_API_KEY` before commercial use. No key is committed to Git.

## Phase 6 — RapidAPI distribution
`api-docs/openapi.yaml` is the initial product contract for a future RapidAPI listing. Pricing and marketplace onboarding are external. RapidAPI currently supports free, pay-per-use, freemium and paid plans and publishes its current marketplace fee in its provider documentation.

## Phase 7 — Event-market research
`scripts/market_research.py` reads public Kalshi market data and compares it with Match Signal probabilities when event matching is sufficiently strong. Execution is disabled. Webull is represented as an auth-required adapter only; no Webull credentials or order code are stored.

### Promotion gates
Do not claim commercial profitability until:
1. predictions are timestamped before start;
2. settlement is authoritative;
3. bookmaker price at publication is captured from a legitimate source;
4. ROI and drawdown are calculated from those prices;
5. calibration is measured by sport/market/confidence;
6. enough out-of-sample history exists to evaluate stability;
7. external marketplace terms and jurisdictional requirements are reviewed.
