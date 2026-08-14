# Security

## Scope

`gtmkit` is standard library only. It makes no network calls, writes only where
you point it, and has no telemetry.

The one area that genuinely warrants attention is **formula evaluation**. Driver
formulas in a business-case spec are arithmetic expressions evaluated at
runtime. These specs are routinely assembled by an agent from customer data
read out of an email, a PDF, or a web page — untrusted input by any reasonable
definition.

Formulas are therefore parsed to an AST and walked against a whitelist
(`gtmkit/expr.py`). `eval` is never used. Attribute access, subscripting,
imports, lambdas, string literals, and any function outside a fixed list of six
math builtins are hard errors, and exponents are capped to prevent CPU
exhaustion. `tests/test_expr.py` contains a test for each of these; every one
corresponds to something `eval` would have executed.

## Reporting a vulnerability

Open a GitHub security advisory on this repository, or email the address on the
maintainer's GitHub profile. Please do not open a public issue for a
vulnerability.

Expect an acknowledgement within a few days. If you find a formula that escapes
the whitelist, that is the highest-severity class of bug in this project and it
will be treated accordingly.

## What is not a vulnerability

Business-case specs and rubrics are configuration you supply. A spec that
produces a wrong number because its inputs are wrong is a data problem, not a
security problem — though it is exactly what the assumption ledger exists to
make visible.
