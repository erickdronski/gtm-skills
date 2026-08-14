"""Market sizing that reconciles bottom-up against top-down.

A TAM number on its own is worthless — anyone can produce one, and everyone
produces a different one. What carries weight in a board room or an investment
memo is *two independent estimates and an explanation of the gap between them*.
That is what this module produces::

    python3 -m gtmkit.sizing --spec examples/sizing/dev-tools.json

Bottom-up multiplies countable units by price. Top-down takes a published
market total and carves it down by share. When they land within a factor of two
of each other, you have a defensible range. When they differ by 10x, one of them
encodes a wrong assumption and finding out which is the actual work — so the
tool reports the ratio prominently rather than quietly averaging them, which is
the standard way this analysis gets fudged.

TAM / SAM / SOM are defined here as:

``TAM``
    Every entity that has the problem, at full price. Not "the market for
    software" — the market for *this* product's job.
``SAM``
    The slice TAM you can actually sell to today: right segment, right
    geography, right compliance posture, right integrations.
``SOM``
    The slice of SAM you can realistically win in the planning horizon given
    the sales capacity you actually have. This is the only one of the three
    that should ever appear in a quota model.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .evidence import EvidenceError, validate_input
from .fmt import fmt_count, fmt_currency, fmt_pct, table

__all__ = ["SizingError", "size", "main"]


class SizingError(ValueError):
    """Raised for sizing specs that cannot produce an honest estimate."""


def size(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Compute bottom-up and top-down estimates and reconcile them.

    Spec shape::

        {
          "name": "Agent observability — North America",
          "currency": "USD",
          "bottom_up": {
            "units": {"value": 48000, "confidence": "fact",
                      "source": "Companies with >200 engineers, Crunchbase
                                 export 2026-07"},
            "attach_rate": {"value": 0.35, "confidence": "assumption",
                            "source": "...", "low": 0.2, "high": 0.5},
            "annual_price": {"value": 24000, "confidence": "fact",
                             "source": "Published list price, 2026 pricing page"}
          },
          "top_down": {
            "market_total": {"value": 4200000000, "confidence": "fact",
                             "source": "..."},
            "share": {"value": 0.09, "confidence": "assumption",
                      "source": "...", "low": 0.04, "high": 0.15}
          },
          "sam_share": 0.42,
          "som_share": 0.06
        }
    """
    if not isinstance(spec, Mapping):
        raise SizingError("spec must be a JSON object")

    name = str(spec.get("name") or "").strip()
    if not name:
        raise SizingError("spec needs a 'name'")
    currency = str(spec.get("currency") or "USD").upper()

    bottom = _bottom_up(spec.get("bottom_up"))
    top = _top_down(spec.get("top_down"))

    if bottom is None and top is None:
        raise SizingError(
            "spec needs at least one of 'bottom_up' or 'top_down'. Both is "
            "the point — a single estimate has nothing to check it against."
        )

    reconciliation = _reconcile(bottom, top, currency)

    tam = bottom["tam"] if bottom else top["tam"]
    sam_share = _fraction(spec.get("sam_share"), "sam_share", default=None)
    som_share = _fraction(spec.get("som_share"), "som_share", default=None)

    sam = tam * sam_share if sam_share is not None else None
    som = (sam if sam is not None else tam) * som_share if som_share is not None else None

    return {
        "name": name,
        "currency": currency,
        "bottom_up": bottom,
        "top_down": top,
        "reconciliation": reconciliation,
        "tam": tam,
        "sam": sam,
        "sam_share": sam_share,
        "som": som,
        "som_share": som_share,
        "som_note": (
            "SOM is %s. If this number does not divide cleanly into the quota "
            "carried by the reps you actually have, one of the two is wrong."
            % fmt_currency(som, currency)
            if som is not None
            else "No SOM computed — add 'som_share' to make this plannable."
        ),
    }


