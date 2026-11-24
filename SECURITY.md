# Security

## Scope

`gtmkit` is standard library only. It makes no network calls, writes only where
you point it, and has no telemetry.

Two areas genuinely warrant attention, and both exist because business-case
specs are routinely assembled by an agent from customer data read out of an
email, a PDF, or a web page — untrusted input by any reasonable definition.

**Formula evaluation.** Driver formulas in a business-case spec are arithmetic
expressions evaluated at runtime. They are therefore parsed to an AST and
walked against a whitelist (`gtmkit/expr.py`). `eval` is never used. Attribute
access, subscripting, imports, lambdas, string literals, and any function
outside a fixed list of six math builtins are hard errors, and exponents are
capped to prevent CPU exhaustion. `tests/test_expr.py` contains a test for each
of these; every one corresponds to something `eval` would have executed.

**The HTML report.** `gtmkit valuecase --format html` writes a file meant to be
forwarded to readers who never see the spec, and it is built from the spec's
own strings: the case name, the currency code, driver and cost labels, units,
sources, cost notes, and `meta` keys and values. Every one of them passes
through `html.escape`, and the page has no JavaScript and loads nothing: no
external fonts, images or stylesheets, and no link but the project's own.
Spec-controlled markup, script, an event-handler attribute, or a URL that loads
or links anything, reaching the rendered page, is a vulnerability.
`TestEscaping` in `tests/test_report.py` feeds markup through each of these
strings and checks that none of it arrives as markup.

## Reporting a vulnerability

Open a GitHub security advisory on this repository, or email the address on the
maintainer's GitHub profile. Please do not open a public issue for a
vulnerability.

Expect an acknowledgement within a few days. If you find a formula that escapes
the whitelist, or spec text that runs or loads anything in the HTML report,
that is the highest-severity class of bug in this project and it will be
treated accordingly.

## What is not a vulnerability

Business-case specs and rubrics are configuration you supply. A spec that
produces a wrong number because its inputs are wrong is a data problem, not a
security problem — though it is exactly what the assumption ledger exists to
make visible. Being configuration does not make a spec's text safe to put in a
page, however: escaping it is the report's job, as above.
