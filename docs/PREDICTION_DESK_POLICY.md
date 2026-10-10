# Prediction Desk and Analyst Operating Policy

This policy is a safety and correctness contract for the public Prediction Desk, Odds Builder, and read-only AI Analyst. It is not a promise of predictive accuracy or profitability.

## 1. Keep the sources of truth separate

- The published model estimate, the market reference, the bookmaker quote, the qualification decision, and settled performance are separate fields.
- A confidence band such as `MODEL_90_PLUS` is a model-estimate label only. It must never overwrite or imply `qualification_status`.
- An event may remain visible as research when it has not qualified. Visibility does not authorize a bet or relax a gate.
- Private, user-reported slips are a selection-biased review cohort. Do not merge them silently into the public model history or claim they retrain model weights.

## 2. Qualified Best and per-fixture ranking

- The public Qualified Best shortlist contains future fixtures only and publishes at most one passing selection per fixture.
- Rank a selection that passes the complete current exact-price gate ahead of any higher model-probability row that is stale, mismatched, watch-only, or otherwise unqualified.
- An explicit watch/research/not-qualified status vetoes contradictory upstream qualification flags. A probability band or candidate-pool label is never a qualification decision.
- The empty state must show zero and the leading gate blockers; never weaken a gate to fill the shortlist.
- Hide started or settled fixtures from Qualified Best and Upcoming without deleting their archived evidence or settlement history.

## 2. SportyBet quote contract

A quote is matched only when the event identity, market, selected outcome, and (for totals) exact goal/game line match the prediction. The quote needs a timestamp within the configured 15-minute display window. A displayed model edge must be recalculated from the same fresh two-sided market quote, with the bookmaker margin removed. If the opposite side or timestamp is absent, the price or edge must be labelled unavailable/unverified rather than inferred from a neighbouring line.

A current price is reference data, not an independent model probability. Never show a quote for O/U 2.5 as though it prices O/U 3.5.

## 3. Upcoming lifecycle and archive preservation

- Sort valid future events chronologically.
- Hide past-kickoff rows unless a current live signal is still credible or a matched settlement is inside the two-hour result-display grace.
- Cap a stale `LIVE` status at four hours for football, eight hours for tennis, and two hours for Virtual/eFootball. These limits are operational cleanup bounds, not predictions about match duration.
- Count rows removed by freshness guards in the generated Prediction Desk health sidecar so the Analyst can distinguish a clean board from a board that filtered stale records.
- Hiding a row from Upcoming must never delete its history, settlement evidence, or archive record.

## 4. High VFootball Under lines

For VFootball Under 7.5 and higher, a high tail probability or a `MODEL_90_PLUS` band is not sufficient for betting qualification. Require at least 30 chronological out-of-sample records for the exact product, line, and side, with a hit rate of at least 65%, before this additional line-specific gate can pass. A missing or smaller sample remains research-only. The normal model, current market, edge, freshness, and Builder gates still apply after this gate passes.

Never infer evidence for Under 8.5 from Under 7.5 or another neighbouring line. Show the actual line/side sample next to the estimate where available.

## 5. Active Virtual product scope

- Active Virtual Prediction Desk candidates and new Odds Builder batches are restricted to **eFootball GT** and **eFootball Adriatic**.
- VFootball and Zoom are **research/monitor-only**. They must not enter the active Virtual candidate pool, Desk selection lane, or newly constructed Builder batches regardless of odds or model estimate.
- Keep their upstream feed collection, Virtual Lab observations, settlement processing, existing user-ticket records, append-only history and model-evaluation artifacts. This policy is not permission to delete, rewrite or relabel historical records.
- eFootball evidence thresholds remain in force, and every eFootball Builder leg must meet the active **80% minimum model-probability floor**. Prefer stronger evidence and probability; a high model estimate is not a guarantee.
- Do not manufacture a batch to meet an odds target. When no eFootball combination passes current price, exact-line evidence, freshness, value, correlation and ticket gates, publish no Virtual batch and report the blocking reasons.
- A separate **compact eFootball lane** may construct **4–5 legs at 2.00x+ combined odds** from already Builder-eligible eFootball GT/Adriatic exact-line/side evidence rows. It retains the 80% per-leg model floor, positive single-leg EV, current exact SportyBet quote and freshness gates, participant/event de-duplication, the 60-minute kickoff window, and at least +2% whole-ticket expected ROI. This is a research construction lane, not evidence that 4–5-leg tickets have proven results; its probability is an independence proxy until a suitable settled-ticket sample exists. It must not use VFootball/Zoom or fill missing slots with weaker legs.

## 6. Tennis discovery and publication

The tennis forward-window report is a distinct ingestion-health signal. A stale report cannot prove no tournament or fixture exists. Validate identity from either the nested athlete identifier or the competitor-level person identifier, together with two distinct real singles-player names. Reject placeholder names, duplicate names, doubles draw markers, and team-pair names. Do not infer a person from a team ID or invent a player.

If current tennis rows are absent, report the discovery artifact age, source error, fixture count, and rejection reason; do not quietly relabel an empty feed as healthy. Showing an unqualified research projection must not promote it to the Odds Builder.

## 7. Analyst diagnosis order

Every system-health answer should:

1. State the exact current critical/warning/info counts and name each warning/critical issue code and detail.
2. State artifact ages and their thresholds; distinguish stale data from a current failure.
3. Separate source errors, identity/fixture-ingestion failures, absent predictions, and zero qualified selections.
4. State the evidence/sample denominator behind each accuracy or coverage rate, and distinguish ticket accuracy, leg hit rate, calibration, and ROI.
5. Report the concrete finding and the next narrow diagnostic action. Do not stop at generic advice like “investigate the warning.”
6. Never claim that a fix, deployment, model update, or learning event happened without corresponding tests or source evidence.

## 8. Changes this policy does not authorize

This policy does not allow automatic wagers, weakened qualification thresholds, fabricated odds, background model-weight changes, deletion of historical evidence, or performance claims without an appropriate out-of-sample and settled sample.
