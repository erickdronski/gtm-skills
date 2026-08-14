---
name: deal-qualification
description: Qualify an opportunity against MEDDPICC or a similar framework, plan discovery calls, and score deal health with explicit coverage of what is known versus assumed. Use this whenever the user asks to qualify a deal, run MEDDPICC or MEDDIC, prep for a discovery call, assess whether a deal is real, review a pipeline, decide what to forecast, write discovery questions, or figure out why a deal stalled. Also use it when someone describes an opportunity in optimistic terms and the underlying qualification has not been checked.
---

# Deal qualification

Qualification frameworks fail in a specific and predictable way: they become a
CRM field exercise. A rep fills in every box, the deal shows fully qualified,
and it slips three quarters running. The fields were filled with what the rep
*believes* rather than what anyone *confirmed*, and nothing in the process
distinguishes the two.

So the discipline here is not the framework. It is separating three states for
every element:

| State | Means |
|-------|-------|
| **Confirmed** | Someone in the account said it, or you saw the artifact |
| **Assumed** | The rep believes it, plausibly, without confirmation |
| **Unknown** | Nobody has asked |

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

## Running it as a score

The qualification rubric is the same weighted-scoring engine used for ICP fit,
which means elements you have not confirmed reduce *coverage* rather than
silently scoring as zero:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m gtmkit.scoring \
  --rubric ${CLAUDE_PLUGIN_ROOT}/skills/deal-qualification/assets/meddpicc-rubric.json \
  --records pipeline.csv --name-field opportunity
```

A deal at 80% qualification on 45% coverage is not a strong deal. It is an
unexamined one, and the engine holds it out of the ranking and tells you exactly
which elements are missing. That missing list is the call plan.

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

Reviewing a set of deals, look for the patterns rather than deal-by-deal detail:

**Deals with no confirmed economic buyer past the halfway point.** These are the
most common source of slip.

**Deals where the metric is the rep's, not the customer's.** Check whose words
the metric is in.

**Deals with a close date that never moves.** A close date held constant across
three reviews while nothing else advanced is a date nobody has retested.

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

Do it explicitly, and tell the buyer why. "Based on what you have described, I
do not think this is the right time — here is what would change that" preserves
the relationship and frequently produces a re-engagement when the situation
shifts. Quiet neglect produces neither.

## Reference material

- `assets/meddpicc-rubric.json` — a ready-to-run qualification rubric for the
  scoring engine, with coverage thresholds tuned so that unconfirmed elements
  correctly hold a deal out of the ranking.
- `references/discovery-questions.md` — a question bank organized by element,
  with notes on what a good answer versus a deflection sounds like.
