<h1 align="center">gtm-skills</h1>

<p align="center"><strong>Go-to-market skills for AI agents — where the numbers come from tested code, not from the model.</strong></p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#the-nine-skills">Skills</a> ·
  <a href="#see-it-work">See it work</a> ·
  <a href="#the-assumption-ledger">Why it's different</a> ·
  <a href="#the-engine">Engine</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-101828">
  <img alt="zero dependencies" src="https://img.shields.io/badge/dependencies-0-08775c">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-174ea6">
  <img alt="Linux macOS Windows" src="https://img.shields.io/badge/tested_on-Linux%20%7C%20macOS%20%7C%20Windows-0f766e">
  <img alt="ruff" src="https://img.shields.io/badge/lint-ruff-d97706">
  <img alt="205 tests" src="https://img.shields.io/badge/tests-205-6b21a8">
</p>

---

Ask an AI agent for a business case and you get a beautiful document built on
invented numbers. It will tell you "industry research shows a 30% productivity
gain," and that sentence survives right up until a CFO asks which industry,
whose research, measured how — at which point the whole document, including the
true parts, is dead.

This pack fixes that structurally. Nine skills covering the go-to-market
surface — business cases, ICP scoring, pricing, market sizing, campaign
planning, positioning, competitive briefs, deal qualification, and executive
communication — sitting on a **tested Python library** that does the arithmetic
and an **assumption ledger** that refuses to accept a number without knowing
where it came from.

Every figure in a generated document traces to a named input with a stated
source. Nothing is written by hand.

## Install

**As a Claude Code plugin** (recommended):

```bash
/plugin marketplace add erickdronski/gtm-skills
/plugin install gtm-skills
```

**Or clone it** — the skills work with any agent that reads `SKILL.md` or
`AGENTS.md` files, and the CLI tools work standalone:

```bash
git clone https://github.com/erickdronski/gtm-skills
cd gtm-skills
python3 -m unittest discover -s tests -t .
```

No dependencies. No install step. No API key. Python 3.9+ and nothing else —
the entire engine is standard library, offline, and does not phone home.

## See it work

One command, no setup:

```bash
python3 -m gtmkit.valuecase examples/value-case/northwind-support-deflection.json
```

```
## Headline

| Metric                | Value                                                    |
|-----------------------|----------------------------------------------------------|
| Net present value     | $105.2k                                                  |
| Discounted payback    | 2 yr 4 mo                                                |
| IRR                   | 32%                                                      |
| Total investment      | $579.7k                                                  |
| Margin of safety      | benefits can come in 17% below plan and still break even |

## Evidence grade: C

Grade C. 35% of modeled value rests on assumptions and only 33% on measured
facts. State this before the reader finds it, and prioritize measuring the
largest assumption.

**Measure this first — Tickets deflected to self-service / deflection_rate.**
This one input moves NPV by $339.9k across its stated range and it flips the
decision at its low bound.
```

That last block is the part no other tool produces. The model grades its own
evidence, names the single number most worth measuring before the decision, and
tells you when an assumption is load-bearing enough to flip the answer.

## The assumption ledger

Every number entering a model declares what kind of number it is:

| Kind | Means | Requires |
|------|-------|----------|
| `fact` | Measured, from a named artifact a reader could open | A specific source |
| `inference` | Derived from facts by stated reasoning | The derivation itself |
| `assumption` | Chosen, not measured | A rationale **and** a low/high range |

Assumptions require ranges because an unbounded assumption cannot be
stress-tested, and a business case whose assumptions cannot be stress-tested is
a brochure.

And these sources are **rejected at the door**, not flagged in a report nobody
reads:

> `industry standard` · `research shows` · `best practice` · `internal data` ·
> a bare analyst-firm name · `estimated` · `TBD` · `assumed`

```
spec error: driver 'deflection': source for 'deflection_rate' reads as an
unfalsifiable claim: 'industry standard'. Replace it with a specific artifact
(a named export, dashboard, contract, or a stated derivation). If the number
really is unmeasured, mark it confidence='assumption' and give it a range.
```

The format has no objection to uncertainty. It objects to uncertainty in
disguise.

## The nine skills

