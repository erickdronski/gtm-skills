# Contributing

Contributions are welcome — especially new skills, sharper methodology, and
corrections from people who do this work for a living.

## The bar

**Anything that produces a number needs a test.** The whole premise of this pack
is that go-to-market arithmetic should come from code with a test suite. A new
calculation without tests undermines that, however correct it is.

Prefer tests checked against hand-computed closed-form values over snapshots. A
snapshot test locks in whatever the code did on the day it was written,
including the bug.

**Any claim about how business works should say what would make it wrong.**
"Lead with the ask" is a claim. "Lead with the ask, because executives are
scanning a queue of documents and section one has to be actionable alone" is a
claim with a mechanism you can argue with. The second is worth shipping.

**No dependencies.** `gtmkit` is standard library only, and CI fails if a
`requirements.txt` appears. This is not asceticism — it means the pack installs
anywhere Python runs, with no supply chain, and it survives being copied into a
locked-down environment.

**Python 3.9 compatible.** No `X | Y` type syntax, no `match` statements.

## Adding a skill

1. `skills/<name>/SKILL.md` with frontmatter `name` (matching the directory) and
   `description`.
2. Write the description to trigger. It is the *only* thing that determines
   whether the skill ever fires, so it must state when to use the skill, not
   just what it does, and it should name the phrasings a real user would type.
3. Keep `SKILL.md` under 500 lines. Detail goes in `references/`, pointed at
   from the body.
4. Include the failure modes. Knowing how an analysis breaks is most of the
   value, and it is what separates a skill from a prompt template.
5. Run the linter:

```bash
python3 tools/validate_skills.py
python3 -m unittest discover -s tests -t .
```

## Adding to the engine

New modules go in `gtmkit/` and follow the existing shape: an importable API, an
`argparse` CLI under `main()`, `--format markdown|json`, and errors that name
the offending field and say what would satisfy the rule.

Two conventions worth preserving:

**Return `None` rather than a fabricated number.** A missing IRR is information;
a made-up IRR is a liability.

**Report what you dropped.** If a function excludes rows, rejects inputs, or
truncates a list, that has to appear in the output. Silent filtering is how two
people get different answers from the same file.

## Style

Explain *why* in comments, not *what*. The code says what it does; the comment
should say what would go wrong without it, or what non-obvious thing motivated
the choice.

## Reporting a problem with the methodology

If a skill gives advice you think is wrong, open an issue and say what you have
seen instead. Domain disagreements are the most useful contributions here and
they do not require writing any code.
