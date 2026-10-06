---
name: deal-qualification
description: Qualify an opportunity against MEDDPICC or a similar framework, plan discovery calls, and review a pipeline — scoring deal health with explicit coverage of what is confirmed versus assumed, and computing coverage and a weighted forecast from sourced stage probabilities. Use this whenever the user asks to qualify a deal, run MEDDPICC or MEDDIC, prep for a discovery call, assess whether a deal is real, review a pipeline, check pipeline coverage, build a weighted forecast or commit call, find stale or slipped deals, decide what to forecast, write discovery questions, or figure out why a deal stalled. Also use it when someone describes an opportunity in optimistic terms and the underlying qualification has not been checked.
---

# Deal qualification

Qualification frameworks fail in a specific and predictable way: they become a
CRM field exercise. A rep fills in every box, the deal shows fully qualified,
and it slips three quarters running. The fields were filled with what the rep
*believes* rather than what anyone *confirmed*, and nothing in the process
distinguishes the two.

So the discipline here is not the framework. It is recording, for every
element, *how anyone knows*:

| Status | Means | Requires |
|--------|-------|----------|
| **Confirmed** | Checked against something a reviewer could open — the dated call, the email, the document | The source |
| **Stated** | A named person in the account said it, and nothing corroborates it yet | Who said it |
| **Assumed** | The rep believes it, plausibly, without anyone in the account saying so | Nothing, but it is labelled |
| **Unknown** | Nobody has asked | No level at all |

Most stalled deals are stalled on something that was "assumed" and was wrong.
Making that visible is the entire value of doing this properly.

## MEDDPICC, with the question that actually tests each element

**Metrics** — the quantified business impact the buyer expects.
*Test:* Can the champion state the number without you prompting them? If the
metric is yours rather than theirs, it will not survive their internal review.
Pair this with the `value-case` skill; a deal with no metric has no business
case, and a deal with no business case does not close on time.

**Economic buyer** — the person who can spend the money without asking.
*Test:* Have you met them? "We know who it is" is not the same as access. If you
have not met the economic buyer by mid-cycle, the forecast is a guess.

**Decision criteria** — how they will choose.
*Test:* Do you have it in writing, in their words? Criteria you inferred are
criteria a competitor may have written.

**Decision process** — the actual steps, with names and dates.
*Test:* Can you name every approval gate — legal, security, procurement,
finance — and roughly how long each takes at this company? Deals do not usually
die at the decision. They die in the approval chain nobody mapped.

**Paper process** — contracting, security review, vendor onboarding.
*Test:* Has anyone confirmed the timeline for this specific company? Six weeks
of security review discovered in the last week of the quarter is the most common
single-cause slip in enterprise software.

**Identified pain** — what breaks if they do nothing.
*Test:* Is it urgent for a *person*, not just for the company? Companies do not
buy; people with problems and deadlines buy. Pain with no deadline loses to
every competing priority, and its most common competitor is not a rival vendor —
it is "next year".

**Champion** — someone who sells internally when you are not there.
*Test:* Have they done something costly for you? Taken a meeting to their boss,
shared internal information, put their name on something. Someone friendly on
calls is a coach, not a champion, and the distinction shows up at the approval
gate.

**Competition** — including "do nothing", which usually leads.
*Test:* Do you know what the alternative actually is, from the buyer rather than
from inference?

## Scoring one deal

Write the deal as a spec — for each element, a level from the rubric and a
status — and let the engine do the arithmetic:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.qualify deal.json
```

`--as-of YYYY-MM-DD` pins the date the close-date checks run against (default:
the spec's `as_of`, then today, which the output prints); `--format json`
returns the full result. An element looks like this:

```json
"economic_buyer": {
  "level": "identified_not_met",
  "status": "stated",
  "by": "Dana Ruiz, VP Customer Support"
}
```

The format, every element's levels, and the rule each status must meet are in
`references/deal-spec.md`. A worked spec is `examples/deal/kestrel-expansion.json`.

**Fill it by asking how they know, not what they think.** For each element,
get the answer and then its provenance. If the user can name the call (with
its date), the email, or the document, it is confirmed and that goes in
`source`. If someone told them, it is stated and the person goes in `by`.
Otherwise it is assumed. Never write a plausible source to get a confirmation
past the validator: it rejects "multiple conversations" for the same reason the
value case rejects "industry standard", and inventing a specific-sounding one
just moves the fiction from the spec into the forecast.

### Reading the output

The score uses the same rubric and arithmetic as the ICP scorer, so the two
engines never disagree about a tier. What comes back on top of it:

- **The verdict** puts the tier on what the team believes next to the tier at
  the *floor* — every element that is not confirmed at its worst level at
  once. "BEST CASE on belief, AT RISK at the floor" is the sentence a forecast
  call needs and almost never gets. Unknown elements lower coverage, not the
  score; under 75% coverage a deal is UNKNOWN — not weak, unexamined.
- **The evidence mix** is the share of rubric weight that is confirmed,
  stated, assumed, and unknown. Status deliberately does not discount the
  score: a penalty for "assumed" would be a number nobody measured, and the
  gap is more useful shown than blended.
- **Failure patterns** — no access to the economic buyer, champion untested,
  decision process assumed, paper process unknown late, no customer-owned
  metric, competition unknown. Each fires only once the deal reaches the stage
  by which its element should be confirmed: an unknown paper process is normal
  in discovery and a quarter-end slip forming at proposal. The paper process
  also fires within six weeks of the close date whatever the stage. Each
  pattern states its mechanism and what would make it wrong.
- **The next action** is the one element whose answer is most likely to move
  the call: one that could change the tier first, then one a pattern is firing
  on, then the latest, then the least known. It comes with the reason and the
  tier at its worst and best outcome.

Lead the review with the next action. "Meet the CFO before the 20th, because
that decides whether this is best case or pipeline" is a review outcome. A
score is not.

### Many deals at once

A CRM export records levels but not how anyone knows them, so the most it
supports is the believed view. The same rubric runs across it on the scoring
engine, which holds under-answered deals out of the ranking:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.scoring \
  --rubric ${CLAUDE_PLUGIN_ROOT}/skills/deal-qualification/assets/meddpicc-rubric.json \
  --records pipeline.csv --name-field opportunity
```

