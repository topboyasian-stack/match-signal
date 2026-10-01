# Match Signal Odds Builder Push Notifications

The Builder now supports background browser push notifications. A subscriber is stored in Cloudflare KV, and the notification sender reads the published `data/odds_builder.json` artifact and only sends when a real batch is at least 2.80x combined odds.

## One-time Cloudflare setup

In the Match Signal Pages project, create a Workers KV namespace and bind it to the Pages project as:

`PUSH_SUBSCRIPTIONS`

Then add these production environment secrets/variables:

- `VAPID_PUBLIC_KEY` — URL-safe base64 VAPID public key
- `VAPID_PRIVATE_KEY` — URL-safe base64 VAPID private key
- `VAPID_SUBJECT` — a contact URL such as `mailto:your-address@example.com`

Generate a key pair locally with:

```bash
npx @mmmike/web-push generate-vapid-keys
```

If that command is unavailable in the installed package version, use:

```js
import { generateVapidKeys } from "@mmmike/web-push/vapid";
const keys = await generateVapidKeys();
console.log(keys);
```

Set both VAPID keys in the Cloudflare Pages production environment; never commit the private key.

## Enable it in Match Signal

Open:

`https://match-signal.pages.dev/odds-builder.html`

Click **Enable notifications** and approve the browser notification permission.

The browser registers `/sw.js`, creates a Web Push subscription, and stores that subscription through `/api/push-subscribe`.

## Delivery rule

The Builder notification workflow only alerts for a newly published batch whose:

- combined SportyBet odds are at least **2.80x**
- leg count is at least 2

The Builder still keeps **4.00x** as the secondary target. It never adds weak legs just to reach either target.

The push sender deduplicates each exact batch fingerprint, so the same batch is not repeatedly announced on every 15-minute Builder refresh.
