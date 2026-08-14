# Value driver patterns

A catalog of the driver shapes that recur across B2B business cases, with the
formula each takes, the realization factor it typically deserves, and the
question that most often breaks it in review.

Use this to find candidate drivers, not to fill a model. A case with two drivers
you can defend beats one with six you cannot.

## Contents

- [Cost avoided](#cost-avoided)
- [Cost reduced](#cost-reduced)
- [Revenue gained or accelerated](#revenue-gained-or-accelerated)
- [Risk avoided](#risk-avoided)
- [Working capital](#working-capital)
- [Drivers to avoid](#drivers-to-avoid)

## Cost avoided

The strongest category, because the money is visibly not spent.

**Replaced tool or contract**

```
current_annual_contract - new_annual_contract
```

Realization 0.9–1.0. The cleanest driver available: there is a contract, it has
a number, and someone can cancel it.

*What breaks it:* the incumbent contract does not actually terminate on the same
schedule, so year one captures a partial saving. Ask for the renewal date and
model it.

**Avoided hire**

```
roles_avoided * fully_loaded_cost_per_role
```

Realization 0.6–0.9. Strong when there is an approved and budgeted requisition
you can point to; weak when it is a hire someone was thinking about.

*What breaks it:* "we were going to hire someone eventually" is not an avoided
cost. Ask whether the req exists and is funded. If it does not, this is
absorbed growth, not avoided hire, and should be modeled that way.

**Avoided infrastructure or capacity**

```
units_avoided * cost_per_unit
```

Realization 0.8–0.95. Good when capacity is provisioned in visible increments.

## Cost reduced

**Volume-driven unit cost reduction**

```
volume * reduction_rate * cost_per_unit
```

Realization 0.7–0.9. The workhorse driver for most operational software. Its
strength depends almost entirely on how well `cost_per_unit` is derived — that
figure should be an `inference` with the arithmetic shown, never a round number.

*What breaks it:* a cost-per-unit built by dividing total departmental cost by
total volume includes fixed costs that do not fall with volume. If the reduction
is meaningful, split fixed from variable and apply the reduction only to the
variable part.

**Time saved per transaction**

```
volume * minutes_saved / 60 * loaded_hourly_cost
```

Realization 0.5–0.8, and lower if there is no plan for the time.

*What breaks it:* this is the single most-abused driver in enterprise software.
Time saved is not money saved unless it aggregates into something the business
can spend differently. Ask directly: does this become fewer people, more output
from the same people, or less overtime? If the answer is "people will have more
time", set realization at 0.3–0.5 and say why in the note.

**Rework and error reduction**

```
error_volume * reduction_rate * cost_per_error
```

Realization 0.6–0.85. Persuasive when the organization already tracks error
rates, unusable when it does not.

## Revenue gained or accelerated

Harder to defend than cost, because attribution is genuinely contested.

**Cycle time reduction pulling revenue forward**

```
annual_revenue * (days_saved / 365) * gross_margin
```

Realization 0.4–0.7. Note this models the *time value* of revenue arriving
earlier, not new revenue. That distinction is what makes it defensible; claiming
accelerated revenue as incremental revenue is what makes a case fall apart.

**Conversion rate improvement**

```
volume * rate_improvement * average_value * gross_margin
```

Realization 0.4–0.7. Apply gross margin, always. A case that counts top-line
revenue as benefit against real cost is comparing incompatible units, and a CFO
will notice within seconds.

**Churn reduction**

```
at_risk_revenue * retention_improvement * gross_margin
```

Realization 0.4–0.7. Strong when the customer already measures churn by cohort
and can name the at-risk segment; speculative otherwise.

**Capacity unlocked**

```
additional_units_servable * contribution_per_unit
```

Realization 0.5–0.8, and only when demand exists to fill the capacity. Capacity
without demand is not value.

## Risk avoided

Probabilistic by construction, which is fine as long as the probability is
stated rather than buried.

```
incident_probability * incident_cost * reduction_in_probability
```

Realization 0.3–0.6.

The failure mode here is expressing certainty about a probability. Bound
`incident_probability` widely and let the sensitivity table carry the argument.
A risk driver that swings the decision on its own is usually doing too much
work — risk is best as the third driver that reinforces a case cost and revenue
have already made.

Compliance-driven risk is the exception. When a regulation carries a defined
penalty and a defined deadline, the driver behaves more like cost avoided and
deserves a realization near 0.8.

## Working capital

Often overlooked and disproportionately persuasive to a CFO, because it is
their language.

**Days sales outstanding reduction**

```
annual_revenue / 365 * days_reduced * cost_of_capital
```

Realization 0.7–0.9.

**Inventory reduction**

```
inventory_value * reduction_rate * carrying_cost_rate
```

Realization 0.7–0.9.

These numbers are usually small relative to operational drivers, and they still
earn credibility out of proportion to their size — including one signals that
you understand how the buyer's finance organization thinks.

## Drivers to avoid

**Stacked productivity percentages.** Three drivers each claiming "20% more
productive" sum to a number nobody believes and taint the drivers that were
real.

**Employee satisfaction and retention, as a primary driver.** Real, and almost
never quantifiable to a standard that survives review. Include it as
qualitative context, or model it narrowly as avoided backfill cost with a wide
range and a low realization.

**Brand, morale, and strategic optionality.** These belong in the narrative, not
the model. Putting an unfalsifiable number on them invites the reader to
discount every number around it.

**Anything where the baseline cannot be produced.** A benefit is a delta. If
nobody can produce the current number, the delta is unfalsifiable and the
driver should be cut — or converted into a proposal to measure it, which is
often more valuable to the customer than the driver would have been.
