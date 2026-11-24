"""Render a value case as one self-contained HTML file to share.

Run it through the value-case CLI::

    python3 -m gtmkit.valuecase case.json --format html --out case.html
    gtmkit valuecase case.json --format html --out case.html

or from code with ``case.to_html()``. The page leads with the headline and
the evidence grade, then shows a tornado of every ranged input, the cash flow,
the value drivers, where the value comes from, the floor case, the full
assumption ledger, and the cost lines.

Rules this module keeps, because the file travels further than the spec does:

* **Computed, not typed.** Every figure comes from the :class:`ValueCase`
  and is formatted by the same helpers the markdown brief uses, so the two
  outputs agree. The only literals here are layout constants.
* **Self-contained.** One file with no JavaScript and no web fonts, images,
  stylesheets, or network references. It opens offline, prints, and survives
  an email attachment scanner.
* **Escaped.** Every string from the spec passes through
  :func:`html.escape`, because specs are assembled from emails and PDFs.
* **Deterministic.** No timestamps and no random ids: identical input gives
  identical bytes, so two reports can be diffed.
* **Readable without the picture.** Every chart has an accessible name, and
  every number drawn in a chart also appears as text or in a table.
"""

from __future__ import annotations

import json
import math
from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import __version__, finance
from .fmt import currency_symbol, fmt_currency, fmt_multiple, fmt_pct, fmt_periods
from .valuecase import FLOOR_FAILS, FLOOR_HOLDS, FLOOR_NOTE, NO_RANGE_NOTE

__all__ = [
    "Scale",
    "currency_step",
    "nice_scale",
    "render_value_case",
    "tick_label",
    "tornado_axis_width",
]

REPO_URL = "https://github.com/erickdronski/gtm-skills"

# Confidence is ordered, so the report gives it one hue: more evidence, more
# ink. (level, plural for the evidence bar, singular for per-input charts)
LEVELS = (
    ("fact", "Measured facts", "Measured fact"),
    ("inference", "Derived inferences", "Derived inference"),
    ("assumption", "Unmeasured assumptions", "Unmeasured assumption"),
)

META_LABELS = (
    ("prepared_for", "Prepared for"),
    ("prepared_by", "Prepared by"),
    ("decision_date", "Decision date"),
    ("status", "Status"),
)

# A segment of the evidence bar narrower than this keeps its percentage in the
# legend only: at 375px a label needs about 11% of the bar to fit.
THIN_SEGMENT = 0.12
# A 375px phone leaves 313px inside a section; the compact cash table pads its
# five cells by 24px in all (see the max-width: 560px rules in CSS).
PHONE_CONTENT_WIDTH = 313.0
PHONE_CELL_PADDING = 24.0

# The tornado's axis is at its narrowest in the narrowest window each layout
# serves: 320px for the phone layout and 761px for the wide one. These mirror
# the stylesheet: page padding, section padding and border, the name column,
# and the least each gutter beside the plot takes (--gut). A test holds them
# to the CSS.
PHONE_MIN_WINDOW = 320.0
WIDE_MIN_WINDOW = 761.0
_PAGE_PAD = {"phone": 14.0, "wide": 28.0}
_SECTION_PAD = {"phone": 16.0, "wide": 26.0}
_SECTION_BORDER = 1.0
_NAME_COLUMN = {"phone": 0.0, "wide": 0.34}
_MIN_GUTTER = {"phone": 58.0, "wide": 70.0}
# Axis labels are 12px; neighbours keep at least this much clear space.
AXIS_FONT = 12.0
AXIS_GAP = 8.0

# Ledger values are 13.5px. The longest the ledger keeps on one line on a wide
# screen, by the _text_width estimate: room for "1.8 minutes per ticket"
# (181px) with a margin for long input names in the next column.
LEDGER_FONT = 13.5
LEDGER_ONE_LINE = 200.0


# -- scales and labels ----------------------------------------------------


class Scale:
    """A linear axis with ticks at clean round values.

    Steps are 1, 2, or 5 times a power of ten. A 2.5 step is deliberately
    excluded: its ticks (1.25M) would round to the same one-decimal label as
    a neighbour, and an axis that prints "$1.2M" twice is worse than none.
    The ends of the axis snap outward to half a step, so the data fills the
    chart without a near-empty interval at either edge; ticks are the whole
    steps inside that span.
    """

    __slots__ = ("exponent", "hi", "lo", "step", "ticks")

    def __init__(
        self, lo: float, hi: float, ticks: List[float], step: float, exponent: int
    ) -> None:
        self.lo = lo
        self.hi = hi
        self.ticks = ticks
        self.step = step
        self.exponent = exponent

    def fraction(self, value: float) -> float:
        """Where ``value`` sits along the axis: 0 at ``lo``, 1 at ``hi``."""
        return (value - self.lo) / (self.hi - self.lo)


def _times_power_of_ten(multiple: int, exponent: int) -> float:
    # Dividing by an exact power of ten keeps 0.3 as the double nearest 0.3,
    # where multiplying by 0.1 would drift to 0.30000000000000004.
    if exponent >= 0:
        return float(multiple * 10**exponent)
    return multiple / float(10 ** (-exponent))


