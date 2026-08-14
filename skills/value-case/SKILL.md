---
name: value-case
description: Build a defensible business case, ROI model, or value justification for a purchase, project, or initiative — with an assumption ledger, sensitivity analysis, and an evidence grade. Use this whenever the user asks for a business case, ROI analysis, cost-benefit analysis, value justification, TCO comparison, payback period, "what's the ROI on X", a CFO-ready or procurement-ready justification, or help defending a number an executive pushed back on. Also use it when the user is about to state a financial benefit in a deck, proposal, or email and that number needs to survive scrutiny.
---

# Value case

A business case is not a persuasion document. It is a falsifiable claim about
money, and its job is to survive contact with someone whose actual job is
finding the hole in it.

Most business cases fail the same way: internally coherent, beautifully
formatted, quietly built on numbers nobody measured. The reader finds one
unsupported figure, and the entire document — including the true parts — loses
credibility. So the goal here is not the biggest number you can defend. It is
the number you can defend, stated alongside what would have to be true for it
to be wrong.

## The workflow

### 1. Find the money before you model it

Before touching a spreadsheet or a spec file, establish three things. If you
cannot get them, say so rather than modeling around the gap.

**What is the customer's own metric?** Not your product's feature — the number
on someone's performance review. "Reduce cost per ticket" is a metric. "Improve
efficiency" is not. If the buyer cannot name a metric that moves, there is no
business case to build, and the honest output of this skill is telling them
that.

**What is the baseline, and who owns it?** A benefit is a delta from something.
If nobody can produce the current number, every benefit downstream is
unfalsifiable. Ask for the export, the dashboard, the report. Name the person
who owns it — that name goes in the ledger.

**Where does the money actually go?** This is where most cases quietly break.
Time saved is not money saved unless it aggregates into something the business
can spend differently: avoided hires, absorbed growth, reduced overtime,
redeployed headcount. If the answer is "people will have more time," the
realization factor should be brutal (0.3–0.5), and you should say why.

Ask these directly. A user who cannot answer them has a discovery problem, not
a modeling problem, and building them a polished model would paper over it.

### 2. Classify every number before you use it

Every input is one of three things, and the distinction is the backbone of the
whole document:

| Kind | Means | Requires |
|------|-------|----------|
| `fact` | Measured, from a named artifact a reader could open | A specific source — system, export, date, person |
| `inference` | Derived from facts by stated reasoning | The derivation itself, not just a citation |
| `assumption` | Chosen, not measured | A rationale **and** a low/high range |

Assumptions require ranges because an unbounded assumption cannot be
stress-tested, and a business case whose assumptions cannot be stress-tested is
a brochure. If you cannot bound a number, you do not understand it well enough
to put it in the model.

Sources like "industry standard", "research shows", "internal data", or a bare
analyst-firm name are rejected by the tooling, on purpose. They are the exact
phrases that get a case dismissed in review. Replace them with the specific
artifact, or downgrade the number to an assumption with a range and an honest
rationale.

### 3. Write the spec

Build the model as a JSON spec rather than prose arithmetic, so every figure
traces to a named input:

```bash
# From the repo root:
python3 -m gtmkit.valuecase case.json

# From anywhere, when installed as a plugin:
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.valuecase case.json

# Validate the spec without producing output — do this first, every time:
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.valuecase case.json --check

# Full model as JSON, for building your own view on top:
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.valuecase case.json --format json
```

Run `--check` before generating output. The validator's error messages are
written to tell you exactly what to fix, and fixing a spec is much cheaper than
regenerating a document built on a bad one.

The spec format is documented in `references/spec-format.md`. Read it before
writing your first spec — the validator is strict, and the rules it enforces
are the ones that matter.

Two modeling choices deserve deliberate thought rather than defaults:

**Ramp** is *when* value arrives — the adoption curve. A platform that needs
content built before it deflects anything might ramp `[0.4, 0.9, 1.0]`.

**Realization** is the haircut between value you can model and value the
business actually captures. These are different things, and conflating them
hides which one you are arguing about. A realization of 1.0 claims you capture
every modeled dollar; be prepared to defend that. Most soft-benefit drivers
belong somewhere between 0.5 and 0.8.

Include the customer's own internal effort as a cost line. Omitting it is the
fastest way to lose a case in procurement review, and including it buys
credibility that costs you far less than the number itself.

### 4. Read what the model tells you

The output leads with headline metrics, then does something unusual: it grades
its own evidence before showing the drivers. That order is deliberate. Naming
the weakness before the reader finds it is what earns the benefit of the doubt
on everything else.

Pay attention to four things:

**The evidence grade.** What share of modeled value traces to measurement
versus to assumption. A grade of C is not a failure — it is a normal early-stage
case, and saying so out loud is far stronger than pretending otherwise.

**The largest assumption.** The tool names the single input whose range moves
the answer most. If any number deserves a week of measurement before the
decision, it is that one. Recommending that measurement is often more valuable
to the customer than the model itself.

**Whether any input flips the decision.** An input that turns NPV negative at
its low bound is the real subject of the meeting. Lead with it.

**The floor case.** Every ranged input at its unfavorable bound simultaneously.
If the case still clears zero at the floor, that is the strongest sentence
available to you and it should be in the first paragraph. If it does not, say
so and name what has to hold.

### 5. Write the narrative around the model

The generated markdown is the appendix, not the pitch. Lead with:

1. The decision being asked for, and by when.
2. The headline number, with its payback period.
3. The margin of safety — how far benefits can slip and still break even.
4. The largest assumption and what you propose doing about it.
5. What you are *not* claiming.

That fifth point is the one people skip and the one that works. A case that
volunteers its own limits reads as authored by someone who has done this
before.

## Things that will get the case dismissed

**Stacking soft benefits.** Three drivers each worth "20% productivity" sum to a
number nobody believes. Pick the one you can measure and make it carry the case.

**Modeling headcount reduction nobody will make.** If the organization has
committed to absorbing growth rather than cutting, model absorbed growth. Claiming
FTE savings the buyer will never realize destroys trust permanently.

**Discount rates borrowed from nowhere.** Ask what the company uses. If you
cannot get it, use something defensible (10–15% for most software decisions),
say where it came from, and show that the conclusion holds across the range.

**Precision as theater.** `$1,247,318.44` signals you have not decided what
matters. Round to the precision your weakest input supports.

**A five-year horizon to make it work.** If the case only clears on year-five
benefits, it does not clear. Most software decisions are made on 3 years or
less; the tooling rejects horizons past 10 for this reason.

## When there is no case

Sometimes the honest output is that the numbers do not support the purchase at
the price being discussed. Say that. The alternatives are: change the scope,
change the price, change the timeline, or find a different value driver. A
seller who says "this does not pay back at this scope, here is what would" is
dramatically more credible than one who stretches assumptions until the model
agrees.

## Reference material

- `references/spec-format.md` — full spec schema, field by field, with the
  validation rules and why each exists.
- `references/value-drivers.md` — a catalog of driver patterns by category
  (cost avoidance, revenue, risk, working capital), with the formula shape and
  the realization factor each typically deserves.
- `references/objections.md` — the standard CFO and procurement objections, and
  what a defensible answer to each looks like.

## Worked example

`examples/value-case/northwind-support-deflection.json` in this repo is a
complete, internally consistent case: three drivers of varying strength, a
deliberately weak third driver bounded at zero, real cost lines including
customer-side effort, and a top assumption that flips the decision at its low
bound. Run it to see the full output shape before writing your own.