| Skill | What it does |
|-------|-------------|
| [`value-case`](skills/value-case/SKILL.md) | Business cases with sensitivity analysis, a floor case, and an evidence grade |
| [`icp-scoring`](skills/icp-scoring/SKILL.md) | ICP definition and account scoring that reports data coverage alongside fit |
| [`campaign-plan`](skills/campaign-plan/SKILL.md) | Inverse funnel math — work backwards from the target to required spend and volume |
| [`market-sizing`](skills/market-sizing/SKILL.md) | TAM/SAM/SOM with bottom-up and top-down reconciled against each other |
| [`pricing-strategy`](skills/pricing-strategy/SKILL.md) | Value metric, packaging, and Van Westendorp price sensitivity |
| [`positioning`](skills/positioning/SKILL.md) | Positioning and messaging hierarchy grounded in competitive alternatives |
| [`competitive-brief`](skills/competitive-brief/SKILL.md) | Battlecards a rep can survive a real objection with — including honest weaknesses |
| [`deal-qualification`](skills/deal-qualification/SKILL.md) | MEDDPICC scoring that separates confirmed from assumed |
| [`exec-comms`](skills/exec-comms/SKILL.md) | Board updates, QBRs, and decision memos that lead with the decision |

Each is a full methodology, not a prompt template — with the failure modes
called out, because knowing how the analysis breaks is most of the value.

## Two ideas that run through everything

**Unknown is not the same as bad.** Every scoring model quietly treats missing
data as bad data — an account with no headcount on file scores like an account
known to be tiny. That single behavior has misdirected more territory plans than
any modeling error, because it systematically buries the accounts nobody has
researched yet. So the scorer reports fit *and* coverage, and holds
under-researched records out of the ranking entirely:

```
| Record          | Tier    | Fit  | Coverage | Notes                                       |
|-----------------|---------|------|----------|---------------------------------------------|
| Northwind       | A       | 100% | 100%     | Fully covered.                              |
| Boreal Retail   | B       | 66%  | 100%     | Fully covered.                              |
| Halden Freight  | UNKNOWN | 83%  | 50%      | Not a low-fit record, an unresearched one.  |
| Marisol Shipping| OUT     | —    | 100%     | Below the volume where deflection pays back |
```

Halden scores 83% and is still held back. Ranking it above a fully-diligenced
peer would be comparing a measurement to a guess.

**Say the weak part first.** Every generated document names its own limitations
before the reader finds them — the evidence grade sits above the driver detail,
the floor case is reported next to the headline, and the rejected survey
responses are listed rather than silently dropped. Volunteering the limit is the
cheapest credibility available, and it costs almost nothing because a competent
reader would have asked anyway.

## The engine

`gtmkit` is the deterministic core. Each module is a CLI and an importable
library:

```bash
python3 -m gtmkit.valuecase case.json          # business case with sensitivity
python3 -m gtmkit.scoring --rubric r.json --records accounts.csv
python3 -m gtmkit.funnel --target-revenue 4000000 --acv 45000 --stage "mql:0.25"
python3 -m gtmkit.sizing --spec market.json    # bottom-up vs top-down
python3 -m gtmkit.pricing --responses survey.csv
```

Add `--format json` to any of them to build your own view on top.

Some things it does that a spreadsheet version generally does not:

- **Period 0 is undiscounted**, per finance convention — which differs from
  Excel's `NPV()`, one of the most common errors in circulated models. Pinned by
  a test.
- **IRR returns `None` rather than a diverged number**, and flags cash flow
  shapes where IRR is mathematically ambiguous.
- **Van Westendorp validates monotonicity per respondent** and reports what it
  dropped. In real survey data, 5–15% of responses have the four answers out of
  order — leaving them in is the most common reason two analysts get different
  answers from the same file.
- **Driver value is attributed across inputs by proportional sensitivity**, so
  the evidence grade discriminates between a case with one soft input and a case
  that is soft all the way through.
- **Formulas are evaluated by a whitelist AST walker, never `eval`.** These
  specs are routinely assembled from data an agent read out of an email or a
  PDF. That is untrusted input, and it is treated as such.

## Testing

```bash
python3 -m unittest discover -s tests -t .   # 205 tests
python3 tools/validate_skills.py             # lint every skill
```

The finance tests check against hand-computed closed-form values rather than
snapshots — a snapshot test would have happily locked in the off-by-one
discounting error those tests exist to prevent. The skill linter checks
frontmatter, description trigger quality, dead links, referenced modules, and
length budgets, and runs in CI.

## Contributing

New skills and better methodology are both welcome. The bar is in
[CONTRIBUTING.md](CONTRIBUTING.md); the short version is that anything producing
a number needs a test, and any claim about how business works should say what
would make it wrong.

## Related

Part of a set of small, standalone tools for working with coding agents:

| Tool | Job |
|---|---|
| [agentsmith](https://github.com/erickdronski/agentsmith) | Derives your AGENTS.md from the repo and detects drift |
| [contexttest](https://github.com/erickdronski/contexttest) | A/B tests whether an AGENTS.md change actually helps |
| [burnrate](https://github.com/erickdronski/burnrate) | Prices what your agent sessions cost, with a hard spend cap |
| [tripwire](https://github.com/erickdronski/tripwire) | Audits what your agent is allowed to do |

## License

MIT. Use it commercially, fork it, ship it inside your product.
