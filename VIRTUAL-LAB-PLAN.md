# Match Signal Virtual Lab v1

**Public owner:** Diddy  
**Build:** MS-VIRTUAL-LAB-V1-2026.09.22  
**Production route:** /virtual-lab/

## Purpose

A standalone, read-only research environment for legitimately observed SportyBet NG eFootball and virtual-football products. The lab is separate from the core football/tennis prediction desk.

## Active products

1. eFootball — GT Sports League
2. eFootball — eAdriatic
3. Virtual Football
4. Zoom / Turbo virtuals

**SRL is excluded from the active collection, prediction and settlement pipeline.**

## Data lifecycle

`source → raw response → canonical event → participant identity → market snapshot → pending observation → official settlement → append-only archive → cumulative history → participant statistics → walk-forward evaluation → paper-only research signal`

The UI reads these artifacts. It does not manufacture research state.

## Preservation

Existing history is preserved. The pre-rebuild evidence is retained under:

`data/virtual_lab_archive/2026-09-22/`

Daily settlement records are appended under:

`data/virtual_lab_archive/settlements/YYYY-MM-DD.jsonl`

The current participant registry is rebuilt from automatic settled history and archived settlements.

## Participant boundaries

Stable participant identity is product-scoped.

- eFootball participant identities come from explicit/observed participant metadata, including historically observed parenthetical identifiers.
- Club/team names are contextual and are never identity keys.
- Unresolved or truncated identities are not guessed.
- The confirmed eFootball watch is separate from automatic participant discovery.
- Tennis participant evidence is preserved separately and is outside the Virtual Lab namespace.

Confirmed eFootball identities currently include DECIMATOR, EXECUTIONER, AGENT, DUSK, DANTE, BOUNTY, STORM, HAYMAKER and CROWN.

## Research lines

Priority O/U lines:
- 1.5 — experimental
- 3.5
- 4.5

O/U 1.5 is tracked because observed evidence may be useful, but it is not promoted by ticket streaks or small samples.

## Validation

The lab uses chronological out-of-sample evaluation, model calibration and replication gates. A high raw hit rate is not enough.

The model must avoid look-ahead information and must not train on user-reported ticket outcomes.

## Production architecture

The public route is:

`https://match-signal.pages.dev/virtual-lab/`

Only one authoritative browser renderer is loaded there:

`virtual-lab-app.js`

Legacy pages remain as compatibility redirects so there is no second production Virtual Lab implementation.

## Debugging contract

Every important settlement row carries:
- record_id
- trace_id
- event_id
- participant keys
- schema version
- pipeline version
- settlement source

The UI exposes build, feed and history diagnostics. A zero-data condition identifies which pipeline layer returned zero.

## Integrity boundary

The lab does not bypass authentication/security, recover secret RNG state, manipulate bookmaker requests, exploit technical faults, automate wagering, or claim that statistical anomalies prove manipulation.
