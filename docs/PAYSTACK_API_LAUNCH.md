# Match Signal Paystack API access setup

This is the no-upfront-cost checkout path for selling time-limited access to the existing read-only Match Signal API. It does not change the prediction engine or execute bets.

## What is included

- `/api-access.html`: customer checkout page (₦5,000 / 30 days by default; one-time, no automatic renewal).
- `POST /api/payments/initialize`: server-side Paystack transaction initialization; price is controlled server-side in kobo.
- `POST /api/payments/verify`: server verifies the transaction with Paystack before issuing an API key.
- `POST /api/payments/webhook`: verifies Paystack's SHA-512 HMAC signature and reconciles successful payments.
- `/payment-success.html`: verifies and displays the API key after the Paystack return.
- `/api/v1/*`: supports time-limited customer API keys as well as the optional existing shared `MATCH_SIGNAL_API_KEY`.
- `migrations/0001_match_signal_payments.sql`: D1 tables for payment and key records.

## Required Cloudflare configuration (production)

1. In Cloudflare, open **Workers & Pages → match-signal → Settings → Bindings**.
2. Create a **D1 database** (no paid third-party service is needed for the D1 binding; check your Cloudflare plan quotas) and bind it with the exact variable name `MATCH_SIGNAL_DB`.
3. Apply `migrations/0001_match_signal_payments.sql` to that database using the D1 console or Cloudflare's D1 migration workflow. Confirm both `ms_payments` and `ms_api_keys` tables exist.
4. Under the Pages project's **Settings → Variables and Secrets**, add `PAYSTACK_SECRET_KEY` as an encrypted secret. Use Paystack test keys for a test deployment first. Never put the key in HTML, a public variable, or Git.
5. Optionally set `MATCH_SIGNAL_API_MONTHLY_PRICE_KOBO` to a whole number of kobo. Default is `500000` (₦5,000). Keep this as a server-side variable; do not accept a price from the browser.
6. `MATCH_SIGNAL_ALLOWED_ORIGINS` defaults to `https://match-signal.pages.dev`. If checkout uses a custom domain, set this to a comma-separated list of exact trusted origins, including the scheme, with no path.
7. Deploy the branch through the pull request and verify the deployment is serving these files. Do not merge or switch the production branch until the checks below pass.

## Paystack dashboard

1. Start with Paystack test mode and the test secret key.
2. Set the webhook URL to `https://match-signal.pages.dev/api/payments/webhook` (replace the host if the actual production domain differs).
3. The customer return URL is `https://match-signal.pages.dev/payment-success.html`; the checkout endpoint sends it to Paystack automatically.
4. Confirm the Paystack account is approved for live payments and confirm your business name, customer support contact, settlement bank, refund process, and applicable business/compliance details before switching to live keys.
5. After successful end-to-end test payments and a refund/reconciliation test, replace the test secret with the live secret in Cloudflare. Never use a live key in test mode or commit it.

## End-to-end acceptance checklist

- [ ] With no secret or no D1 binding, checkout returns a clear 503 and does not claim a payment was taken.
- [ ] Invalid email is rejected; the browser cannot set the amount.
- [ ] Paystack initialization returns a hosted checkout URL and a checkout token.
- [ ] Failed, pending, wrong-currency, wrong-amount, wrong-reference, or wrong-email transactions do not issue an API key.
- [ ] Webhook rejects missing/invalid signatures.
- [ ] A verified successful test transaction creates exactly one payment record and one API-key record.
- [ ] The success page displays the key only after verification; reloading the page can recover the same key for that checkout session.
- [ ] A valid key can call all four `/api/v1/*` endpoints; invalid keys return 401; expired keys return 401.
- [ ] Confirm the key expires after 30 days and confirm a new purchase creates a new key.
- [ ] Confirm API docs, terms, mobile checkout, Paystack callback, and webhook work on the deployed production origin.
- [ ] Confirm the API and checkout never expose the Paystack secret in HTML, JavaScript, responses, or logs.
- [ ] Confirm any internal scripts/workflows previously found publicly accessible are removed from the static output or otherwise denied before launch.
- [ ] Run a final end-to-end test using Paystack test mode before enabling live collections.

## Customer API use

Send the API key in the request header, never as a query parameter:

```http
Authorization: Bearer ms_live_REPLACE_WITH_ISSUED_KEY
```

Example endpoint: `GET https://match-signal.pages.dev/api/v1/performance`.

The API is research-only. Prediction accuracy is not a guarantee of profit, and ROI must remain unavailable when qualifying bookmaker-price records do not exist.

## Current limitations / launch gate

- D1 must be bound and migrated in Cloudflare; this repository change cannot create or bind a database inside your Cloudflare account.
- A Paystack secret must be added in Cloudflare; no secret belongs in the repository.
- Live collections are not verified until the deployed test checkout, callback, webhook, key expiry and failed-payment paths have passed.
- The API keys currently authorize the documented API endpoints. This change does not lock existing public HTML pages behind a subscription.
- Before launch, inspect the static output for private/internal files; HTTP cache headers alone do not make a public file private.