def nice_scale(
    values: Iterable[Optional[float]],
    include_zero: bool = False,
    max_intervals: int = 6,
    min_span: float = 0.0,
) -> Scale:
    """The tightest clean axis that holds every finite value.

    Non-finite and missing values are ignored rather than allowed to turn the
    whole chart into NaN. A flat series is given a band around its value so
    there is still an axis to draw. ``min_span`` widens a narrower spread
    evenly about its middle, so a tiny difference is not stretched to fill
    the chart.
    """
    finite = [float(v) for v in values if v is not None and math.isfinite(v)]
    lo = min(finite) if finite else 0.0
    hi = max(finite) if finite else 0.0
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi - lo < min_span:
        middle = (lo + hi) / 2
        lo, hi = middle - min_span / 2, middle + min_span / 2
    if hi == lo:
        pad = abs(lo) or 1.0
        lo, hi = lo - pad, hi + pad

    # Work in units of 10**(exponent - 1) so a step and its half are both
    # whole numbers of units: 1 -> 10 and 5, 2 -> 20 and 10, 5 -> 50 and 25.
    exponent = math.floor(math.log10((hi - lo) / max_intervals))
    while True:
        unit = _times_power_of_ten(1, exponent - 1)
        for digit in (1, 2, 5):
            step_units, half_units = digit * 10, digit * 5
            # The epsilon keeps 0.3 / 0.1 == 2.9999999999999996 from adding
            # an empty half step at either end.
            first = math.floor(lo / unit / half_units + 1e-9) * half_units
            last = math.ceil(hi / unit / half_units - 1e-9) * half_units
            if last - first > max_intervals * step_units:
                continue
            ticks = [
                _times_power_of_ten(k * step_units, exponent - 1)
                for k in range(-((-first) // step_units), last // step_units + 1)
            ]
            return Scale(
                _times_power_of_ten(first, exponent - 1),
                _times_power_of_ten(last, exponent - 1),
                ticks,
                _times_power_of_ten(step_units, exponent - 1),
                exponent,
            )
        exponent += 1


def tick_label(value: float, exponent: int, currency: str = "USD") -> str:
    """An axis label with exactly the precision the tick step needs.

    ``fmt_currency`` rounds to one decimal of k/M/B, which is right for a
    figure and wrong for an axis: ticks 20k apart around $1.05M would all read
    "$1.1M". Here the decimals follow the step's power of ten instead.
    """
    symbol = currency_symbol(currency)
    if value == 0:
        return "%s0" % symbol
    magnitude = abs(value)
    unit, suffix = 0, ""
    for power, letter in ((9, "B"), (6, "M"), (3, "k")):
        if magnitude >= 10**power:
            unit, suffix = power, letter
            break
    decimals = max(0, unit - exponent)
    # No thousands separator, matching fmt_currency's "$4400B".
    text = "{:.{d}f}".format(magnitude / 10**unit, d=decimals)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "%s%s%s%s" % ("-" if value < 0 else "", symbol, text, suffix)


def currency_step(value: float) -> float:
    """The step :func:`fmt_currency` rounds ``value`` to.

    $100 at $74.9k, $100k at $1.2M, a dollar below $1,000, a cent below $1.
    """
    magnitude = abs(value)
    for power in (9, 6, 3):
        if magnitude >= 10**power:
            return 10.0 ** (power - 1)
    return 1.0 if magnitude >= 1 else 0.01


_NARROW = frozenset(" .,:;'!|il()[]-")
_WIDE = frozenset("MWmw%@—")


def _text_width(text: str, size: float) -> float:
    """Rough rendered width of ``text`` in a sans-serif face at ``size`` px.

    Only used to reserve room for labels, so it errs wide: the em widths sit
    at or above semibold system-ui as Chrome draws it ("-$200k" is 44.2px at
    12px; this says 45.4). Capitals are wide, and a currency code such as
    "CHF " is mostly capitals.
    """
    ems = 0.0
    for ch in text:
        if ch in _NARROW:
            ems += 0.38
        elif ch in _WIDE:
            ems += 0.95
        elif ch.isupper():
            ems += 0.8
        else:
            ems += 0.68
    return ems * size


def _pc(fraction: float) -> str:
    """A CSS percentage from a 0..1 fraction, clamped and trimmed."""
    value = min(100.0, max(0.0, fraction * 100.0))
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return (text or "0") + "%"


def _n(value: float) -> str:
    """An SVG coordinate: one decimal, trimmed, never ``-0``."""
    text = ("%.1f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _e(value: Any) -> str:
    """Escape anything for HTML text or a double-quoted attribute."""
    return escape("" if value is None else str(value), quote=True)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _class_attr(*names: str) -> str:
    """A ``class`` attribute for the non-empty ``names``, or nothing."""
    joined = " ".join(name for name in names if name)
    return ' class="%s"' % joined if joined else ""


class _Money:
    """``fmt_currency`` for one currency, refusing to print a non-number."""

    def __init__(self, currency: str) -> None:
        self.currency = currency

    def __call__(self, value: Optional[float]) -> str:
        if value is None or not _finite(value):
            return "n/a"
        return fmt_currency(value, self.currency)


# -- shared fragments -----------------------------------------------------


def _chip(level: str) -> str:
    return '<span class="chip"><i class="sw %s"></i>%s</span>' % (_e(level), _e(level))


def _legend(items: Sequence[Tuple[str, str]], extra: str = "") -> str:
    lis = "".join('<li><i class="%s"></i>%s</li>' % (_e(c), text) for c, text in items)
    return '<ul class="legend"%s>%s</ul>\n' % (extra, lis)


def _row_drivers(row: Mapping[str, Any], labels: Mapping[str, str]) -> str:
    """Driver label(s) for a sensitivity row, one per driver a shared input feeds."""
    if row.get("applies_to"):
        ids = [item["driver_id"] for item in row["applies_to"]]
        return "; ".join(dict.fromkeys(labels.get(i, i) for i in ids))
    return str(row["driver_label"])


def _range_text(low: float, high: float) -> str:
    return "%s to %s" % (fmt_multiple(low), fmt_multiple(high))


def _table(
    label: str,
    headers: Sequence[Tuple[str, str]],
    rows: Sequence[Sequence[str]],
    layout: str = "stack",
) -> str:
    """A table; ``headers`` are (text, css class) and row cells are raw HTML.

    On a phone a ``stack`` table shows each row as a card with every value
    beside its column name (``data-label``), so no column scrolls out of view
    and no number is cut off at the edge. A ``compact`` table stays a grid at
    a smaller size, for short numeric columns that fit a phone as they are.
    """
    head = "".join(
        '<th%s scope="col">%s</th>' % (' class="%s"' % c if c else "", _e(t))
        for t, c in headers
    )
    body = []
    for row in rows:
        cells = "".join(
            '<td%s data-label="%s">%s</td>'
            % (
                ' class="%s"' % headers[i][1] if headers[i][1] else "",
                _e(headers[i][0]),
                cell,
            )
            for i, cell in enumerate(row)
        )
        body.append("<tr>%s</tr>" % cells)
    return (
        '<div class="table-wrap"><table class="%s" aria-label="%s">\n'
        "<thead><tr>%s</tr></thead>\n<tbody>\n%s\n</tbody>\n</table></div>\n"
        % (layout, _e(label), head, "\n".join(body))
    )


# -- sections -------------------------------------------------------------


def _header(case: Any) -> str:
    out = [
        '<header class="top">\n<div class="kicker">Business case</div>\n',
        "<h1>%s</h1>\n" % _e(case.name),
        '<p class="basis">%s</p>\n' % _e(case.basis()),
    ]
    items = _meta_items(case.meta)
    if items:
        out.append('<dl class="meta">')
        out.extend(
            "<div><dt>%s</dt><dd>%s</dd></div>" % (_e(k), _e(v)) for k, v in items
        )
        out.append("</dl>\n")
    out.append("</header>\n")
    return "".join(out)


def _meta_items(meta: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Every non-empty meta field: the four known ones first, then the rest.

    ``meta`` is free-form and passed through, so nothing in it is dropped;
    nested values are shown as compact JSON.
    """
    known = dict(META_LABELS)
    keys = [k for k, _ in META_LABELS if k in meta]
    keys += [k for k in meta if k not in known]
    items = []
    for key in keys:
        value = meta[key]
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            text = str(value)
        label = known.get(key) or str(key).replace("_", " ").strip().capitalize()
        items.append((label or "Note", text))
    return items


def _headline(case: Any) -> str:
    rows = case.headline()
    (npv_label, npv_text), tiles, (_, safety) = rows[0], rows[1:-1], rows[-1]
    size = "" if len(npv_text) <= 8 else (" l2" if len(npv_text) <= 11 else " l3")
    # The hero figure must stay on one line in any width its cell gets, a
    # narrow window or a printed page included. Its estimated width in ems
    # (less the -0.035em tracking) gives the largest font, in cqi of the cell,
    # that still fits; CSS caps it at the design size.
    ems = _text_width(npv_text, 1.0) - 0.035 * len(npv_text)
    fit = math.floor(1000.0 / max(ems, 1.0)) / 10
    sub = "Base case, %d year%s at %s" % (
        case.horizon,
        "" if case.horizon == 1 else "s",
        fmt_pct(case.discount_rate),
    )
    out = [
        '<section class="kpis" aria-label="Headline">\n',
        '<div class="kpi hero"><div class="label">%s</div>'
        '<div class="value num%s" style="--fit: %s">%s</div>'
        '<div class="sub">%s</div></div>\n'
        % (_e(npv_label), size, fit, _e(npv_text), _e(sub)),
    ]
    for label, text in tiles:
        # A sentence such as "never within the modeled horizon" is the honest
        # value for some cases; it gets a text size rather than a truncation.
        # So does a value in words ("immediate", "n/a"): at figure size one
        # word can outgrow a 320px phone's tile, and must not break mid-word.
        words = not any(ch.isdigit() for ch in text)
        long = " long" if len(text) > 14 or words else ""
        out.append(
            '<div class="kpi"><div class="label">%s</div>'
            '<div class="value num%s">%s</div></div>\n' % (_e(label), long, _e(text))
        )
    out.append("</section>\n")
    end = "" if safety.endswith((".", "!", "?")) else "."
    out.append(
        '<p class="safety"><b>Margin of safety:</b> %s%s</p>\n' % (_e(safety), end)
    )
    return "".join(out)


def _evidence(data: Mapping[str, Any], labels: Mapping[str, str]) -> str:
    ev = data["evidence"]
    grade = str(ev["grade"])
    shares = [
        (level, plural, float(ev["share_%s" % level])) for level, plural, _ in LEVELS
    ]
    out = [
        '<section aria-labelledby="h-evidence">\n<div class="grade">\n',
        '<div class="badge%s" role="img" aria-label="Evidence grade %s">'
        "<div>%s<small>Grade</small></div></div>\n"
        % (" wide" if len(grade) > 1 else "", _e(grade), _e(grade)),
        '<div>\n<h2 id="h-evidence">Evidence grade: %s</h2>\n' % _e(grade),
        '<p class="lede tight">%s</p>\n' % _e(_without_grade(ev["headline"], grade)),
    ]
    if ev.get("total_value_graded", 0) > 0:
        described = ", ".join("%s %s" % (p.lower(), fmt_pct(s)) for _, p, s in shares)
        out.append(
            '<div class="seg" role="img" aria-label="%s">'
            % _e("Share of modeled value by evidence: " + described)
        )
        for level, plural, share in shares:
            grow = "%.1f" % (share * 100)
            if grow == "0.0":
                continue
            # A sliver too narrow for its label keeps the number in the
            # legend and the tooltip rather than clipping it in the bar.
            thin = share < THIN_SEGMENT
            out.append(
                '<span class="%s%s" style="flex: %s 1 0" title="%s: %s of modeled value">%s</span>'
                % (
                    level,
                    " thin" if thin else "",
                    grow,
                    _e(plural),
                    _e(fmt_pct(share)),
                    "" if thin else _e(fmt_pct(share)),
                )
            )
        out.append("</div>\n")
        out.append(
            _legend(
                [
                    (
                        "sw %s" % level,
                        '%s <b class="num">%s</b>' % (_e(plural), _e(fmt_pct(share))),
                    )
                    for level, plural, share in shares
                ]
            )
        )
    out.append("</div>\n</div>\n")

    largest = ev.get("largest_assumption")
    top = next(
        (r for r in data["sensitivity"] if r["confidence"] == "assumption"), None
    )
    if largest and top is not None:
        out.append(
            '<div class="callout">\n<h3>Measure this first: <code>%s</code></h3>\n'
            '<p class="drv">%s</p>\n<p>%s</p>\n</div>\n'
            % (
                _e(largest["input"]),
                _e(_row_drivers(top, labels)),
                _e(largest["advice"]),
            )
        )
    out.append("</section>\n")
    return "".join(out)


def _without_grade(headline: str, grade: str) -> str:
    """The evidence headline minus its "Grade C." lead; the heading says it."""
    lead = "Grade %s. " % grade
    return headline[len(lead) :] if headline.startswith(lead) else headline


def _sensitivity(
    data: Mapping[str, Any], money: _Money, labels: Mapping[str, str]
) -> str:
    rows = data["sensitivity"]
    out = [
        '<section aria-labelledby="h-sens">\n'
        '<h2 id="h-sens">What would have to be true</h2>\n'
    ]
    if not rows:
        out.append('<p class="lede">%s</p>\n</section>\n' % _e(NO_RANGE_NOTE))
        return "".join(out)
    out.append(
        '<p class="lede">Each bar swings one input across its stated range while '
        "everything else holds at base. Sorted by how much the decision moves.</p>\n"
    )
    out.append(_tornado(rows, data["summary"]["npv"], money, labels))
    table_rows = [
        [
            '<b>%s</b><span class="under">%s</span>'
            % (_e(row["input"]), _e(_row_drivers(row, labels))),
            _chip(row["confidence"]),
            _e(_range_text(row["low"], row["high"])),
            _e(money(row["npv_low"])),
            _e(money(row["npv_high"])),
            "yes" if row["flips_decision"] else "no",
        ]
        for row in rows
    ]
    out.append(
        _table(
            "Sensitivity of NPV to each ranged input",
            [
                ("Input", "label"),
                ("Confidence", ""),
                ("Range", "nowrap"),
                ("NPV at low", "n"),
                ("NPV at high", "n"),
                ("Flips decision", ""),
            ],
            table_rows,
        )
    )
    out.append("</section>\n")
    return "".join(out)


def tornado_axis_width(layout: str, tip: int) -> float:
    """The tornado axis in px at the narrowest window ``layout`` serves.

    ``layout`` is "phone" or "wide"; ``tip`` is the chart's --tip gutter in px.
    """
    window = PHONE_MIN_WINDOW if layout == "phone" else WIDE_MIN_WINDOW
    content = window - 2 * (_PAGE_PAD[layout] + _SECTION_PAD[layout] + _SECTION_BORDER)
    gutter = max(_MIN_GUTTER[layout], float(tip))
    return content * (1 - _NAME_COLUMN[layout]) - 2 * gutter


def _label_stride(widest: float, step_px: float, count: int, every: int = 1) -> int:
    """How many ticks apart axis labels must sit so neighbours never touch.

    The smallest multiple of ``every`` whose spacing clears the widest label
    plus AXIS_GAP. ``count`` or more leaves a single label.
    """
    stride = every
    while stride < count and stride * step_px < widest + AXIS_GAP:
        stride += every
    return stride


def _tornado(
    rows: Sequence[Mapping[str, Any]],
    base: float,
    money: _Money,
    labels: Mapping[str, str],
) -> str:
    """One row per ranged input on one shared NPV axis, base line marked."""
    values = [base] + [r[k] for r in rows for k in ("npv_low", "npv_high")]
    # A bar must not stretch a difference the printed figures round away: the
    # axis spans at least ten of the steps fmt_currency rounds to, so a swing
    # of $2.50 on a -$74.9k base stays a sliver beside labels that agree.
    rounding = max([currency_step(v) for v in values if _finite(v)] or [0.0])
    scale = nice_scale(values, min_span=10 * rounding)
    frac = scale.fraction
    base_at = frac(base) if _finite(base) else 0.0
    tips: List[str] = []
    described = []
    body = []
    for row in rows:
        name = str(row["input"])
        ordered = row["npv_low"] <= row["npv_high"]
        lo_value, hi_value = (
            (row["npv_low"], row["npv_high"])
            if ordered
            else (row["npv_high"], row["npv_low"])
        )
        lo_bound, hi_bound = (
            (row["low"], row["high"]) if ordered else (row["high"], row["low"])
        )
        plot = []
        if _finite(lo_value) and lo_value < base:
            plot.append(
                '<div class="bar below" style="left: %s; width: %s" title="%s"></div>'
                % (
                    _pc(frac(lo_value)),
                    _pc(base_at - frac(lo_value)),
                    _e(
                        "%s at %s: NPV %s"
                        % (name, fmt_multiple(lo_bound), money(lo_value))
                    ),
                )
            )
        if _finite(hi_value) and hi_value > base:
            plot.append(
                '<div class="bar above" style="left: %s; width: %s" title="%s"></div>'
                % (
                    _pc(base_at),
                    _pc(frac(hi_value) - base_at),
                    _e(
                        "%s at %s: NPV %s"
                        % (name, fmt_multiple(hi_bound), money(hi_value))
                    ),
                )
            )
        if _finite(lo_value) and lo_value < base:
            tips.append(money(lo_value))
            plot.append(
                '<span class="tip lo" style="left: %s">%s</span>'
                % (_pc(frac(lo_value)), _e(money(lo_value)))
            )
        if _finite(hi_value) and hi_value > base:
            tips.append(money(hi_value))
            plot.append(
                '<span class="tip hi" style="left: %s">%s</span>'
                % (_pc(frac(hi_value)), _e(money(hi_value)))
            )
        if not plot:
            # The input moves nothing. Say so beside the base line, toward the
            # middle of the axis, so the note never needs a gutter of its own.
            plot.append(
                '<span class="tip %s quiet" style="left: %s">no change</span>'
                % ("hi" if base_at <= 0.5 else "lo", _pc(base_at))
            )
        flag = ""
        if row["flips_decision"]:
            flag = (
                '<div class="flag"><svg viewBox="0 0 12 12" aria-hidden="true" '
                'focusable="false"><path d="M6 1 11.5 11H.5z"/></svg>'
                "Crosses break-even inside its range</div>"
            )
        body.append(
            '<div class="t-row">\n<div class="t-name"><code>%s</code><span>%s</span>'
            '<span class="rng">%s · %s</span>%s</div>\n<div class="t-plot">%s</div>\n</div>\n'
            % (
                _e(name),
                _e(_row_drivers(row, labels)),
                _e(row["confidence"]),
                _e(_range_text(row["low"], row["high"])),
                flag,
                "".join(plot),
            )
        )
        described.append(
            "%s %s to %s%s"
            % (
                name,
                money(row["npv_low"]),
                money(row["npv_high"]),
                ", crosses break-even" if row["flips_decision"] else "",
            )
        )

    ticks = [(t, tick_label(t, scale.exponent, money.currency)) for t in scale.ticks]
    # The gutters either side of the plot must hold the widest end label: a
    # bar can end at either edge of the axis, and its label sits outside it.
    gutter = max([_text_width(t, 12.5) for t in tips] or [0.0]) + 14
    tip = math.ceil(gutter)
    # Label every k-th tick, counted from zero when the axis has it, with k as
    # small as the narrowest window of each layout allows. A phone labels a
    # subset of the ticks a wide window labels, and hides the other gridlines.
    widest = max(_text_width(text, AXIS_FONT) for _, text in ticks)
    values = [t for t, _ in ticks]
    start = values.index(0.0) if 0.0 in values else 0
    step_px = {
        layout: tornado_axis_width(layout, tip) * scale.step / (scale.hi - scale.lo)
        for layout in ("wide", "phone")
    }
    every = _label_stride(widest, step_px["wide"], len(ticks))
    every_phone = _label_stride(widest, step_px["phone"], len(ticks), every)
    shown = [
        (t, text, (i - start) % every_phone == 0)
        for i, (t, text) in enumerate(ticks)
        if (i - start) % every == 0
    ]
    caption = (
        "Net present value when one input moves to the low or high end of its "
        "stated range."
    )
    # The axis spans the data, not zero, so say when zero is off the chart.
    if scale.lo > 0:
        caption += (
            " The axis does not start at zero: no input takes NPV below zero at "
            "either end of its range."
        )
    elif scale.hi < 0:
        caption += (
            " The axis does not reach zero: no input lifts NPV above zero at "
            "either end of its range."
        )
    base_label = "Base case %s" % money(base)
    anchor = "start" if base_at < 0.18 else ("end" if base_at > 0.82 else "mid")
    lines = "".join(
        '<i%s style="left: %s"></i>'
        % (_class_attr("zero" if t == 0 else "", "" if phone else "wide"), _pc(frac(t)))
        for t, _, phone in shown
    )
    axis = "".join(
        '<span%s style="left: %s">%s</span>'
        % (_class_attr("" if phone else "wide"), _pc(frac(t)), _e(text))
        for t, text, phone in shown
    )
    aria = (
        "Tornado chart of net present value at the low and high end of each ranged input, against a base case of %s. %s."
        % (
            money(base),
            "; ".join(described),
        )
    )
    return (
        '<figure>\n<div class="tornado" role="group" aria-label="%s" style="--tip: %dpx">\n'
        '<div class="t-top"><span class="%s" style="left: %s">%s</span></div>\n'
        '<div class="t-lines">%s<i class="base" style="left: %s"></i></div>\n'
        '%s<div class="t-axis">%s</div>\n</div>\n%s'
        "<figcaption>%s</figcaption>\n</figure>\n"
        % (
            _e(aria),
            tip,
            anchor,
            _pc(base_at),
            _e(base_label),
            lines,
            _pc(base_at),
            "".join(body),
            axis,
            _legend(
                [
                    ("sw below", "NPV below the base case"),
                    ("sw above", "NPV above the base case"),
                ]
            ),
            _e(caption),
        )
    )


def _cash_flow(case: Any, data: Mapping[str, Any], money: _Money) -> str:
    flows = data["cash_flows"]
    benefits, costs, net = flows["benefits"], flows["costs"], flows["net"]
    running = finance.cumulative(net)
    periods = ["Today" if p == 0 else "Year %d" % p for p in range(case.horizon + 1)]
    aria = (
        "Net cash flow by period with cumulative total. %s. Cumulative ends at %s."
        % (
            ", ".join("%s %s" % (p, money(v)) for p, v in zip(periods, net)),
            money(running[-1]),
        )
    )
    headers = [
        ("Period", "nowrap"),
        ("Benefit", "n"),
        ("Cost", "n"),
        ("Net", "n"),
        ("Cumulative", "n"),
    ]
    texts = [
        [
            periods[i],
            money(benefits[i]),
            money(-costs[i]),
            money(net[i]),
            money(running[i]),
        ]
        for i in range(len(periods))
    ]
    # Five columns fit a 375px phone at the compact size unless the amounts
    # are long (a code such as "CHF " before each one); then every period
    # becomes a card of four labelled values on any phone.
    needed = PHONE_CELL_PADDING + sum(
        max([_text_width(h, 11.0)] + [_text_width(row[i], 12.0) for row in texts])
        for i, (h, _) in enumerate(headers)
    )
    layout = "compact" if needed <= PHONE_CONTENT_WIDTH else "compact cards"
    rows = [[_e(cell) for cell in row] for row in texts]
    return "".join(
        [
            '<section aria-labelledby="h-cash">\n<h2 id="h-cash">Cash flow</h2>\n',
            '<p class="lede">Net cash by period, and the running total.</p>\n',
            '<figure class="cash">\n',
            # Two drawings of the same data: an SVG scales its text with its
            # width, so a phone gets a narrower canvas rather than 4px labels.
            _cash_svg(periods, net, running, money, aria, 880, 300, 12.0, "wide"),
            _cash_svg(periods, net, running, money, aria, 360, 280, 13.0, "narrow"),
            _legend(
                [
                    ("sw above", "Net inflow"),
                    ("sw below", "Net outflow"),
                    ("key-line", "Cumulative"),
                ]
            ),
            "</figure>\n",
            _table("Cash flow by period", headers, rows, layout=layout),
            "</section>\n",
        ]
    )


def _bar_path(x: float, base_y: float, width: float, height: float, up: bool) -> str:
    """A bar from the zero line, rounded only at its far end."""
    r = min(4.0, height, width / 2)
    inner = width - 2 * r
    if up:
        return "M%s %sv%sa%s %s 0 0 1 %s %sh%sa%s %s 0 0 1 %s %sv%sz" % tuple(
            _n(v)
            for v in (
                x,
                base_y,
                -(height - r),
                r,
                r,
                r,
                -r,
                inner,
                r,
                r,
                r,
                r,
                height - r,
            )
        )
    return "M%s %sh%sv%sa%s %s 0 0 1 %s %sh%sa%s %s 0 0 1 %s %sz" % tuple(
        _n(v) for v in (x, base_y, width, height - r, r, r, -r, r, -inner, r, r, -r, -r)
    )


def _overlaps(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _cash_svg(
    periods: Sequence[str],
    net: Sequence[float],
    running: Sequence[float],
    money: _Money,
    aria: str,
    width: int,
    height: int,
    font: float,
    variant: str,
) -> str:
    """Net bars per period from a zero line, with the cumulative line on top."""
    scale = nice_scale(list(net) + list(running), include_zero=True)
    ticks = [(t, tick_label(t, scale.exponent, money.currency)) for t in scale.ticks]
    count = len(periods)
    left = max(
        64.0 if width > 600 else 40.0, 14 + max(_text_width(t, font) for _, t in ticks)
    )
    # Leave room right of the last period for the cumulative end label, but
    # keep the full width when it already fits.
    end_text = money(running[-1])
    end_width = _text_width(end_text, font)
    half = 1.0 / (2 * count)
    right = min(
        width - 20.0,
        (width - 16.0 - 12.0 - end_width - left * half) / (1 - half),
    )
    # Only a currency code far longer than ISO's three letters gets here: keep
    # the drawing valid and leave the labels to the table below it.
    left = min(left, width * 0.4)
    right = max(right, left + (width - 20.0 - left) * 0.5)
    top, bottom = 24.0, height - 50.0
    slot = (right - left) / count
    bar = min(24.0, slot * 0.42)

    def y(value: float) -> float:
        return bottom - scale.fraction(value) * (bottom - top)

    zero = y(0.0)
    centers = [left + slot * (i + 0.5) for i in range(count)]
    out = [
        '<svg class="%s" viewBox="0 0 %d %d" role="img" aria-label="%s">'
        % (variant, width, height, _e(aria))
    ]
    for value, text in ticks:
        ty = y(value)
        out.append(
            '<line class="%s" x1="%s" x2="%s" y1="%s" y2="%s"/>'
            % ("z" if value == 0 else "g", _n(left), _n(right), _n(ty), _n(ty))
        )
        out.append(
            '<text x="%s" y="%s" text-anchor="end">%s</text>'
            % (_n(left - 10), _n(ty + font / 3), _e(text))
        )

    boxes: List[Tuple[float, float, float, float]] = []
    for i, value in enumerate(net):
        if not _finite(value) or value == 0:
            continue
        height_px = abs(y(value) - zero)
        x = centers[i] - bar / 2
        out.append(
            '<path class="%s" d="%s"><title>%s</title></path>'
            % (
                "pos" if value > 0 else "neg",
                _bar_path(x, zero, bar, height_px, value > 0),
                _e("%s: net %s" % (periods[i], money(value))),
            )
        )
        boxes.append((x, min(zero, y(value)), x + bar, max(zero, y(value))))

    points = [(cx, y(v) if _finite(v) else zero) for cx, v in zip(centers, running)]
    out.append(
        '<polyline class="line" points="%s"/>'
        % " ".join("%s,%s" % (_n(px), _n(py)) for px, py in points)
    )
    for (px, py), period, value in zip(points, periods, running):
        out.append(
            '<circle class="dot" cx="%s" cy="%s" r="4.5"><title>%s</title></circle>'
            % (_n(px), _n(py), _e("%s: cumulative %s" % (period, money(value))))
        )
        boxes.append((px - 5, py - 5, px + 5, py + 5))

    # Label where the cumulative line ends, and its lowest point (the most
    # cash at risk) when that is a deficit somewhere earlier.
    px, py = points[-1]
    x = px + bar / 2 + 8
    out.append(
        '<text class="v" x="%s" y="%s">%s</text>'
        % (_n(x), _n(py + font / 3), _e(end_text))
    )
    boxes.append((x, py - font, x + end_width, py + font / 2))
    finite_running = [v if _finite(v) else 0.0 for v in running]
    trough = min(range(count), key=lambda i: finite_running[i])
    if trough != count - 1 and finite_running[trough] < 0:
        text = money(running[trough])
        tw = _text_width(text, font)
        tx, ty = points[trough][0] + bar / 2 + 8, points[trough][1] + font + 7
        for candidate, anchor in (
            (tx, "start"),
            (points[trough][0] - bar / 2 - 8, "end"),
        ):
            x0 = candidate if anchor == "start" else candidate - tw
            box = (x0, ty - font, x0 + tw, ty + font / 3)
            if (
                box[0] >= 2
                and box[2] <= width - 2
                and not any(_overlaps(box, b) for b in boxes)
            ):
                out.append(
                    '<text class="v" x="%s" y="%s"%s>%s</text>'
                    % (
                        _n(candidate),
                        _n(ty),
                        "" if anchor == "start" else ' text-anchor="end"',
                        _e(text),
                    )
                )
                break

    # Period names: in full when they fit the slot, then short, then every
    # other one. The table below always carries all of them.
    short = ["Now" if p == "Today" else p.replace("Year ", "Y") for p in periods]
    if max(_text_width(p, font) for p in periods) + 8 <= slot:
        names, every = periods, 1
    elif max(_text_width(p, font) for p in short) + 6 <= slot:
        names, every = short, 1
    else:
        names, every = short, 2
    shown = set(range(0, count, every))
    if count - 1 not in shown:
        # Always name the last period; drop its neighbour to make room.
        shown.discard(count - 2)
        shown.add(count - 1)
    for i, name in enumerate(names):
        if i in shown:
            out.append(
                '<text x="%s" y="%s" text-anchor="middle">%s</text>'
                % (_n(centers[i]), _n(height - 8), _e(name))
            )
    out.append("</svg>\n")
    return "".join(out)


def _drivers(data: Mapping[str, Any], money: _Money) -> str:
    rows = [
        [
            _e(row["label"]),
            _chip(row["confidence"]),
            _e(money(row["annual_run_rate"])),
            _e(fmt_pct(row["realization"])),
            _e(money(row["npv"])),
        ]
        for row in data["drivers"]
    ]
    return (
        '<section aria-labelledby="h-drivers">\n<h2 id="h-drivers">Value drivers</h2>\n'
        '<p class="lede">Each benefit stream at full run rate, the haircut applied to '
        "it, and its NPV. Weakest link is the softest evidence among its inputs.</p>\n"
        + _table(
            "Value drivers",
            [
                ("Driver", "label"),
                ("Weakest link", ""),
                ("Annual run rate", "n"),
                ("Realization", "n"),
                ("NPV", "n"),
            ],
            rows,
        )
        + "</section>\n"
    )


def _attribution(data: Mapping[str, Any], money: _Money) -> str:
    rows = data["evidence"]["by_input"]
    biggest = max(
        [abs(r["npv_attributed"]) for r in rows if _finite(r["npv_attributed"])]
        or [0.0]
    )
    values = [money(r["npv_attributed"]) for r in rows]
    reserve = max([_text_width(v, 12.5) for v in values] or [0.0]) + 14
    singular = {level: one for level, _, one in LEVELS}
    out = [
        '<section aria-labelledby="h-attr">\n'
        '<h2 id="h-attr">Where the value actually comes from</h2>\n'
        '<p class="lede">Each driver\'s NPV split across its inputs by proportional '
        "sensitivity. The first row is the number carrying the most weight in the "
        "entire case.</p>\n<figure>\n"
        '<div class="ranked" role="group" aria-label="NPV attributed to each input, '
        'largest first, colored by confidence" style="--valw: %dpx">\n'
        % math.ceil(reserve)
    ]
    negative = False
    for row, text in zip(rows, values):
        value = row["npv_attributed"]
        share = abs(value) / biggest if biggest > 0 and _finite(value) else 0.0
        negative = negative or (_finite(value) and value < 0)
        out.append(
            '<div class="r-name"><code>%s</code><span>%s</span></div>'
            '<div class="r-plot"><i class="r-bar %s" style="width: %s" title="%s"></i>'
            '<span class="r-val" style="left: %s">%s</span></div>\n'
            % (
                _e(row["input"]),
                _e(row["driver_label"]),
                _e(row["confidence"]),
                _pc(share),
                _e(
                    "%s: %s, %s of this driver's NPV"
                    % (
                        singular.get(row["confidence"], row["confidence"]),
                        text,
                        fmt_pct(row["share_of_driver"]),
                    )
                ),
                _pc(share),
                _e(text),
            )
        )
    out.append("</div>\n")
    out.append(
        _legend(
            [("sw %s" % level, _e(one)) for level, _, one in LEVELS],
            ' style="margin-top: 14px"',
        )
    )
    if negative:
        out.append(
            "<figcaption>Bar length is the size of each input's share; a minus "
            "sign marks value it takes away.</figcaption>\n"
        )
    out.append("</figure>\n</section>\n")
    return "".join(out)


def _floor(data: Mapping[str, Any], money: _Money) -> str:
    floor = data["floor_case"]
    holds = bool(floor["still_positive"])
    verdict = (
        "<b>%s</b>%s" % (_e(FLOOR_HOLDS[0]), _e(FLOOR_HOLDS[1]))
        if holds
        else _e(FLOOR_FAILS)
    )
    return (
        '<section class="floor%s" aria-labelledby="h-floor">\n<h2 id="h-floor">Floor case</h2>\n'
        '<p class="lede tight">%s</p>\n<ul>\n'
        "<li>NPV at the floor: <b>%s</b> (%s vs base)</li>\n"
        "<li>Discounted payback at the floor: %s</li>\n<li>%s</li>\n</ul>\n</section>\n"
        % (
            " holds" if holds else "",
            _e(FLOOR_NOTE),
            _e(money(floor["npv"])),
            _e(money(floor["delta_vs_base"])),
            _e(fmt_periods(floor["payback_periods"])),
            verdict,
        )
    )


def _ledger_value(text: str) -> str:
    """A ledger value, kept on one line on a wide screen unless it is long.

    The ledger is 870px wide there, and its other four columns need about
    560px; a value past LEDGER_ONE_LINE (estimated) may wrap at any width,
    so a long unit cannot push the Source column off the card.
    """
    if _text_width(text, LEDGER_FONT) <= LEDGER_ONE_LINE:
        return _e(text)
    return '<span class="long">%s</span>' % _e(text)


def _ledger(case: Any) -> str:
    rows = []
    for driver in case.drivers:
        for name, inp in driver.inputs.items():
            low, high = inp.range
            rows.append(
                [
                    '<b>%s</b><span class="under">%s</span>'
                    % (_e(name), _e(driver.label)),
                    _ledger_value(
                        fmt_multiple(inp.value) + (" %s" % inp.unit if inp.unit else "")
                    ),
                    _chip(inp.confidence),
                    _e(
                        "%s–%s" % (fmt_multiple(low), fmt_multiple(high))
                        if inp.swing
                        else "point estimate"
                    ),
                    _e(inp.source),
                ]
            )
    return (
        '<section aria-labelledby="h-ledger">\n<h2 id="h-ledger">Assumption ledger</h2>\n'
        '<p class="lede">Every number in this model, what kind of number it is, and '
        "where it came from.</p>\n"
        + _table(
            "Assumption ledger",
            [
                ("Input", "label"),
                ("Value", "n wrap"),
                ("Confidence", ""),
                ("Range", "nowrap"),
                ("Source", "src"),
            ],
            rows,
        )
        + "</section>\n"
    )


def _costs(case: Any, money: _Money) -> str:
    rows = [
        [_e(cost.label), _e(money(sum(cost.schedule))), _e(cost.note or "")]
        for cost in case.costs
    ]
    return (
        '<section aria-labelledby="h-costs">\n<h2 id="h-costs">Cost lines</h2>\n'
        '<p class="lede">Each cost the case carries, summed across the horizon.</p>\n'
        + _table(
            "Cost lines", [("Cost", "label"), ("Total", "n"), ("Note", "src")], rows
        )
        + "</section>\n"
    )


def render_value_case(case: Any) -> str:
    """The complete HTML document for a :class:`~gtmkit.valuecase.ValueCase`."""
    data = case.to_dict()
    money = _Money(case.currency)
    labels: Dict[str, str] = {d["id"]: d["label"] for d in data["drivers"]}
    return "".join(
        [
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n',
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
            "<title>%s</title>\n<style>\n%s</style>\n</head>\n<body>\n"
            % (_e(case.name), CSS),
            '<main class="report">\n',
            _header(case),
            _headline(case),
            _evidence(data, labels),
            _sensitivity(data, money, labels),
            _cash_flow(case, data, money),
            _drivers(data, money),
            _attribution(data, money),
            _floor(data, money),
            _ledger(case),
            _costs(case, money) if case.costs else "",
            '<footer>Generated by <a href="%s">gtm-skills</a> %s. Every figure above '
            "is computed from the declared inputs by a tested library; no number in "
            "this document was written by hand.</footer>\n"
            % (REPO_URL, _e(__version__)),
            "</main>\n</body>\n</html>",
        ]
    )


CSS = """\
:root {
  color-scheme: light;
  --page: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --wash: rgba(11, 11, 11, 0.035);
  /* Confidence is ordered, so it wears one hue: more evidence, more ink. */
  --fact: #104281;
  --inference: #2a78d6;
  --assumption: #86b6ef;
  --on-fact: #ffffff;
  --on-inference: #ffffff;
  --on-assumption: #0b0b0b;
  /* Polarity against the base case: two opposite hues. */
  --above: #2a78d6;
  --below: #e34948;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #f0efec;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --wash: rgba(255, 255, 255, 0.04);
    --fact: #9ec5f4;
    --inference: #3987e5;
    --assumption: #184f95;
    --on-fact: #0b0b0b;
    --on-inference: #ffffff;
    --on-assumption: #ffffff;
    --above: #3987e5;
    --below: #e66767;
    --critical: #e66767;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.report { max-width: 980px; margin: 0 auto; padding: 40px 28px 56px; }
header.top { margin-bottom: 28px; }
.kicker { font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { font-size: 30px; line-height: 1.18; letter-spacing: -0.015em; font-weight: 650; margin: 8px 0 8px; text-wrap: balance; overflow-wrap: anywhere; }
.basis { color: var(--ink-2); margin: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 10px 32px; margin: 16px 0 0; }
.meta div { min-width: 0; max-width: 100%; }
.meta dt { font-size: 12px; color: var(--muted); }
.meta dd { margin: 0; font-size: 13.5px; color: var(--ink-2); overflow-wrap: anywhere; }
section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px 26px; margin-top: 16px; }
h2 { font-size: 17px; font-weight: 650; letter-spacing: -0.005em; margin: 0 0 4px; }
.lede { color: var(--ink-2); margin: 0 0 18px; max-width: 70ch; }
.lede.tight { margin-bottom: 0; }
p { margin: 0 0 12px; }
.num { font-variant-numeric: tabular-nums; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }

/* Headline: one hero figure, the rest are stat tiles. */
.kpis { display: grid; grid-template-columns: 1.15fr 1fr 1fr; gap: 0; padding: 0; overflow: hidden; }
.kpi { padding: 20px 22px 18px; border-left: 1px solid var(--border); border-top: 1px solid var(--border); min-width: 0; }
.kpi.hero { grid-row: 1 / span 2; border-left: 0; border-top: 0; display: flex; flex-direction: column; justify-content: center; padding: 26px 26px 24px; container-type: inline-size; }
.kpi:nth-child(2), .kpi:nth-child(3) { border-top: 0; }
.kpi .label { font-size: 12.5px; color: var(--ink-2); }
.kpi .value { font-size: 25px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.15; margin-top: 6px; overflow-wrap: anywhere; }
.kpi .value.long { font-size: 16px; font-weight: 600; letter-spacing: 0; line-height: 1.35; }
.kpi.hero .value { font-size: 60px; letter-spacing: -0.035em; line-height: 1; margin-top: 10px; }
.kpi.hero .value.l2 { font-size: 46px; }
.kpi.hero .value.l3 { font-size: 34px; }
/* Where container units work, the hero figure shrinks with its cell (--fit is
   set from its length) rather than break mid-number; elsewhere the sizes above. */
@supports (width: 1cqi) {
  .kpi.hero .value.num { font-size: min(60px, calc(var(--fit) * 1cqi)); }
}
.kpi .sub { font-size: 12.5px; color: var(--muted); margin-top: 6px; }
.safety { margin: 14px 2px 0; color: var(--ink-2); }
.safety b { color: var(--ink); font-weight: 600; }

/* Evidence grade. */
.grade { display: grid; grid-template-columns: auto 1fr; gap: 20px; align-items: start; }
.badge { width: 68px; height: 68px; border-radius: 14px; border: 1.5px solid var(--ink); display: grid; place-items: center; font-size: 38px; font-weight: 650; line-height: 1; text-align: center; }
.badge.wide { font-size: 22px; }
.badge small { display: block; font-size: 10px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-top: 2px; }
.seg { display: flex; gap: 2px; height: 28px; margin: 16px 0 10px; }
.seg > span { display: flex; align-items: center; padding: 0 9px; font-size: 12.5px; font-weight: 600; border-radius: 4px; min-width: 0; white-space: nowrap; overflow: hidden; }
.seg > span.thin { padding: 0; }
.seg .fact { background: var(--fact); color: var(--on-fact); }
.seg .inference { background: var(--inference); color: var(--on-inference); }
.seg .assumption { background: var(--assumption); color: var(--on-assumption); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 12.5px; color: var(--ink-2); margin: 0; padding: 0; list-style: none; }
.legend li { display: flex; align-items: center; gap: 7px; }
.legend b { font-weight: 600; color: var(--ink); }
.sw { width: 10px; height: 10px; border-radius: 2px; flex: none; }
.sw.fact { background: var(--fact); } .sw.inference { background: var(--inference); } .sw.assumption { background: var(--assumption); }
.sw.above { background: var(--above); } .sw.below { background: var(--below); }
.callout { margin-top: 18px; padding: 14px 16px; border-radius: 10px; background: var(--wash); border: 1px solid var(--border); }
.callout h3 { margin: 0 0 4px; font-size: 14px; font-weight: 650; overflow-wrap: anywhere; }
.callout p { margin: 0; color: var(--ink-2); }
.callout p.drv { color: var(--muted); font-size: 12.5px; margin-bottom: 6px; }

/* Tornado: a row per ranged input, bars laid out by percentage on one shared axis. */
.tornado { --label: 34%; --tip: 0px; --gut: max(70px, var(--tip)); position: relative; margin-top: 6px; }
.t-row { display: grid; grid-template-columns: var(--label) 1fr; align-items: center; min-height: 54px; padding: 5px 0; }
.t-name { padding-right: 18px; min-width: 0; }
.t-name code { font: 600 13px/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--ink); }
.t-name span { display: block; font-size: 12px; line-height: 1.35; color: var(--muted); margin-top: 2px; overflow-wrap: anywhere; }
.t-name span.rng { margin-top: 0; }
.flag { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-2); margin-top: 3px; }
.flag svg { width: 11px; height: 11px; flex: none; }
.flag path { fill: var(--critical); }
.t-plot { position: relative; height: 54px; margin: 0 var(--gut); }
.bar { position: absolute; top: 50%; height: 16px; margin-top: -8px; }
.bar.below { background: var(--below); border-radius: 4px 0 0 4px; }
.bar.above { background: var(--above); border-radius: 0 4px 4px 0; }
.tip { position: absolute; top: 50%; transform: translateY(-50%); font-size: 12.5px; font-weight: 600; white-space: nowrap; }
.tip.lo { transform: translate(-100%, -50%); padding-right: 7px; }
.tip.hi { padding-left: 7px; }
.tip.quiet { font-weight: 400; color: var(--muted); }
.t-lines { position: absolute; top: 22px; bottom: 28px; left: calc(var(--label) + var(--gut)); right: var(--gut); pointer-events: none; }
.t-lines i { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--grid); }
.t-lines i.zero { background: var(--axis); }
.t-lines i.base { background: var(--ink); width: 1.5px; }
.t-axis { position: relative; height: 28px; margin: 0 var(--gut) 0 calc(var(--label) + var(--gut)); }
.t-axis::before { content: ""; position: absolute; top: 0; left: calc(-1 * var(--gut)); right: calc(-1 * var(--gut)); border-top: 1px solid var(--axis); }
.t-axis span { position: absolute; top: 7px; transform: translateX(-50%); font-size: 12px; color: var(--muted); white-space: nowrap; }
.t-top { position: relative; height: 22px; margin: 0 var(--gut) 0 calc(var(--label) + var(--gut)); }
.t-top span { position: absolute; bottom: 4px; transform: translateX(-50%); font-size: 12px; font-weight: 600; color: var(--ink); white-space: nowrap; }
.t-top span.start { transform: none; }
.t-top span.end { transform: translateX(-100%); }
figure { margin: 0; }
figcaption { font-size: 12.5px; color: var(--muted); margin-top: 12px; }
figure .legend { margin-top: 10px; }

/* Ranked bars: where the value comes from. */
.ranked { --valw: 72px; display: grid; grid-template-columns: minmax(0, 38%) 1fr; row-gap: 9px; align-items: center; margin-top: 8px; }
.r-name { padding-right: 16px; font-size: 13px; line-height: 1.3; min-width: 0; }
.r-name code { font: 600 12.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.r-name span { color: var(--muted); font-size: 12px; display: block; overflow-wrap: anywhere; }
.r-plot { position: relative; height: 18px; margin-right: var(--valw); min-width: 0; }
.r-bar { position: absolute; left: 0; top: 3px; height: 12px; border-radius: 0 4px 4px 0; }
.r-bar.fact { background: var(--fact); } .r-bar.inference { background: var(--inference); } .r-bar.assumption { background: var(--assumption); }
.r-val { position: absolute; top: 50%; transform: translateY(-50%); padding-left: 8px; font-size: 12.5px; font-weight: 600; white-space: nowrap; }

/* Cash flow chart. */
.cash svg { display: block; width: 100%; height: auto; }
.cash svg.narrow { display: none; }
.cash text { font: 12px system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; fill: var(--muted); }
.cash svg.narrow text { font-size: 13px; }
.cash text.v { fill: var(--ink); font-weight: 600; }
.cash .g { stroke: var(--grid); stroke-width: 1; }
.cash .z { stroke: var(--axis); stroke-width: 1; }
.cash .pos { fill: var(--above); } .cash .neg { fill: var(--below); }
.cash .line { fill: none; stroke: var(--ink-2); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.cash .dot { fill: var(--ink-2); stroke: var(--surface); stroke-width: 2; }
.key-line { width: 16px; height: 2px; background: var(--ink-2); border-radius: 1px; flex: none; }

/* Tables: the complete record behind every chart. */
.table-wrap { overflow-x: auto; margin-top: 18px; }
figure + .table-wrap { margin-top: 22px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th { text-align: left; font-size: 12px; font-weight: 600; color: var(--muted); padding: 8px 12px 8px 0; border-bottom: 1px solid var(--axis); white-space: nowrap; }
td { padding: 10px 12px 10px 0; border-bottom: 1px solid var(--grid); vertical-align: top; overflow-wrap: break-word; }
tr:last-child td { border-bottom: 0; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; padding-right: 0; padding-left: 12px; overflow-wrap: normal; }
td.n:not(:last-child), th.n:not(:last-child) { padding-right: 16px; }
td.nowrap { white-space: nowrap; overflow-wrap: normal; }
td.n.wrap { min-width: 6em; }
td.n .long { white-space: normal; overflow-wrap: anywhere; }
td.label { min-width: 8em; }
td.src { color: var(--ink-2); min-width: 200px; overflow-wrap: anywhere; }
td .under { display: block; color: var(--muted); font-size: 12px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; white-space: nowrap; }
.floor { border-left: 3px solid var(--critical); border-radius: 0 12px 12px 0; }
.floor.holds { border-left-color: var(--above); }
.floor ul { margin: 8px 0 0; padding-left: 18px; }
footer { margin-top: 22px; font-size: 12.5px; color: var(--muted); }
footer a { color: inherit; }

/* A value with a long unit ("1.8 minutes per ticket") may wrap where the
   ledger is squeezed: a window under 1000px, or paper. */
@media screen and (max-width: 1000px) {
  td.n.wrap { white-space: normal; }
}
@media screen and (max-width: 760px) {
  .report { padding: 24px 14px 40px; }
  section { padding: 18px 16px; }
  h1 { font-size: 24px; }
  .kpis { grid-template-columns: 1fr 1fr; }
  .kpi, .kpi:nth-child(2), .kpi:nth-child(3) { border-left: 0; border-top: 1px solid var(--border); padding: 16px; }
  .kpi:nth-child(odd) { border-left: 1px solid var(--border); }
  .kpi.hero { grid-column: 1 / -1; grid-row: auto; border-top: 0; border-left: 0; padding: 20px 16px; }
  .kpi.hero .value { font-size: 44px; }
  .kpi.hero .value.l2 { font-size: 36px; }
  .kpi.hero .value.l3 { font-size: 30px; }
  .tornado { --label: 0%; --gut: max(58px, var(--tip)); }
  /* Ticks only a wide window has room to label, with their gridlines. */
  .t-axis span.wide, .t-lines i.wide { display: none; }
  .t-row { grid-template-columns: 1fr; }
  /* The name sits above its bar here; mask the grid lines behind it. */
  .t-name { padding: 10px 0 0; position: relative; z-index: 1; background: var(--surface); }
  .ranked { grid-template-columns: 1fr; row-gap: 3px; }
  .seg > span { padding: 0 6px; }
  .r-plot { margin-bottom: 8px; }
  .grade { grid-template-columns: 1fr; }
  .cash svg.wide { display: none; }
  .cash svg.narrow { display: block; }
  /* One card per row: every value beside its column name, nothing to scroll. */
  table.stack thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  table.stack, table.stack tbody, table.stack tr { display: block; }
  table.stack tr { padding: 10px 0; border-bottom: 1px solid var(--grid); }
  table.stack tr:last-child { border-bottom: 0; }
  table.stack td, table.stack td.n, table.stack td.label, table.stack td.src { display: grid; grid-template-columns: 7.5em minmax(0, 1fr); column-gap: 12px; padding: 2px 0; border: 0; text-align: left; white-space: normal; min-width: 0; }
  table.stack td::before { content: attr(data-label); color: var(--muted); font-size: 12px; line-height: 1.75; }
  table.stack td:first-child { display: block; padding-bottom: 6px; font-weight: 600; }
  table.stack td:first-child .under { font-weight: 400; }
  table.stack td:first-child::before { content: none; }
}
@media screen and (max-width: 560px) {
  table.compact { font-size: 12px; }
  table.compact th { font-size: 11px; }
  table.compact td, table.compact th { padding-right: 8px; }
  table.compact td.n, table.compact th.n, table.compact td.n:not(:last-child), table.compact th.n:not(:last-child) { padding-left: 4px; padding-right: 0; }
}
@media screen and (max-width: 359px) {
%(compact)s}
@media screen and (max-width: 560px) {
%(cards)s}
@supports (width: 1cqi) {
  @media screen and (max-width: 760px) {
    .kpi.hero .value.num { font-size: min(44px, calc(var(--fit) * 1cqi)); }
  }
}
@media print {
  :root { color-scheme: light; --page: #fff; --surface: #fff; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,.14); --wash: rgba(11,11,11,.035); --fact: #104281; --inference: #2a78d6; --assumption: #86b6ef; --on-fact: #fff; --on-inference: #fff; --on-assumption: #0b0b0b; --above: #2a78d6; --below: #e34948; --critical: #d03b3b; }
  body { font-size: 11pt; }
  .report { max-width: none; padding: 0; }
  .table-wrap { overflow: visible; }
  td.n.wrap { white-space: normal; }
  section { break-inside: avoid; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""

# Too narrow for five columns: each period becomes a card of four values.
# Applied below 360px to every compact table, and below 560px to the ones
# whose amounts are too long for five columns at 375px.
_CARDS = """\
  table.%(t)s thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%%); white-space: nowrap; }
  table.%(t)s, table.%(t)s tbody { display: block; }
  table.%(t)s tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 12px; padding: 10px 0; border-bottom: 1px solid var(--grid); }
  table.%(t)s tr:last-child { border-bottom: 0; }
  table.%(t)s td, table.%(t)s td.n, table.%(t)s td.n:not(:last-child) { display: block; padding: 0; border: 0; text-align: left; }
  table.%(t)s td::before { content: attr(data-label); display: block; color: var(--muted); font-size: 11px; }
  table.%(t)s td:first-child { grid-column: 1 / -1; font-weight: 600; }
  table.%(t)s td:first-child::before { content: none; }
"""
CSS = CSS.replace("%(compact)s", _CARDS % {"t": "compact"}).replace(
    "%(cards)s", _CARDS % {"t": "compact.cards"}
)
