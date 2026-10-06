# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-10-06

Deal qualification and pipeline math move from the model into the engine.

### Engine

- `gtmkit.qualify` — MEDDPICC for one deal, with each element's provenance
  (confirmed, stated, assumed, unknown) kept apart from its score: believed
  tier beside a floor case, evidence mix by weight, stage-aware failure
  patterns, and the next element to confirm
- `gtmkit.pipeline` — coverage against target next to the coverage the stage
  probabilities require, weighted forecast with range and standard deviation,
  commit / best case / pipeline view, past-due, pushed, and stale flags, and
  concentration; every stage probability goes through the assumption ledger
- `gtmkit.evidence.MIN_SOURCE_CHARS` is public, so the deal ledger holds a
  confirmed source to the same floor

### Skills

- `deal-qualification` — scores deals on `gtmkit.qualify` and reviews
  pipelines on `gtmkit.pipeline`; new `references/deal-spec.md` and
  `references/pipeline-format.md`
- `exec-comms` — pipeline and forecast slides computed by the engine
- `campaign-plan` — subtracts what open pipeline is expected to close before
  working the funnel backwards
- The MEDDPICC rubric gains stages, a `confirm_by` stage and an `action` per
  element, and `paper_lead_days`; `gtmkit.scoring` ignores them

### Examples

- `examples/deal/kestrel-expansion.json` — one deal with its evidence recorded
- `examples/pipeline/pipeline.csv` is now a full 18-deal export that still
  carries MEDDPICC levels, with a sourced `examples/pipeline/stages.json`

### Tooling

- The skill linter checks every flag on every `python3 -m gtmkit.<module>`
  command in SKILL.md and references/, not only that the module exists
- 326 tests, up from 205; CI runs both new examples

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
