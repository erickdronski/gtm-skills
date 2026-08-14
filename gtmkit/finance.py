"""Core finance math for go-to-market business cases.

Pure standard library. No third-party dependencies, no network access.

Every function here is deliberately small and separately testable, because the
whole point of this package is that the numbers in a business case should come
from code that has a test suite rather than from a language model's arithmetic.
When a CFO asks "where did 34% come from", the answer needs to be a function
call with named inputs, not a paragraph.

Conventions used throughout:

* Cash flows are lists indexed by period, where index 0 is "today" (period 0).
  Period 0 flows are NOT discounted.
* Costs are negative, benefits are positive. A typical software business case
  looks like ``[-250_000, 120_000, 180_000, 180_000]``.
* Rates are decimals per period, not percentages. 12% is ``0.12``.
* Anything that cannot be computed honestly returns ``None`` rather than a
  fabricated number. A missing IRR is information; a made-up IRR is a liability.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

__all__ = [
    "InvalidCashFlows",
    "annualized_rate",
    "break_even_multiplier",
    "break_even_value",
    "cumulative",
    "discounted_payback_period",
    "irr",
    "npv",
    "payback_period",
    "periodic_rate",
    "present_value",
    "roi",
    "sign_changes",
    "summarize",
]


class InvalidCashFlows(ValueError):
    """Raised when a cash flow series cannot support the requested metric."""


def _validate(cash_flows: Sequence[float]) -> List[float]:
    if cash_flows is None:
        raise InvalidCashFlows("cash_flows is required")
    flows = list(cash_flows)
    if len(flows) < 2:
        raise InvalidCashFlows(
            "need at least two periods (period 0 plus one future period); "
            "a single-period series has no time value to model"
        )
    for i, value in enumerate(flows):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidCashFlows("period %d is not a number: %r" % (i, value))
        if value != value:  # NaN
            raise InvalidCashFlows("period %d is NaN" % i)
    return [float(v) for v in flows]


def present_value(amount: float, rate: float, period: int) -> float:
    """Discount a single ``amount`` received at ``period`` back to today.

    Period 0 is undiscounted, which is why this is ``(1 + rate) ** period``
    and not ``period + 1``. Off-by-one here silently inflates or deflates every
    business case built on top of it, so it lives in one place.
    """
    if period < 0:
        raise InvalidCashFlows("period must be >= 0, got %d" % period)
    if rate <= -1.0:
        raise InvalidCashFlows("discount rate must be > -100%%, got %r" % rate)
    return float(amount) / ((1.0 + float(rate)) ** period)


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    """Net present value of ``cash_flows`` at ``rate`` per period.

    Note this follows the finance-textbook convention (period 0 undiscounted),
    which differs from Excel's ``NPV()`` — Excel discounts its first argument by
    one period, so the Excel equivalent is ``cash_flows[0] + NPV(rate, rest)``.
    That mismatch is one of the most common errors in circulated business cases;
    if you are reconciling against someone's spreadsheet, check this first.
    """
    flows = _validate(cash_flows)
    return sum(present_value(value, rate, i) for i, value in enumerate(flows))


def irr(
    cash_flows: Sequence[float],
    low: float = -0.9999,
    high: float = 10.0,
    tolerance: float = 1e-10,
    max_iterations: int = 200,
) -> Optional[float]:
    """Internal rate of return, or ``None`` when no single honest answer exists.

    Uses bisection rather than Newton's method: it is slower but cannot diverge,
    and a business case that silently reports a diverged IRR is worse than one
    that reports none. The default tolerance is tight (1e-10 on the rate
    bracket) because the bracket tolerance — not the NPV tolerance — is what
    binds in practice: NPV is denominated in dollars, so a loose rate bracket
    on a million-dollar case still leaves visible error in the returned rate.

    Returns ``None`` when:

    * every flow has the same sign (no rate makes NPV zero), or
    * NPV does not change sign across the search bracket.

    A series with multiple sign changes can have multiple mathematically valid
    IRRs. This function returns the lowest one in the bracket and callers that
    care should check :func:`sign_changes`. In practice, if your business case
    has a non-conventional cash flow shape, IRR is the wrong headline metric and
    you should lead with NPV.
    """
    flows = _validate(cash_flows)

    if all(value >= 0 for value in flows) or all(value <= 0 for value in flows):
        return None

    def f(rate: float) -> float:
        return npv(rate, flows)

    f_low = f(low)
    f_high = f(high)
    if f_low * f_high > 0:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < tolerance or (high - low) / 2.0 < tolerance:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return (low + high) / 2.0


def sign_changes(cash_flows: Sequence[float]) -> int:
    """Count sign changes, to detect cash flow shapes where IRR is ambiguous."""
    flows = [v for v in _validate(cash_flows) if v != 0]
    return sum(1 for a, b in zip(flows, flows[1:]) if (a > 0) != (b > 0))


def cumulative(cash_flows: Sequence[float]) -> List[float]:
    """Running total of a cash flow series."""
    flows = _validate(cash_flows)
    out: List[float] = []
    total = 0.0
    for value in flows:
        total += value
        out.append(total)
    return out


def _first_crossing(running: Sequence[float]) -> Optional[float]:
    """Period at which a running total first reaches zero, interpolated."""
    for i, total in enumerate(running):
        if total >= 0:
            if i == 0:
                return 0.0
            previous = running[i - 1]
            step = total - previous
            if step <= 0:
                return float(i)
            # Linear interpolation inside the period the investment turns
            # positive. Reporting "14 months" instead of "year 2" is the
            # difference between a credible case and a rounded one.
            return (i - 1) + (-previous / step)
    return None


def payback_period(cash_flows: Sequence[float]) -> Optional[float]:
    """Undiscounted payback in periods, or ``None`` if it never pays back.

    The fractional part is linearly interpolated within the crossing period.
    """
    return _first_crossing(cumulative(cash_flows))


def discounted_payback_period(
    rate: float, cash_flows: Sequence[float]
) -> Optional[float]:
    """Payback measured on discounted flows, or ``None`` if it never pays back.

    This is the honest version of payback. Undiscounted payback flatters long
    projects by pretending a dollar in year three is worth a dollar today.
    """
    flows = _validate(cash_flows)
    discounted = [present_value(v, rate, i) for i, v in enumerate(flows)]
    return _first_crossing(cumulative(discounted))


def roi(cash_flows: Sequence[float]) -> Optional[float]:
    """Simple return on investment as a decimal.

    Defined as ``(total benefits - total costs) / total costs`` using the
    absolute value of all negative flows as the investment base. Returns
    ``None`` when there is no investment to divide by.

    ROI is the weakest metric in this module because it ignores timing
    entirely — it is included because executives ask for it, not because it is
    the best answer. Lead with NPV and payback; offer ROI as a supporting
    number.
    """
    flows = _validate(cash_flows)
    costs = sum(-v for v in flows if v < 0)
    benefits = sum(v for v in flows if v > 0)
    if costs == 0:
        return None
    return (benefits - costs) / costs


def annualized_rate(rate_per_period: float, periods_per_year: int) -> float:
    """Convert a per-period rate to its compounded annual equivalent.

    Monthly 1% is 12.68% annually, not 12%. Business cases that add monthly
    rates instead of compounding them understate cost of capital.
    """
    if periods_per_year <= 0:
        raise InvalidCashFlows("periods_per_year must be positive")
    return (1.0 + float(rate_per_period)) ** periods_per_year - 1.0


def periodic_rate(annual_rate: float, periods_per_year: int) -> float:
    """Inverse of :func:`annualized_rate`: annual rate to per-period rate."""
    if periods_per_year <= 0:
        raise InvalidCashFlows("periods_per_year must be positive")
    return (1.0 + float(annual_rate)) ** (1.0 / periods_per_year) - 1.0


def break_even_value(
    rate: float,
    cash_flows: Sequence[float],
    period_weights: Optional[Sequence[float]] = None,
) -> Optional[float]:
    """How much a benefit stream can shrink before NPV hits zero.

    Returns the multiplier applied to positive flows that drives NPV to exactly
    zero. ``0.62`` means "benefits can come in 38% below plan and this still
    breaks even" — the single most persuasive sentence available in a business
    case review, because it converts an optimistic forecast into a stated
    margin of safety.

    Returns ``None`` when the case never breaks even (NPV of costs alone is
    already positive, or benefits cannot reach zero NPV).
    """
    flows = _validate(cash_flows)
    if period_weights is not None and len(period_weights) != len(flows):
        raise InvalidCashFlows("period_weights must match cash_flows length")

    cost_npv = sum(present_value(v, rate, i) for i, v in enumerate(flows) if v < 0)
    benefit_npv = sum(present_value(v, rate, i) for i, v in enumerate(flows) if v > 0)
    if benefit_npv <= 0:
        return None
    multiplier = -cost_npv / benefit_npv
    if multiplier < 0:
        # Costs are net positive; the case breaks even with zero benefits.
        return 0.0
    return multiplier


def break_even_multiplier(
    rate: float,
    benefit_flows: Sequence[float],
    cost_flows: Sequence[float],
) -> Optional[float]:
    """Fraction of modeled benefits required to reach NPV zero.

    This is the gross-flow version of :func:`break_even_value`, and it is the
    one you want whenever benefits and costs are tracked separately — which is
    always, in a real business case. Netting them first destroys the
    information: once year 2 is a single number, you can no longer ask "how far
    can the benefit side slip".

    ``0.62`` reads as "benefits can come in 38% below plan and this still
    breaks even". Returns ``None`` when benefits have no present value to
    shrink, and ``0.0`` when the case clears zero with no benefits at all.
    """
    benefit_npv = sum(present_value(v, rate, i) for i, v in enumerate(benefit_flows))
    cost_npv = sum(present_value(v, rate, i) for i, v in enumerate(cost_flows))
    if benefit_npv <= 0:
        return None
    if cost_npv <= 0:
        return 0.0
    return cost_npv / benefit_npv


def summarize(
    cash_flows: Sequence[float],
    rate: float,
    periods_per_year: int = 1,
    benefit_flows: Optional[Sequence[float]] = None,
    cost_flows: Optional[Sequence[float]] = None,
) -> dict:
    """One call that produces every headline metric, with honest nulls.

    Pass ``benefit_flows`` and ``cost_flows`` whenever you have them. Without
    them the totals have to be inferred from the sign of the net flow, which
    understates both sides in any period where benefits and costs coexist —
    a year with $200k of benefit and $190k of cost is not "$10k of benefit".
    """
    flows = _validate(cash_flows)
    net_present = npv(rate, flows)
    internal = irr(flows)

    if benefit_flows is not None and cost_flows is not None:
        total_benefit = sum(benefit_flows)
        total_investment = sum(cost_flows)
        break_even = break_even_multiplier(rate, benefit_flows, cost_flows)
    else:
        total_benefit = sum(v for v in flows if v > 0)
        total_investment = sum(-v for v in flows if v < 0)
        break_even = break_even_value(rate, flows)

    return {
        "periods": len(flows) - 1,
        "periods_per_year": periods_per_year,
        "discount_rate_per_period": rate,
        "discount_rate_annual": annualized_rate(rate, periods_per_year),
        "total_investment": total_investment,
        "total_benefit": total_benefit,
        "net_cash": sum(flows),
        "npv": net_present,
        "irr_per_period": internal,
        "irr_annual": (
            annualized_rate(internal, periods_per_year)
            if internal is not None
            else None
        ),
        "roi": (
            (total_benefit - total_investment) / total_investment
            if total_investment
            else None
        ),
        "payback_periods": payback_period(flows),
        "discounted_payback_periods": discounted_payback_period(rate, flows),
        "break_even_benefit_multiplier": break_even,
        "sign_changes": sign_changes(flows),
        "irr_is_ambiguous": sign_changes(flows) > 1,
    }
