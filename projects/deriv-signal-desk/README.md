DERIV SIGNAL DESK - CLOUDFLARE PAGES DIRECT UPLOAD

This ZIP contains index.html (the complete dashboard) and _headers (security headers plus the Deriv public WebSocket allow-list).

DEPLOY
1. Sign in to your own Cloudflare account.
2. Open Workers & Pages and choose Create, then Pages / Direct Upload (labels may vary).
3. Name the project deriv-signal-desk.
4. Upload this ZIP on the Direct Upload screen and deploy.
5. Open the resulting https://<project-name>.pages.dev URL.

SAFETY
- Public market data only. No Deriv password, API token, account balance, or account connection.
- No code submits, modifies, cancels, or closes trades.
- Green BUY arrows and red SELL arrows are confirmed on closed candles using EMA20/EMA50, RSI(14), and ATR(14) reference levels.
- These are analytical signals, not financial advice or a profit guarantee. Validate symbol/price in Deriv MT5 and evaluate on demo first.

CONNECTION
The public endpoint wss://api.derivws.com/trading/v1/options/ws/public was tested from the build environment and returned active symbols, live ticks, and historical candles. Your browser/network must allow secure WebSocket traffic to this endpoint. The dashboard includes legacy endpoint fallbacks.
