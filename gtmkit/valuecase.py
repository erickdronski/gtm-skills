"""Build an auditable business case from a declarative spec.

Run it directly::

    python3 -m gtmkit.valuecase path/to/case.json
    python3 -m gtmkit.valuecase path/to/case.json --format json
    python3 -m gtmkit.valuecase path/to/case.json --out case.md

The spec format is documented in ``skills/value-case/references/spec-format.md``
and validated by :func:`validate_spec`. The short version::

    {
      "name": "Support deflection — Northwind",
      "currency": "USD",
      "horizon_years": 3,
      "discount_rate_annual": 0.12,
      "drivers": [{
        "id": "deflection",
        "label": "Deflected support tickets",
        "formula": "tickets_per_year * deflection_rate * cost_per_ticket",
        "inputs": {
          "tickets_per_year": {"value": 120000, "confidence": "fact",
                               "source": "Zendesk export, FY25 full year"},
          "deflection_rate": {"value": 0.22, "confidence": "assumption",
                              "source": "Observed 18-26% at three reference
                                         customers of similar ticket mix",
                              "low": 0.12, "high": 0.28},
          "cost_per_ticket": {"value": 6.50, "confidence": "inference",
                              "source": "Fully loaded agent cost $78k / 12000
                                         tickets handled per agent-year"}
        },
        "ramp": [0.4, 1.0, 1.0],
        "realization": 0.85
      }],
      "costs": [
        {"id": "subscription", "label": "Subscription",
         "schedule": [0, 180000, 180000, 180000]},
        {"id": "implementation", "label": "Implementation and change management",
         "schedule": [250000, 0, 0, 0]}
      ]
    }

Design choices worth knowing about:

* **Period 0 is today.** Implementation cost lands there, undiscounted. Benefits
  start in period 1. Schedules therefore have ``horizon_years + 1`` entries.
* **Ramp is separate from realization.** Ramp is *when* value arrives (adoption
  curve); realization is a flat haircut for the gap between modeled and captured
  value. Conflating them hides which one you are actually arguing about.
* **Sensitivity is one-at-a-time.** Each ranged input is swung to its low and
  high while everything else holds at base. This produces a tornado, which is
  what reviewers expect, and it deliberately does not compound worst cases —
  a simultaneous all-inputs-low scenario is reported separately as the floor.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import finance
from .evidence import (
    EvidenceError,
    Input,
    grade_evidence,
    validate_input,
    weakest_confidence,
)
from .expr import ExpressionError, evaluate, referenced_names
from .fmt import fmt_currency, fmt_multiple, fmt_periods, fmt_pct, table

__all__ = [
    "SpecError",
    "ValueCase",
    "load_spec",
    "validate_spec",
    "build",
    "main",
]


class SpecError(ValueError):
    """Raised when a business-case spec is structurally invalid."""


class Driver:
    """One benefit stream: a formula, its declared inputs, and its ramp."""

    __slots__ = ("id", "label", "formula", "inputs", "ramp", "realization", "note")

    def __init__(
        self,
        id: str,
        label: str,
        formula: str,
        inputs: Dict[str, Input],
        ramp: List[float],
        realization: float,
        note: Optional[str] = None,
    ) -> None:
        self.id = id
        self.label = label
        self.formula = formula
        self.inputs = inputs
        self.ramp = ramp
        self.realization = realization
        self.note = note

    def annual_value(self, overrides: Optional[Mapping[str, float]] = None) -> float:
        """Full run-rate annual value, before ramp and realization."""
        variables = {name: inp.value for name, inp in self.inputs.items()}
        if overrides:
            variables.update(overrides)
        return evaluate(self.formula, variables)

    def schedule(
        self, horizon: int, overrides: Optional[Mapping[str, float]] = None
    ) -> List[float]:
        """Benefit by period, index 0 = today (always zero for benefits)."""
        run_rate = self.annual_value(overrides)
        out = [0.0]
        for year in range(horizon):
            ramp = self.ramp[year] if year < len(self.ramp) else self.ramp[-1]
            out.append(run_rate * ramp * self.realization)
        return out

    @property
    def confidence(self) -> str:
        """Weakest confidence among inputs — the chain's real strength."""
        return weakest_confidence(inp.confidence for inp in self.inputs.values())

    def input_shares(self) -> Dict[str, float]:
        """Attribute the driver's value across its inputs, summing to 1.

        Uses proportional sensitivity: nudge each input by 1% of its own
        magnitude and measure how much the driver's value moves. Normalizing
        those movements gives each input a defensible share of the result.

        Why this and not something simpler: a driver is a chain, and grading it
        by its weakest link alone makes every multi-input driver read as pure
        assumption, which is both discouraging and useless for prioritizing.
        For the common multiplicative shape ``a * b * c`` this method assigns
        each input exactly one third — which is the intuitively right answer,
        and is what makes the resulting evidence grade discriminate between a
        case with one soft input and a case that is soft all the way through.

        Inputs the formula is genuinely insensitive to get a near-zero share,
        which is correct: an assumption that does not move the answer should
        not drag down the grade.
        """
        base = self.annual_value()
        movements: Dict[str, float] = {}
        for name, inp in self.inputs.items():
            step = abs(inp.value) * 0.01
            if step == 0:
                # A base value of zero has no proportional scale to nudge, so
                # fall back to a step drawn from the input's declared range.
                low, high = inp.range
                step = abs(high - low) * 0.01 or 1e-6
            try:
                moved = self.annual_value({name: inp.value + step})
            except ExpressionError:
                moved = base
            movements[name] = abs(moved - base)

        total = sum(movements.values())
        if total <= 0:
            # Degenerate driver (constant formula, or all inputs inert).
            # Split evenly rather than divide by zero.
            even = 1.0 / len(self.inputs)
            return {name: even for name in self.inputs}
        return {name: value / total for name, value in movements.items()}


