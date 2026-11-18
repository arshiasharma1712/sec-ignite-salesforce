# Agent instructions

Read README.md and your assigned GitHub issue before editing. Work on one issue per feature branch in your own clone or worktree. Open a pull request with a summary and test results. Coordinate shared interface changes in the issue before implementing them.

## Ownership

- Data agent owns CSV ingestion, normalization, validation, and data-quality tests.
- Engine agent owns scoring, routing, capacity accounting, and engine tests.
- Dashboard agent owns UI, filters, run/reset controls, and capacity displays.
- Integration agent owns shared data definitions, pipeline integration, end-to-end tests, benchmarks, and setup instructions.

Agree on language, framework, function signatures, and normalized record fields before parallel implementation. The team has not selected a technology stack yet.

## Required behavior

- Normalize region, language, industry, seniority, booleans, and numeric values explicitly.
- Preserve every input lead with a traceable outcome. Record reasons for Manager Review.
- VIP referrals receive score 100 and Critical priority.
- Baseline tiers are Critical >=85, High 60–84, Medium 40–59, Low 0–39.
- Route Critical leads first. Match region, language, and industry strictly.
- Critical leads go to eligible Seniors with capacity, then eligible Managers. Never assign Critical leads to Juniors.
- Respect maximum capacity and fairly distribute leads among eligible representatives.
- Keep processing in memory. Support sample and scale runs, and resetting outputs and capacity to baseline.
- Test missing and invalid values, alias normalization, scoring boundaries, seniority, ties, overflow, and reset behavior.
- Measure the 50,000-lead/1,600-representative dataset. Report actual measurements and environment.

## Proposed fallback decisions

These are starting recommendations for team review, not additional challenge requirements. Send ambiguous or unresolved routing fields to Manager Review. Exclude representatives with invalid capacities from assignment and display the reason. Parse explicit numeric abbreviations such as 5k. Preserve unknown VIP status as a data-quality flag and document handling.

## Handoffs

In each PR list changed files, public interfaces, tests run, assumptions, and remaining work. Do not claim unrun tests passed. Keep original challenge data unchanged. Do not commit credentials or local environment files.
