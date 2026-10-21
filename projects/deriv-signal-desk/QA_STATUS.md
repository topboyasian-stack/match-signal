# Deriv Signal Desk QA status

Updated: 2026-10-21

## Source control
- Project files are committed on the isolated branch `feature/deriv-signal-desk`.
- This branch is currently stored inside `topboyasian-stack/match-signal` under `projects/deriv-signal-desk/`.
- No changes have been made to the repository's `main` branch.
- A standalone GitHub repository has not been created because the currently connected GitHub actions do not expose repository creation. Keep this branch isolated until a dedicated repository can be created.

## Checks completed
- Static QA script passed: version stamp, current and fallback Deriv endpoints, public symbol normalization, closed-candle signal confirmation, BUY/SELL labels, explicit read-only method scan, CSP hosts, manual-only wording, and JavaScript syntax.
- Live public-feed smoke test from the build environment passed for:
  - Synthetic index: `1HZ100V`, 60 historical candles and live tick received.
  - Forex: `frxAUDCAD`, 60 historical candles and live tick received.
  - Commodity: `frxXAGUSD`, historical candles and live tick received.
- The public endpoint `wss://api.derivws.com/trading/v1/options/ws/public` returned active symbols, candle history, and tick updates.
- Known order-submission method scan passed. Dashboard source contains no trade submission or position-management API call.

## Not yet passed
- Browser smoke test from the user's Chromebook.
- Final Cloudflare Pages deployment of Build 0.5. The previous hosted app's Build 0.2 remains the last confirmed live deployment; later builds were blocked by that hosting platform's scanner.
- Profitability and signal accuracy have not been established. Demo evaluation is required before any live trading consideration.

## Acceptance criteria before calling it ready
1. Fresh Cloudflare Pages deployment serves Build 0.5.
2. In a normal Chrome browser, the status reads connected and candles/ticks populate for synthetic, forex, and commodities.
3. Switching symbol and timeframe reloads the chart without stale subscriptions.
4. BUY/SELL arrows are plotted only on confirmed closed candles and do not repaint historical confirmed markers.
5. Automated QA passes and a manual browser smoke test is recorded.
6. Confirm there are no account, balance, order, modify, cancel, or close-position connections.
