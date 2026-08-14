# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-08-13

Initial release.

### Skills

- `value-case` — business cases with sensitivity, floor case, and evidence grade
- `icp-scoring` — ICP definition and account scoring with coverage reporting
- `campaign-plan` — inverse funnel math from target to required spend
- `market-sizing` — TAM/SAM/SOM with bottom-up and top-down reconciliation
- `pricing-strategy` — value metric, packaging, Van Westendorp analysis
- `positioning` — positioning and messaging hierarchy
- `competitive-brief` — battlecards with honest weaknesses and trap questions
- `deal-qualification` — MEDDPICC scoring separating confirmed from assumed
- `exec-comms` — board updates, QBRs, escalations, decision memos

### Engine

- `gtmkit.finance` — NPV, IRR, payback, break-even, summary metrics
- `gtmkit.evidence` — the assumption ledger and evidence grading
- `gtmkit.expr` — whitelist-based safe formula evaluation
- `gtmkit.valuecase` — business case model with proportional-sensitivity attribution
- `gtmkit.funnel` — inverse funnel planning with audience ceiling checks
- `gtmkit.sizing` — bottom-up and top-down sizing with reconciliation
- `gtmkit.pricing` — Van Westendorp with per-respondent monotonicity validation
- `gtmkit.scoring` — weighted rubric scoring with coverage gating
- `gtmkit.fmt` — executive-readable number and table formatting

### Tooling

- 188 tests, standard library only
- `tools/validate_skills.py` — frontmatter, trigger quality, dead links, budgets
- CI across Python 3.9–3.13, plus a job that runs every shipped example