class CostLine:
    __slots__ = ("id", "label", "schedule", "note")

    def __init__(
        self, id: str, label: str, schedule: List[float], note: Optional[str] = None
    ) -> None:
        self.id = id
        self.label = label
        self.schedule = schedule
        self.note = note


class ValueCase:
    """A validated, computed business case."""

    def __init__(
        self,
        name: str,
        currency: str,
        horizon: int,
        discount_rate: float,
        drivers: List[Driver],
        costs: List[CostLine],
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.name = name
        self.currency = currency
        self.horizon = horizon
        self.discount_rate = discount_rate
        self.drivers = drivers
        self.costs = costs
        self.meta = dict(meta or {})

    # -- cash flows ------------------------------------------------------

    def benefit_flows(
        self, overrides: Optional[Mapping[str, Mapping[str, float]]] = None
    ) -> List[float]:
        totals = [0.0] * (self.horizon + 1)
        for driver in self.drivers:
            driver_overrides = (overrides or {}).get(driver.id)
            for i, value in enumerate(driver.schedule(self.horizon, driver_overrides)):
                totals[i] += value
        return totals

    def cost_flows(self) -> List[float]:
        totals = [0.0] * (self.horizon + 1)
        for cost in self.costs:
            for i, value in enumerate(cost.schedule):
                totals[i] += value
        return totals

    def net_flows(
        self, overrides: Optional[Mapping[str, Mapping[str, float]]] = None
    ) -> List[float]:
        benefits = self.benefit_flows(overrides)
        costs = self.cost_flows()
        return [b - c for b, c in zip(benefits, costs)]

    # -- metrics ---------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        return finance.summarize(
            self.net_flows(),
            self.discount_rate,
            benefit_flows=self.benefit_flows(),
            cost_flows=self.cost_flows(),
        )

    def npv_with(
        self, overrides: Optional[Mapping[str, Mapping[str, float]]] = None
    ) -> float:
        return finance.npv(self.discount_rate, self.net_flows(overrides))

    def driver_contributions(self) -> List[Dict[str, Any]]:
        """NPV contributed by each driver, with its evidence grade."""
        out = []
        for driver in self.drivers:
            flows = driver.schedule(self.horizon)
            out.append(
                {
                    "id": driver.id,
                    "label": driver.label,
                    "confidence": driver.confidence,
                    "annual_run_rate": driver.annual_value(),
                    "realization": driver.realization,
                    "npv": finance.npv(self.discount_rate, flows),
                }
            )
        out.sort(key=lambda d: d["npv"], reverse=True)
        return out

    def sensitivity(self) -> List[Dict[str, Any]]:
        """One-at-a-time tornado over every input that declares a range."""
        base = self.npv_with()
        rows: List[Dict[str, Any]] = []
        for driver in self.drivers:
            for name, inp in driver.inputs.items():
                if inp.low is None and inp.high is None:
                    continue
                low, high = inp.range
                npv_low = self.npv_with({driver.id: {name: low}})
                npv_high = self.npv_with({driver.id: {name: high}})
                rows.append(
                    {
                        "driver_id": driver.id,
                        "driver_label": driver.label,
                        "input": name,
                        "confidence": inp.confidence,
                        "base": inp.value,
                        "low": low,
                        "high": high,
                        "npv_low": npv_low,
                        "npv_high": npv_high,
                        "swing": abs(npv_high - npv_low),
                        "downside": npv_low - base,
                        "upside": npv_high - base,
                        "flips_decision": (npv_low < 0) != (base < 0),
                    }
                )
        rows.sort(key=lambda r: r["swing"], reverse=True)
        return rows

    def floor_case(self) -> Dict[str, Any]:
        """Every ranged input simultaneously at its unfavorable bound.

        Reported separately from the tornado because compounding every downside
        at once is not a forecast — it is a stress test. Presenting it as the
        "conservative case" overstates pessimism; presenting it as the floor is
        accurate and much more persuasive when the floor is still positive.
        """
        overrides: Dict[str, Dict[str, float]] = {}
        base = self.npv_with()
        for driver in self.drivers:
            for name, inp in driver.inputs.items():
                if inp.low is None and inp.high is None:
                    continue
                low, high = inp.range
                trial_low = self.npv_with({driver.id: {name: low}})
                trial_high = self.npv_with({driver.id: {name: high}})
                worst = low if trial_low <= trial_high else high
                overrides.setdefault(driver.id, {})[name] = worst
        flows = self.net_flows(overrides)
        return {
            "npv": finance.npv(self.discount_rate, flows),
            "payback_periods": finance.discounted_payback_period(
                self.discount_rate, flows
            ),
            "delta_vs_base": finance.npv(self.discount_rate, flows) - base,
            "still_positive": finance.npv(self.discount_rate, flows) > 0,
        }

    def evidence(self) -> Dict[str, Any]:
        """Grade the case on how much of its value traces to measurement.

        Each driver's NPV is split across its inputs by proportional
        sensitivity (see :meth:`Driver.input_shares`), and each slice inherits
        that input's confidence. So a driver worth $200k built from one fact,
        one inference, and one assumption contributes roughly $67k to each
        bucket rather than $200k of pure assumption.
        """
        contributions: List[Tuple[str, float]] = []
        for driver in self.drivers:
            driver_npv = finance.npv(
                self.discount_rate, driver.schedule(self.horizon)
            )
            for name, share in driver.input_shares().items():
                contributions.append(
                    (driver.inputs[name].confidence, driver_npv * share)
                )
        graded = grade_evidence(contributions)
        graded["largest_assumption"] = self._largest_assumption()
        graded["by_input"] = self.evidence_by_input()
        return graded

    def evidence_by_input(self) -> List[Dict[str, Any]]:
        """Per-input value attribution, sorted by how much value each carries.

        This is the table that answers "which unmeasured number is doing the
        most work in this case" — the first question any serious reviewer asks
        and the last one most business cases can answer.
        """
        rows: List[Dict[str, Any]] = []
        for driver in self.drivers:
            driver_npv = finance.npv(
                self.discount_rate, driver.schedule(self.horizon)
            )
            for name, share in driver.input_shares().items():
                inp = driver.inputs[name]
                rows.append(
                    {
                        "driver_id": driver.id,
                        "driver_label": driver.label,
                        "input": name,
                        "confidence": inp.confidence,
                        "share_of_driver": share,
                        "npv_attributed": driver_npv * share,
                        "source": inp.source,
                    }
                )
        rows.sort(key=lambda r: abs(r["npv_attributed"]), reverse=True)
        return rows

    def _largest_assumption(self) -> Optional[Dict[str, Any]]:
        """The single assumption worth spending a week measuring."""
        candidates = [
            row
            for row in self.sensitivity()
            if row["confidence"] == "assumption"
        ]
        if not candidates:
            return None
        top = candidates[0]
        return {
            "driver": top["driver_label"],
            "input": top["input"],
            "swing": top["swing"],
            "flips_decision": top["flips_decision"],
            "advice": (
                "This one input moves NPV by %s across its stated range%s. "
                "If any number in this case deserves a measurement before the "
                "decision, it is this one."
                % (
                    fmt_currency(top["swing"], self.currency),
                    " and it flips the decision at its low bound"
                    if top["flips_decision"]
                    else "",
                )
            ),
        }

    # -- output ----------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "currency": self.currency,
            "horizon_years": self.horizon,
            "discount_rate_annual": self.discount_rate,
            "meta": self.meta,
            "cash_flows": {
                "benefits": self.benefit_flows(),
                "costs": self.cost_flows(),
                "net": self.net_flows(),
            },
            "summary": self.summary(),
            "drivers": self.driver_contributions(),
            "sensitivity": self.sensitivity(),
            "floor_case": self.floor_case(),
            "evidence": self.evidence(),
            "ledger": [
                dict(inp.to_dict(), driver=driver.id)
                for driver in self.drivers
                for inp in driver.inputs.values()
            ],
        }

    def to_markdown(self) -> str:
        cur = self.currency
        summary = self.summary()
        evidence = self.evidence()
        floor = self.floor_case()

        lines: List[str] = []
        lines.append("# %s" % self.name)
        lines.append("")
        lines.append(
            "%d-year case, discounted at %s annually. All figures in %s."
            % (self.horizon, fmt_pct(self.discount_rate), cur)
        )
        lines.append("")

        # Headline metrics first: a reader who stops after this block should
        # still have the decision-relevant facts.
        lines.append("## Headline")
        lines.append("")
        headline_rows = [
            ["Net present value", fmt_currency(summary["npv"], cur)],
            [
                "Discounted payback",
                fmt_periods(summary["discounted_payback_periods"]),
            ],
            [
                "IRR",
                fmt_pct(summary["irr_annual"])
                if summary["irr_annual"] is not None
                else "not meaningful for this cash flow shape",
            ],
            ["Total investment", fmt_currency(summary["total_investment"], cur)],
            ["Total modeled benefit", fmt_currency(summary["total_benefit"], cur)],
            ["Margin of safety", _margin_of_safety(summary)],
        ]
        lines.append(table(["Metric", "Value"], headline_rows))
        lines.append("")

        # Evidence grade sits above the driver detail on purpose. Naming the
        # weakness before the reader finds it is what earns the benefit of the
        # doubt on everything else.
        lines.append("## Evidence grade: %s" % evidence["grade"])
        lines.append("")
        lines.append(evidence["headline"])
        lines.append("")
        lines.append(
            "- Measured facts: %s of modeled value"
            % fmt_pct(evidence["share_fact"])
        )
        lines.append(
            "- Derived inferences: %s" % fmt_pct(evidence["share_inference"])
        )
        lines.append(
            "- Unmeasured assumptions: %s" % fmt_pct(evidence["share_assumption"])
        )
        if evidence.get("largest_assumption"):
            lines.append("")
            largest = evidence["largest_assumption"]
            lines.append(
                "**Measure this first — %s / %s.** %s"
                % (largest["driver"], largest["input"], largest["advice"])
            )
        lines.append("")

        lines.append("## Value drivers")
        lines.append("")
        driver_rows = [
            [
                row["label"],
                row["confidence"],
                fmt_currency(row["annual_run_rate"], cur),
                fmt_pct(row["realization"]),
                fmt_currency(row["npv"], cur),
            ]
            for row in self.driver_contributions()
        ]
        lines.append(
            table(
                ["Driver", "Weakest link", "Annual run rate", "Realization", "NPV"],
                driver_rows,
            )
        )
        lines.append("")

        lines.append("## Where the value actually comes from")
        lines.append("")
        lines.append(
            "Each driver's NPV split across its inputs by proportional "
            "sensitivity. Read this top-down: the first row is the number "
            "carrying the most weight in the entire case."
        )
        lines.append("")
        attribution_rows = [
            [
                "%s / %s" % (row["driver_label"], row["input"]),
                row["confidence"],
                fmt_pct(row["share_of_driver"]),
                fmt_currency(row["npv_attributed"], cur),
            ]
            for row in self.evidence_by_input()[:12]
        ]
        lines.append(
            table(
                ["Input", "Confidence", "Share of driver", "NPV attributed"],
                attribution_rows,
            )
        )
        lines.append("")

        lines.append("## Cash flow")
        lines.append("")
        benefits = self.benefit_flows()
        costs = self.cost_flows()
        net = self.net_flows()
        running = finance.cumulative(net)
        flow_rows = []
        for period in range(self.horizon + 1):
            flow_rows.append(
                [
                    "Today" if period == 0 else "Year %d" % period,
                    fmt_currency(benefits[period], cur),
                    fmt_currency(-costs[period], cur),
                    fmt_currency(net[period], cur),
                    fmt_currency(running[period], cur),
                ]
            )
        lines.append(
            table(
                ["Period", "Benefit", "Cost", "Net", "Cumulative"],
                flow_rows,
            )
        )
        lines.append("")

        lines.append("## What would have to be true")
        lines.append("")
        lines.append(
            "Each row swings one input across its stated range while everything "
            "else holds at base. Sorted by how much the decision moves."
        )
        lines.append("")
        sens_rows = [
            [
                "%s / %s" % (row["driver_label"], row["input"]),
                row["confidence"],
                "%s to %s" % (fmt_multiple(row["low"]), fmt_multiple(row["high"])),
                fmt_currency(row["npv_low"], cur),
                fmt_currency(row["npv_high"], cur),
                "yes" if row["flips_decision"] else "no",
            ]
            for row in self.sensitivity()[:12]
        ]
        if sens_rows:
            lines.append(
                table(
                    [
                        "Input",
                        "Confidence",
                        "Range",
                        "NPV at low",
                        "NPV at high",
                        "Flips decision",
                    ],
                    sens_rows,
                )
            )
        else:
            lines.append(
                "_No input declared a range, so no sensitivity could be run. "
                "Add low/high bounds to the assumptions — a case without a "
                "stated range invites the reader to invent their own._"
            )
        lines.append("")

        lines.append("## Floor case")
        lines.append("")
        lines.append(
            "Every ranged input simultaneously at its unfavorable bound. This "
            "is a stress test, not a forecast."
        )
        lines.append("")
        lines.append(
            "- NPV at the floor: **%s** (%s vs base)"
            % (
                fmt_currency(floor["npv"], cur),
                fmt_currency(floor["delta_vs_base"], cur),
            )
        )
        lines.append(
            "- Discounted payback at the floor: %s"
            % fmt_periods(floor["payback_periods"])
        )
        lines.append(
            "- %s"
            % (
                "**The case still clears zero even at the floor.** That is the "
                "strongest sentence available here — lead with it."
                if floor["still_positive"]
                else "The case goes negative at the floor. Say so, and name "
                "which input has to hold for it not to."
            )
        )
        lines.append("")

        lines.append("## Assumption ledger")
        lines.append("")
        lines.append(
            "Every number in this model, what kind of number it is, and where "
            "it came from. If a line here cannot survive a follow-up question, "
            "fix it before the meeting, not during it."
        )
        lines.append("")
        ledger_rows = []
        for driver in self.drivers:
            for name, inp in driver.inputs.items():
                low, high = inp.range
                ledger_rows.append(
                    [
                        driver.label,
                        name,
                        fmt_multiple(inp.value)
                        + (" %s" % inp.unit if inp.unit else ""),
                        inp.confidence,
                        "%s–%s" % (fmt_multiple(low), fmt_multiple(high))
                        if inp.swing
                        else "point estimate",
                        inp.source,
                    ]
                )
        lines.append(
            table(
                ["Driver", "Input", "Value", "Confidence", "Range", "Source"],
                ledger_rows,
            )
        )
        lines.append("")

        if self.costs:
            lines.append("## Cost lines")
            lines.append("")
            cost_rows = [
                [
                    cost.label,
                    fmt_currency(sum(cost.schedule), cur),
                    cost.note or "",
                ]
                for cost in self.costs
            ]
            lines.append(table(["Cost", "Total", "Note"], cost_rows))
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            "_Generated by [gtm-skills](https://github.com/erickdronski/gtm-skills). "
            "Every figure above is computed from the declared inputs by a tested "
            "library — no number in this document was written by hand._"
        )
        return "\n".join(lines)


