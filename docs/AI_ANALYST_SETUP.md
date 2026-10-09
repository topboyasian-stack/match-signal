# AI Analyst deployment setup

The analyst source is fail-closed. The page can exist on the site, but private storage and AI requests remain unavailable until bindings and a secret are configured. Never add these values to GitHub or paste them into ChatGPT.

## Configure Cloudflare Pages

Open Cloudflare Dashboard, then Workers & Pages, the Match Signal Pages project, Settings, and Production bindings/secrets.

1. Create a dedicated Workers KV namespace and bind it as MATCH_SIGNAL_ANALYST_STORE. Do not reuse PUSH_SUBSCRIPTIONS or another application namespace. This namespace stores private ticket review records and small AI usage counters.
2. Add a Workers AI binding named AI.
3. Add a secret named MATCH_SIGNAL_ANALYST_TOKEN. Generate a unique high-entropy token locally, for example with openssl rand -hex 32. Do not reuse a password.
4. Optionally set ANALYST_AI_MODEL to a currently supported Workers AI model ID. If omitted, the source defaults to @cf/meta/llama-3.1-8b-instruct-fast. Check the current model catalog before changing it.
5. Redeploy Pages after binding changes, then open /analyst.html and enter the token.

Official references:
- https://developers.cloudflare.com/pages/functions/bindings/
- https://developers.cloudflare.com/workers-ai/configuration/bindings/
- https://developers.cloudflare.com/workers-ai/models/
- https://developers.cloudflare.com/workers-ai/platform/pricing/

## Privacy and limits

- All API operations on the private ledger require the token and reject cross-origin requests when an Origin header is present. Responses are private and no-store.
- Ticket records are stored in KV, never the public repository or public static JSON assets.
- AI calls are on-demand and limited in this application to 25 requests per UTC day. Actual Cloudflare quotas, billing and model availability still apply.
- For chat and parsing, the server sends selected system aggregates and up to eight recent user tickets to the configured model. Do not submit information that you do not want processed by that model.
- Parsing returns a draft and never saves automatically. Check every fixture, product, selected side, line, odds, score and result before saving.
- The original desk snapshot is stored only when explicitly present. It is never inferred from the actual ticket.
- User-selected tickets remain a selection-biased evaluation cohort, separate from Builder outcomes and all model-training history.
- The AI cannot change model weights, selection gates, deployments or place bets.

## Production checklist

- [ ] Create the dedicated KV namespace and binding.
- [ ] Add Workers AI binding AI.
- [ ] Add the random MATCH_SIGNAL_ANALYST_TOKEN secret.
- [ ] Redeploy Cloudflare Pages.
- [ ] Verify unauthenticated API requests fail and the page connects with the token.
- [ ] Parse a synthetic slip, inspect the draft, save, export, reload and delete the synthetic record.
- [ ] Ask one question and inspect the evidence timestamps.
- [ ] Confirm no populated user-ticket records appear in GitHub or public data endpoints.
