# Qualification diagnosis and sport-expansion research
Research date: 10 October 2026. Status: research and paper-only; no new sport is promoted by this document.

## Decision
1. Do not remove or lower the Odds Builder's probability, current-price, data-quality, ROI, correlation, or settled-ticket construction gates just to make a non-zero qualified count.
2. Display current near-misses and exact reasons in a Qualification Monitor when there are no qualified batches. Near-misses stay unqualified, cannot generate booking codes, and are not betting recommendations.
3. Finish the existing Tennis Total Games “tempo” challenger market holdout before starting a new sport engine.
4. The best new sport to investigate is cricket, limited initially to recognized official T20 International and ODI competitions. This is a research hypothesis based on historical data availability, not a claim of profitability. First prove that SportyBet Nigeria quotes can be joined to official event IDs/results.
5. NBA, darts, and table tennis remain on hold based on current repository evidence.

## Why the current Desk shows nothing
The Builder runs every 15 minutes; Virtual Lab collection/sync runs every 5 minutes. There is no mandatory 24-hour wait. New settled observations only become available once events settle, but every builder refresh re-evaluates the current eligible pool.

Production artifact `data/odds_builder.json`, generated 2026-10-10 around 21:59 UTC:
- Final status `NO_BET`, 0 qualified legs, 0 batches.
- 10 tennis candidate rows; 115 virtual evidence/value rows.
- `virtual_gate_diagnostics.evidence_pass=0` is measured after Results-first construction qualification. It does **not** mean no settlement data exists: 115 exact-evidence/value candidates were retained, and 378 eFootball GT events were evaluated.
- Example near-miss: Racing Club (nicky) vs Boca Juniors (rostyk), Under 7.5. Builder-calibrated probability 71.62%; exact line/side history 51 wins from 70 (72.86%); SportyBet price 2.55. It passes candidate-level freshness and recent-line evidence checks but is below the active 80% per-leg floor, and the ticket-family gate does not prove a profitable construction shape.
- Current eFootball construction history is weak: the 4-leg family has 18 settled tickets, 3 won and 15 lost (empirical return estimate roughly -49.3%). The current 2-leg sample has only 2 losses and no wins. Removing this gate to force a batch would mask a poor observed record.
- The front end currently emphasizes batches/qualified legs and a generic empty state; it does not show the `best_available_legs` explanations, so active monitoring is invisible to the user.

Required action: retain the thresholds; show best informational candidates and blockers; never allow the monitor to mint a ticket or present a near-miss as qualified.

## Sport-by-sport decision

### 1. Tennis total-games tempo challenger — first to complete
Artifact `data/tennis_total_research.json` (2026-10-10):
- 350 research rows, 70-row chronological holdout.
- Incumbent holdout: accuracy 71.43%, Brier 0.2111, log loss 0.6198.
- Tempo challenger: accuracy 71.43%, Brier 0.2015, log loss 0.5925.
Proper scoring improved in this holdout, but it is still only 70 rows and has not yet demonstrated superiority over a frozen, same-event SportyBet market benchmark. The existing activation gate correctly remains HOLD. Collect prices at prediction time and evaluate on the next untouched block.

### 2. Cricket — new pilot candidate, not approved
Cricsheet provides ball-by-ball structured historical data for 23,080 matches. Reported competition coverage includes IPL 1,243/1,243, Big Bash 662/678, SA20 130/130 and The Hundred 389/389. SportyBet Nigeria lists Cricket. The ICC anti-corruption framework covers official international and domestic cricket.
This gives cricket good reproducible offline-data potential. It does **not** prove that SportyBet NG has enough exact, timestamped pre-match prices to support a calibrated value model; that coverage must be audited first.

Initial scope if the data audit passes: T20I and ODI winner markets; then specific recognized franchise competitions only when SportyBet quotes and result IDs join cleanly. Keep formats and competitions isolated until each has enough evidence. Potential features: team/player strength, shrinkage-adjusted recent form, venue, format, rest/travel, and lineup/availability only if that information existed at the stored prediction timestamp. Toss can only be a feature for markets captured after toss. No future/live match information may enter pre-match predictions.

