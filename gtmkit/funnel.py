"""Inverse funnel math: work backwards from a target to what it costs.

Most campaign plans are written forwards — "we'll spend $200k, here's what we
hope happens" — which makes them impossible to falsify and easy to approve.
Working backwards from the number the business actually committed to produces a
plan that either closes or visibly doesn't::

    python3 -m gtmkit.funnel --target-revenue 4000000 --acv 45000 \\
        --stage "impression:0.002" --stage "visit:0.08" --stage "mql:0.25" \\
        --stage "sql:0.35" --stage "opp:0.28" --cpm 22

The output states the required volume at every stage, the implied spend, the
blended CAC, and — the part that usually ends the meeting — whether the top of
funnel required is larger than the addressable audience.

Stage conversion rates are given as ``name:rate`` where ``rate`` is the
probability of moving from that stage to the next one. The final stage converts
to closed-won.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .fmt import fmt_count, fmt_currency, fmt_pct, table

__all__ = ["FunnelError", "Stage", "main", "plan"]


class FunnelError(ValueError):
    """Raised for funnel definitions that cannot produce an honest plan."""


class Stage:
    __slots__ = ("name", "rate")

    def __init__(self, name: str, rate: float) -> None:
        self.name = name
        self.rate = rate


def parse_stage(text: str) -> Stage:
    """Parse a ``name:rate`` stage definition."""
    if ":" not in text:
        raise FunnelError("stage %r must look like 'name:rate', e.g. 'mql:0.25'" % text)
    name, _, raw_rate = text.partition(":")
    name = name.strip()
    if not name:
        raise FunnelError("stage %r has an empty name" % text)
    try:
        rate = float(raw_rate)
    except ValueError:
        raise FunnelError("stage %r has a non-numeric rate %r" % (text, raw_rate))
    if not (0 < rate <= 1):
        raise FunnelError(
            "stage %r has rate %r; conversion rates are decimals above 0 and "
            "at most 1 (25%% is 0.25, not 25)" % (name, rate)
        )
    return Stage(name, rate)


def plan(
    target_revenue: float,
    acv: float,
    stages: Sequence[Stage],
    cost_per_unit: Optional[float] = None,
    cost_stage: Optional[str] = None,
    win_rate: float = 1.0,
    audience_ceiling: Optional[float] = None,
    sales_cycle_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute the volume required at each stage to hit ``target_revenue``.

    ``cost_per_unit`` is the cost of one unit at ``cost_stage`` — a CPM is
    entered as cost-per-impression (``cpm / 1000``) at the impression stage, a
    cost-per-click at the click stage, and so on. Keeping it general means the
    same function serves paid media, outbound sequences, and event programs.

    ``win_rate`` applies to the final stage's conversion to closed-won, so a
    funnel can be described in terms of opportunity creation and have the
    close step modeled separately — which is how most teams actually track it.
    """
    if acv <= 0:
        raise FunnelError("acv must be positive")
    if target_revenue <= 0:
        raise FunnelError("target_revenue must be positive")
    if not stages:
        raise FunnelError(
            "define at least one stage; a funnel with no stages is just a wish"
        )
    if not (0 < win_rate <= 1):
        raise FunnelError("win_rate must be above 0 and at most 1")

    deals_needed = target_revenue / acv

    # Walk backwards. Each stage's required volume is the next stage's volume
    # divided by this stage's conversion rate.
    required: List[Tuple[str, float]] = []
    downstream = deals_needed / win_rate
    for stage in reversed(stages):
        volume = downstream / stage.rate
        required.append((stage.name, volume))
        downstream = volume
    required.reverse()

    top_stage_name, top_volume = required[0]

    cumulative_rate = 1.0
    for stage in stages:
        cumulative_rate *= stage.rate
    cumulative_rate *= win_rate

    spend = None
    cac = None
    cost_stage_volume = None
    if cost_per_unit is not None:
        target_stage = cost_stage or top_stage_name
        matches = [vol for name, vol in required if name == target_stage]
        if not matches:
            raise FunnelError(
                "cost_stage %r is not one of the defined stages: %s"
                % (target_stage, ", ".join(name for name, _ in required))
            )
        cost_stage_volume = matches[0]
        spend = cost_stage_volume * cost_per_unit
        cac = spend / deals_needed if deals_needed else None

    feasible = True
    ceiling_note = None
    if audience_ceiling is not None:
        feasible = top_volume <= audience_ceiling
        if not feasible:
            ceiling_note = (
                "This plan requires %s at the %s stage against an addressable "
                "ceiling of %s — it needs %.1fx the audience that exists. The "
                "target is not reachable through this channel mix at these "
                "conversion rates; either the rates have to improve, the ACV "
                "has to rise, or the target has to come down."
                % (
                    fmt_count(top_volume),
                    top_stage_name,
                    fmt_count(audience_ceiling),
                    top_volume / audience_ceiling,
                )
            )

    return {
        "target_revenue": target_revenue,
        "acv": acv,
        "deals_needed": deals_needed,
        "win_rate": win_rate,
        "end_to_end_conversion": cumulative_rate,
        "stages": [
            {
                "name": name,
                "required_volume": volume,
                "rate_to_next": stages[i].rate,
            }
            for i, (name, volume) in enumerate(required)
        ],
        "top_of_funnel_stage": top_stage_name,
        "top_of_funnel_volume": top_volume,
        "cost_per_unit": cost_per_unit,
        "cost_stage": cost_stage or (top_stage_name if cost_per_unit else None),
        "cost_stage_volume": cost_stage_volume,
        "spend": spend,
        "cac": cac,
        "ltv_cac_note": (
            "CAC of %s against an ACV of %s is a payback of %s of first-year "
            "contract value. Compare against gross margin before calling this "
            "efficient." % (fmt_currency(cac), fmt_currency(acv), fmt_pct(cac / acv))
            if cac
            else None
        ),
        "sales_cycle_days": sales_cycle_days,
        "pipeline_start_by": (
            "Work must start %d days before the revenue is due to land, so a "
            "quarter-end number requires the top of funnel to be filled in the "
            "prior quarter." % sales_cycle_days
            if sales_cycle_days
            else None
        ),
        "feasible": feasible,
        "ceiling_note": ceiling_note,
    }


