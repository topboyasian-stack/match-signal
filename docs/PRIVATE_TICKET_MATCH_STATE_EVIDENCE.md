# Private ticket match-state evidence

The private user-ticket review ledger may store an optional `match_observations` array on each leg. This is a chronological research timeline, separate from the final settlement record.

Each observation contains:
- `observed_at`: ISO-8601 timestamp for when the score was observed (not the match kickoff or time the receipt was pasted).
- `phase`: `PRE_MATCH`, `IN_PLAY`, `HALF_TIME`, `PERIOD_BREAK`, `SET`, or `FINAL`.
- `home` and `away`: non-negative score values at that observation.
- `source`: `user_reported` or `provider_feed`.
- Optional `source_event_id`: provider event identity when available.

Rules:
1. At most 40 observations per leg; timestamps must be strictly increasing.
2. A live, half-time, set, or period-break score is never a final score and never settles a leg.
3. The final result remains in `final_score` / `leg_outcome`, with its own settlement timestamp and provenance.
4. A receipt parser may extract an observation only when both score and observation time/phase are explicit. It must not infer a timeline from a single score.
5. User-reported observations are useful review context, not independent provider verification. Do not promote them to model-training labels.
6. Preserve the actual ticket selection, original desk snapshot, qualification state, market quote and model probability as separate facts. A ticket-selected leg remains a selection-biased cohort.
7. Never retroactively change a prediction's qualification state because the selected leg won or lost.

This schema addition is backward-compatible: existing records without `match_observations` remain valid. All records remain private and paper/research-only.
