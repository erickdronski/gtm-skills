---
name: campaign-plan
description: Plan a marketing campaign, demand generation program, or pipeline target by working backwards from the revenue number to the volume, spend, and timing it actually requires. Use this whenever the user asks to plan a campaign, build a demand gen plan, set a marketing budget, figure out how much pipeline they need, work out required MQLs or leads, forecast whether a target is reachable, justify marketing spend, or asks "how do we hit $X". Also use it when someone proposes a campaign budget without having checked whether the math closes.
---

# Campaign plan

Most campaign plans are written forwards: *we'll spend $200k, here's what we
hope happens.* That shape is unfalsifiable and therefore easy to approve, which
is why so many of them get approved and so few of them work.

Working backwards inverts the burden. Start from the number the business has
already committed to, derive what has to happen at every stage for it to land,
and the plan either closes or visibly does not — before anyone spends money.

## The workflow

### 1. Get the real target and the real conversion rates

The target is whatever revenue or pipeline number marketing is accountable for.
Take it as given; the point of this exercise is not to negotiate it.

Conversion rates are where plans go wrong, and there are only three honest
sources for them, in descending order of trustworthiness:

1. **The user's own historical data**, segmented the same way the campaign is.
2. **The user's own historical data, unsegmented** — usable, but say so, because
   blended rates hide that enterprise and self-serve convert differently by an
   order of magnitude.
3. **Nothing** — in which case you are building a scenario, not a forecast, and
   the output must be labeled that way.

Never supply industry benchmark conversion rates as though they were the user's.
The variance between companies in the same category is larger than the
difference the campaign is trying to make.

### 2. Establish the audience ceiling before anything else

Ask: how many organizations or people are actually reachable in this segment,
through this channel, in this timeframe?

This single number kills more plans than any other, and it is the one most often
skipped. A plan requiring 22 million impressions against an addressable audience
of 200,000 people is not aggressive, it is arithmetically impossible — and it is
far better to discover that in planning than in month two.

### 3. Run the math

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.funnel \
  --target-revenue 4000000 \
  --acv 45000 \
  --stage "impression:0.002" \
  --stage "visit:0.08" \
  --stage "mql:0.25" \
  --stage "sql:0.35" \
  --stage "opp:0.28" \
  --cpm 22 \
  --audience-ceiling 40000000 \
  --sales-cycle-days 96
```

Each `--stage` is `name:rate`, where the rate is the probability of moving to
the *next* stage. The final stage converts to closed-won, or to
`--win-rate` if you model the close separately.

The command exits non-zero when the plan exceeds the audience ceiling, so it can
gate a CI check or a planning script.

### 4. Stress the plan before presenting it

Run it three times: at the user's stated rates, at rates 25% worse, and at the
best rates they have ever achieved. The spread between those three is the real
finding.

If the plan only closes at the best rates the team has ever achieved, it does
not close. Say that plainly, then offer the levers rather than just the verdict.

### 5. Name the lever, not just the gap

When a plan does not close, there are exactly five things that can change, and
naming which one you are recommending is what separates a planner from a
reporter:

| Lever | When it is the right answer | What it costs |
|-------|----------------------------|---------------|
| Raise ACV | Pipeline is adequate, deals are small | Longer cycles, narrower segment |
| Improve a conversion rate | One stage is visibly worse than peers | Time; usually a quarter before it shows |
| Add a channel | Ceiling-bound, not rate-bound | New CAC to learn from scratch |
| Extend the timeline | Cycle length exceeds the period | Misses the committed date |
| Lower the target | The others are exhausted | The conversation nobody wants |

Pick the one with the best ratio of impact to elapsed time, and state the second
choice too — planning conversations go better when the recommendation has a
visible alternative.

### 6. Work the calendar backwards

A 96-day sales cycle means Q4 revenue requires pipeline created in Q3. This is
obvious and routinely ignored, producing plans that commit to revenue in a
period whose pipeline window has already closed.

Put the pipeline-creation deadline in the plan as a dated milestone, not as a
note. If that date is already in the past, the plan needs a different shape
entirely and you should say so in the first paragraph.

## Budget allocation across channels

When splitting spend across channels, allocate against *marginal* CAC rather
than blended CAC. A channel with $400 blended CAC that degrades to $1,200 at
triple the volume is not a $400 channel at the volume you are planning.

Ask for the historical relationship between spend and volume per channel. If it
does not exist, cap incremental spend in any single channel at roughly 1.5x its
proven level and route the rest elsewhere. Saturation is the most common reason
a plan that penciled at the portfolio level misses in execution.

## What to hand over

A campaign plan that will survive review contains:

1. The target, and the deal count it implies.
2. Required volume at each stage, with the source of every conversion rate.
3. Spend, blended CAC, and CAC as a share of first-year ACV.
4. The audience ceiling and the headroom against it.
5. The pipeline-creation deadline, dated.
6. What happens if the two weakest rates come in 25% below plan.
7. The one lever you would pull first if it does.

Point seven is the one that gets the plan approved.

## Common failures

**Blended rates across mixed segments.** Enterprise and self-serve converting at
one blended rate produces a plan that is wrong for both.

**Counting MQLs as the goal.** MQL volume is an input. A plan that hits MQL
target and misses revenue has failed, and structuring the plan around the
intermediate metric is how that happens.

**Ignoring sales capacity.** 317 opportunities against 4 reps and a 96-day cycle
is not a marketing plan, it is a marketing plan and a hiring plan. Check the
opportunity count against the coverage the team can actually work.

**Treating CAC as efficient without knowing gross margin.** CAC at 12% of ACV
sounds excellent and may not be, depending on margin and retention. State the
comparison rather than implying it.
