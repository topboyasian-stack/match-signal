# Precision Sports Upgrade — Darts-X + Table Tennis-X

## Boundary
Darts-X and Table Tennis-X are standalone pre-match research engines. They do not read, write, retrain, calibrate, settle, or promote any Football, Tennis, Basketball, NBA, eFootball/Virtual Lab, Odds Builder, Telegram, or shared prediction-feed artifact.

Each sport has its own:
- SportyBet provider boundary.
- historical-result archive.
- upcoming feed.
- walk-forward model artifact.
- precision gate.
- candidate artifact.
- status artifact.
- page, CSS, browser renderer, workflow.

The only shared system-level touchpoints are navigation links, production deployment verification, and the read-only Reports presentation.

## Data contract
Current SportyBet prices are the bookmaker input. Public historical event results are the outcome input. The model never attempts to influence results, RNGs, bookmaker prices, accounts, or event generation.

Historical results are collected from TheSportsDB's public API. TheSportsDB documents a free JSON API and rate limits; the collectors stay below the published free-tier request rate by using a 21-day rolling daily schedule with deliberate pacing.

## Model
Both engines start with a participant Elo walk-forward model and compare isolated variants:
- Elo only.
- Elo + recent form.
- Elo + recent form + exact H2H.
- Darts: Elo + recent form + recent score-margin signal.
- Table Tennis: same research scaffold, with score-margin behavior retained for evaluation.

The final variant is chosen only from chronological historical evaluation. No future result is visible when the event probability is calculated.

## Promotion benchmark
Frozen benchmark: Virtual Football holdout hit rate 0.80325064 (80.33%) from the Match Signal Virtual Lab artifact available when this upgrade was scoped.

A Darts-X or Table Tennis-X regime may enter the qualified candidate desk only when:
- holdout sample >= 30 high-confidence observations;
- high-confidence holdout accuracy > 80.325064%;
- Wilson lower 90% confidence bound >= 75%;
- current SportyBet price has sufficient positive model edge;
- the event/player names are not placeholders;
- the source data are fresh.

Until all conditions pass, the sport remains PAPER_ONLY / RESEARCH ONLY.

## Instant virtuals and manipulation
No instant-virtual, RNG, feed, price, account, or bookmaker manipulation is part of this upgrade. The only permitted advantage is improved statistical selection from legitimately observed data.

## Future extension
If either engine fails the benchmark, it continues collecting and testing. It is not weakened by lowering the benchmark, changing the holdout, importing another sport's history, or promoting a convenient small sample.

The next upgrade can add richer sport-specific features only as isolated experiments after enough chronological data exist.
