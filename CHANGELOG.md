# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-11-24

The engine installs with pip behind one `gtmkit` command, and a value case
renders as an HTML report to share.

### Install

- `pip install git+https://github.com/erickdronski/gtm-skills` installs the
  `gtmkit` package and command, with no dependencies. It is not published on
  PyPI. The skills stay in the repository: use the Claude Code plugin or a
  clone for them.
- `gtmkit` lists every analysis with an example, and `gtmkit <analysis>`
  passes its arguments unchanged to the module, so it takes exactly what
  `python3 -m gtmkit.<analysis>` takes. `python3 -m gtmkit` is the same front
  door without installing.
- `gtmkit init value-case|deal|sizing` prints a starter spec, or writes it with
  `--out` and will not overwrite an existing file without `--force`. Each
  starter is a byte-for-byte copy of the shipped example; a test fails if one
  drifts.
- The MEDDPICC rubric `gtmkit qualify` reads ships inside the package as well,
  so the command each starter names next runs after a pip install. A clone or
  the plugin still reads the skill's own copy; a test keeps the two identical.

### Engine

- `gtmkit valuecase --format html` writes one self-contained HTML file: the
  headline and margin of safety, the evidence grade, a tornado of every ranged
  input, the cash flow, value drivers, where the value comes from, the floor
  case, the full assumption ledger, the cost lines, and the spec's `meta`
  fields. No JavaScript and no external fonts, images or stylesheets; light and
  dark themes, a print stylesheet, and a phone layout down to 320px. Figures
  come from the same code as the markdown brief, every number a chart shows is
  also written out, every spec string is escaped, and identical input gives
  identical bytes.
- `--out` that cannot be written prints one line and exits 1 in every
  analysis, instead of a traceback.
- `gtmkit valuecase --check` builds the whole model, so a range bound that
  breaks a formula (a denominator whose low bound is 0) is a spec error before
  any output is written. An unreadable or non-UTF-8 spec file and a `meta` that
  is not an object are spec errors too.
- The markdown brief says how many attribution and sensitivity rows it leaves
  out after the first twelve.
- The markdown brief's footer no longer says that no number in it was written
  by hand: its ledger prints the spec's own inputs. It now makes the same
  claim as the HTML report's footer, that the computed figures come from the
  library and the inputs, sources and other text from the spec, with numbers
  rounded for display.
- The margin of safety never rounds up to 100%, which would say benefits
  could fall to nothing: a case that breaks even 99.5% below plan says 99.5%.
- A floor NPV of exactly zero is no longer called negative: the verdict now
  says the case does not clear zero at the floor. A case with no cost says it
  breaks even with no benefits at all, not that it clears zero.

### Skills

- `value-case` shows the `--format html` command, and the spec reference says
  where `meta` appears in the report.

### Tooling

- The skill linter checks `gtmkit <analysis>` commands as well as
  `python3 -m gtmkit.<module>` ones.
- The README's quoted brief is checked line by line against the example's
  output, and its report screenshot for size.
- 463 tests, up from 346. CI also builds the wheel, installs it, and runs the
  installed `gtmkit` command, every starter with the command it names, and the
  HTML report outside the repository.

## [0.3.0] — 2026-11-20

- Value cases support shared inputs with one evidence record and explicit
  references across drivers. Sensitivity ranges, scenario overrides, and the
  floor case move every reference together. Inline inputs retain their
  existing driver-local behavior.
- The Northwind example now uses one ticket-deflection assumption for both
  affected benefit streams. Its NPV swing is $311.6k across the 10–24% range.
  The base NPV remains $105.2k.
- Simple and discounted payback now measure the first recovery from a
  cumulative deficit even when the outlay occurs after kickoff. An investment
  that never recovers reports no payback within the modeled horizon.
- Includes earlier fixes on the default branch for sensitivity decision flips,
  finite financial inputs, and installation of the complete skill pack.

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