def _margin_of_safety(summary: Mapping[str, Any]) -> str:
    """Phrase the break-even multiplier in the direction it actually points.

    Below 1.0 the case has slack: benefits can slip and it still clears zero.
    Above 1.0 there is no margin at all — benefits have to *exceed* plan just
    to break even, which is the single most important thing a reviewer can
    know and the easiest thing for a rounded percentage to hide.
    """
    multiplier = summary.get("break_even_benefit_multiplier")
    if multiplier is None:
        return "n/a — no modeled benefit to shrink"
    if multiplier <= 0:
        return "case clears zero even with no benefits at all"
    if multiplier < 1:
        return "benefits can come in %s below plan and still break even" % fmt_pct(
            1 - multiplier
        )
    return (
        "none — benefits must exceed plan by %s just to break even"
        % fmt_pct(multiplier - 1)
    )


# -- loading and validation ---------------------------------------------


def validate_spec(spec: Mapping[str, Any]) -> ValueCase:
    """Validate a raw spec mapping and return a computed :class:`ValueCase`.

    Errors are raised eagerly and name the offending field, because the caller
    is usually an agent editing a JSON file and a vague error costs a round trip.
    """
    if not isinstance(spec, Mapping):
        raise SpecError("spec must be a JSON object")

    name = str(spec.get("name") or "").strip()
    if not name:
        raise SpecError("spec needs a 'name'")

    currency = str(spec.get("currency") or "USD").strip().upper()

    horizon = spec.get("horizon_years")
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise SpecError("'horizon_years' must be an integer >= 1")
    if horizon > 10:
        raise SpecError(
            "'horizon_years' is %d. Cases longer than 10 years are not "
            "credible in software buying decisions; the discount rate swamps "
            "the tail and reviewers discount the whole document." % horizon
        )

    rate = spec.get("discount_rate_annual")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        raise SpecError("'discount_rate_annual' must be a number, e.g. 0.12")
    if not (-0.5 < rate < 1.0):
        raise SpecError(
            "'discount_rate_annual' of %r is outside any plausible cost of "
            "capital. Use a decimal: 12%% is 0.12, not 12." % rate
        )

    raw_drivers = spec.get("drivers")
    if not isinstance(raw_drivers, list) or not raw_drivers:
        raise SpecError("spec needs a non-empty 'drivers' array")

    drivers: List[Driver] = []
    seen_ids = set()
    for index, raw in enumerate(raw_drivers):
        drivers.append(_build_driver(raw, index, horizon, seen_ids))

    costs: List[CostLine] = []
    raw_costs = spec.get("costs") or []
    if not isinstance(raw_costs, list):
        raise SpecError("'costs' must be an array")
    cost_ids = set()
    for index, raw in enumerate(raw_costs):
        costs.append(_build_cost(raw, index, horizon, cost_ids))

    if not costs:
        raise SpecError(
            "spec has no 'costs'. A benefit-only case is a wish list; include "
            "at least the subscription and the implementation effort."
        )

    return ValueCase(
        name=name,
        currency=currency,
        horizon=horizon,
        discount_rate=float(rate),
        drivers=drivers,
        costs=costs,
        meta=spec.get("meta") or {},
    )


