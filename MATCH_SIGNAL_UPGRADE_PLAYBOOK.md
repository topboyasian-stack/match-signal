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
- expected sets
- total games
- games handicap
- signal quality

### Basketball

Keep the basketball pipeline isolated. Do not infer basketball fields from football or tennis structures.

Any basketball-specific market/normalization changes require their own regression check.

---

## 6. Live-coverage checklist

When the user says a live match is missing:

1. Verify the match is genuinely live from an authoritative/current provider.
2. Find its provider league slug.
3. Check that slug exists in `live.html`/live data configuration.
4. Check provider event retrieval.
5. Check event-ID matching.
6. Check normalized league + home/away team fallback matching.
7. Check that the live page is actually querying that league.
8. Check production deployment includes the changed live files.
9. Open the production `/live.html` and verify visually.

Never assume a missing live match means the prediction engine is broken.

---

## 7. Routing and frontend checklist

A new page is not complete until all intended URLs are mapped.

When replacing an old page:

- preserve the old URL where possible;
- add a `_redirects` mapping;
- cache-bust changed JS/CSS where needed;
- avoid duplicate old/new renderers competing for the same page;
- test both the canonical new URL and the legacy URL.

Example current mapping:

`/expansion-update` → `/expansion.html`

The current Expansion Desk loads `expansion.js` separately so a runtime failure is visible and diagnosable rather than leaving the page indefinitely at “Loading”.

---

## 8. Deployment checklist

Cloudflare Pages is the production system.

The repository also contains a GitHub Pages workflow for historical/secondary deployment purposes. **Do not use its URL as the production URL.**

Before saying “live”:

- [ ] Git commit exists on `main`.
- [ ] Changed files are in the commit.
- [ ] Generated data is valid/non-empty where required.
- [ ] Cloudflare production deployment references the new commit.
- [ ] Cloudflare deployment succeeded.
- [ ] Production HTML reflects the new version.
- [ ] Production JSON reflects current data.
- [ ] Browser/runtime behavior works.
- [ ] Affected feature is visibly verified.

---

## 9. Failure-prevention lessons from the current recovery

These are now permanent rules because each caused real confusion during the recovery:

### Green CI is not production verification

A successful GitHub Actions run does not prove Cloudflare has deployed or that the browser can execute the new code.

### Generated data is part of the product

Never verify only source code. Inspect the generated JSON that the UI consumes.

### A missing league slug can hide a valid live match

Prediction coverage and live coverage are separate configuration surfaces.

### Provider IDs are not always stable across pipelines

Live matching needs a safe fallback using league + normalized home/away names when IDs differ.

### Deployment path filters can hide frontend changes

If a changed frontend file is not included in a deployment trigger, the source can be correct while production remains old.

### Inline JavaScript is more fragile than an external renderer

The Expansion Desk now uses `expansion.js`; future substantial UI logic should follow the same pattern.

### Empty candidate selection must not destroy the primary feed

Selection/qualification output must remain separate from the complete prediction feed.

### Experimental does not mean invisible

Experimental leagues can have full prediction outputs and dedicated monitoring while remaining clearly marked as experimental/paper-only.

---

## 10. Standard verification report format

For every substantial upgrade, report internally in this order:

**Change**
- What was changed.

**Root cause**
- What actually caused the problem.

**Files changed**
- Exact source files.

**Data validation**
- Counts, leagues/sports, errors.

**Commit**
- SHA and message.

**Cloudflare deployment**
- Production deployment SHA/status.

**Production verification**
- Exact URL(s) tested.
- What was visibly confirmed.

**Remaining issues**
- Only genuine unresolved items; never hide them behind “done”.

---

## 11. Current known state at creation of this playbook

As of 2026-09-15:

- Cloudflare Pages is the production host at `match-signal.pages.dev`.
- The Expansion Desk is working and renders published Football + Tennis feeds.
- `/expansion-update` is preserved as a legacy route to `/expansion.html`.
- `data/predictions.json` contains published WTA and football prediction records.
- `data/ere_divisie_predictions.json` contains the independent Eredivisie expansion feed.
- `data/pipeline_status.json` is the operational source for latest prediction counts/QC/errors.
- `data/prediction_history.json` is the settlement history.
- `data/accuracy.json` is the performance summary.
- `match-tracker-v3.html` uses the tracker shim and must be tested whenever tracker bootstrap code changes.

### Known follow-up to handle before treating experimental leagues as fully settled

`scripts/settle_same_day.py` currently maps the core football leagues but does not yet list Eredivisie or Saudi Pro League in its `FOOTBALL_LEAGUES` mapping. If those experimental leagues are expected to settle through the same-day settlement pipeline, add and test those mappings as a separate controlled change.

Do not silently alter settlement logic while making unrelated frontend upgrades.

---

## 12. Golden rule for future work

**Never make a new update on top of an assumption about what is live.**

First establish:

`GitHub source → generated data → deployment commit → Cloudflare production → browser behavior`

Then change only the layer that is actually broken.

This playbook is the map to use before every future Match Signal upgrade.