def to_markdown(result: Dict[str, Any], currency: str = "USD") -> str:
    lines: List[str] = []
    lines.append("# Funnel plan")
    lines.append("")
    lines.append(
        "To land %s at an ACV of %s, %s deals must close. Working backwards "
        "from there:"
        % (
            fmt_currency(result["target_revenue"], currency),
            fmt_currency(result["acv"], currency),
            fmt_count(result["deals_needed"]),
        )
    )
    lines.append("")

    rows = []
    for stage in result["stages"]:
        rows.append(
            [
                stage["name"],
                fmt_count(stage["required_volume"]),
                fmt_pct(stage["rate_to_next"]),
            ]
        )
    rows.append(["closed-won", fmt_count(result["deals_needed"]), "—"])
    lines.append(table(["Stage", "Required volume", "Converts at"], rows))
    lines.append("")

    lines.append(
        "End-to-end conversion is %s — one closed deal for every %s at the "
        "top."
        % (
            fmt_pct(result["end_to_end_conversion"]),
            fmt_count(1 / result["end_to_end_conversion"])
            if result["end_to_end_conversion"]
            else "n/a",
        )
    )
    lines.append("")

    if result["spend"] is not None:
        lines.append("## Cost")
        lines.append("")
        lines.append(
            "- Required spend: **%s** (%s at %s each)"
            % (
                fmt_currency(result["spend"], currency),
                fmt_count(result["cost_stage_volume"]),
                fmt_currency(result["cost_per_unit"], currency, precise=True),
            )
        )
        lines.append("- Blended CAC: **%s**" % fmt_currency(result["cac"], currency))
        if result["ltv_cac_note"]:
            lines.append("- %s" % result["ltv_cac_note"])
        lines.append("")

    if result["pipeline_start_by"]:
        lines.append("## Timing")
        lines.append("")
        lines.append(result["pipeline_start_by"])
        lines.append("")

    lines.append("## Feasibility")
    lines.append("")
    if result["ceiling_note"]:
        lines.append("**Not reachable as specified.** %s" % result["ceiling_note"])
    elif result["feasible"]:
        lines.append(
            "No audience ceiling was supplied, so feasibility is unverified. "
            "Add `--audience-ceiling` with the real size of the reachable "
            "segment — a plan that requires more audience than exists is the "
            "most common way a credible-looking campaign fails."
            if result.get("audience_ceiling") is None
            else "The plan fits within the stated addressable audience."
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
        prog="python3 -m gtmkit.funnel",
        description=(
            "Work backwards from a revenue target to the funnel volume and "
            "spend it requires."
        ),
    )
    parser.add_argument("--target-revenue", type=float, required=True)
    parser.add_argument(
        "--acv", type=float, required=True, help="average contract value"
    )
    parser.add_argument(
        "--stage",
        action="append",
        required=True,
        metavar="NAME:RATE",
        help="stage and its conversion rate to the next stage, repeatable",
    )
    parser.add_argument("--win-rate", type=float, default=1.0)
    parser.add_argument(
        "--cost-per-unit",
        type=float,
        help="cost of one unit at --cost-stage",
    )
    parser.add_argument(
        "--cpm",
        type=float,
        help="cost per thousand impressions; shorthand for --cost-per-unit cpm/1000",
    )
    parser.add_argument("--cost-stage", help="stage the cost applies to")
    parser.add_argument("--audience-ceiling", type=float)
    parser.add_argument("--sales-cycle-days", type=int)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    cost_per_unit = args.cost_per_unit
    if args.cpm is not None:
        if cost_per_unit is not None:
            sys.stderr.write("use either --cpm or --cost-per-unit, not both\n")
            return 2
        cost_per_unit = args.cpm / 1000.0

    try:
        stages = [parse_stage(text) for text in args.stage]
        result = plan(
            target_revenue=args.target_revenue,
            acv=args.acv,
            stages=stages,
            cost_per_unit=cost_per_unit,
            cost_stage=args.cost_stage,
            win_rate=args.win_rate,
            audience_ceiling=args.audience_ceiling,
            sales_cycle_days=args.sales_cycle_days,
        )
    except FunnelError as exc:
        sys.stderr.write("funnel error: %s\n" % exc)
        return 2

    result["audience_ceiling"] = args.audience_ceiling
    if args.format == "json":
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(to_markdown(result, args.currency) + "\n")
    return 0 if result["feasible"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