def _build_driver(
    raw: Any, index: int, horizon: int, seen_ids: set
) -> Driver:
    where = "drivers[%d]" % index
    if not isinstance(raw, Mapping):
        raise SpecError("%s must be an object" % where)

    driver_id = str(raw.get("id") or "").strip()
    if not driver_id:
        raise SpecError("%s needs an 'id'" % where)
    if driver_id in seen_ids:
        raise SpecError("duplicate driver id %r" % driver_id)
    seen_ids.add(driver_id)

    label = str(raw.get("label") or driver_id).strip()
    formula = str(raw.get("formula") or "").strip()
    if not formula:
        raise SpecError("driver %r needs a 'formula'" % driver_id)

    raw_inputs = raw.get("inputs")
    if not isinstance(raw_inputs, Mapping) or not raw_inputs:
        raise SpecError("driver %r needs a non-empty 'inputs' object" % driver_id)

    inputs: Dict[str, Input] = {}
    for input_name, raw_input in raw_inputs.items():
        try:
            inputs[input_name] = validate_input(input_name, raw_input)
        except EvidenceError as exc:
            raise SpecError("driver %r: %s" % (driver_id, exc)) from exc

    try:
        referenced = referenced_names(formula)
    except ExpressionError as exc:
        raise SpecError("driver %r: %s" % (driver_id, exc)) from exc

    missing = [name for name in referenced if name not in inputs]
    if missing:
        raise SpecError(
            "driver %r references undefined input(s): %s. Declare them in "
            "'inputs' with a value, confidence, and source."
            % (driver_id, ", ".join(sorted(missing)))
        )
    unused = [name for name in inputs if name not in referenced]
    if unused:
        raise SpecError(
            "driver %r declares input(s) the formula never uses: %s. Either "
            "the formula is stale or the ledger is — both mislead a reviewer."
            % (driver_id, ", ".join(sorted(unused)))
        )

    ramp = raw.get("ramp")
    if ramp is None:
        ramp = [1.0] * horizon
    if not isinstance(ramp, list) or not ramp:
        raise SpecError("driver %r has an invalid 'ramp'" % driver_id)
    for value in ramp:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecError("driver %r ramp contains a non-number" % driver_id)
        if value < 0:
            raise SpecError("driver %r ramp contains a negative value" % driver_id)
    ramp = [float(v) for v in ramp]

    realization = raw.get("realization", 1.0)
    if (
        isinstance(realization, bool)
        or not isinstance(realization, (int, float))
        or not (0 < realization <= 1)
    ):
        raise SpecError(
            "driver %r has realization %r; it must be greater than 0 and at "
            "most 1. Realization is the haircut between modeled and captured "
            "value — 1.0 claims you capture every modeled dollar, which is a "
            "position you should be prepared to defend."
            % (driver_id, realization)
        )

    # Sanity-check the formula evaluates at base before anyone builds on it.
    try:
        evaluate(formula, {name: inp.value for name, inp in inputs.items()})
    except ExpressionError as exc:
        raise SpecError("driver %r: %s" % (driver_id, exc)) from exc

    return Driver(
        id=driver_id,
        label=label,
        formula=formula,
        inputs=inputs,
        ramp=ramp,
        realization=float(realization),
        note=raw.get("note"),
    )


