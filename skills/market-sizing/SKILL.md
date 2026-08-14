---
name: market-sizing
description: Size a market with reconciled bottom-up and top-down estimates, producing TAM, SAM, and SOM with a full assumption ledger. Use this whenever the user asks for market size, TAM, SAM, SOM, addressable market, "how big is this market", market opportunity sizing, help with a fundraising or board deck's market slide, or whether a segment is worth entering. Also use it when someone quotes a market size number they got from an analyst report and needs to defend it.
---

# Market sizing

A TAM number on its own is worthless. Anyone can produce one, everyone produces
a different one, and the reader knows it. What carries weight in a board room or
an investment memo is *two independent estimates and an honest account of the
gap between them*.

That is the entire method here: size it twice, by methods that share no
assumptions, then explain the difference rather than averaging it away.

## Definitions worth being strict about

These three terms get used interchangeably and should not be:

**TAM** — every entity that has the problem, at full price. Not "the market for
software", but the market for *this product's specific job*. If your TAM is a
category number lifted from an analyst report, it is measuring someone else's
job, not yours.

**SAM** — the slice of TAM you can sell to today. Right segment, right
geography, right compliance posture, right integrations. The gap between TAM and
SAM is a roadmap, and stating it explicitly is more persuasive than hiding it,
because it shows you know what you are not yet.

**SOM** — the slice of SAM you can realistically win in the planning horizon
given the sales capacity you actually have. This is the only one of the three
that belongs anywhere near a quota model.

The most common error in this analysis is quoting TAM where SOM is the relevant
number. TAM answers "is this worth building". SOM answers "what will we sell".
Confusing them is how a plan gets built on a number that was never a forecast.

## The workflow

### 1. Build bottom-up first

Bottom-up is the estimate you control, and doing it first stops the top-down
number from anchoring you.

`units × attach rate × annual price`

**Units** must be countable and the counting method must be stated. "Companies
with more than 200 employees and a public engineering job posting in the last 12
months, from a Crunchbase and Greenhouse export dated 2026-07-02" is a unit
count. "Enterprises" is not.

**Attach rate** is the share of those units with enough of the problem to buy.
This is almost always the softest input in the model and it deserves a wide
range. Anchor it on something real: your own install-base penetration in a
segment you have worked, or an observed adoption rate for an adjacent product
at a comparable stage.

**Annual price** should be realized ACV, not list. If you discount 20% on
average, list price overstates the market by 25%.

### 2. Build top-down independently

`published market total × relevant share`

The discipline that makes this useful is *independence*. If you derive the
relevant share from the same reasoning that produced your attach rate, you have
not built a second estimate, you have built the first one twice.

Be specific about what the published total covers. Most category numbers are
broader than your product's job — that is not disqualifying, it is exactly what
the share multiplier is for, but the multiplier needs a stated basis.

### 3. Reconcile

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.sizing --spec market.json
```

The tool reports the ratio between the two methods and says what to do about it:

- **Within 2x** — you have a defensible range. Report both endpoints and both
  methods. A reconciled range beats either point estimate.
- **2x to 5x** — usually a definition mismatch. Most often the top-down category
  includes adjacent products the bottom-up unit count excludes. Reconcile the
  definitions before either number leaves the building.
- **Beyond 5x** — one of them encodes a wrong assumption, and averaging would
  hide it. Find the error. Check whether the unit count is really the set of
  buyers, and whether the published total measures the same job you do.

The instinct when two estimates disagree is to split the difference. Resist it.
The gap is the finding.

### 4. Derive SAM and SOM with stated constraints

SAM comes off TAM by naming what excludes the rest — geography, segment,
regulatory, integration. Each exclusion should be a sentence, not a percentage
pulled from nowhere.

SOM should be checked against sales capacity, not just asserted as a share. If
SOM implies 240 new logos and the team can work 60, one of those numbers is
wrong. The tool prompts for this check because it is the one that makes the
number plannable.

## Presenting it

The market slide that survives diligence has four things:

1. **The range, not a point.** "$300M–$375M depending on attach rate" is more
   credible than "$340M", because the first admits it is an estimate.
2. **Both methods, briefly.** One line each on how the number was built.
3. **The reconciliation.** Why the two differ and which you weight.
4. **SOM against capacity.** The number that connects to the plan.

Then the assumption ledger as an appendix. Nobody reads it, and its existence
changes how the rest is received.

## Common failures

**Analyst-report laundering.** Quoting a category number, applying an
unexplained percentage, and presenting the result as analysis. If the share
multiplier has no basis, the whole estimate has no basis.

**TAM inflation by definition creep.** Widening the definition until the number
is impressive. A reader who notices this discounts everything else in the deck.

**Sizing the market instead of the segment.** If you sell to one segment, size
that segment. A large TAM with a tiny reachable slice is a worse position than a
modest TAM you can actually capture, and sophisticated readers know it.

**Forgetting that price is an input.** Market size scales linearly with your
price assumption. If pricing is undecided, size it at two or three price points
rather than picking one silently.

**No time dimension.** A market growing 40% annually and one that is flat are
different opportunities at the same size. State the growth rate and where it
came from, or say you do not know.

## Reference material

- `references/sizing-methods.md` — additional methods (value-based sizing,
  analogous-market sizing, spend-displacement sizing) and when each is the right
  instrument.

A worked spec lives at `examples/sizing/agent-observability-na.json`.
