"""The ``gtmkit`` command: one front door for every analysis.

Installed by ``pip`` as a console script, and also runnable as
``python3 -m gtmkit``::

    gtmkit                                    # list the analyses
    gtmkit valuecase case.json --format html --out case.html
    gtmkit init value-case --out case.json    # a starter spec to edit
    gtmkit --version

``gtmkit <analysis> [args...]`` hands the remaining arguments, unchanged, to
that module's ``main()``. ``gtmkit sizing --spec m.json`` and
``python3 -m gtmkit.sizing --spec m.json`` are the same command; the front door
adds no options of its own, so nothing can drift between the two spellings.
It passes only the name to print in usage and errors, the command as typed:
``gtmkit sizing``, or ``python3 -m gtmkit sizing``.
"""

from __future__ import annotations

import argparse
import difflib
import errno
import importlib
import os
import sys
from importlib import resources
from typing import Optional, Sequence, Tuple

from . import __version__

__all__ = ["ANALYSES", "STARTERS", "emit", "main", "starter_bytes"]

# (name, what it does, example arguments). The name is the module name, so
# every entry also runs as ``python3 -m gtmkit.<name>``.
ANALYSES: Tuple[Tuple[str, str, str], ...] = (
    (
        "valuecase",
        "Business case: NPV, payback, IRR, sensitivity, floor case, evidence grade",
        "case.json --format html --out case.html",
    ),
    (
        "scoring",
        "Weighted rubric scoring (ICP fit, qualification) with data coverage",
        "--rubric rubric.json --records accounts.csv",
    ),
    (
        "funnel",
        "Inverse funnel: from a revenue target back to the volume and spend it needs",
        '--target-revenue 4000000 --acv 45000 --stage "mql:0.25" --stage "opp:0.28"',
    ),
    (
        "sizing",
        "Market sizing bottom-up and top-down, reconciled against each other",
        "--spec market.json",
    ),
    (
        "pricing",
        "Van Westendorp price sensitivity from survey responses",
        "--responses survey.csv",
    ),
    (
        "qualify",
        "MEDDPICC for one deal, keeping confirmed answers apart from assumed ones",
        "deal.json",
    ),
    (
        "pipeline",
        "Pipeline coverage, weighted forecast, hygiene flags and concentration",
        "pipeline.csv --stages stages.json --target 1200000",
    ),
)

# (kind, template under gtmkit/templates/, what it is, the command to run next).
# Each template is a byte-for-byte copy of a shipped example; a test fails if
# a copy drifts from its source in examples/. {prog} is the front door as the
# user typed it, so a clone without pip is told to run `python3 -m gtmkit`.
STARTERS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "value-case",
        "value-case.json",
        "business-case spec for `{prog} valuecase`",
        "{prog} valuecase {path} --check",
    ),
    (
        "deal",
        "deal.json",
        "one deal's MEDDPICC answers for `{prog} qualify`",
        "{prog} qualify {path}",
    ),
    (
        "sizing",
        "sizing.json",
        "market-sizing spec for `{prog} sizing`",
        "{prog} sizing --spec {path}",
    ),
)


def emit(text: str, out: Optional[str]) -> int:
    """Print an analysis's output, or write it to ``out``; return the exit code.

    Every analysis's ``--out`` goes through here. A file that cannot be written
    (most often a directory name with a typo) is one line on stderr and exit
    status 1, as with ``gtmkit init``, rather than a traceback.
    """
    if not out:
        sys.stdout.write(text + "\n")
        return 0
    try:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError as exc:
        sys.stderr.write("error: cannot write %s: %s\n" % (out, exc.strerror or exc))
        return 1
    sys.stderr.write("wrote %s\n" % out)
    return 0


def starter_bytes(kind: str) -> bytes:
    """The starter spec for ``kind``, exactly as shipped."""
    for name, filename, _, _ in STARTERS:
        if name == kind:
            return (
                resources.files("gtmkit")
                .joinpath("templates")
                .joinpath(filename)
                .read_bytes()
            )
    raise KeyError(kind)


