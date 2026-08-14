"""Van Westendorp price sensitivity, computed properly and reported honestly.

The Price Sensitivity Meter asks four questions per respondent — at what price
is this *too cheap* (you'd doubt the quality), *cheap* (a bargain), *expensive*
(you'd have to think), and *too expensive* (you'd never buy) — then intersects
the resulting cumulative curves::

    python3 -m gtmkit.pricing --responses examples/pricing/responses.csv

What this implementation does that most spreadsheet versions do not:

* **It validates monotonicity per respondent.** A response where "cheap" is
  higher than "expensive" is not data, it is a person who misread the question.
  Those rows are dropped and counted, rather than silently distorting every
  curve. In real survey data this is routinely 5-15% of responses, and leaving
  them in is the single most common reason two analysts get different answers
  from the same file.
* **It reports the sample size next to every number.** A Van Westendorp run on
  22 responses produces four decimal places of precision and none of the
  reliability, and the output says so.

A caution worth internalizing before you use the output: Van Westendorp
measures *stated* willingness to pay, in the absence of a competitor, a budget
cycle, or a procurement team. It tells you where the acceptable band is, not
what to charge. Treat the optimal price point as the center of a conversation,
not the answer to one.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .fmt import fmt_count, fmt_currency, fmt_pct, table

__all__ = ["PricingError", "analyze", "main"]

_COLUMNS = ("too_cheap", "cheap", "expensive", "too_expensive")


class PricingError(ValueError):
    """Raised for unusable response data."""


class Response:
    __slots__ = _COLUMNS

    def __init__(self, too_cheap, cheap, expensive, too_expensive):
        self.too_cheap = too_cheap
        self.cheap = cheap
        self.expensive = expensive
        self.too_expensive = too_expensive

    def is_monotonic(self) -> bool:
        return (
            self.too_cheap <= self.cheap <= self.expensive <= self.too_expensive
        )


def parse_responses(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Response], List[Dict[str, Any]]]:
    """Split raw rows into valid responses and rejected rows with reasons."""
    valid: List[Response] = []
    rejected: List[Dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        missing = [c for c in _COLUMNS if c not in row]
        if missing:
            raise PricingError(
                "row %d is missing column(s): %s. Required columns are: %s"
                % (index, ", ".join(missing), ", ".join(_COLUMNS))
            )
        try:
            values = [
                float(str(row[c]).replace(",", "").replace("$", "").strip())
                for c in _COLUMNS
            ]
        except (TypeError, ValueError):
            rejected.append(
                {"row": index, "reason": "non-numeric price", "data": dict(row)}
            )
            continue
        if any(v < 0 for v in values):
            rejected.append(
                {"row": index, "reason": "negative price", "data": dict(row)}
            )
            continue

        response = Response(*values)
        if not response.is_monotonic():
            rejected.append(
                {
                    "row": index,
                    "reason": (
                        "prices are not in ascending order "
                        "(too_cheap <= cheap <= expensive <= too_expensive); "
                        "the respondent most likely misread the questions"
                    ),
                    "data": dict(row),
                }
            )
            continue
        valid.append(response)

    return valid, rejected


def _curves(responses: Sequence[Response], grid: Sequence[float]) -> Dict[str, List[float]]:
    """Cumulative share of respondents at each grid price.

    ``too_cheap`` and ``cheap`` are descending curves (share who consider the
    product at least this cheap at price p); ``expensive`` and ``too_expensive``
    are ascending.
    """
    n = float(len(responses))
    return {
        "too_cheap": [
            sum(1 for r in responses if r.too_cheap >= p) / n for p in grid
        ],
        "cheap": [sum(1 for r in responses if r.cheap >= p) / n for p in grid],
        "expensive": [
            sum(1 for r in responses if r.expensive <= p) / n for p in grid
        ],
        "too_expensive": [
            sum(1 for r in responses if r.too_expensive <= p) / n for p in grid
        ],
    }


def _intersect(
    grid: Sequence[float], a: Sequence[float], b: Sequence[float]
) -> Optional[float]:
    """First price where curve ``a`` crosses curve ``b``, linearly interpolated."""
    for i in range(len(grid) - 1):
        d0 = a[i] - b[i]
        d1 = a[i + 1] - b[i + 1]
        if d0 == 0:
            return grid[i]
        if d0 * d1 < 0:
            span = d0 - d1
            if span == 0:
                return grid[i]
            fraction = d0 / span
            return grid[i] + fraction * (grid[i + 1] - grid[i])
    return None


def analyze(rows: Sequence[Dict[str, Any]], currency: str = "USD") -> Dict[str, Any]:
    """Run the full price sensitivity analysis."""
    responses, rejected = parse_responses(rows)
    if len(responses) < 2:
        raise PricingError(
            "only %d usable response(s) after validation. Van Westendorp needs "
            "a real sample — below roughly 50 responses the intersections move "
            "several percent with every added row." % len(responses)
        )

    prices = sorted(
        {
            value
            for r in responses
            for value in (r.too_cheap, r.cheap, r.expensive, r.too_expensive)
        }
    )
    # Densify the grid so intersections are not snapped to observed values only.
    grid: List[float] = []
    for i, price in enumerate(prices):
        grid.append(price)
        if i + 1 < len(prices):
            step = (prices[i + 1] - price) / 4.0
            grid.extend(price + step * k for k in range(1, 4))
    curves = _curves(responses, grid)

    pmc = _intersect(grid, curves["too_cheap"], curves["expensive"])
    pme = _intersect(grid, curves["cheap"], curves["too_expensive"])
    opp = _intersect(grid, curves["too_cheap"], curves["too_expensive"])
    ipp = _intersect(grid, curves["cheap"], curves["expensive"])

    n = len(responses)
    total = n + len(rejected)
    reliability = (
        "strong" if n >= 200 else "usable" if n >= 50 else "indicative only"
    )

    return {
        "currency": currency,
        "sample": {
            "submitted": total,
            "usable": n,
            "rejected": len(rejected),
            "rejection_rate": (len(rejected) / total) if total else 0.0,
            "reliability": reliability,
            "reliability_note": _reliability_note(n, reliability),
        },
        "rejected_rows": rejected,
        "points": {
            "point_of_marginal_cheapness": pmc,
            "optimal_price_point": opp,
            "indifference_price_point": ipp,
            "point_of_marginal_expensiveness": pme,
        },
        "acceptable_range": {"low": pmc, "high": pme},
        "range_width_pct": (
            ((pme - pmc) / pmc) if (pmc and pme and pmc > 0) else None
        ),
        "interpretation": _interpretation(pmc, opp, ipp, pme, currency),
    }


def _reliability_note(n: int, reliability: str) -> str:
    if reliability == "strong":
        return (
            "%d usable responses. Intersections are stable; treat the range as "
            "a real finding." % n
        )
    if reliability == "usable":
        return (
            "%d usable responses. Directionally sound, but expect the "
            "intersections to move a few percent with more data. Report the "
            "range, not the point." % n
        )
    return (
        "%d usable responses — below the threshold where these intersections "
        "are stable. Use this to shape the next conversation, not to set a "
        "price. Every number below will move with the next twenty responses."
        % n
    )


def _interpretation(
    pmc: Optional[float],
    opp: Optional[float],
    ipp: Optional[float],
    pme: Optional[float],
    currency: str,
) -> str:
    if pmc is None or pme is None:
        return (
            "The curves do not intersect cleanly, which usually means the "
            "sample holds two distinct segments with different price "
            "expectations. Split the responses by segment and run each "
            "separately — a blended curve across two populations describes "
            "neither."
        )
    parts = [
        "The acceptable band runs from %s to %s."
        % (fmt_currency(pmc, currency), fmt_currency(pme, currency))
    ]
    if opp is not None:
        parts.append(
            "The optimal price point — where the fewest people reject the "
            "product on price in either direction — is %s."
            % fmt_currency(opp, currency)
        )
    if ipp is not None and opp is not None:
        if ipp > opp:
            parts.append(
                "Indifference sits above the optimal point (%s vs %s), which "
                "typically signals a brand or category where buyers read price "
                "as a quality signal. There is room to price toward the upper "
                "half of the band." % (fmt_currency(ipp, currency), fmt_currency(opp, currency))
            )
        else:
            parts.append(
                "Indifference sits at or below the optimal point, which "
                "suggests a price-sensitive commodity dynamic. Pricing near "
                "the top of the band will cost volume."
            )
    parts.append(
        "None of this accounts for competitive alternatives or budget cycles. "
        "Use the band to bound the decision, then choose within it based on "
        "positioning."
    )
    return " ".join(parts)


def to_markdown(result: Dict[str, Any]) -> str:
    cur = result["currency"]
    sample = result["sample"]
    points = result["points"]
    lines: List[str] = []
    lines.append("# Price sensitivity (Van Westendorp)")
    lines.append("")
    lines.append(
        "%s of %s submitted responses were usable (%s rejected). Reliability: "
        "**%s**."
        % (
            fmt_count(sample["usable"]),
            fmt_count(sample["submitted"]),
            fmt_count(sample["rejected"]),
            sample["reliability"],
        )
    )
    lines.append("")
    lines.append(sample["reliability_note"])
    lines.append("")

    rows = [
        [
            "Point of marginal cheapness",
            fmt_currency(points["point_of_marginal_cheapness"], cur),
            "Below this, buyers start doubting quality",
        ],
        [
            "Optimal price point",
            fmt_currency(points["optimal_price_point"], cur),
            "Fewest rejections in either direction",
        ],
        [
            "Indifference price point",
            fmt_currency(points["indifference_price_point"], cur),
            "Equal shares call it cheap and expensive",
        ],
        [
            "Point of marginal expensiveness",
            fmt_currency(points["point_of_marginal_expensiveness"], cur),
            "Above this, resistance rises sharply",
        ],
    ]
    lines.append(table(["Point", "Price", "What it means"], rows))
    lines.append("")

    lines.append("## Interpretation")
    lines.append("")
    lines.append(result["interpretation"])
    lines.append("")

    if result["rejected_rows"]:
        lines.append("## Rejected responses")
        lines.append("")
        lines.append(
            "These rows were excluded. Leaving them in would have shifted every "
            "intersection above, so they are listed rather than dropped "
            "silently."
        )
        lines.append("")
        reject_rows = [
            [str(item["row"]), item["reason"]]
            for item in result["rejected_rows"][:25]
        ]
        lines.append(table(["Row", "Reason"], reject_rows))
        if len(result["rejected_rows"]) > 25:
            lines.append("")
            lines.append(
                "_...and %d more._" % (len(result["rejected_rows"]) - 25)
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
        prog="python3 -m gtmkit.pricing",
        description=(
            "Van Westendorp price sensitivity from a CSV of survey responses."
        ),
    )
    parser.add_argument(
        "--responses",
        required=True,
        help="CSV with columns: too_cheap, cheap, expensive, too_expensive",
    )
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        with open(args.responses, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError:
        sys.stderr.write("no such file: %s\n" % args.responses)
        return 2

    if not rows:
        sys.stderr.write("no rows found in %s\n" % args.responses)
        return 2

    try:
        result = analyze(rows, args.currency)
    except PricingError as exc:
        sys.stderr.write("pricing error: %s\n" % exc)
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
