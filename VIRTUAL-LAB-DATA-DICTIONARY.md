# Virtual Lab v1 Data Dictionary

The durable research record is an observed, settled market row. Product boundaries are enforced before rows enter the registry/model pipeline.

| Field | Required | Meaning |
|---|---|---|
| product | yes | efootball_gt, efootball_adriatic, vfootball, zoom, or other explicitly supported research product |
| provider | yes | Source/provider label |
| event_id | yes | Stable source event identifier |
| timestamp | yes | Event start/observation time |
| competition | recommended | League/competition label |
| participant_1 | recommended | First participant as observed |
| participant_2 | recommended | Second participant as observed |
| participant_1_key | derived | Product-scoped stable participant identity |
| participant_2_key | derived | Product-scoped stable participant identity |
| market | yes | winner, ou, btts, handicap, other |
| market_id | recommended | Source market identifier |
| specifier | optional | Source market specifier |
| line | optional | Numeric O/U line |
| selection | yes | Normalized tested selection |
| odds | recommended | Observed bookmaker price |
| result | yes | Normalized settled result |
| win | derived | Whether selection matched the settled result |
| score | recommended | Final observed score |
| model_prob | optional | Probability produced before settlement |
| captured_at | yes | Time the price/event was captured |
| settled_at | recommended | Time official settlement was recorded |
| settlement_source | yes | Authoritative result source |
| record_id | yes | Deterministic row identity |
| trace_id | yes | Trace identifier linking the row through the pipeline |
| schema_version | yes | Data schema version |
| pipeline_version | yes | Collector/model pipeline version |

## Identity rules

For eFootball, the stable participant is the explicit participant identifier observed inside the event metadata or historically observed parenthetical identity. The real-world club/team label is contextual and may rotate.

For Virtual Football and Zoom, the source participant field is product-scoped; it is never compared across products.

A missing or truncated identity is unresolved rather than guessed.

## Preservation rules

Raw observed evidence is never replaced with model fair odds.

User-reported ticket outcomes are retained as external evidence only and never injected into automatic training labels.

Settled evidence is appended to the daily archive and reflected into the cumulative history/registry.

## Model rules

Use chronological training/validation/test splits.

Do not allow post-event information into a pre-event feature.

O/U 1.5 is experimental until its own untouched evidence meets the same research discipline as the other lines.
