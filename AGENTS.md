# Working in this repository

Instructions for coding agents. Humans should read CONTRIBUTING.md.

## What this is

A pack of go-to-market skills sitting on `gtmkit`, a dependency-free Python
library that does the arithmetic. The premise is that numbers in business
documents should come from tested code rather than from a language model, so
the tests are the point, not overhead.

## Non-negotiables

- **Standard library only.** CI fails if `requirements.txt` appears.
- **Python 3.9 compatible.** No `X | Y` unions, no `match`.
- **Never use `eval` or `exec`.** Formula evaluation goes through
  `gtmkit/expr.py`, which walks an AST against a whitelist. Specs come from
  untrusted sources.
- **Return `None`, never a fabricated number.** A missing IRR is information.
- **Report what you drop.** Filtered rows, rejected inputs, and truncated lists
  must appear in the output.

## Before you finish

```bash
python3 -m unittest discover -s tests -t .
python3 tools/validate_skills.py
```

Both must pass. The linter checks skill frontmatter, description trigger
quality, dead links, referenced `gtmkit` modules, and length budgets.

If you change a number that appears in README.md, regenerate it and update the
README. A README quoting output the code no longer produces is worse than no
README.

## Layout

```
gtmkit/          the engine — one module per analysis, each a CLI and a library
skills/          one directory per skill: SKILL.md, references/, assets/
tests/           unittest, no pytest, no plugins
tools/           repository tooling (skill linter)
examples/        every example is exercised by CI
```

## Writing skills

`SKILL.md` frontmatter needs `name` (matching the directory) and `description`.
The description is the only thing that determines whether a skill triggers —
it must state when to use the skill and name phrasings a real user would type.

Keep the body under 500 lines; move detail to `references/`. Include failure
modes, and explain the reasoning rather than issuing rules — the instructions
are read by a capable model that does better with a stated mechanism than with
an unexplained MUST.
