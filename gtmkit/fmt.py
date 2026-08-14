"""Formatting helpers for executive-readable output.

Numbers in a business document are a communication problem, not a precision
problem. ``$1,247,318.44`` in a board deck signals that the author has not
decided what matters; ``$1.2M`` signals that they have. These helpers enforce
that judgment in one place so every skill in the pack renders consistently.

The one rule that matters: never print more precision than the underlying
estimate supports. If a benefit rests on an assumption with a ±40% range,
rendering it to the cent is a lie told in typography.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

__all__ = [
    "fmt_currency",
    "fmt_pct",
    "fmt_periods",
    "fmt_multiple",
    "fmt_count",
    "table",
    "bar",
]

_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CAD": "CA$",
    "AUD": "A$",
    "INR": "₹",
}


def fmt_currency(
    amount: Optional[float], currency: str = "USD", precise: bool = False
) -> str:
    """Render an amount at a precision an executive can hold in their head.

    ``precise=True`` keeps full digits with thousands separators, for the rare
    places exactness matters (an invoice line, a contract value).
    """
    if amount is None:
        return "n/a"
    symbol = _SYMBOLS.get((currency or "USD").upper(), (currency or "USD").upper() + " ")
    sign = "-" if amount < 0 else ""
    value = abs(float(amount))

    if precise:
        # Unit economics live below a dollar — a cost-per-impression rendered
        # as "$0.02" hides the difference between a $0.022 and a $0.017 CPM,
        # which is the whole ballgame in paid media.
        places = 4 if 0 < value < 1 else 2
        return "%s%s%s" % (sign, symbol, "{:,.{p}f}".format(value, p=places))

    if value >= 1_000_000_000:
        return "%s%s%sB" % (sign, symbol, _trim(value / 1_000_000_000))
    if value >= 1_000_000:
        return "%s%s%sM" % (sign, symbol, _trim(value / 1_000_000))
    if value >= 1_000:
        return "%s%s%sk" % (sign, symbol, _trim(value / 1_000))
    if value >= 1:
        return "%s%s%s" % (sign, symbol, "{:,.0f}".format(value))
    if value == 0:
        return "%s0" % symbol
    return "%s%s%s" % (sign, symbol, "{:,.2f}".format(value))


def _trim(value: float) -> str:
    """One decimal place, dropping a trailing ``.0``."""
    text = "{:.1f}".format(value)
    return text[:-2] if text.endswith(".0") else text


def fmt_pct(fraction: Optional[float], decimals: Optional[int] = None) -> str:
    """Render a decimal fraction as a percentage.

    Defaults to whole percentages above 10% and one decimal below, because
    "7.5%" carries information that "8%" loses while "22.4%" carries noise that
    "22%" correctly discards.
    """
    if fraction is None:
        return "n/a"
    value = float(fraction) * 100
    if decimals is None:
        decimals = 1 if abs(value) < 10 else 0
        # Funnel conversion rates are routinely a fraction of a percent.
        # Rounding 0.0004% to "0%" turns a real number into a wrong one, so
        # widen precision until something survives.
        while (
            value != 0
            and decimals < 6
            and abs(round(value, decimals)) < 10 ** -decimals
        ):
            decimals += 1
    text = "{:,.{d}f}".format(value, d=decimals)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("0", "-0") and value != 0:
        return "<0.000001%"
    return text + "%"


def fmt_periods(periods: Optional[float], unit: str = "year") -> str:
    """Render a fractional period count as years and months.

    ``1.17`` becomes ``1 yr 2 mo``. Executives make decisions on payback in
    months; reporting "1.17 years" makes them do arithmetic in the meeting.
    """
    if periods is None:
        return "never within the modeled horizon"
    if periods < 0:
        return "n/a"
    if unit != "year":
        return "%s %s%s" % (
            _trim(periods),
            unit,
            "" if abs(periods - 1) < 1e-9 else "s",
        )

    whole = int(periods)
    months = int(round((periods - whole) * 12))
    if months == 12:
        whole += 1
        months = 0
    if whole == 0 and months == 0:
        return "immediate"
    if whole == 0:
        return "%d mo" % months
    if months == 0:
        return "%d yr" % whole
    return "%d yr %d mo" % (whole, months)


def fmt_multiple(value: Optional[float]) -> str:
    """General-purpose number rendering for ledger and range columns."""
    if value is None:
        return "n/a"
    value = float(value)
    if value != value:  # NaN
        return "n/a"
    if abs(value) >= 1000:
        return "{:,.0f}".format(value)
    if abs(value) >= 10:
        return "{:,.2f}".format(value).rstrip("0").rstrip(".")
    if value == int(value):
        return str(int(value))
    return "{:,.4f}".format(value).rstrip("0").rstrip(".")


def fmt_count(value: Optional[float]) -> str:
    """Whole-number rendering with thousands separators."""
    if value is None:
        return "n/a"
    return "{:,.0f}".format(float(value))


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Render a GitHub-flavored markdown table with padded columns.

    Padding costs nothing and makes the raw markdown readable in a terminal or
    a diff, which matters because these documents get reviewed in pull requests
    as often as they get rendered.
    """
    if not rows:
        return "_No rows._"

    string_rows = [[_cell(value) for value in row] for row in rows]
    columns = len(headers)
    widths = [len(str(h)) for h in headers]
    for row in string_rows:
        for i in range(min(columns, len(row))):
            widths[i] = max(widths[i], len(row[i]))

    def line(cells: Sequence[str]) -> str:
        padded = [
            str(cells[i]).ljust(widths[i]) if i < len(cells) else " " * widths[i]
            for i in range(columns)
        ]
        return "| " + " | ".join(padded) + " |"

    out = [line([str(h) for h in headers])]
    out.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for row in string_rows:
        out.append(line(row))
    return "\n".join(out)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    # Newlines and pipes both break markdown tables; collapse rather than
    # letting a long source string silently corrupt the document.
    return text.replace("\n", " ").replace("|", "\\|").strip()


def bar(fraction: float, width: int = 20, filled: str = "█", empty: str = "░") -> str:
    """A text bar for terminal output, clamped to [0, 1]."""
    fraction = max(0.0, min(1.0, float(fraction)))
    count = int(round(fraction * width))
    return filled * count + empty * (width - count)
