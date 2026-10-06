# Pipeline format

The inputs to `gtmkit.pipeline`: a pipeline export with one row per open deal,
and a stage model whose every probability says where it came from.

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.pipeline pipeline.csv \
  --stages stages.json --target 1200000 --closed 95000 \
  --period-end 2026-12-31 --as-of 2026-10-06
```

A worked pair lives in `examples/pipeline/`: `pipeline.csv` (18 deals, which
also carries MEDDPICC levels for the scoring engine) and `stages.json`.

## Contents

- [Flags](#flags)
- [The pipeline file](#the-pipeline-file)
- [The stage model](#the-stage-model)
- [What comes back](#what-comes-back)
- [What the numbers assume](#what-the-numbers-assume)

## Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--stages` | placeholder model | Stage model JSON. Without it, every probability is a labelled placeholder and the output says the result is a scenario. |
| `--target` | none | Revenue target for the period. Without it there is no coverage or gap. |
| `--closed` | 0 | Revenue already closed-won in the period. |
| `--period-end` | none | Deals closing after it are left out of coverage and the forecast, and counted separately. |
| `--as-of` | today | The review date every past-due and staleness check is measured from. Always pass it for anything someone else will read, so the numbers reproduce. |
| `--stale-days` | model, else 30 | Days without logged activity before a deal is flagged stale. |
| `--top` | 3 | Deals in the concentration view. |
| `--name-field` | `opportunity` | Column holding the deal name. |
| `--currency` | model, else USD | Display currency. |
| `--format` | markdown | `json` returns every figure and every deal. |
| `--out` | stdout | Write to a file. |

## The pipeline file

CSV or JSON (an array of rows, or an object with a `records` array). Headers
are matched case-insensitively with spaces read as underscores, so a CRM
export's `Close Date` works.

| Column | Required | Rule |
|--------|----------|------|
| `amount` | yes | Positive. `$` and thousands separators are fine; `186k` is not. |
| `stage` | yes | A stage id from the model. `Closed Won` and friends are excluded with a pointer to `--closed`. |
| `close_date` | yes | `YYYY-MM-DD`. US-style dates are refused, not guessed — 03/04 is two different days. |
| `opportunity` | no | The deal's name (see `--name-field`). |
| `owner` | no | Shown in the hygiene table. |
| `forecast_category` | no | `commit`, `best_case` (also `best case`, `upside`), `pipeline`, or `omitted`. Blank takes the stage model's category. |
| `last_activity` | no | `YYYY-MM-DD`. Turns on the stale check. |
| `original_close_date` | no | `YYYY-MM-DD`. A later `close_date` is flagged as pushed. |
| `push_count` | no | Whole number. One or more is flagged. |
| `probability` | ignored | Read and deliberately not used; the output says so. |

A row missing a required value is **left out and listed** with its reason;
every total excludes it. A row with an unreadable optional value stays in the
totals and skips only that check, also listed — dropping a large deal over a
malformed activity date would move the forecast more than the date ever could.

Deals marked `omitted` are left out of the totals and counted.

### Why the probability column is ignored

Per-deal CRM probabilities are almost always the picklist default for the
stage, typed in once by an admin. Reading them would let an unsourced number
back in through the side door. A probability belongs in the stage model, where
it has to say where it came from.

## The stage model

```json
{
  "name": "Stage-to-close, FY2026 history",
  "currency": "USD",
  "stale_after_days": 30,
  "stages": [
    {
      "id": "discovery",
      "label": "Discovery",
      "category": "pipeline",
      "probability": {
        "value": 0.08,
        "confidence": "fact",
        "source": "Salesforce report 'Stage entry to close', FY2026: 31 of 388 opportunities that entered Discovery closed-won"
      }
    }
  ]
}
```

Stages are listed earliest first. Each `probability` is an entry in the
assumption ledger, validated by the same rules as a business-case input:

| Confidence | Means | Requires |
|------------|-------|----------|
| `fact` | A measured stage-to-close rate | A source naming the report and the counts |
| `inference` | Derived from facts by stated reasoning | The derivation |
| `assumption` | Chosen, not measured | A rationale **and** `low`/`high` |

Probabilities are decimals (0.35, not 35). Sources like `industry standard`
are rejected at the door. One rule is specific to pipelines: **a CRM's default
stage probability cannot be declared a fact.** A default is a setting someone
chose, not a rate anyone measured; enter it as an assumption with a range if
it is all you have.

**Measure the rate as stage entry to close.** Of the deals that *entered* this
stage in a past period, the share that closed-won. Rates computed from deals
currently sitting in a stage are biased by whatever is stuck there.

`category` (`commit`, `best_case`, `pipeline`) is used only for deals whose row
has no `forecast_category`. A probability lower than an earlier stage's is
allowed and noted, since it usually means an ordering mistake or a stage deals
stall in.

### The placeholder model

Without `--stages`, the engine uses six stages — `discovery`,
`qualification`, `solution`, `proposal`, `negotiation`, `closing`, the same
ids the qualification rubric uses — with probabilities from 10% to 90%, every
one an assumption with a wide range and a source that says it was measured
from nobody's pipeline. The evidence grade reads F and the first note says the
result is a scenario. Use it to show the shape of the math, never as the
forecast.

## What comes back

- **Headline.** Target and what is left; open pipeline in the period;
  coverage of what is left; the coverage these probabilities need (one over
  the blended expected close rate); the weighted forecast with its range from
  the probability bounds; the expected landing against target; the spread;
  and the share held by the largest deals.
- **Evidence grade** on the probabilities behind each forecast dollar, then
  every note about what is thin, missing, or left out — before the detail.
- **Forecast categories.** Commit, best case, and pipeline, each with amount,
  weighted amount, and closed-plus-cumulative against target. Commit deals
  carrying a hygiene flag are called out.
- **Needs a new date or a touch.** Past-due close dates, pushed dates, and
  stale deals, commit first, across every open deal including those after the
  period.
- **Concentration.** The largest deals, how many hold half the pipeline, and
  the forecast and coverage if the largest slips.
- **Stage model.** Each probability, its range, confidence, source, and the
  deals and dollars it carries.

## What the numbers assume

**Each deal is an independent draw at its stage probability.** The spread is
the standard deviation of that sum. Deals that share a cause — one budget
freeze, one economic shock, one competitor's price cut — move together, and
the real spread is then wider than reported, never narrower.

**The stage probability fits every deal in the stage.** It does not: a deal
with no economic-buyer access converts below its stage's rate. That is what
`gtmkit.qualify` is for. The pipeline engine says how much pipeline there is;
qualification says which of it is real.

**Ranges come only from the stated bounds.** A fact with no `low`/`high` is
treated as exact; a rate measured from 87 deals is not, and the output notes
which stages that applies to.

Two thresholds only decide when a sentence is printed: fewer than ten deals
in the period triggers the "single outcomes dominate" note, and one deal at a
quarter or more of the pipeline triggers the concentration note. The spread
and the shares are always printed, so neither threshold changes a number.
