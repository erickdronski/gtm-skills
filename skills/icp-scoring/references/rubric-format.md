# Rubric format

The schema for `gtmkit.scoring`, used by both `icp-scoring` and
`deal-qualification`. One engine, one format, three criterion types.

## Top level

```json
{
  "name": "ICP fit — mid-market logistics",
  "scale": 5,
  "min_coverage": 0.6,
  "tiers": [
    {"min": 0.8, "label": "A"},
    {"min": 0.62, "label": "B"},
    {"min": 0.45, "label": "C"},
    {"min": 0.0, "label": "D"}
  ],
  "disqualifiers": [ ... ],
  "criteria": [ ... ]
}
```

| Field | Required | Rule |
|-------|----------|------|
| `name` | no | Document title; defaults to "Unnamed rubric". |
| `scale` | no | Positive number, defaults to `5`. Every score must fall in `0..scale`. |
| `min_coverage` | no | 0–1, defaults to `0.6`. Below this, a record is held out of ranking. |
| `tiers` | no | Sorted descending by `min`. Defaults to A/B/C/D at 0.8/0.6/0.4/0. |
| `disqualifiers` | no | Hard exclusions with stated reasons. |
| `criteria` | yes | Non-empty array. |

### `min_coverage` is the important one

Coverage is the share of scoring weight that had real data behind it. A record
below `min_coverage` is tiered `UNKNOWN` and sorted after every ranked record,
regardless of how well it scored on the criteria that *were* known.

This exists because every scoring model quietly treats missing data as bad data,
which systematically buries the accounts nobody has researched yet. Raise the
threshold when your data is generally complete and a gap is meaningful; lower it
when you are working an unresearched list and want directional ordering.

## Criteria

Three types. All share `id`, `label`, `weight`, and an optional `note`.

`id` must match the field name in your records. `weight` must be positive —
weighting a criterion zero is rejected, because dropping it from the rubric
entirely makes what you chose not to measure visible.

### numeric

```json
{
  "id": "support_tickets_monthly",
  "label": "Monthly ticket volume",
  "weight": 4,
  "type": "numeric",
  "bands": [
    {"min": 8000, "score": 5},
    {"min": 3000, "score": 4},
    {"min": 1000, "score": 2},
    {"min": 0, "score": 1}
  ]
}
```

Bands are evaluated highest threshold first; the first match wins. Each band
takes `min`, `max`, or both. A value matching no band scores `0`.

Values are parsed leniently — `"1,200"` and `"$1,200"` both work — because real
CRM exports contain both.

### boolean

```json
{
  "id": "exec_sponsor_identified",
  "label": "Named exec sponsor",
  "weight": 3,
  "type": "boolean",
  "true_score": 5,
  "false_score": 1
}
```

Truthy values: `true`, `yes`, `y`, `1`, `t` (case-insensitive). Anything else
present is false. Anything *absent* is missing, which is different — see below.

Note `false_score` need not be zero. A missing exec sponsor is a real negative
but rarely a total one, and scoring it `1` rather than `0` keeps it from
dominating the model.

### categorical

```json
{
  "id": "helpdesk",
  "label": "Helpdesk platform",
  "weight": 2,
  "type": "categorical",
  "map": {"zendesk": 5, "salesforce": 4, "intercom": 3, "homegrown": 1},
  "default": 1
}
```

Keys are matched case-insensitively. Unmapped values take `default`.

## Missing data

These values all count as **missing**, not as zero:

`null` · `""` · `unknown` · `n/a` · `na` · `null` · `-` · `?`

A missing value is excluded from both the numerator and the denominator, so fit
is computed over known weight only and coverage drops instead. This is the
central design decision of the engine: an unresearched account reads as
unresearched rather than as a bad fit.

## Disqualifiers

```json
{
  "field": "employees",
  "op": "<",
  "value": 50,
  "reason": "Below 50 employees the ticket volume never reaches the threshold where deflection pays back implementation"
}
```

Operators: `<` `<=` `>` `>=` `==` `!=` `in` `not in`. For `in` and `not in`,
`value` is an array.

`reason` is **required**. A record removed without a stated reason looks like a
bug to whoever reviews the list, and they will override it.

A disqualified record is tiered `OUT`, keeps its coverage figure, and sorts last.
Disqualifiers are checked against raw record values; a missing value never
disqualifies, since absence of evidence is not evidence.

## Records

CSV or JSON. CSV needs a header row whose names match criterion ids. JSON is
either an array of objects or an object with a `records` array.

Columns not referenced by any criterion are ignored and preserved in JSON output,
so you can carry an account id or CRM link through the pipeline.

## Output

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.scoring \
  --rubric rubric.json --records accounts.csv --name-field name
```

Records sort: ranked and qualified first (by fit, then coverage), then `UNKNOWN`,
then `OUT`. The markdown output ends with a "research these before ranking them"
section naming exactly which fields each under-covered record is missing — that
list is usually the highest-leverage work available to the team.

`--format json` gives per-criterion detail for every record, including which
band matched and what each contributed.

## Setting tier boundaries

The defaults are arbitrary. Set them against real capacity: if the team can work
40 accounts this quarter, the A tier should contain roughly 40 accounts. A
tiering model that produces 300 A-accounts has not prioritized anything.

The fastest validation available: score the current top ten customers. If the
rubric ranks them poorly, the rubric is wrong. It takes five minutes and it
catches most modeling errors.