A deal at 80% qualification on 45% coverage is not a strong deal. It is an
unexamined one. Use this pass to pick the deals worth a full `gtmkit.qualify`
spec — the large ones someone is calling commit or best case.

## Planning the discovery call

Discovery is not a questionnaire. The goal is for the buyer to articulate their
own problem in their own words, because a problem they described themselves is
one they will defend internally when you are not in the room.

**Open wide, then narrow.** Start where they have room to tell you what actually
matters, not where your form starts.

**Ask about the last time, not the general case.** "Walk me through the last
time this happened" produces specifics. "How do you usually handle this"
produces a policy description that may not reflect reality.

**Quantify inside the conversation.** When they describe a problem, ask how
often and how much. Numbers gathered live are facts with a named source; numbers
reconstructed afterwards are estimates.

**Ask what happens if nothing changes.** The answer tells you whether there is a
deal at all. If the honest answer is "we carry on", there is no urgency and the
forecast should reflect that.

**Ask who else cares.** Surfaces the buying center before it surfaces you.

Leave the call with: the metric, the person it belongs to, the deadline it is
tied to, and the name of the next person you need to meet. If you have those
four, discovery worked.

## Pipeline review

A pipeline review asks two questions, and they need different tools.

**How much is there, and what will it produce?** That is arithmetic, so it
comes from the engine:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.pipeline pipeline.csv \
  --stages stages.json --target 1200000 --closed 95000 \
  --period-end 2026-12-31 --as-of 2026-10-06
```

It reports coverage of what is left of the target next to the coverage the
stage probabilities actually require, the weighted forecast with its range and
standard deviation, the commit / best case / pipeline build against target,
concentration in the largest deals, and every deal whose close date has passed,
been pushed, or gone untouched. The file format, flags, and stage model are in
[the pipeline format reference](references/pipeline-format.md).

The stage probabilities are the whole forecast, so get them from the user's own
history — of the deals that *entered* each stage last year, the share that
closed-won — and record the report they came from. If all they have is the
CRM's default percentages, those go in as assumptions with ranges; the engine
refuses a default declared as a fact, and with no stage model it runs on
labelled placeholders and calls the result a scenario. Never type in "typical"
stage probabilities yourself: that is the invented-benchmark failure this pack
exists to stop, wearing a forecast's clothes.

Lead with the expected landing against target and the commit number. Report
coverage only next to the coverage the probabilities need — "2.2x" sounds
healthy until the reader learns this stage mix needs 2.6x.

**Which of it is real?** That is qualification. Run the scoring pass over the
same file, then a full `gtmkit.qualify` spec on the large deals someone is
calling commit or best case. Where the rep's category and the qualification
tier disagree — a commit that scores best case, a best case that scores commit
— is where the review should spend its time. Then look for the patterns rather
than deal-by-deal detail:

**Deals with no confirmed economic buyer past the halfway point.** These are the
most common source of slip; `gtmkit.qualify` flags them from Solution on.

**Deals where the metric is the rep's, not the customer's.** Check whose words
the metric is in.

**Deals with a close date that never moves.** The engine flags dates that have
passed or been pushed. A date held constant across three reviews while nothing
else advanced needs review history it does not have, so ask: it is a date
nobody has retested.

**Deals with no paper-process timeline.** Ask for the security review estimate.
Silence here is a quarter-end problem forming.

Then ask the question that matters: *what is the single next thing that must
happen, who does it, and by when?* A deal that cannot answer that is not a deal
in progress; it is a deal in hope.

## Disqualifying well

The highest-leverage skill in this whole area is walking away early. Time spent
on a deal that will not close is not neutral — it is time not spent on one that
would.

Disqualify when: there is no metric anyone owns, no access to economic buying
authority after genuine attempts, no deadline attached to the pain, or a
structural blocker you cannot clear.

The engine makes the bluntest version of this call itself: a deal with no
identified pain at all is tiered OUT, and its next action is to disqualify — or,
if that "none" was only assumed, to confirm it first. The rest are judgment
calls the failure patterns inform but do not make.

Do it explicitly, and tell the buyer why. "Based on what you have described, I
do not think this is the right time — here is what would change that" preserves
the relationship and frequently produces a re-engagement when the situation
shifts. Quiet neglect produces neither.

## Reference material

- `assets/meddpicc-rubric.json` — the rubric both engines read: levels and
  weights, the stages, when each element is due, and the action that resolves
  each one.
- `references/deal-spec.md` — the deal spec, the status rules, the failure
  patterns, and how the next action is ranked.
- `references/pipeline-format.md` — the pipeline file, the stage model, every
  flag, and what the forecast arithmetic assumes.
- `references/discovery-questions.md` — a question bank organized by element,
  with notes on what a good answer versus a deflection sounds like.

Worked examples live in `examples/deal/` and `examples/pipeline/`. The deal
spec is the pipeline's Kestrel row with its provenance recorded, so the two
show the believed view and the evidenced view of the same deal.