def _fraction(value: Any, field: str, default: Optional[float] = None):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SizingError("'%s' must be a number between 0 and 1" % field)
    if not (0 < value <= 1):
        raise SizingError(
            "'%s' is %r; it must be a decimal share above 0 and at most 1 "
            "(42%% is 0.42, not 42)" % (field, value)
        )
    return float(value)


def _bottom_up(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise SizingError("'bottom_up' must be an object")

    required = ("units", "annual_price")
    for field in required:
        if field not in raw:
            raise SizingError("'bottom_up' needs '%s'" % field)

    inputs = {}
    for key, value in raw.items():
        try:
            inputs[key] = validate_input(key, value)
        except EvidenceError as exc:
            raise SizingError("bottom_up: %s" % exc) from exc

    units = inputs["units"].value
    price = inputs["annual_price"].value
    attach = inputs["attach_rate"].value if "attach_rate" in inputs else 1.0

    def compute(u: float, a: float, p: float) -> float:
        return u * a * p

    low = compute(
        inputs["units"].range[0],
        inputs["attach_rate"].range[0] if "attach_rate" in inputs else 1.0,
        inputs["annual_price"].range[0],
    )
    high = compute(
        inputs["units"].range[1],
        inputs["attach_rate"].range[1] if "attach_rate" in inputs else 1.0,
        inputs["annual_price"].range[1],
    )

    return {
        "tam": compute(units, attach, price),
        "low": low,
        "high": high,
        "units": units,
        "attach_rate": attach,
        "annual_price": price,
        "inputs": {k: v.to_dict() for k, v in inputs.items()},
        "method": (
            "%s addressable units x %s attach x %s annual price"
            % (fmt_count(units), fmt_pct(attach), fmt_currency(price))
        ),
    }


def _top_down(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise SizingError("'top_down' must be an object")
    for field in ("market_total", "share"):
        if field not in raw:
            raise SizingError("'top_down' needs '%s'" % field)

    inputs = {}
    for key, value in raw.items():
        try:
            inputs[key] = validate_input(key, value)
        except EvidenceError as exc:
            raise SizingError("top_down: %s" % exc) from exc

    total = inputs["market_total"].value
    share = inputs["share"].value
    return {
        "tam": total * share,
        "low": inputs["market_total"].range[0] * inputs["share"].range[0],
        "high": inputs["market_total"].range[1] * inputs["share"].range[1],
        "market_total": total,
        "share": share,
        "inputs": {k: v.to_dict() for k, v in inputs.items()},
        "method": (
            "%s published market x %s relevant share"
            % (fmt_currency(total), fmt_pct(share))
        ),
    }


def _reconcile(
    bottom: Optional[Dict[str, Any]],
    top: Optional[Dict[str, Any]],
    currency: str,
) -> Dict[str, Any]:
    if bottom is None or top is None:
        return {
            "possible": False,
            "verdict": (
                "Only one method was supplied, so nothing checks it. A single "
                "market size estimate is an assertion; two that agree are "
                "evidence. Add the missing method before this number leaves "
                "the building."
            ),
        }

    a, b = bottom["tam"], top["tam"]
    if min(a, b) <= 0:
        ratio = None
    else:
        ratio = max(a, b) / min(a, b)

    if ratio is None:
        verdict = "One method produced a non-positive size; check the inputs."
        agrees = False
    elif ratio <= 2.0:
        agrees = True
        verdict = (
            "The two methods agree within %.1fx. Report the range %s to %s and "
            "state both methods — a reconciled range is far more persuasive "
            "than either point estimate alone."
            % (
                ratio,
                fmt_currency(min(a, b), currency),
                fmt_currency(max(a, b), currency),
            )
        )
    elif ratio <= 5.0:
        agrees = False
        verdict = (
            "The methods differ by %.1fx. That gap is usually a definition "
            "mismatch — most often the top-down market includes adjacent "
            "categories the bottom-up unit count excludes. Reconcile the "
            "definitions before using either number." % ratio
        )
    else:
        agrees = False
        verdict = (
            "The methods differ by %.0fx. One of them encodes a wrong "
            "assumption and averaging them would hide it. Find the error: "
            "check whether the unit count is really the set of buyers, and "
            "whether the published market total measures the same job your "
            "product does." % ratio
        )

    return {
        "possible": True,
        "bottom_up_tam": a,
        "top_down_tam": b,
        "ratio": ratio,
        "agrees": agrees,
        "verdict": verdict,
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    cur = result["currency"]
    lines: List[str] = []
    lines.append("# Market sizing — %s" % result["name"])
    lines.append("")

    rows = []
    if result["bottom_up"]:
        rows.append(
            [
                "Bottom-up",
                fmt_currency(result["bottom_up"]["tam"], cur),
                "%s – %s"
                % (
                    fmt_currency(result["bottom_up"]["low"], cur),
                    fmt_currency(result["bottom_up"]["high"], cur),
                ),
                result["bottom_up"]["method"],
            ]
        )
    if result["top_down"]:
        rows.append(
            [
                "Top-down",
                fmt_currency(result["top_down"]["tam"], cur),
                "%s – %s"
                % (
                    fmt_currency(result["top_down"]["low"], cur),
                    fmt_currency(result["top_down"]["high"], cur),
                ),
                result["top_down"]["method"],
            ]
        )
    lines.append(table(["Method", "TAM", "Range", "How it was built"], rows))
    lines.append("")

    lines.append("## Reconciliation")
    lines.append("")
    lines.append(result["reconciliation"]["verdict"])
    lines.append("")

    lines.append("## TAM / SAM / SOM")
    lines.append("")
    tam_rows = [["TAM", fmt_currency(result["tam"], cur), "Everyone with the problem"]]
    if result["sam"] is not None:
        tam_rows.append(
            [
                "SAM",
                fmt_currency(result["sam"], cur),
                "%s of TAM — the slice sellable today"
                % fmt_pct(result["sam_share"]),
            ]
        )
    if result["som"] is not None:
        tam_rows.append(
            [
                "SOM",
                fmt_currency(result["som"], cur),
                "%s of SAM — winnable in the planning horizon"
                % fmt_pct(result["som_share"]),
            ]
        )
    lines.append(table(["Layer", "Value", "Definition"], tam_rows))
    lines.append("")
    lines.append(result["som_note"])
    lines.append("")

    lines.append("## Assumption ledger")
    lines.append("")
    ledger_rows = []
    for method_name, method in (
        ("Bottom-up", result["bottom_up"]),
        ("Top-down", result["top_down"]),
    ):
        if not method:
            continue
        for key, value in method["inputs"].items():
            ledger_rows.append(
                [
                    method_name,
                    key,
                    fmt_count(value["value"])
                    if value["value"] >= 1000
                    else value["value"],
                    value["confidence"],
                    value["source"],
                ]
            )
    lines.append(
        table(["Method", "Input", "Value", "Confidence", "Source"], ledger_rows)
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by [gtm-skills](https://github.com/erickdronski/gtm-skills)._"
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m gtmkit.sizing",
        description=(
            "Size a market bottom-up and top-down, and reconcile the two."
        ),
    )
    parser.add_argument("--spec", required=True, help="path to the sizing JSON spec")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        with open(args.spec, "r", encoding="utf-8") as handle:
            spec = json.load(handle)
        result = size(spec)
    except FileNotFoundError:
        sys.stderr.write("no such spec file: %s\n" % args.spec)
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write("%s is not valid JSON: %s\n" % (args.spec, exc))
        return 2
    except (SizingError, EvidenceError) as exc:
        sys.stderr.write("sizing error: %s\n" % exc)
        return 2

    output = (
        json.dumps(result, indent=2)
        if args.format == "json"
        else to_markdown(result)
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
        sys.stderr.write("wrote %s\n" % args.out)
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
