# Criteria library

Candidate ICP criteria organized by business model, with what each actually
predicts and where each tends to mislead.

Treat this as a menu to test against your own outcome data, not a template. A
criterion that predicts strongly in one company is noise in another, and the
only way to know which is to check it against closed-won, closed-lost, and
churn.

## Contents

- [The two-rubric rule](#the-two-rubric-rule)
- [Enterprise and mid-market sales](#enterprise-and-mid-market-sales)
- [Product-led growth](#product-led-growth)
- [Marketplace and two-sided](#marketplace-and-two-sided)
- [Timing signals](#timing-signals)
- [Criteria that usually disappoint](#criteria-that-usually-disappoint)

## The two-rubric rule

Split criteria into two rubrics before doing anything else:

**Prospecting criteria** are observable from outside the account, before contact.
They drive list building and territory design.

**Qualification criteria** are learned during the process. They drive forecast
and resource allocation.

Mixing them produces a rubric that cannot be used for either job — you cannot
prospect on "has an engaged executive sponsor", and you should not forecast on
headcount alone. The `deal-qualification` skill covers the second rubric.

## Enterprise and mid-market sales

### Operational scale — usually the strongest single predictor

The volume of whatever your product acts on: tickets, transactions, shipments,
endpoints, records, builds, incidents.

*Predicts:* whether the value case clears at all. Accounts where the math works
are accounts that buy, which is why this is the same number that drives your
business case.

*Misleads when:* the metric is reported at company level but the buying unit is
a division. Score the division you would actually sell to.

*Weight:* highest in most B2B models.

### Headcount and revenue

*Predicts:* budget availability and process complexity. Weak on its own —
correlates with everything and causes nothing.

*Misleads when:* used as a proxy for operational scale. A 5,000-person
professional services firm and a 5,000-person logistics company have wildly
different volumes of most things.

*Weight:* moderate, and mostly as a floor rather than a gradient. Often better
expressed as a disqualifier than as a scored criterion.

### Technographic fit

Whether they run the systems you integrate with.

*Predicts:* implementation friction and time to value. Strong when integration
is a genuine barrier; near-zero when everyone has an API.

*Misleads when:* the data is stale. Technographic data ages badly — a stack
detected 18 months ago may be two migrations out of date.

### Buying center existence

Whether a team or role exists that owns the problem.

*Predicts:* whether there is anyone to sell to at all. Frequently the real
disqualifier — an account with the problem and nobody who owns it will consume
enormous cycles and not close.

*Sourced from:* job titles on the company's own careers page and public
profiles, which is more reliable than any purchased dataset.

### Regulatory or contractual exposure

Whether they are compelled to care.

*Predicts:* urgency and deadline. Among the strongest predictors when it
applies, and inapplicable to most accounts, which makes it a good high-weight
criterion with a narrow band rather than a broad gradient.

### Geography and data residency

*Predicts:* whether you can legally serve them. Almost always a disqualifier
rather than a score — half a point of fit does not help if you cannot host their
data.

## Product-led growth

### In-product usage depth

Number of activated features, frequency, breadth across a team.

*Predicts:* conversion to paid and expansion, better than any firmographic.

*Misleads when:* it measures a single power user rather than a team. Weight
breadth over depth for expansion prediction.

### Team spread

How many distinct users from the same domain have signed up.

*Predicts:* expansion potential more reliably than company size, because it
measures adoption that already happened.

### Time to first value

How quickly a new account reached the activation moment.

*Predicts:* retention strongly. Accounts that took a long time to activate churn
at higher rates almost universally.

### Support and documentation behavior

Accounts reading integration documentation or asking about limits, security, or
SSO are self-identifying as evaluators.

*Predicts:* near-term intent. Decays fast — this belongs in a timing score, not
a fit score.

## Marketplace and two-sided

Score supply and demand separately; a single blended ICP for a two-sided market
describes neither side.

**Supply side:** inventory depth, fill rate, responsiveness, quality signals.
**Demand side:** frequency, basket size, retention.
**Geographic density:** usually the binding constraint. A marketplace works or
fails locally, so score the metro rather than the account.

## Timing signals

Keep these in a separate score. Blending fit and timing produces a number that
means neither, and the two decay at completely different rates.

| Signal | Predicts | Half-life |
|--------|----------|-----------|
| Hiring for the relevant role | A budgeted initiative | ~1 quarter |
| Leadership change in the buying center | New priorities, new budget | ~2 quarters |
| Funding round | Budget availability | ~2 quarters |
| Public commitment to a relevant goal | Executive attention | ~1 year |
| Competitor contract renewal window | Displacement opportunity | Weeks |
| Incident or public failure in your domain | Urgency | Weeks |
| Documentation or pricing page visits | Active evaluation | Days |

## Criteria that usually disappoint

**Industry, on its own.** Wildly popular and weakly predictive. Industry is
usually a proxy for operational scale — model the scale directly and industry
often stops earning its weight.

**Tech-forwardness or "innovation" scores.** Unfalsifiable, and typically
smuggles in a bias toward companies that look like the ones you already have.

**Funding stage as a fit criterion.** Predicts ability to pay, not need. Better
as a disqualifier floor than as a gradient.

**Anything you cannot source for most of the list.** A brilliant criterion with
20% coverage will push most of your list into the UNKNOWN tier and tell you
nothing. Coverage is a real constraint on rubric design, not an afterthought —
prefer a decent criterion you can populate over an excellent one you cannot.