def _build_cost(raw: Any, index: int, horizon: int, seen_ids: set) -> CostLine:
    where = "costs[%d]" % index
    if not isinstance(raw, Mapping):
        raise SpecError("%s must be an object" % where)
    cost_id = str(raw.get("id") or "").strip()
    if not cost_id:
        raise SpecError("%s needs an 'id'" % where)
    if cost_id in seen_ids:
        raise SpecError("duplicate cost id %r" % cost_id)
    seen_ids.add(cost_id)

    schedule = raw.get("schedule")
    if not isinstance(schedule, list):
        raise SpecError(
            "cost %r needs a 'schedule' array with %d entries (period 0 "
            "through year %d)" % (cost_id, horizon + 1, horizon)
        )
    if len(schedule) != horizon + 1:
        raise SpecError(
            "cost %r has %d schedule entries but the horizon needs %d "
            "(period 0 is today, then one entry per year)"
            % (cost_id, len(schedule), horizon + 1)
        )
    for value in schedule:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecError("cost %r schedule contains a non-number" % cost_id)
        if value < 0:
            raise SpecError(
                "cost %r has a negative entry. Costs are positive numbers in "
                "the schedule; the model subtracts them." % cost_id
            )

    return CostLine(
        id=cost_id,
        label=str(raw.get("label") or cost_id),
        schedule=[float(v) for v in schedule],
        note=raw.get("note"),
    )


