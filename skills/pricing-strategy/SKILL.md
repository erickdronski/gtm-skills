---
name: pricing-strategy
description: Choose a value metric, design packaging and tiers, and analyze willingness to pay including Van Westendorp price sensitivity. Use this whenever the user asks about pricing, how much to charge, packaging or tiering, price increases, discounting policy, whether they are underpriced, how to structure plans, per-seat versus usage-based pricing, or analyzing pricing survey data. Also use it when someone is setting a price by looking at a competitor's pricing page, which is the most common and most expensive pricing mistake.
---

# Pricing strategy

Pricing is three decisions, and they are usually made in the wrong order. Most
teams start with the number. The number is the last decision and the least
important one.

1. **Value metric** — what you charge *for*. Determines whether revenue grows
   with customer success or fights it.
2. **Packaging** — what is bundled, gated, and tiered. Determines who
   self-selects into which price.
3. **Price level** — the actual number. Easiest to change, and the one everyone
   starts with.

Work them in that order. A wrong value metric cannot be fixed by adjusting the
price; it produces a business that has to fight its own customers for revenue.

## 1. The value metric

The right value metric satisfies three tests at once:

**It scales with realized value.** As the customer gets more out of the product,
they pay more, and it feels fair rather than punitive. Seats fail this test for
products where value concentrates in a few power users.

**It is predictable enough to budget.** A metric the buyer cannot forecast
creates procurement friction out of proportion to the revenue it captures. Pure
consumption pricing on a volatile workload is technically fair and commercially
painful — which is why usage-based products so often ship a committed floor.

**It is countable without argument.** If you and the customer can disagree about
the number at renewal, you have designed a recurring fight into the contract.

When these conflict, resolve toward predictability for enterprise buyers and
toward value-scaling for self-serve. That single distinction explains most of
the pricing divergence between otherwise similar products.

Candidate metrics worth evaluating explicitly: seats, active users, usage
volume, outcomes delivered, capacity provisioned, entities managed, revenue
processed. For each, ask what happens when the customer succeeds wildly, and
what happens when they have a slow quarter. Both answers should be tolerable.

## 2. Packaging

Packaging decides who buys what, and it does more work than price level.

**Tier on a dimension buyers can self-assess.** A buyer must be able to look at
the tiers and know which one they are, without a sales call. Tiers separated by
feature lists nobody understands push every deal into a conversation, which is
expensive at low ACV and is exactly why so many self-serve funnels underperform.

**Gate on scale and risk, not on quality.** Withholding SSO, audit logs, or
permissions from lower tiers works because those needs correlate with
willingness to pay. Withholding *reliability* or basic usability trains
customers to distrust the product.

**Three tiers is the default for a reason, not a rule.** Two tiers under-serve
the middle; five tiers make the choice hard. Add a fourth only when a genuinely
distinct buyer exists, not to fill a grid.

**Design the anchor deliberately.** The top tier's job is often to make the
middle tier look reasonable rather than to sell in volume. That is legitimate;
just be aware of which tier is the anchor and which is the target.

## 3. Price level

### Willingness to pay

Van Westendorp is the standard instrument. Four questions per respondent — at
what price is this *too cheap* (you would doubt the quality), *cheap* (a
bargain), *expensive* (you would have to think), *too expensive* (you would
never buy) — then intersect the cumulative curves.

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.pricing \
  --responses responses.csv
```

The CSV needs columns `too_cheap`, `cheap`, `expensive`, `too_expensive`.

The implementation validates monotonicity per respondent and drops rows where
the four answers are not in ascending order — those respondents misread the
question, and in real survey data they are routinely 5–15% of responses.
Leaving them in is the most common reason two analysts get different answers
from the same file. Rejected rows are listed rather than silently discarded.

**What the output means, and what it does not.** The acceptable band runs from
the point of marginal cheapness to the point of marginal expensiveness. The
optimal price point is where the fewest people reject the product on price in
either direction. But all of it measures *stated* willingness to pay, absent a
competitor, a budget cycle, or a procurement team. It bounds the decision. It
does not make it.

Below roughly 50 usable responses the intersections move several percent with
every added row, and the tool labels the result "indicative only". Respect that
label — a price set from 22 responses has four decimal places of precision and
none of the reliability.

### Value-based anchoring

Where you have a business case, price against it. If the product delivers
$300k of measurable annual value, a $60k price is a 5x return the buyer can
articulate to their CFO. Pricing at 10–20% of quantified value is a defensible
starting position for most B2B software, and it gives the seller a number to
reason from rather than a competitor's pricing page.

This is why `value-case` and this skill belong together: the ROI model is also
the pricing argument.

### Competitive reference

Use competitor pricing to understand *what buyers are anchored on*, never to set
your own number. You do not know their margins, their strategy, their discount
reality, or whether their published price is what anyone pays. Copying a price
copies a strategy you cannot see.

## Price increases

The mechanics matter more than the percentage:

- Grandfather existing customers for a stated period, and say the period.
- Give the increase a reason tied to delivered value, not to costs. Nobody buys
  "our costs went up."
- Announce with enough notice for a budget cycle — 90 days minimum for
  enterprise.
- Expect and model churn. A price increase with zero churn was too small.

## Discounting

A discount without a concession is a price cut with extra steps. Every discount
should buy something: a longer term, an earlier payment, a reference, a case
study, a broader deployment.

Publish the approval thresholds internally. Ad-hoc discounting does not just
lose margin, it teaches the market what your real price is — and that number,
not the published one, becomes the anchor for every subsequent negotiation.

## Common failures

**Charging for the wrong unit and papering over it with tiers.** If the value
metric is wrong, no amount of packaging fixes it.

**Pricing from cost.** Buyers do not care what it cost you to build.

**One price for two segments.** If enterprise and self-serve buy the same SKU at
the same price, one of them is badly mispriced.

**Never testing.** Most companies that suspect they are underpriced are, and
most never run the test. A price test on new logos only, in one segment, is low
risk and settles the question.
