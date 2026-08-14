"""gtmkit — the deterministic core behind the gtm-skills pack.

Standard library only, Python 3.9+. No network access, no telemetry, nothing
that phones home. Everything here exists so that the numbers in a go-to-market
document come from tested code rather than from a language model's arithmetic.

Modules:

``finance``
    NPV, IRR, payback, break-even, and the summary block every business case
    leads with.
``evidence``
    The assumption ledger — what kind of number is this, and where did it come
    from. Rejects unfalsifiable sources at the door.
``expr``
    A small safe arithmetic evaluator so driver formulas stay readable without
    handing arbitrary code execution to a JSON file.
``valuecase``
    Ties the above together into an auditable business case with sensitivity,
    a floor case, and an evidence grade.
``funnel``
    Inverse funnel math: work backwards from a pipeline target to the spend and
    volume it actually requires.
``sizing``
    Bottom-up and top-down market sizing with a reconciliation between them.
``pricing``
    Van Westendorp price sensitivity and value-metric analysis.
``scoring``
    Weighted rubric scoring for ICP fit, deal qualification, and account health.
``fmt``
    Executive-readable number and table formatting.

Every CLI is invoked the same way::

    python3 -m gtmkit.<module> --help
"""

__version__ = "0.1.0"

__all__ = [
    "finance",
    "evidence",
    "expr",
    "valuecase",
    "funnel",
    "sizing",
    "pricing",
    "scoring",
    "fmt",
]
