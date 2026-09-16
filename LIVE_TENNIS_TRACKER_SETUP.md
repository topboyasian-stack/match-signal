# Live Tennis Tracker

Match Signal now has a secure live-play adapter at `/api/tennis-live` and a Live Play panel on `match-tracker-v3.html`.

## Provider

Live Tennis API: https://api.livetennisapi.com/

The current integration uses the provider's `GET /matches?status=live` current-state feed. The published FREE tier supports live matches/current scores; the provider documents current `sets`, `games`, `points`, and `server` state on its score surface. A free key requires no card.

## Cloudflare secret

Add this Pages project environment variable:

`LIVE_TENNIS_API_KEY`

Use the provider API key as the secret value. Do not put the key in repository files or browser JavaScript.

## What the current tracker shows

- live set score
- current game score
- current point score
- server
- tiebreak state when supplied
- provider refresh timestamp

The tracker polls the secure same-origin adapter every 5 seconds.

## Point-by-point stream

The current integration intentionally uses the lower-cost current-state feed. If Match Signal later needs every individual point event as it happens, Live Tennis API documents that live per-point events and its WebSocket point stream require the ULTRA tier. Do not simulate point events from snapshots.

## Failure behavior

If the secret is missing or the provider does not cover a match, the UI displays an explicit unavailable state. It never fabricates a point, server, or score.
