# Business case spec format

The complete schema for a `gtmkit.valuecase` spec, field by field, with the
validation rule attached to each and the reason it exists.

Validate before generating:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.valuecase case.json --check
```

## Contents

- [Top level](#top-level)
- [Drivers](#drivers)
- [Inputs and the assumption ledger](#inputs-and-the-assumption-ledger)
- [Formulas](#formulas)
- [Ramp and realization](#ramp-and-realization)
- [Costs](#costs)
- [Complete minimal example](#complete-minimal-example)
- [Validation rules, and why](#validation-rules-and-why)

## Top level

```json
{
  "name": "Support deflection — Northwind Logistics",
  "currency": "USD",
  "horizon_years": 3,
  "discount_rate_annual": 0.12,
  "meta": { "prepared_for": "...", "decision_date": "2026-09-30" },
  "drivers": [ ... ],
  "costs": [ ... ]
}
```

| Field | Required | Rule |
|-------|----------|------|
| `name` | yes | Non-empty. Appears as the document title. |
| `currency` | no | ISO code, defaults to `USD`. Drives the symbol only; no conversion happens. |
| `horizon_years` | yes | Integer, 1–10. |
| `discount_rate_annual` | yes | Decimal between -0.5 and 1.0. `0.12`, never `12`. |
| `meta` | no | Free-form object, passed through to JSON output. |
| `drivers` | yes | Non-empty array. |
| `costs` | yes | Non-empty array. |

**Why the horizon caps at 10.** Beyond a decade the discount rate swamps the
tail and reviewers discount the entire document. Most software decisions are
made on three years or fewer; if a case only clears on year-eight benefits, it
does not clear.

## Drivers

A driver is one benefit stream.

```json
{
  "id": "deflection",
  "label": "Tickets deflected to self-service",
  "formula": "tickets_per_year * deflection_rate * cost_per_ticket",
  "inputs": { ... },
  "ramp": [0.4, 0.9, 1.0],
  "realization": 0.85,
  "note": "Ramp reflects the content build-out schedule."
}
```

| Field | Required | Rule |
|-------|----------|------|
| `id` | yes | Unique across drivers. Used in sensitivity overrides. |
| `label` | no | Human-readable; defaults to `id`. |
| `formula` | yes | See [Formulas](#formulas). |
| `inputs` | yes | Non-empty object; every name the formula references. |
| `ramp` | no | Array of non-negative numbers. Defaults to all `1.0`. |
| `realization` | no | Above 0, at most 1. Defaults to `1.0`. |
| `note` | no | Passed through; use it to explain a modeling choice. |

## Inputs and the assumption ledger

Every input declares what kind of number it is. This is the core discipline of
the whole format.

```json
"deflection_rate": {
  "value": 0.18,
  "confidence": "assumption",
  "source": "Three reference customers with comparable ticket mix reported 14%, 19%, and 24% in their first full year; midpoint rounded down",
  "low": 0.10,
  "high": 0.24,
  "unit": "share of tickets",
  "note": "Optional"
}
```

| Field | Required | Rule |
|-------|----------|------|
| `value` | yes | Number. Booleans rejected. |
| `confidence` | yes | One of `fact`, `inference`, `assumption`. |
| `source` | yes | At least 12 characters, and not an unfalsifiable phrase. |
| `low` / `high` | see below | Numbers; `low <= value <= high`. |
| `unit` | no | Rendered in the ledger. |
| `note` | no | Free text. |

### The three confidence levels

**`fact`** — measured, from a named artifact a reader could open. Name the
system, the export, the date, and ideally the person: *"Zendesk ticket export,
2025-01-01 to 2025-12-31, shared by Dana Whitfield on 2026-07-14."*

**`inference`** — derived from facts by stated reasoning. Give the derivation
itself, not a citation: *"Fully loaded agent cost of $82,000 divided by 6,400
tickets handled per agent-year."*

**`assumption`** — chosen, not measured. Requires both `low` and `high`.

### Rejected sources

These are rejected outright rather than flagged, because they are the exact
phrases that get a case dismissed in review:

`industry standard` · `industry benchmark` · `research shows` · `studies show` ·
`best practice` · `internal data` · a bare analyst-firm name · `analyst report` ·
`vendor data` · `widely known` · `experience` · `estimated` · `TBD` · `assumed` ·
`unknown`

If the number really is unmeasured, that is fine — mark it
`confidence: "assumption"`, give it a range, and state the honest rationale. The
format has no objection to uncertainty. It objects to uncertainty in disguise.

### Why assumptions require a range

An unbounded assumption cannot be stress-tested, and a business case whose
assumptions cannot be stress-tested is a brochure. The ranges drive the
sensitivity table and the floor case — the two sections that do the most work in
a review.

If you cannot bound a number, you do not understand it well enough to model it.

## Formulas

Readable arithmetic over the driver's declared input names:

```
tickets_per_year * deflection_rate * cost_per_ticket
tickets_per_year * (1 - deflection_rate) * minutes_saved / 60 * loaded_hourly_cost
seats * (rate_high if seats > 500 else rate_low)
```

Supported: `+ - * / // % **`, parentheses, comparisons, ternaries, and the
functions `min`, `max`, `abs`, `round`, `floor`, `ceil`, `sqrt`.

