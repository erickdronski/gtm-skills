# Additional sizing methods

Bottom-up and top-down are the default pair because they are independent and
both are auditable. These four alternatives are worth reaching for when one of
the defaults is unavailable or unconvincing.

Whichever you use, the discipline is unchanged: **two methods that share no
assumptions, and an explanation of the gap between them.**

## Contents

- [Spend displacement](#spend-displacement)
- [Value-based sizing](#value-based-sizing)
- [Analogous market](#analogous-market)
- [Capacity-constrained sizing](#capacity-constrained-sizing)
- [Choosing a pair](#choosing-a-pair)

## Spend displacement

*What is the target already spending on the job you replace?*

```
addressable_entities x current_annual_spend_on_the_job x capturable_share
```

The strongest method when you displace something with a budget line — an
incumbent tool, an outsourced service, a staffed internal function.

Its advantage over unit-times-price is that it sizes a budget that already
exists. A market defined by existing spend is one where the buyer does not have
to find new money, which is a materially different and easier sale.

**Where it goes wrong:** `capturable_share` is doing enormous work and is
usually asserted. If the incumbent spend is $4M per account and you charge
$200k, you are not capturing 100% of it — you are capturing the fraction the
buyer will reallocate, which depends on whether the displaced cost is a contract
(cancellable) or people (usually not).

## Value-based sizing

*How much value does the product create, and what share can be priced?*

```
addressable_entities x annual_value_created x price_capture_rate
```

`price_capture_rate` for B2B software typically lands between 10% and 20% of
quantified value — enough for the buyer to see a clear return.

Use this when the category is new and there is no incumbent spend to displace,
which is exactly when spend displacement is unavailable.

**Where it goes wrong:** it sizes the market you could theoretically address if
every buyer perceived the value you have modeled. That gap is large and
persistent. Treat the result as an upper bound and say so.

The useful by-product: this method runs on the same math as the `value-case`
skill. If you have built business cases for real accounts, you have empirical
input for `annual_value_created` rather than an assumption — which makes this
method unusually strong for companies with a few deployments behind them.

## Analogous market

*How large did a comparable category become, and why?*

Not a formula — a structured argument. Identify a category that faced a similar
adoption problem with a similar buyer, and reason from its trajectory.

For this to be worth anything, name the structural similarity explicitly:
comparable buyer, comparable procurement path, comparable switching cost,
comparable regulatory pressure. "Both are developer tools" is not a structural
similarity.

**Where it goes wrong:** analogies are selected after the fact to support a
number. The discipline that fixes this is naming the analogy *and* the most
important way it breaks, in the same paragraph. A stated disanalogy is what
separates reasoning from decoration.

Best used as a sanity check on a number produced another way, or as a source for
the adoption *curve* rather than the final size.

## Capacity-constrained sizing

*How much can you actually serve?*

```
sellable_capacity x average_contract_value
```

Where capacity is set by whatever genuinely binds: implementation consultants,
account managers, supply, regulatory approvals, physical footprint.

This is the SOM check, and it is the one most often skipped. When capacity-based
sizing produces a number far below your SOM, the SOM is fiction. This is
routine, and finding it in planning is much cheaper than finding it in Q3.

Always run this as a cross-check on SOM, whatever method produced the TAM.

## Choosing a pair

| Situation | Recommended pair |
|-----------|-----------------|
| Established category, incumbent vendors | Bottom-up + top-down |
| Displacing an internal function or service | Bottom-up + spend displacement |
| New category, no published market total | Bottom-up + value-based |
| Product exists but adoption path is unproven | Bottom-up + analogous market |
| Any SOM claim, always | The chosen pair + capacity-constrained |

Two methods that share an assumption are one method. Before running a pair, ask
what each depends on and confirm the lists do not overlap — bottom-up attach
rate and top-down relevant share are frequently the same belief wearing two
labels, and a pair built that way will "agree" while telling you nothing.

## Reporting whichever pair you use

1. The range, not a point.
2. One line on how each estimate was constructed.
3. The ratio between them, and your explanation for the gap.
4. Which one you weight, and why.
5. The assumption ledger, as an appendix.

Point three is where credibility is won. A reader who sees two estimates and an
honest account of their disagreement will trust the range far more than a single
confident number — and a reader who catches you averaging away a 10x gap will
trust nothing in the document.
