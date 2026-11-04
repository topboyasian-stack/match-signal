# QA & Product Quality Portfolio

**David Egwu** — Lagos, Nigeria  
**Focus:** Software QA · Product Validation · Data Quality · AI Evaluation · Release Readiness

This portfolio presents two substantial software products as practical QA case studies. The emphasis is on requirements-led testing, data integrity, workflow validation, regression controls and honest release decisions.

## 1. Match Signal — Multi-Sport Analytics & Research Platform

**Live product:** https://match-signal.pages.dev  
**Public source repository:** https://github.com/topboyasian-stack/match-signal

Match Signal is a multi-sport analytics product with automated data ingestion, event and market matching, prediction workflows, settlement, reporting and a production web interface.

### QA and engineering quality work

- **Data integrity:** validate incoming fixtures, team/event identities, market identifiers, prices, timestamps and normalized records.
- **Freshness controls:** enforce quote-age and event-state rules so missing, stale or mismatched data is not presented as current.
- **Model and market separation:** keep model projections distinct from bookmaker prices and guard against invalid evaluation joins or information leakage.
- **Evaluation discipline:** use chronological / walk-forward evaluation structures and retain explicit release gates where evidence is insufficient.
- **Settlement and reporting:** validate result mapping, settlement behavior, historical tracking and publication contracts.
- **Workflow regression:** maintain focused automated checks and GitHub Actions workflows for key data, model, ticket-builder and publication contracts.

### Inspectable examples in the public repository

- [NBA totals walk-forward tests](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_nba_totals_walk_forward.py)
- [NBA ticket guard tests](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_nba_ticket_guard.mjs)
- [UCL history coverage tests](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_ucl_history_coverage.py)
- [eFootball market research tests](https://github.com/topboyasian-stack/match-signal/blob/main/scripts/test_efootball_market_research.py)
- [GitHub Actions validation workflows](https://github.com/topboyasian-stack/match-signal/tree/main/.github/workflows)
- [Evidence bar and evaluation rules](https://github.com/topboyasian-stack/match-signal/blob/main/docs/EVIDENCE_BAR.md)

**Scope note:** Match Signal is a research / paper-analysis product. Its ticket and prediction features are not automatic betting execution. Test files and workflows demonstrate implemented quality controls; their presence alone is not a claim that every current production release gate has passed.

## 2. Hustle Academy — Learning Management Platform

**Preview:** https://hustle-academy-preview.pages.dev  
**Platform:** Cloudflare Pages, Pages Functions and D1-backed application data

Hustle Academy is a mobile-first digital learning platform with a course catalogue, student journeys, lesson delivery and progress, assessments, and administrative workflows.

### QA and release-validation work

- **Curriculum integrity:** review course, module, lesson and assessment relationships; check question structure, answer-key consistency, explanations and scoring data.
- **Application workflows:** assess course discovery, student access, lesson navigation, saved progress, assessment attempts and administrative release controls.
- **API and database checks:** validate Pages Functions, API health and D1 schema / seed relationships.
- **Content quality:** check lesson completeness, instructional flow, practical activities and assessment alignment.
- **Release decisions:** document what has been verified and what remains gated; distinguish source-data checks and preview health from unverified end-to-end learner, email or payment flows.

A dated release-QA review recorded curriculum-source checks and preview health / database connectivity, while explicitly retaining further learner-flow and production-payment checks as release controls.

**Access note:** the source repository is private. The public preview is provided for product review; implementation details can be discussed or shared where access is appropriate.

## QA approach

1. Translate requirements into observable acceptance criteria.
2. Identify risk, positive paths, negative paths, boundary conditions and data dependencies.
3. Design traceable test cases with clear expected results.
4. Execute in an authorised environment and preserve reproducible evidence.
5. Report defects with steps, expected / actual behavior, impact and supporting evidence.
6. Retest fixes, run focused regression and record release limitations.

## Tools and working areas

GitHub · GitHub Actions · Python · JavaScript · HTML / CSS · browser-based testing · API and workflow validation · SQLite / Cloudflare D1 · data-quality review · AI output evaluation exposure · technical documentation

## Evidence and accuracy

I distinguish implemented controls, designed test cases, executed tests and verified release outcomes. I do not present unrun test designs as completed test execution, illustrative defects as observed defects, or a partially verified preview as a fully released production system.

**Contact:** davidegwu5@gmail.com · +234 815 619 6053  
**GitHub profile:** https://github.com/topboyasian-stack  
**LinkedIn:** https://www.linkedin.com/in/david-egwu