Not supported, deliberately: attribute access, subscripting, imports, lambdas,
string literals, and any function outside that list. Formulas are evaluated by a
whitelist-based AST walker, never by `eval` — these specs are routinely
assembled from customer data an agent read out of an email or a PDF, and that is
untrusted input.

Two rules the validator enforces:

- **Every referenced name must be declared.** A typo becomes an error, not a
  silent zero.
- **Every declared input must be referenced.** An orphaned input means either
  the formula is stale or the ledger is, and both mislead a reviewer.

## Ramp and realization

These are different things and conflating them hides which one you are actually
arguing about.

**`ramp`** is *when* value arrives — the adoption curve. One entry per year. If
shorter than the horizon, the last value repeats. `[0.4, 0.9, 1.0]` says you
capture 40% of run-rate value in year one.

**`realization`** is the haircut between value you can model and value the
business actually captures. A flat multiplier across all years.

Guidance on realization by driver type:

| Driver type | Typical realization | Why |
|-------------|--------------------|-----|
| Hard cost avoided (a cancelled contract, a line item removed) | 0.9–1.0 | The money is visibly not spent |
| Volume-driven cost reduction | 0.7–0.9 | Depends on the reduction actually being taken |
| Time saved that converts to absorbed growth | 0.5–0.8 | Real, but diffuse |
| Time saved with no plan to redeploy it | 0.3–0.5 | Often not captured at all |
| Revenue acceleration | 0.4–0.7 | Attribution is genuinely hard |
| Risk or incident avoidance | 0.3–0.6 | Probabilistic by nature |

A realization of `1.0` claims you capture every modeled dollar. Be ready to
defend it.

## Costs

```json
{
  "id": "implementation",
  "label": "Implementation and change management",
  "schedule": [214000, 0, 0, 0],
  "note": "Fixed-fee SOW, 9 weeks."
}
```

`schedule` must have exactly `horizon_years + 1` entries — index 0 is today,
then one per year. Entries are **positive** numbers; the model subtracts them.

**Include the customer's own internal effort.** Omitting customer-side cost is
the fastest way to lose a case in procurement review, and including it buys more
credibility than it costs.

## Complete minimal example

```json
{
  "name": "Minimal example",
  "currency": "USD",
  "horizon_years": 3,
  "discount_rate_annual": 0.12,
  "drivers": [{
    "id": "savings",
    "label": "Reduced processing cost",
    "formula": "volume * unit_saving",
    "inputs": {
      "volume": {
        "value": 50000,
        "confidence": "fact",
        "source": "ERP transaction export for FY2025, pulled 2026-07-01"
      },
      "unit_saving": {
        "value": 1.4,
        "confidence": "assumption",
        "source": "Observed between $0.90 and $2.10 across two pilot sites",
        "low": 0.9,
        "high": 2.1
      }
    },
    "ramp": [0.5, 1.0, 1.0],
    "realization": 0.8
  }],
  "costs": [
    {"id": "sub", "label": "Subscription", "schedule": [0, 24000, 24000, 24000]},
    {"id": "impl", "label": "Implementation", "schedule": [40000, 0, 0, 0]}
  ]
}
```

## Validation rules, and why

| Rule | Reason |
|------|--------|
| Discount rate must be a decimal | `12` instead of `0.12` silently produces a nonsense model |
| Horizon 1–10 years | Longer horizons are not credible and reviewers discount them |
| At least one cost line | A benefit-only case is a wish list |
| Cost schedule length must match horizon | Off-by-one here misstates the whole case |
| Cost entries non-negative | Costs are positive in the schedule; the model subtracts |
| Realization in (0, 1] | Above 1 claims you capture more than you modeled |
| Assumptions need low and high | Unbounded assumptions cannot be stress-tested |
| Base value inside its own range | Either the base or the range is wrong |
| Source at least 12 chars, no weasel phrases | A source that identifies nothing is not a source |
| Every formula name declared | Typos become errors, not silent zeros |
| Every declared input used | A stale ledger misleads as much as a stale formula |
| Driver and cost ids unique | Ambiguous ids break sensitivity overrides |
