# Match Signal Virtual Lab v1 — Traceable Architecture

Build family: MS-VIRTUAL-LAB-V1
Rebuild date: 2026-09-22
Production route: /virtual-lab/

## Purpose

The Virtual Lab is a standalone, read-only research environment for legitimately observed SportyBet NG eFootball and virtual-football data. It never places wagers or bypasses security, private endpoints, authentication, or RNG protections.

## Canonical data flow

SportyBet public/authorized feed
→ feed snapshot / response
→ canonical event normalization
→ stable participant identity
→ market/odds snapshot
→ pending observation
→ official result settlement
→ append-only settlement archive
→ cumulative history
→ participant registry and statistics
→ walk-forward model evaluation
→ paper-only prediction desk

The UI is a consumer of these artifacts. It is not the source of truth.

## Product boundaries

Production Virtual Lab products:
- efootball_gt
- efootball_adriatic
- vfootball
- zoom

SRL is excluded from the active pipeline.

Tennis is outside the Virtual Lab namespace. Tennis participant evidence is preserved in the tennis archive and is never displayed or used by the Virtual Lab eFootball watch layer.

## Participant identity

Stable identity is product-scoped.

For eFootball, explicit participant metadata or the historically observed parenthetical participant identifier is used when present. Club/team labels are contextual and may rotate; they are never identity keys.

Unresolved or truncated identities are retained only as unresolved evidence and are never guessed.

Every settled observation carries:
- record_id
- trace_id
- participant_1_key
- participant_2_key
- schema_version
- pipeline_version
- settlement source

## Preservation

The pre-rebuild snapshot remains in:
data/virtual_lab_archive/2026-09-22/

The original mixed watchlist is preserved verbatim at:
data/virtual_lab_archive/2026-09-22/participant-watch-original.json

Existing settled evidence is preserved at:
data/virtual_lab_archive/2026-09-22/settled-history-baseline.json

New settlements are appended by UTC day under:
data/virtual_lab_archive/settlements/YYYY-MM-DD.jsonl

The current cumulative history is retained for UI/model compatibility. The archive is the durable forensic ledger.

## Watch namespaces

Confirmed eFootball watch:
data/virtual_lab_participants/efootball_confirmed_watch.json

Tennis preservation:
data/virtual_lab_participants/tennis_archive.json

Automatic participant statistics:
data/virtual_lab_participants/registry.json

The confirmed watch is never populated from automatic discovery. Automatic discovery can add statistics to the registry, while user-confirmed identities remain a separate evidence/watch namespace.

## Frontend rule

Only one authoritative production renderer is loaded:
virtual-lab-app.js

Legacy renderer files are retained only as forensic history/compatibility artifacts and are not referenced by the production route.

The public standalone route is:
https://match-signal.pages.dev/virtual-lab/

Compatibility routes redirect to the standalone route:
- /research.html
- /virtual-lab.html

## Diagnostics

The production UI exposes:
- build identifier
- Git commit/build trace
- feed status
- raw/normalized/displayed counts
- history count
- participant count
- model evaluation status

A zero-fixture state must report the layer that produced zero data. The browser must not apply a second time-window cutoff to backend-authoritative events.

## Model discipline

O/U 1.5, 3.5 and 4.5 remain research lines with O/U 1.5 explicitly experimental until untouched evidence qualifies it.

User-reported ticket outcomes are external evidence only. They do not become automatic training labels.

No model result is promoted to a paper signal merely because of a short winning streak. Qualification requires the configured chronological, out-of-sample and replication gates.

## Recovery rule

When a production problem appears:
1. identify build and commit shown by the UI;
2. inspect feed artifact;
3. inspect normalization counts;
4. inspect participant identity linkage;
5. inspect pending/settlement state;
6. inspect model artifact;
7. compare the exact commit to the last verified deployment.

Never troubleshoot by blindly reverting the entire research history.