### 3. NBA / basketball — hold
Artifact `data/nba_oos_value_test.json`, strict chronological holdout: 803 matched games, 161 holdout games. Model accuracy 59.01% vs market 63.98%; model Brier 0.2442 vs market 0.2116. The tested value set had ROI -17.08% (-8.54 units) and 36% accuracy. Status remains RESEARCH_ONLY.

### 4. Darts — hold
Artifact `data/darts_model.json`: 141 history events, 43-row holdout; selected variant holdout accuracy 58.14%, Brier 0.2380, log loss 0.6687. The selected 75% precision band has zero examples; current candidate count is zero. Remain TESTING.

### 5. Table tennis — collection repair first
Artifact `data/table_tennis_status.json`: zero settled history events, 100 upcoming, 29 source errors and zero candidates. The current model has no variants; its data cannot support a meaningful performance comparison yet.

### 6. Current eFootball / real football — no shortcut
Pooled Virtual Lab results mix products and should not be treated as eFootball-only forecast evidence. Product-specific eFootball performance is materially weaker than the mixed VFootball-heavy pooled metrics. Keep separate sport/product histories, preserve the existing architecture, and let losses influence eligibility.

| Candidate | Evidence now | Decision |
|---|---|---|
| Tennis total-games tempo | Promising proper-score movement; only 70 holdout rows; no confirmed market advantage | Finish frozen market evaluation |
| Recognized cricket | 23,080 public structured matches; exact SportyBet mapping unverified | Data-coverage audit, then isolated paper pilot |
| NBA | OOS value ROI -17.08%; worse Brier than market | Hold |
| Darts | Small holdout and no candidates passing 75% precision band | Hold |
| Table tennis | No settled history and 29 source errors | Repair collection |
| eFootball active ticket lane | Current best candidate 71.62%; poor settled 4-leg family record | Keep all gates; expose blockers |

## Integrity is a protection criterion
Do not choose events because they might be manipulated or fixed. “Manipulatable” is a risk to screen out, not a source of edge. Limit pilots to recognized official competitions with independently verifiable event/result IDs; suspend a market on credible integrity concerns or anomalous price movement. Exclude opaque, unofficial, or unverified events and preserve any alert for audit. IBIA's 2025 report recorded 300 suspicious betting alerts across 16 sports; member intelligence contributed to 54 matches being proven corrupted. These are monitored alerts and investigations, not estimates that any particular sport or match is fixed.

## Promotion protocol
1. **Integrity/identity:** official competition and results, stable provider event ID, explicit format mapping; suspicious or unverifiable events are blocked.
2. **Odds coverage:** record pre-match SportyBet prices, timestamp, market and outcome. Audit raw/matched/unmatched counts and require at least 90% joins on the eligible evaluation set.
3. **Chronological evaluation:** lock train/holdout periods before model selection; only use information available at the saved quote time. Compare a calibrated sport-appropriate model with a naive/rating baseline and de-vig SportyBet probability.
4. **Data sufficiency:** target 500 clean historical matches for development and 100 untouched out-of-time events. If unavailable, remain COLLECTING rather than lowering thresholds.
5. **Value test:** freeze selection rule and odds snapshot policy; publish Brier, log loss, calibration, ROI in flat units, drawdown, and uncertainty intervals. A minimum 100 selected out-of-sample wagers is a research floor, not proof by itself.
6. **Prospective paper test:** then collect 300 new independently settled predictions under the same locked rule, including no-bets, and require positive out-of-sample performance with stable calibration before considering promotion.
7. **Isolation:** separate model, data artifacts, tests and thresholds per sport and competition. Never reuse another sport's hit rate or priors.

## Sources
- Cricsheet match data and competition coverage: https://cricsheet.org/matches/ and https://cricsheet.org/coverage/
- SportyBet Nigeria categories (includes cricket): https://shop.sportybet.com/ng/
- ICC Anti-Corruption Code for Participants: https://www.icc-cricket.com/about/integrity/anti-corruption/the-code-pmoa
- IBIA, 2025 Sports Betting Integrity Report announcement, 3 February 2026: https://ibia.bet/news-details/46
- Angelini & De Angelis (2019), “Efficiency of online football betting markets”, https://doi.org/10.1016/j.ijforecast.2018.07.008
- Bridwell & Ryan (2025), MLB moneyline market efficiency, https://doi.org/10.1080/00036846.2024.2364115
