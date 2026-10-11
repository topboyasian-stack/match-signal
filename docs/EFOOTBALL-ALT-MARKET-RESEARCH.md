# Isolated eFootball Winner / BTTS market research

**State: paper research only.** This lane is deliberately separate from Prediction Desk, Qualified Best, Selection Gate, model approvals and Odds Builder.

## Scope

- Only SportyBet eFootball GT and eFootball Adriatic fixtures are observed.
- Records the pre-match **Match Result / 1X2** market and **Both Teams to Score (BTTS / GG-NGG)** market, where both sides and usable decimal prices are present.
- Freezes one sample per exact event + product + market identifier/specifier when the scheduled start is within 15 minutes. Each sample retains participant identities, event/scope IDs, market/outcome IDs, all recognized outcomes, odds, no-vig market probabilities, capture time and provider's last-odds-change field.
- Totals/O-U are explicitly excluded from this research collector; the existing O/U pipeline is unchanged.
- A scoped SportyBet result lookup settles samples by exact provider event ID and score. Two-way winner markets that end in a draw are not scored as a win/loss; they are marked `UNSETTLED_DRAW_SCOPE` pending confirmation of the provider's void/push semantics.

## Interpretation and promotion

This is first a market-coverage and market-baseline study, **not** evidence that an independent winner or BTTS model has an edge. The reported favourite hit rate, flat-stake return, no-vig Brier and log loss are descriptive. They must not be used alone to claim a model advantage.

Do not promote a new market until each separate product/market lane has adequate settled observations (100 is only a preliminary review threshold; 200–300+ plus a chronological holdout is preferred), exact settlement integrity, calibrated probabilities, positive post-margin value and an independent walk-forward holdout. Promotion is never automatic. Every output marks production qualification and Odds Builder eligibility false.

## Operational design

The virtual feed exposes the additional market IDs and preserves tournament/category IDs so settlement can query only relevant result scopes. A separate five-minute GitHub Actions workflow captures/settles the research archive. It merges snapshots by deterministic sample ID after concurrent pushes, preserving the original frozen quote; a settled version supersedes a pending one. Its data artifact is kept outside the Pages asset deployment and cannot feed production qualification.