def _usage(prog: str = "gtmkit") -> str:
    """The listing, naming the front door ``prog`` as the user typed it."""
    width = max(len(name) for name in [*(n for n, _, _ in ANALYSES), "init"])
    lines = [
        "gtmkit %s: go-to-market analysis with explicit assumptions." % __version__,
        "",
        "usage: %s <analysis> [arguments...]" % prog,
        "       %s init <kind> [--out FILE] [--force]" % prog,
        "       %s --version" % prog,
        "",
        "Analyses:",
    ]
    for name, summary, example in ANALYSES:
        lines.append("  %s  %s" % (name.ljust(width), summary))
        lines.append("  %s  e.g. %s %s %s" % (" " * width, prog, name, example))
    lines.extend(
        [
            "",
            "Starter specs:",
            "  %s  Print a starter spec to edit: %s"
            % ("init".ljust(width), ", ".join(kind for kind, _, _, _ in STARTERS)),
            "  %s  e.g. %s init value-case --out case.json" % (" " * width, prog),
            "",
            "Each analysis takes its own arguments: %s <analysis> --help." % prog,
            "Every analysis also runs as python3 -m gtmkit.<analysis>.",
        ]
    )
    return "\n".join(lines) + "\n"


def _init(argv: Sequence[str], prog: str = "gtmkit") -> int:
    """``gtmkit init``; ``prog`` is the front door as typed, for every message."""
    command = "%s init" % prog
    kinds = "\n".join(
        "  %-11s %s" % (kind, summary.format(prog=prog))
        for kind, _, summary, _ in STARTERS
    )
    parser = argparse.ArgumentParser(
        prog=command,
        description=(
            "Print a starter spec to stdout, or write it with --out. Each "
            "starter is a complete worked example that validates as shipped; "
            "replace its numbers and sources with your own."
        ),
        epilog="kinds:\n" + kinds,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "kind", choices=[kind for kind, _, _, _ in STARTERS], help="which starter"
    )
    parser.add_argument(
        "--out", metavar="FILE", help="write the starter to FILE instead of stdout"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite FILE if it already exists"
    )
    args = parser.parse_args(list(argv))
    data = starter_bytes(args.kind)

    if args.out is None:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:  # a replaced stdout, e.g. under a test harness
            sys.stdout.write(data.decode("utf-8"))
        else:
            # Bytes, not text, so the starter arrives exactly as shipped
            # whatever the console encoding.
            sys.stdout.flush()
            buffer.write(data)
            buffer.flush()
        return 0

    if os.path.isdir(args.out):
        # No flag can write a file over a directory, so --force is not offered.
        sys.stderr.write(
            "%s: cannot write %s: %s\n" % (command, args.out, os.strerror(errno.EISDIR))
        )
        return 1
    try:
        # "x" fails atomically if the file exists, so a starter can never
        # silently replace a spec somebody has been editing.
        with open(args.out, "wb" if args.force else "xb") as handle:
            handle.write(data)
    except FileExistsError:
        sys.stderr.write(
            "%s: %s already exists; pass --force to overwrite it\n"
            % (command, args.out)
        )
        return 1
    except OSError as exc:
        sys.stderr.write(
            "%s: cannot write %s: %s\n" % (command, args.out, exc.strerror or exc)
        )
        return 1

    follow_up = next(cmd for kind, _, _, cmd in STARTERS if kind == args.kind)
    shown = '"%s"' % args.out if " " in args.out else args.out
    sys.stderr.write(
        "wrote %s. Edit it, then run: %s\n"
        % (args.out, follow_up.format(prog=prog, path=shown))
    )
    return 0


def main(argv: Optional[Sequence[str]] = None, prog: str = "gtmkit") -> int:
    """Run the front door. ``prog`` is how it was invoked: the listing, every
    error and the command ``init`` suggests next name it, so a clone without
    pip is never told to run a ``gtmkit`` it does not have."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        sys.stdout.write(_usage(prog))
        return 0
    if args[0] in ("-V", "--version"):
        sys.stdout.write("gtmkit %s\n" % __version__)
        return 0
    command, rest = args[0], args[1:]
    if command == "init":
        return _init(rest, prog)

    names = [name for name, _, _ in ANALYSES]
    if command not in names:
        if command.startswith("-"):
            problem = "expected an analysis name first, got %r." % command
        else:
            problem = "unknown analysis %r." % command
            close = difflib.get_close_matches(command, [*names, "init"], n=1)
            if close:
                problem += " Did you mean %r?" % close[0]
        sys.stderr.write(
            "%s: %s\nValid analyses: %s.\nAlso: init, --version, --help.\n"
            % (prog, problem, ", ".join(names))
        )
        return 2

    module = importlib.import_module("gtmkit.%s" % command)
    result = module.main(rest, prog="%s %s" % (prog, command))
    return 0 if result is None else int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
