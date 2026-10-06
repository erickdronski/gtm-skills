# Deal spec format

The input to `gtmkit.qualify`: one deal, one entry per MEDDPICC element, each
with a **level** (how good the answer is) and a **status** (how anyone knows).

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.qualify deal.json
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.qualify deal.json --as-of 2026-10-06
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.qualify deal.json --format json
```

`--rubric` points at a different rubric; the default is
`assets/meddpicc-rubric.json`. A complete worked spec is
`examples/deal/kestrel-expansion.json`.

## Contents

- [Top level](#top-level)
- [Elements](#elements)
- [Statuses](#statuses)
- [Levels](#levels)
- [Stages and when each element is due](#stages-and-when-each-element-is-due)
- [Failure patterns](#failure-patterns)
- [How the next action is chosen](#how-the-next-action-is-chosen)
- [Rubric fields qualification adds](#rubric-fields-qualification-adds)

## Top level

```json
{
  "name": "Kestrel Distribution — support platform expansion",
  "owner": "Marcus Bell",
  "amount": 186000,
  "currency": "USD",
  "stage": "proposal",
  "close_date": "2026-11-20",
  "as_of": "2026-10-06",
  "elements": { ... }
}
```

| Field | Required | Rule |
|-------|----------|------|
| `name` | yes | The deal, as the reader knows it. |
| `stage` | yes | One of the rubric's stage ids (below). |
| `elements` | yes | Keyed by element id. An id the rubric does not define is an error. |
| `amount` | no | Positive number. Display only; it does not change the score. |
| `currency` | no | Defaults to `USD`. |
| `close_date` | no | `YYYY-MM-DD`. Turns on the paper-process clock. |
| `as_of` | no | `YYYY-MM-DD`. `--as-of` overrides it; with neither, today is used and printed. |
| `owner` | no | Carried through to the JSON output. |

## Elements

```json
"economic_buyer": {
  "level": "identified_not_met",
  "status": "stated",
  "by": "Dana Ruiz, VP Customer Support",
  "notes": "Dana says the CFO approves anything over $150k. We have not met him."
}
```

| Key | When | Rule |
|-----|------|------|
| `status` | always | `confirmed`, `stated`, `assumed`, or `unknown`. |
| `level` | unless unknown | One of the element's levels. Case and spacing are forgiven (`Met Once` matches `met_once`). |
| `source` | confirmed | What a reviewer could open. Rules below. |
| `by` | stated | The person who said it, by name and role. |
| `basis` | assumed, optional | Why the rep believes it. Shown in the output. |
| `notes` | optional | Free text, shown under the elements table. |

Any other key is an error, so a misspelled `sorce` cannot quietly vanish. An
element missing from the spec is treated as `unknown` and listed as not
recorded.

## Statuses

| Status | Means | Scores? | Requires |
|--------|-------|---------|----------|
| `confirmed` | Checked against something a reviewer could open | yes | `source` |
| `stated` | A named person in the account said it; nothing corroborates it | yes | `by` |
| `assumed` | The rep believes it | yes | nothing — but it is labelled |
| `unknown` | Nobody has asked | no — lowers coverage instead | no `level` |

Status never changes the score. It changes the **evidence mix** (the share
of rubric weight at each status) and the **floor** (everything not confirmed
at its worst level at once). Keeping it out of the score is deliberate: a
discount for "assumed" would be a number nobody measured, and it would let a
deal buy its way to a tier with optimism. Reporting the two side by side
shows the gap instead.

### What a confirmed source must do

The source passes the same checks as the assumption ledger in
`gtmkit.evidence` — at least 12 characters, and none of the phrases it
rejects (`industry standard`, `research shows`, `TBD`, and the rest) — plus
two more:

- **No confirmation-shaped vagueness.** "Multiple calls with the customer",
  "several emails from the buyer", "the customer said so", "rep's notes",
  "CRM", "verbal confirmation" are all rejected. They are this domain's
  "research shows": they sound like evidence and point at nothing.
- **A date or a document.** "Discovery call with Dana Ruiz" names a
  conversation without saying which one; add the date. "Dana Ruiz email
  2026-09-14", "Signed mutual action plan v3", and "Call with Tom Akers on Sep
  12, Gong" all pass.

If the honest answer is "she told me", the status is `stated`, with her name.
Do not write a plausible-sounding source to get past the check — that is the
exact failure the check exists to catch, and it moves the problem from the
spec into the forecast.

### What a stated attribution must do

Name a person. "the customer", "they", "the champion", "the team" are roles
in the conversation, not people in the account, and are rejected.

## Levels

From `assets/meddpicc-rubric.json`, best first. Weight is out of 26.

| Element | Weight | Levels (points of 4) |
|---------|--------|----------------------|
| `metrics` | 3 | customer_stated 4 · jointly_built 3 · seller_proposed 1 · none 0 |
| `economic_buyer` | 4 | met_and_engaged 4 · met_once 3 · identified_not_met 1 · unidentified 0 |
| `decision_criteria` | 3 | written_from_customer 4 · verbal_from_customer 3 · inferred 1 · not_established 0 |
| `decision_process` | 3 | mapped_with_dates 4 · mapped_no_dates 2 · partial 1 · not_established 0 |
| `paper_process` | 3 | confirmed_timeline 4 · estimated_timeline 2 · not_started 0 |
| `identified_pain` | 4 | urgent_with_deadline 4 · urgent_no_deadline 2 · acknowledged 1 · none 0 |
| `champion` | 4 | tested_and_selling 4 · willing_untested 2 · coach_only 1 · none 0 |
| `competition` | 2 | known_from_buyer 4 · known_inferred 2 · not_established 0 |

`identified_pain: none` disqualifies the deal (tier `OUT`), whatever its
status — though when it is not confirmed, the next action is to confirm it
before walking away.

## Stages and when each element is due

`discovery` → `qualification` → `solution` → `proposal` → `negotiation` →
`closing`. Map a CRM's stages onto these by what has to be true to enter
each, not by name: Solution means the buyer is evaluating a specific
solution, Proposal means pricing is in front of them, Closing means paperwork
is in motion.

| Due by | Elements |
|--------|----------|
| Qualification | identified pain |
| Solution | metrics, economic buyer, decision criteria, champion, competition |
| Proposal | decision process, paper process |

Before an element's stage, a gap is normal and is only listed. From that stage
on, an unconfirmed element is marked "due now" or "overdue" in the table, and
the failure patterns below can fire.

These are the shipped defaults, and they are claims: they would be wrong for
a motion where, say, the economic buyer is routinely engaged only at
negotiation and deals still close on time. Change `confirm_by` in the rubric
if your won deals show a different order.

## Failure patterns

Each fires only from its element's due stage onward.

| Pattern | Element | Fires when |
|---------|---------|-----------|
| No access to the economic buyer | economic_buyer | unknown, or level unidentified / identified_not_met |
| Champion unconfirmed or untested | champion | not confirmed, or level none / coach_only / willing_untested |
| Decision process assumed | decision_process | assumed or unknown |
| Paper process unknown this late | paper_process | assumed, unknown, or level not_started |
| No quantified metric the customer owns | metrics | unknown, or level none / seller_proposed |
| Competition unknown | competition | unknown, or level not_established |

The paper-process pattern also fires on a clock: within `paper_lead_days` (42
by default — six weeks) of the close date, whatever the stage, because
security review and contracting run on the buyer's calendar.

Each pattern in the output carries the mechanism and what would make it
wrong, so it can be argued with rather than obeyed.

## How the next action is chosen

Every element that is not already confirmed at its best level is tried at its
worst and its best outcome, with everything else held as believed. They are
ranked by, in order:

1. Whether either outcome changes the tier — the point is to move the call.
2. Whether a failure pattern is firing on it.
3. How many stages late it is.
4. How little is known: unknown, then assumed, then stated, then confirmed.
5. How far its best and worst outcomes move the score.

The fourth rule ranks above size because the less verified an answer is, the
more likely the truth differs from what the forecast assumes. It would be
wrong for a team whose reps' assumptions reliably survive confirmation; check
how often they did in last quarter's won and lost deals.

Two cases are handled separately. An `UNKNOWN` deal gets the smallest set of
unanswered elements that would make it tierable, heaviest first. An `OUT` deal
gets "disqualify, and say why" when the disqualifying answer is confirmed, and
"confirm it first" when it is not.

## Rubric fields qualification adds

`gtmkit.scoring` ignores these, so the same rubric serves both engines.

| Field | Level | Rule |
|-------|-------|------|
| `stages` | top | Ordered array of `{"id", "label"}`, earliest first. Required. |
| `paper_lead_days` | top | Positive whole number, optional. Turns on the paper clock. |
| `confirm_by` | criterion | A stage id. Without it the element has no stage gate, and its pattern is listed as not checked (the paper clock still runs). |
| `action` | criterion | The sentence shown when this element is the next action. |

Every criterion must be `categorical`: a status describes a stated answer,
not a measurement.
