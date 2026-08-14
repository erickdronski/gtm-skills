---
name: icp-scoring
description: Define an ideal customer profile and score accounts, leads, or opportunities against it with a weighted rubric that reports data coverage alongside fit. Use this whenever the user asks to build or refine an ICP, score or rank a list of accounts, prioritize a territory or target list, qualify leads, decide which prospects to work, build an account tiering model, or figure out which customers look like their best ones. Also use it when someone is about to prioritize a list by gut feel and a stated rubric would be better.
---

# ICP scoring

An ideal customer profile is a falsifiable claim: *these attributes predict that
a deal closes, expands, and renews.* Most ICPs are not that. They are a
description of the customers a company already has, written after the fact, and
they cannot be wrong because they never predicted anything.

This skill builds the falsifiable kind, then scores against it with an engine
that separates two things everyone else conflates: **how well an account fits**
and **how much you actually know about it**.

## Why coverage is the whole point

Every scoring model quietly treats missing data as bad data. An account with no
headcount on file scores like an account known to be tiny. That one behavior has
misdirected more territory plans than any modeling error, because it
systematically buries the accounts nobody has researched yet — which are, by
definition, the ones with the most upside left in them.

So the scorer reports two numbers per record. An account at 82% fit on 40%
coverage is not a good account; it is an unresearched one, and it is held out of
the ranking entirely rather than placed above a fully-diligenced peer.

When you present results, never show fit without coverage next to it.

## Building the rubric

### 1. Start from outcomes, not attributes

Do not begin by listing what your good customers look like. Begin by asking
which accounts actually produced good outcomes, then work backwards to what
distinguished them.

Ask the user for whichever of these they can get:
- Closed-won and closed-lost from the last 12–18 months, with deal size
- Renewal and churn outcomes, with reasons
- Expansion history
- Time-to-close by segment

If they have none of it, the rubric you build together is a hypothesis, and you
should label it that way in the output. A hypothesis is fine. A hypothesis
presented as a finding is not.

### 2. Pick criteria that could be wrong

A good criterion divides the population and predicts something. Test each
candidate against two questions:

*Does it discriminate?* If 95% of the market has it, it is table stakes, not a
criterion. It will add weight without adding signal.

*Is it observable before the deal?* "Has an engaged executive sponsor" predicts
outcomes beautifully and is useless for prospecting, because you learn it after
you are already in the deal. Separate **prospecting criteria** (observable from
outside) from **qualification criteria** (learned in the process). Build two
rubrics rather than one muddled one.

Criteria generally worth testing:

| Type | Examples | Notes |
|------|----------|-------|
| Firmographic | Headcount, revenue, geography, industry | Easy to source, weak on their own |
| Operational | Volume of the thing your product acts on | Usually the strongest predictor — it drives the value case |
| Technographic | Systems you integrate with | Strong when integration is a real barrier |
| Behavioral | Hiring for the role, published commitments | Best timing signal, worst durability |
| Structural | Whether the buying center exists at all | Often the real disqualifier |

The operational row deserves the most weight in most B2B models. It is the same
number that drives the value case, which is not a coincidence: accounts where
the math works are accounts that buy.

### 3. Write disqualifiers separately from scores

A disqualifier is not a low score. It is a reason the account cannot be sold to
at all — no data residency, below the volume where the ROI clears, a competitor
you have never displaced. Modeling these as low scores lets a strong-elsewhere
account float into your top tier on the strength of criteria that no longer
matter.

Every disqualifier requires a stated reason. A record removed without one looks
like a bug to whoever reviews the list, and they will override it.

### 4. Weight by predictive strength, not by importance

Weights are commonly assigned by how important something *feels*. Assign them by
how much the criterion moved the outcome in the data you have. When you have no
data, distribute weight evenly across a small number of criteria and say so —
false precision in weights is worse than admitted ignorance.

## Running it

Rubric format is documented in `references/rubric-format.md`. Records can be CSV
or JSON.

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.scoring \
  --rubric rubric.json --records accounts.csv --name-field name

# Machine-readable, for feeding a CRM update or a further pass:
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.scoring \
  --rubric rubric.json --records accounts.csv --format json
```

The engine handles three criterion types — `numeric` with bands, `boolean`, and
`categorical` with a map — and treats blanks, `unknown`, `n/a`, and `-` as
missing rather than as zero.

## Reading the output

**The UNKNOWN tier is a work queue, not a failure.** Records below the coverage
threshold are listed separately with exactly which fields are missing. That list
is the highest-leverage research task available to the team, and it is usually
shorter than people expect.

**Tier boundaries are decisions, not discoveries.** The default A/B/C/D cuts are
arbitrary. Set them where the user's actual capacity falls: if the team can work
40 accounts this quarter, the A tier should hold roughly 40 accounts. A tiering
model that produces 300 A-accounts has not prioritized anything.

**Check what the rubric does to your existing best customers.** Score the
current top ten. If the model ranks them poorly, the model is wrong — this is
the single most useful validation available and it takes five minutes.

## Common failures

**Scoring the market you wish you had.** If the rubric's A tier contains almost
nobody, it is describing an aspiration. Either the product is not ready for that
segment or the criteria are too strict.

**Confusing fit with intent.** ICP fit says an account *should* buy. It says
nothing about whether they will buy *now*. Timing signals belong in a separate
score; blending them produces a number that means neither thing.

**Letting the rubric ossify.** Re-score against closed-won and closed-lost
quarterly. A rubric that has never been revised has never been tested.

**Presenting rank without coverage.** Covered above, and worth repeating,
because it is the thing most likely to be dropped when the output gets pasted
into a deck.

## Reference material

- `references/rubric-format.md` — the full rubric schema with every field.
- `references/criteria-library.md` — candidate criteria by business model
  (PLG, enterprise sales, marketplace), with notes on what each actually
  predicts and where each tends to mislead.

A worked rubric and account list live in `examples/icp/`.