def load_spec(path: str) -> ValueCase:
    """Read and validate a spec file from disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise SpecError("no such spec file: %s" % path)
    except json.JSONDecodeError as exc:
        raise SpecError("%s is not valid JSON: %s" % (path, exc))
    return validate_spec(raw)


def build(spec: Mapping[str, Any]) -> ValueCase:
    """Alias for :func:`validate_spec`, for callers who read better this way."""
    return validate_spec(spec)


# -- CLI ------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m gtmkit.valuecase",
        description=(
            "Build an auditable business case from a declarative spec. "
            "Outputs a markdown brief or the full JSON model."
        ),
    )
    parser.add_argument("spec", help="path to the business-case JSON spec")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format (default: markdown)",
    )
    parser.add_argument(
        "--out",
        help="write to this file instead of stdout",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the spec and exit without producing output",
    )
    args = parser.parse_args(argv)

    try:
        case = load_spec(args.spec)
    except (SpecError, EvidenceError, ExpressionError) as exc:
        sys.stderr.write("spec error: %s\n" % exc)
        return 2

    if args.check:
        sys.stdout.write(
            "%s is valid: %d driver(s), %d cost line(s), %d-year horizon.\n"
            % (args.spec, len(case.drivers), len(case.costs), case.horizon)
        )
        return 0

    if args.format == "json":
        output = json.dumps(case.to_dict(), indent=2, sort_keys=False)
    else:
        output = case.to_markdown()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
        sys.stderr.write("wrote %s\n" % args.out)
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
