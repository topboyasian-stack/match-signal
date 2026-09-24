# Match Signal — Upgrade & Release Playbook

## Purpose

This file is the permanent operating procedure for changing Match Signal without losing track of the architecture, mixing sport engines, breaking production, or assuming that a GitHub commit means the live site is fixed.

**Production is Cloudflare Pages:** `https://match-signal.pages.dev`

GitHub is the source repository. Cloudflare Pages is the user-facing production deployment. The GitHub Pages workflow that exists in the repository is legacy/secondary and must not be treated as the production URL.

---

## 1. Non-negotiable upgrade rule

Every change follows:

**Inspect → isolate → change → validate → commit → deploy → inspect production → verify user-visible behavior.**

Never report an upgrade as complete merely because:
- the code committed;
- GitHub Actions is green;
- Cloudflare shows a successful deployment; or
- a file exists on `main`.

A change is complete only after the actual Cloudflare production page/data endpoint is checked and the affected feature is visibly working.

If any verification stage fails, continue fixing rather than stopping at the failed stage.

---

## 2. Architecture map — keep responsibilities separate

### Prediction engines

`predict_today.py` contains separate prediction paths for:

- **Football:** 1X2, Poisson/xG, O/U, BTTS, handicap, form, and market benchmark inputs.
- **Tennis:** ATP/WTA singles, rankings, recent form, match probability, set probability, straight-set probability, three-set probability, expected sets, total games, and games handicap.

Do not modify one sport's engine while trying to repair another sport's UI/data problem unless the evidence shows the engine itself is the cause.

### Precision sports engines

- **Darts-X:** standalone page/workflow/data pipeline. It belongs on its own Darts desk and must not be wired into the Virtual Lab.
- **Table Tennis-X:** standalone page/workflow/data pipeline. It belongs on its own Table Tennis desk and must not be wired into the Virtual Lab.
- The shared boundary across those two sports is navigation and production verification only.

### Generated data

Important outputs:

- `data/predictions.json` — primary published Football + ATP/WTA prediction feed.
- `data/ere_divisie_predictions.json` — independent Eredivisie expansion feed.
- `data/prediction_history.json` — prediction/settlement history.
- `data/accuracy.json` — settled performance summary.
- `data/pipeline_status.json` — latest pipeline counts, QC, errors, and source status.

The Expansion Desk intentionally reads the primary feed plus the Eredivisie expansion feed and deduplicates them before rendering.

### Live system

- `live.html` — live dashboard.
- `live-analysis.js` / `live-data-worker.js` — live analysis/data handling.
- `match-tracker-v3.html` — individual live tracker page.
- `match-tracker-v2-shim.js` — tracker bootstrap/compatibility layer.

Live coverage must be checked against the configured provider league slugs. Adding a prediction league does **not** automatically add it to live coverage.

### Expansion Desk

- `expansion.html` — current all-fixtures Expansion Desk UI.
- `expansion.js` — runtime renderer and feed loader.
- `_redirects` — preserves legacy routes such as `/expansion-update` by routing them to `/expansion.html`.

The Expansion Desk is a **renderer of published engine outputs**. It must not silently create a second prediction engine.

### Production

Cloudflare Pages is connected to `topboyasian-stack/match-signal` and automatic deployments are enabled.

Current production URL:

`https://match-signal.pages.dev`

Useful production checks after a release:

- `/`
- `/expansion`
- `/expansion.html`
- `/expansion-update`
- `/live.html`
- `/match-tracker.html`
- `/data/predictions.json`
- `/data/ere_divisie_predictions.json`

---

## 3. Standard upgrade procedure

### Step A — Identify the layer

Before changing code, classify the request:

1. **Engine/model** — calculation is wrong.
2. **Data ingestion** — fixtures/results are missing or malformed.
3. **Settlement** — completed fixtures are not being settled.
4. **Live provider mapping** — current matches are not detected.
5. **Frontend renderer** — correct data exists but is not displayed.
6. **Routing** — correct page exists but old URL points elsewhere.
7. **Deployment** — correct GitHub code is not reaching Cloudflare.
8. **Caching/runtime** — production has the new files but browser/runtime executes stale or broken code.

Do not rewrite an engine when the actual problem is routing, deployment, or rendering.

