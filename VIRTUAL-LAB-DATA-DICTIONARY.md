# Virtual Lab Data Dictionary

One row represents one settled market observation.

| Field | Required | Meaning |
|---|---|---|
| product | yes | efootball_gt, efootball_adriatic, srl, vfootball, zoom, other |
| provider | yes | Simulation/provider label when known |
| event_id | yes | Stable event identifier |
| timestamp | yes | Event or observation timestamp |
| competition | recommended | Competition/league |
| participant_1 | recommended | First displayed participant |
| participant_2 | recommended | Second displayed participant |
| market | yes | 1x2, winner, ou, btts, handicap, other |
| selection | yes | The tested selection |
| odds | recommended | Decimal market price at observation |
| result | yes | Settled outcome normalized to same label vocabulary as selection |
| win | derived | selection == result when both are known |
| score | recommended | Final simulated score |
| model_prob | optional | Probability emitted by a research model |
| bookmaker | optional | Operator/source of the observed market |
| observed_at | optional | Timestamp at which the price/result was captured |

## Data quality rules

- Never mix two providers without retaining the provider field.
- Never overwrite raw observed odds with model fair odds.
- Preserve bookmaker observation time separately from event time.
- Keep event IDs stable.
- Mark missing/ambiguous settlements instead of guessing.
- Do not infer real-world team form as though it were simulation state.