### Step B — Inspect before editing

Check the relevant source file **and** the generated data it consumes.

For example:

- UI bug → inspect HTML/JS + actual JSON feed.
- Missing fixture → inspect generator + feed + provider coverage.
- Live bug → inspect live page + league slug list + provider response + matching logic.
- Tracker bug → inspect tracker page + shim + tracker script.
- Deployment bug → inspect Cloudflare deployment commit and production URL.

### Step C — Make the smallest isolated change

Prefer a focused change that preserves existing engines and feeds.

Examples from the current recovery:

- Added Eredivisie to live coverage instead of changing football prediction logic.
- Added team/league fallback matching instead of depending only on provider event IDs.
- Expanded Saudi fixture collection without inventing a match on a date with no scheduled match.
- Changed the Expansion Desk to consume published feeds instead of rebuilding predictions.
- Externalized `expansion.js` after the inline runtime failed in production.
- Added legacy routing so `/expansion-update` remains usable.

### Step D — Validate locally/in repository

At minimum:

- JavaScript/Python syntax checks for changed code.
- JSON parsing for changed/generated feeds.
- Non-empty data assertions where the feature requires data.
- Check that sport fields remain correct (`football`, `tennis`, etc.).
- Check that ATP/WTA live/prediction filtering remains singles-only.
- Check that no fabricated market values are introduced.
- Check that an empty replacement feed cannot overwrite a healthy published feed.

### Step E — Commit with a descriptive message

Use one clear commit per logical fix where practical.

Good:

`Fix Expansion Desk runtime loading`

`Fix missing Eredivisie live coverage`

`Expand Saudi Pro League fixture window`

Avoid vague messages such as `update`, `changes`, or `fix stuff`.

### Step F — Wait for Cloudflare

After the push:

1. Open Cloudflare → Workers & Pages → `match-signal` → Deployments.
2. Confirm the production deployment references the **new commit SHA**.
3. Confirm status is successful.
4. Only then inspect the production URL.

Do not switch production back to GitHub Pages.

### Step G — Verify the actual user-facing result

For a frontend change:

1. Open the exact affected Cloudflare URL.
2. Hard refresh (`Ctrl+Shift+R`).
3. Confirm the new UI is visible.
4. Confirm data counts/cards are populated.
5. Confirm browser/runtime errors are absent.

For a data change:

1. Open the relevant production JSON endpoint.
2. Confirm it contains current rows.
3. Confirm the expected league/sport is present.
4. Confirm the frontend displays those rows.

For live changes:

1. Confirm the provider is actually returning the event.
2. Confirm the league slug is configured.
3. Confirm ID matching and fallback team matching.
4. Confirm the event appears in `/live.html`.
5. If an individual tracker is involved, open `/match-tracker.html?...` and verify the tracker itself.

---

## 4. Prediction-feed safety rules

### Never do this

A pipeline must not replace `data/predictions.json` with `[]` simply because a selector, confidence gate, experimental filter, or temporary provider failure produced no qualifying rows.

### Required behavior

- Preserve the complete valid prediction feed.
- Store selected/qualified candidates separately.
- Treat empty provider responses as a data-quality event.
- Fail loudly when a required sport disappears unexpectedly.
- Keep historical/settlement data separate from today's published predictions.

### Required checks

Before publication:

- feed parses as JSON;
- feed is a list;
- required sports exist when their scheduled coverage exists;
- expected leagues are present when fixtures are scheduled;
- no duplicate event IDs unless explicitly justified;
- no obviously fabricated odds/markets;
- prediction timestamps are current enough for the pipeline run.

The current pipeline status file is the first place to inspect counts, errors, rejected matches, and source status.

---

## 5. Sport-engine protection

### Football

Keep the football calculation path independent from tennis and basketball.

Core fields to protect:

- 1X2 probabilities
- expected goals
- O/U
- BTTS
- handicap
- model/source
- independent probabilities
- calibrated probabilities
- market benchmark fields
- diagnostics/history fields

### Tennis

Keep ATP and WTA separate from football.

Only accept valid singles fixtures. Reject doubles, generic players, missing athlete IDs, and malformed two-player events.

Core fields to protect:

- match probabilities
- rankings
- recent form
- set-win probabilities
- straight-set probabilities
- three-set probability
