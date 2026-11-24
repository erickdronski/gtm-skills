"""Tests for the self-contained HTML report (``--format html``).

The report is the output most likely to be forwarded to someone who never
sees the spec, so these tests hold it to the same standard as the markdown:
the same numbers, nothing invented, nothing executable smuggled in from an
untrusted spec, and charts whose numbers can be read without the picture.
"""

import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser

from gtmkit import cli, finance, report, valuecase
from gtmkit.valuecase import load_spec, validate_spec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(
    REPO_ROOT, "examples", "value-case", "northwind-support-deflection.json"
)
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "wbr",
}
ALLOWED_TAGS = {
    "a", "b", "body", "circle", "code", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "h1", "h2", "h3", "head", "header", "html", "i", "li",
    "line", "main", "meta", "p", "path", "polyline", "section", "small", "span",
    "style", "svg", "table", "tbody", "td", "text", "th", "thead", "title", "tr",
    "ul",
}  # fmt: skip
NON_NUMBERS = re.compile(r"\b(nan|inf|infinity)\b", re.IGNORECASE)


class Document(HTMLParser):
    """A strict reading of the report: tags must nest and close exactly."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack, self.problems, self.elements, self.text = [], [], [], []
        self.doctype = None
        self.feed(html)
        self.close()
        if self.stack:
            self.problems.append("unclosed: %s" % self.stack)

    def handle_decl(self, decl):
        self.doctype = decl

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.problems.append("</%s> closes %s" % (tag, self.stack[-1:]))
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)

    def find(self, tag=None, cls=None):
        return [
            attrs
            for t, attrs in self.elements
            if (tag is None or t == tag)
            and (cls is None or cls in attrs.get("class", "").split())
        ]


def spec(**overrides):
    base = {
        "name": "Report test case",
        "currency": "USD",
        "horizon_years": 3,
        "discount_rate_annual": 0.12,
        "drivers": [
            {
                "id": "d1",
                "label": "Driver one",
                "formula": "volume * rate * unit_value",
                "inputs": {
                    "volume": {
                        "value": 1000,
                        "confidence": "fact",
                        "source": "Warehouse export dated 2026-01-01",
                    },
                    "rate": {
                        "value": 0.2,
                        "confidence": "assumption",
                        "source": "Observed between 10% and 30% at two peers",
                        "low": 0.1,
                        "high": 0.3,
                    },
                    "unit_value": {
                        "value": 50,
                        "confidence": "inference",
                        "source": "Loaded cost of $104,000 over 2,080 hours",
                    },
                },
                "ramp": [0.5, 1.0, 1.0],
                "realization": 0.8,
            }
        ],
        "costs": [
            {"id": "sub", "label": "Subscription", "schedule": [0, 3000, 3000, 3000]},
            {"id": "impl", "label": "Implementation", "schedule": [5000, 0, 0, 0]},
        ],
    }
    base.update(overrides)
    return base


def render(raw):
    return validate_spec(raw).to_html()


def markdown_headline(markdown):
    section = markdown.split("## Headline", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]
    return {
        cells[0]: cells[1]
        for cells in (
            [c.strip() for c in row.strip().strip("|").split("|")] for row in rows
        )
    }


def html_headline(html):
    tiles = re.findall(
        r'<div class="label">(.*?)</div><div class="value[^"]*"[^>]*>(.*?)</div>', html
    )
    values = {unescape(label): unescape(value) for label, value in tiles}
    safety = re.search(r'<p class="safety"><b>Margin of safety:</b> (.*?)</p>', html)
    values["Margin of safety"] = unescape(safety.group(1)).rstrip(".")
    return values


def axis_labels(html):
    """(place along the axis, 0 to 1; text; shown on a phone) per tick label."""
    axis = html.split('<div class="t-axis">', 1)[1].split("</div>", 1)[0]
    return [
        (float(left) / 100, unescape(text), cls == "")
        for cls, left, text in re.findall(
            r'<span(?: class="([^"]*)")? style="left: ([\d.]+)%">([^<]*)</span>', axis
        )
    ]


def wide_northwind(**changes):
    """The example with a wider deflection range: six ticks on its axis."""
    with open(EXAMPLE, encoding="utf-8") as handle:
        raw = json.load(handle)
    raw["shared_inputs"]["deflection_rate"]["high"] = 0.3
    raw.update(changes)
    return raw


def edge_cases():
    """Specs for every shape the report must survive, by name."""
    cases = {}
    cases["one driver"] = spec()

    no_range = spec()
    no_range["drivers"][0]["inputs"]["rate"] = {
        "value": 0.2,
        "confidence": "inference",
        "source": "200 of 1,000 tickets tagged in the March 2026 export",
    }
    cases["no sensitivity rows"] = no_range

    # Period 0 carries no cost and every later year nets positive: no sign
    # change, so IRR is undefined and nothing is ever at risk.
    cases["all-positive cash flows"] = spec(
        costs=[
            {"id": "sub", "label": "Subscription", "schedule": [0, 1000, 1000, 1000]}
        ]
    )
    cases["payback never"] = spec(
        costs=[
            {
                "id": "sub",
                "label": "Subscription",
                "schedule": [0, 20000, 20000, 20000],
            },
            {"id": "impl", "label": "Implementation", "schedule": [5000, 0, 0, 0]},
        ]
    )
    holds = spec()
    holds["drivers"][0]["inputs"]["rate"].update(low=0.19, high=0.21)
    cases["floor stays positive"] = holds

    large = spec(
        costs=[
            {"id": "sub", "label": "Subscription", "schedule": [0, 3e11, 3e11, 3e11]},
            {"id": "impl", "label": "Implementation", "schedule": [4e12, 0, 0, 0]},
        ]
    )
    large["drivers"][0]["inputs"]["volume"]["value"] = 5e11
    cases["very large values"] = large

    small = spec(
        costs=[
            {"id": "sub", "label": "Subscription", "schedule": [0, 0.3, 0.3, 0.3]},
            {"id": "impl", "label": "Implementation", "schedule": [0.5, 0, 0, 0]},
        ]
    )
    small["drivers"][0]["inputs"]["volume"]["value"] = 0.1
    cases["very small values"] = small

    long_text = spec(name="A very long case name " * 12)
    long_text["drivers"][0]["label"] = "An unusually long driver label " * 10
    long_text["drivers"][0]["inputs"]["volume"]["source"] = (
        "Warehouse export dated 2026-01-01, file "
        + "x" * 240
        + " and https://dashboards.example.com/cx/q2/"
        + "y" * 120
    )
    long_text["costs"][0]["note"] = "Contract schedule " * 40
    cases["long labels and sources"] = long_text

    cases["unicode"] = spec(
        name="Düsseldorf rollout — 東京 pilot 🚀",
        currency="EUR",
        meta={"prepared_for": "Zoë Ångström", "status": "brouillon ✓"},
    )
    cases["unicode"]["drivers"][0]["label"] = "Ärger vermeiden · 节省时间"

    negative = spec()
    negative["drivers"][0]["formula"] = "volume * rate * unit_value - 12000"
    cases["driver worth less than nothing"] = negative

    # No modeled benefit at all: nothing to grade, no IRR, no payback.
    nothing = spec()
    nothing["drivers"][0]["inputs"]["volume"]["value"] = 0
    cases["zero benefit"] = nothing

    # A declared range the formula cannot feel.
    inert = spec()
    inert["drivers"][0]["formula"] = "volume * unit_value * 0.2 + rate * 0"
    cases["ranged input with no effect"] = inert

    # Every outcome above zero, so the tornado axis does not include it.
    rich = spec()
    rich["drivers"][0]["inputs"]["volume"]["value"] = 5000
    cases["every outcome positive"] = rich

    # An odd number of years, so the last period name has an even neighbour.
    cases["nine years"] = spec(
        horizon_years=9,
        costs=[{"id": "sub", "label": "Sub", "schedule": [9000] + [3000] * 9}],
    )

    # A currency code instead of a symbol, on amounts in the millions.
    chf = spec(currency="CHF")
    chf["drivers"][0]["inputs"]["volume"]["value"] = 400000
    chf["costs"] = [
        {"id": "sub", "label": "Sub", "schedule": [600000, 300000, 300000, 300000]}
    ]
    cases["currency code"] = chf
    return cases


class TestDocument(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_spec(EXAMPLE)
        cls.html = cls.case.to_html()
        cls.doc = Document(cls.html)

    def test_parses_strictly(self):
        self.assertEqual(self.doc.problems, [])
        self.assertEqual(self.doc.doctype, "doctype html")
        self.assertTrue(self.html.startswith("<!doctype html>\n"))
        self.assertTrue(self.html.endswith("</html>"))

    def test_uses_only_inert_tags_and_unique_ids(self):
        self.assertLessEqual({t for t, _ in self.doc.elements}, ALLOWED_TAGS)
        ids = [a["id"] for _, a in self.doc.elements if "id" in a]
        self.assertEqual(len(ids), len(set(ids)))

    def test_self_contained(self):
        hrefs = [a["href"] for _, a in self.doc.elements if "href" in a]
        self.assertEqual(hrefs, [report.REPO_URL])
        self.assertFalse([a for _, a in self.doc.elements if "src" in a])
        for marker in ("<script", "<link", "@import", "url(", "@font-face"):
            self.assertNotIn(marker, self.html.lower())
        self.assertEqual(self.html.count("http"), 1, "only the footer link")

    def test_headline_matches_the_markdown(self):
        expected = markdown_headline(self.case.to_markdown())
        self.assertEqual(
            sorted(expected),
            sorted(
                [
                    "Net present value",
                    "Discounted payback",
                    "IRR",
                    "Total investment",
                    "Total modeled benefit",
                    "Margin of safety",
                ]
            ),
        )
        self.assertEqual(html_headline(self.html), expected)

    def test_quoted_readme_numbers_appear(self):
        for quoted in ("$105.2k", "2 yr 4 mo", "32%", "$579.7k", "$311.6k"):
            with self.subTest(quoted=quoted):
                self.assertIn(quoted, self.html)

    def test_light_and_dark_tokens_come_from_the_design(self):
        self.assertIn("@media (prefers-color-scheme: dark)", self.html)
        self.assertIn("@media print", self.html)
        for token in ("--fact: #104281", "--fact: #9ec5f4", "--below: #e34948"):
            self.assertIn(token, self.html)

    def test_meta_is_shown(self):
        for label, value in (
            ("Prepared for", "VP Customer Operations, Northwind Logistics"),
            ("Prepared by", "Solutions Consulting"),
            ("Decision date", "2026-09-30"),
            ("Status", "draft — pending measurement of deflection_rate"),
        ):
            self.assertIn("<dt>%s</dt><dd>%s</dd>" % (label, value), self.html)

    def test_every_sensitivity_row_is_charted_and_tabled(self):
        rows = self.case.sensitivity()
        self.assertEqual(len(self.doc.find("div", "t-row")), len(rows))
        flips = sum(1 for r in rows if r["flips_decision"])
        self.assertEqual(len(self.doc.find("div", "flag")), flips)
        tornado = self.html.split('class="tornado"', 1)[1].split("</figure>", 1)[0]
        table = self.html.split("</figure>", 1)[1].split("</section>", 1)[0]
        tips = re.findall(r'<span class="tip (?:lo|hi)"[^>]*>([^<]*)</span>', tornado)
        self.assertEqual(len(tips), 2 * len(rows))
        for tip in tips:
            self.assertIn(">%s<" % tip, table, "tornado value missing from its table")

    def test_axes_sit_on_clean_ticks(self):
        tornado = self.html.split('class="t-axis"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(
            re.findall(r">([^<]+)</span>", tornado), ["-$100k", "$0", "$100k", "$200k"]
        )
        wide = self.html.split('<svg class="wide"', 1)[1].split("</svg>", 1)[0]
        self.assertEqual(
            re.findall(r'text-anchor="end">([^<]+)<', wide),
            ["-$200k", "-$100k", "$0", "$100k", "$200k"],
        )

    def test_cash_bars_match_the_cash_table(self):
        net = self.case.net_flows()
        wide = self.html.split('<svg class="wide"', 1)[1].split("</svg>", 1)[0]
        self.assertEqual(wide.count('class="neg"'), sum(1 for v in net if v < 0))
        self.assertEqual(wide.count('class="pos"'), sum(1 for v in net if v > 0))
        table = self.html.split('aria-label="Cash flow by period"', 1)[1]
        table = table.split("</table>", 1)[0]
        for title in re.findall(r"<title>([^<]+)</title>", wide):
            value = unescape(title).split(" ")[-1]
            self.assertIn(">%s<" % value, table, title)

    def test_every_chart_has_an_accessible_name(self):
        drawings = [a for a in self.doc.find("svg") if a.get("aria-hidden") != "true"]
        charts = (
            drawings
            + self.doc.find("div", "tornado")
            + self.doc.find("div", "ranked")
            + self.doc.find("div", "seg")
            + self.doc.find("div", "badge")
        )
        self.assertEqual(len(self.doc.find("svg", "wide")), 1)
        self.assertEqual(len(self.doc.find("svg", "narrow")), 1)
        for attrs in charts:
            self.assertTrue(attrs.get("aria-label", "").strip(), attrs)
            self.assertIn(attrs.get("role"), ("img", "group"))

    def test_evidence_shares_are_written_out(self):
        evidence = self.case.evidence()
        legend = self.html.split('class="seg"', 1)[1].split("</ul>", 1)[0]
        for level in ("fact", "inference", "assumption"):
            share = valuecase.fmt_pct(evidence["share_%s" % level])
            self.assertIn('<b class="num">%s</b>' % share, legend)

    def test_attribution_lists_every_input(self):
        rows = self.case.evidence_by_input()
        self.assertEqual(len(self.doc.find("div", "r-plot")), len(rows))

    def test_full_ledger_and_cost_lines(self):
        ledger = self.html.split('aria-label="Assumption ledger"', 1)[1]
        ledger = ledger.split("</table>", 1)[0]
        count = sum(len(d.inputs) for d in self.case.drivers)
        self.assertEqual(ledger.count("<tr>") - 1, count)
        for cost in self.case.costs:
            self.assertIn(">%s<" % cost.label, self.html)

    def test_deterministic(self):
        again = load_spec(EXAMPLE).to_html()
        self.assertEqual(again, self.html)
        self.assertEqual(self.case.to_html(), self.html)

    def test_every_cell_carries_its_column_name_for_phones(self):
        tables = re.findall(r"<table [^>]*>(.*?)</table>", self.html, re.S)
        # Sensitivity, cash flow, value drivers, assumption ledger, costs.
        self.assertEqual(len(tables), 5)
        for table in tables:
            headers = [unescape(h) for h in re.findall(r"<th[^>]*>([^<]*)</th>", table)]
            for row in re.findall(r"<tr>(.*?)</tr>", table.split("<tbody>", 1)[1]):
                labels = re.findall(r'<td[^>]* data-label="([^"]*)">', row)
                self.assertEqual([unescape(x) for x in labels], headers)

    def test_cash_table_stays_a_grid_on_a_phone(self):
        self.assertIn(
            '<table class="compact" aria-label="Cash flow by period">', self.html
        )
        self.assertEqual(self.html.count('<table class="stack"'), 4)


class TestGeometry(unittest.TestCase):
    """Bars point the way their numbers do, at the size the axis says."""

    @classmethod
    def setUpClass(cls):
        cls.case = load_spec(EXAMPLE)
        cls.html = cls.case.to_html()

    def test_tornado_bars_run_from_the_base_to_each_outcome(self):
        rows = self.case.sensitivity()
        base = self.case.summary()["npv"]
        scale = report.nice_scale(
            [base] + [r[k] for r in rows for k in ("npv_low", "npv_high")]
        )

        def at(value):
            return 100 * scale.fraction(value)

        base_line = re.search(r'<i class="base" style="left: ([\d.]+)%"', self.html)
        self.assertAlmostEqual(float(base_line.group(1)), at(base), places=2)
        plots = re.findall(r'<div class="t-plot">(.*?)</div>\n</div>', self.html)
        self.assertEqual(len(plots), len(rows))
        for row, plot in zip(rows, plots):
            with self.subTest(input=row["input"]):
                bars = {
                    kind: (float(left), float(width))
                    for kind, left, width in re.findall(
                        r'class="bar (below|above)" style="left: ([\d.]+)%; '
                        r'width: ([\d.]+)%"',
                        plot,
                    )
                }
                low = min(row["npv_low"], row["npv_high"])
                high = max(row["npv_low"], row["npv_high"])
                self.assertEqual("below" in bars, low < base)
                self.assertEqual("above" in bars, high > base)
                if "below" in bars:
                    left, width = bars["below"]
                    self.assertAlmostEqual(left, at(low), delta=0.01)
                    self.assertAlmostEqual(left + width, at(base), delta=0.02)
                if "above" in bars:
                    left, width = bars["above"]
                    self.assertAlmostEqual(left, at(base), delta=0.01)
                    self.assertAlmostEqual(left + width, at(high), delta=0.02)

    def test_tornado_gutters_hold_the_widest_value_label(self):
        tips = re.findall(r'<span class="tip (?:lo|hi)"[^>]*>([^<]*)</span>', self.html)
        gutter = int(re.search(r'style="--tip: (\d+)px"', self.html).group(1))
        self.assertTrue(tips)
        for tip in tips:
            self.assertGreaterEqual(gutter, report._text_width(unescape(tip), 12.5))

    def test_label_width_estimate_errs_wide(self):
        """Widths Chrome drew for semibold system-ui on macOS, the face the
        report asks for first. Room is reserved from the estimate, so it must
        never come in under what is drawn."""
        measured = [
            ("$238.7k", 12.5, 50.4),
            ("-$72.8k", 12.5, 48.5),
            ("-$200k", 12.0, 44.2),
            ("$0", 12.0, 15.9),
            ("-$0.50", 12.0, 40.5),
            ("-CHF 600k", 12.5, 67.4),
            ("CA$999.9k", 13.0, 71.8),
            ("WWW 100k", 12.5, 70.5),
            ("-$1000000B", 13.0, 81.3),
            ("CHF 4M", 13.0, 50.6),
        ]
        for text, size, width in measured:
            with self.subTest(text=text, size=size):
                self.assertGreaterEqual(report._text_width(text, size), width)

    def test_cash_bars_point_the_way_their_sign_says_and_share_one_scale(self):
        wide = self.html.split('<svg class="wide"', 1)[1].split("</svg>", 1)[0]
        grid = [
            float(y)
            for y in re.findall(r'<line class="[gz]"[^>]* y1="([-\d.]+)"', wide)
        ]
        zero = float(re.search(r'<line class="z"[^>]* y1="([-\d.]+)"', wide).group(1))
        net = self.case.net_flows()
        running = finance.cumulative(net)
        ticks = report.nice_scale(net + running, include_zero=True).ticks
        # Pixels per currency unit, read off the drawn grid lines.
        ppu = (grid[0] - grid[-1]) / (ticks[-1] - ticks[0])
        self.assertGreater(ppu, 0)
        bars = re.findall(
            r'<path class="(pos|neg)" d="M[-\d.]+ ([-\d.]+)'
            r"(?:v([-\d.]+)a([\d.]+)|h[\d.]+v([\d.]+)a([\d.]+))",
            wide,
        )
        drawn = [v for v in net if v != 0]
        self.assertEqual(len(bars), len(drawn))
        for (kind, start, up, up_r, down, down_r), value in zip(bars, drawn):
            with self.subTest(value=value):
                self.assertEqual(kind, "pos" if value > 0 else "neg")
                self.assertAlmostEqual(float(start), zero, delta=0.1)
                # Up: v -(h - r), then a rounded corner of radius r.
                height = (
                    -float(up) + float(up_r)
                    if value > 0
                    else float(down) + float(down_r)
                )
                self.assertAlmostEqual(height, abs(value) * ppu, delta=0.2)
        dots = [
            float(y)
            for y in re.findall(
                r'<circle class="dot" cx="[-\d.]+" cy="([-\d.]+)"', wide
            )
        ]
        self.assertEqual(len(dots), len(running))
        for cy, value in zip(dots, running):
            self.assertAlmostEqual(cy, zero - value * ppu, delta=0.2)


class TestAxisLabels(unittest.TestCase):
    """Tick labels never run into each other, on a 320px phone or a desktop."""

    def assert_clear(self, labels, width):
        placed = sorted(
            (at * width, report._text_width(text, report.AXIS_FONT))
            for at, text, _ in labels
        )
        for (a, wa), (b, wb) in zip(placed, placed[1:]):
            self.assertGreaterEqual(b - a - (wa + wb) / 2, report.AXIS_GAP)

    def check(self, html):
        tip = int(re.search(r'style="--tip: (\d+)px"', html).group(1))
        labels = axis_labels(html)
        phone = [label for label in labels if label[2]]
        self.assertTrue(phone, "a phone must keep at least one label")
        self.assert_clear(labels, report.tornado_axis_width("wide", tip))
        self.assert_clear(phone, report.tornado_axis_width("phone", tip))
        # A tick a phone leaves unlabelled loses its gridline there too.
        tornado = html.split('class="tornado"', 1)[1].split("</figure>", 1)[0]
        self.assertEqual(
            tornado.count('<i class="wide"'), sum(1 for label in labels if not label[2])
        )
        # When the axis has zero, a phone always labels it and keeps its line.
        zero = re.search(r'<i class="zero" style="left: ([\d.]+)%"', tornado)
        if zero:
            at = float(zero.group(1)) / 100
            self.assertIn((at, True), [(place, shown) for place, _, shown in labels])
        return labels

    def test_a_six_tick_axis_thins_on_a_phone(self):
        labels = self.check(render(wide_northwind()))
        self.assertEqual(
            [text for _, text, _ in labels],
            ["-$100k", "$0", "$100k", "$200k", "$300k", "$400k"],
        )
        self.assertEqual([text for _, text, shown in labels if shown], ["$0", "$300k"])

    def test_the_example_keeps_every_label_wide_and_half_on_a_phone(self):
        labels = self.check(load_spec(EXAMPLE).to_html())
        self.assertEqual(
            [(text, shown) for _, text, shown in labels],
            [("-$100k", False), ("$0", True), ("$100k", False), ("$200k", True)],
        )

    def test_long_labels_thin_the_wide_axis_too(self):
        labels = self.check(render(wide_northwind(currency="CHF")))
        self.assertEqual(
            [text for _, text, _ in labels], ["CHF 0", "CHF 200k", "CHF 400k"]
        )

    def test_every_edge_case_keeps_its_labels_apart(self):
        for name, raw in edge_cases().items():
            html = render(raw)
            if 'class="t-axis"' in html:
                with self.subTest(case=name):
                    self.check(html)

    def test_phone_rules_hide_the_thinned_ticks(self):
        phone = report.CSS.split("@media screen and (max-width: 760px) {", 1)[1]
        phone = phone.split("\n}\n", 1)[0]
        self.assertIn(".t-axis span.wide, .t-lines i.wide { display: none; }", phone)

    def test_axis_geometry_matches_the_stylesheet(self):
        css = report.CSS
        phone = css.split("@media screen and (max-width: 760px) {", 1)[1]
        self.assertEqual(report.WIDE_MIN_WINDOW, 761)
        self.assertIn(
            ".report { max-width: 980px; margin: 0 auto; padding: 40px %dpx 56px; }"
            % report._PAGE_PAD["wide"],
            css,
        )
        self.assertIn(
            "section { background: var(--surface); border: %dpx solid var(--border); "
            "border-radius: 12px; padding: 24px %dpx;"
            % (report._SECTION_BORDER, report._SECTION_PAD["wide"]),
            css,
        )
        self.assertIn(
            ".tornado { --label: %d%%; --tip: 0px; --gut: max(%dpx, var(--tip));"
            % (100 * report._NAME_COLUMN["wide"], report._MIN_GUTTER["wide"]),
            css,
        )
        self.assertIn(
            ".report { padding: 24px %dpx 40px; }" % report._PAGE_PAD["phone"], phone
        )
        self.assertIn(
            "section { padding: 18px %dpx; }" % report._SECTION_PAD["phone"], phone
        )
        self.assertIn(
            ".tornado { --label: %d%%; --gut: max(%dpx, var(--tip)); }"
            % (100 * report._NAME_COLUMN["phone"], report._MIN_GUTTER["phone"]),
            phone,
        )


class TestEscaping(unittest.TestCase):
    def test_spec_strings_cannot_inject_markup(self):
        payload = "<script>alert(\"x\")</script><img src=x onerror=alert(1)> & 'q'"
        raw = spec(name="Case " + payload, currency="<b onmouseover=1>")
        raw["meta"] = {"prepared_for": payload, payload: payload}
        driver = raw["drivers"][0]
        driver["label"] = "Label " + payload
        driver["inputs"]["volume"]["source"] = payload + " Warehouse export 2026-01-01"
        driver["inputs"]["volume"]["unit"] = '"unit" & <i>'
        raw["costs"][0]["label"] = "Cost " + payload
        raw["costs"][0]["note"] = "Note " + payload
        html = render(raw)
        doc = Document(html)
        self.assertEqual(doc.problems, [])
        self.assertLessEqual({t for t, _ in doc.elements}, ALLOWED_TAGS)
        for _, attrs in doc.elements:
            for name in attrs:
                self.assertFalse(name.startswith("on"), name)
                self.assertNotEqual(name, "src")
        self.assertNotIn("<script", html.lower())
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", html)
        self.assertIn("&#x27;q&#x27;", html)
        self.assertIn("&lt;B ONMOUSEOVER=1&gt;", html)
        # Ampersands and quotes from the name, labels, sources, meta keys and
        # values, cost lines, and units arrive as entities, never raw.
        self.assertNotIn("& 'q'", html)
        self.assertIn("&amp; &#x27;q&#x27;", html)
        self.assertIn("&quot;unit&quot; &amp; &lt;i&gt;", html)
        self.assertIn("<title>Case &lt;script&gt;", html)
        self.assertIn("<dt>&lt;script&gt;alert(&quot;x&quot;)", html)

    def test_spec_links_are_text_not_links(self):
        html = render(edge_cases()["long labels and sources"])
        doc = Document(html)
        self.assertEqual(
            [a["href"] for _, a in doc.elements if "href" in a], [report.REPO_URL]
        )
        for found in re.findall(r"https?://[^\s\"<>]+", html):
            self.assertTrue(
                found == report.REPO_URL or "dashboards.example.com" in found, found
            )


class TestEdgeCases(unittest.TestCase):
    def test_every_edge_case_renders_cleanly(self):
        for name, raw in edge_cases().items():
            with self.subTest(case=name):
                html = render(raw)
                doc = Document(html)
                self.assertEqual(doc.problems, [])
                self.assertIsNone(NON_NUMBERS.search(html), name)
                self.assertEqual(html, render(deepcopy(raw)), "not deterministic")
                self.assertEqual(
                    html_headline(html),
                    markdown_headline(validate_spec(raw).to_markdown()),
                )

    def test_undefined_irr_and_payback_render_as_words(self):
        never = render(edge_cases()["payback never"])
        self.assertIn(">never within the modeled horizon</div>", never)
        self.assertIn(">not meaningful for this cash flow shape</div>", never)
        self.assertIn('class="value num long"', never)

    def test_no_ranges_explains_instead_of_charting(self):
        html = render(edge_cases()["no sensitivity rows"])
        self.assertIn(report.NO_RANGE_NOTE, unescape(html))
        self.assertNotIn('class="tornado"', html)
        self.assertNotIn('class="callout"', html)

    def test_all_positive_flows_draw_no_outflow(self):
        raw = edge_cases()["all-positive cash flows"]
        case = validate_spec(raw)
        self.assertTrue(all(v >= 0 for v in case.net_flows()))
        self.assertIsNone(case.summary()["irr_annual"])
        html = case.to_html()
        self.assertNotIn('class="neg"', html)
        self.assertIn('<line class="z"', html)

    def test_floor_that_holds_says_so(self):
        html = render(edge_cases()["floor stays positive"])
        self.assertIn('class="floor holds"', html)
        self.assertIn("<b>%s</b>" % report.FLOOR_HOLDS[0], html)
        failing = render(spec())
        self.assertIn('class="floor"', failing)
        self.assertIn(report.FLOOR_FAILS, failing)

    def test_unicode_survives(self):
        html = render(edge_cases()["unicode"])
        for text in (
            "Düsseldorf rollout — 東京 pilot 🚀",
            "Ärger vermeiden · 节省时间",
            "€",
        ):
            self.assertIn(text, html)
        self.assertIn('<meta charset="utf-8">', html)

    def test_negative_attribution_is_explained(self):
        html = render(edge_cases()["driver worth less than nothing"])
        self.assertIn("a minus sign marks value it takes away", html)

    def test_long_values_shrink_the_hero_figure(self):
        def hero(html):
            found = re.search(
                r'<div class="value num( l2| l3)?" style="--fit: ([\d.]+)">([^<]+)<',
                html,
            )
            return found.group(1), float(found.group(2)), unescape(found.group(3))

        _, short_fit, short = hero(load_spec(EXAMPLE).to_html())
        for name in ("very large values", "currency code"):
            with self.subTest(case=name):
                _, fit, text = hero(render(edge_cases()[name]))
                self.assertLess(fit, short_fit, (text, short))
                # At --fit cqi the estimated width of the figure, with the
                # -0.035em tracking, fills no more than its cell.
                ems = report._text_width(text, 1.0) - 0.035 * len(text)
                self.assertLessEqual(fit * ems, 100.0)
        self.assertIn("@supports (width: 1cqi)", load_spec(EXAMPLE).to_html())

    def test_zero_benefit_has_nothing_to_grade(self):
        raw = edge_cases()["zero benefit"]
        case = validate_spec(raw)
        self.assertIsNone(case.summary()["irr_annual"])
        html = case.to_html()
        self.assertIn('aria-label="Evidence grade n/a"', html)
        self.assertNotIn('class="seg"', html)
        self.assertEqual(
            html_headline(html)["Margin of safety"],
            "n/a — no modeled benefit to shrink",
        )

    def test_a_range_that_moves_nothing_says_so_without_widening_the_chart(self):
        html = render(edge_cases()["ranged input with no effect"])
        self.assertIn('quiet" style="left: ', html)
        self.assertIn(">no change</span>", html)
        # No value label to make room for, so the gutters fall to their minimum.
        self.assertIn('style="--tip: 14px"', html)

    def test_an_axis_without_zero_says_so(self):
        html = render(edge_cases()["every outcome positive"])
        self.assertIn("The axis does not start at zero", html)
        self.assertNotIn('<i class="zero"', html)
        northwind = load_spec(EXAMPLE).to_html()
        self.assertNotIn("does not start at zero", northwind)
        self.assertIn('<i class="zero"', northwind)

    def test_a_swing_the_figures_round_away_stays_a_sliver(self):
        raw = spec()
        raw["drivers"][0]["inputs"]["rate"].update(low=0.19999, high=0.20001)
        case = validate_spec(raw)
        base = case.summary()["npv"]
        row = case.sensitivity()[0]
        self.assertLess(abs(row["npv_high"] - row["npv_low"]), 5)
        html = case.to_html()
        widths = re.findall(
            r'class="bar (?:below|above)" style="[^"]*width: ([\d.]+)%', html
        )
        self.assertEqual(len(widths), 2)
        for width in widths:
            self.assertLess(float(width), 1.0)
        # The printed ends agree with the base, as the bars now do.
        tips = re.findall(r'<span class="tip (?:lo|hi)"[^>]*>([^<]*)</span>', html)
        self.assertEqual(set(tips), {valuecase.fmt_currency(base)})

    def test_the_last_period_is_always_named(self):
        html = render(edge_cases()["nine years"])
        for variant in ("wide", "narrow"):
            svg = html.split('<svg class="%s"' % variant, 1)[1].split("</svg>", 1)[0]
            names = re.findall(r'text-anchor="middle">([^<]+)<', svg)
            with self.subTest(variant=variant):
                self.assertIn(names[-1], ("Year 9", "Y9"))
                self.assertEqual(len(names), len(set(names)))

    def test_a_long_unit_wraps_instead_of_widening_the_ledger(self):
        with open(EXAMPLE, encoding="utf-8") as handle:
            raw = json.load(handle)
        unit = "minutes saved per ticket on suggested-reply acceptance"
        raw["drivers"][1]["inputs"]["minutes_saved"]["unit"] = unit
        self.assertIn('<span class="long">1.8 %s</span>' % unit, render(raw))
        # Every value the example has stays on one line on a wide screen.
        self.assertNotIn('<span class="long">', load_spec(EXAMPLE).to_html())
        # The rule that lets it wrap is top-level (rules inside @media blocks
        # are indented), so it holds at every width, not only narrow ones.
        self.assertIn("\ntd.n .long { white-space: normal;", report.CSS)

    def test_long_currency_codes_turn_the_cash_table_into_cards(self):
        html = render(edge_cases()["currency code"])
        self.assertIn(
            '<table class="compact cards" aria-label="Cash flow by period">', html
        )
        self.assertIn("CHF ", html)


class TestSharedWording(unittest.TestCase):
    """Sentences both renderers print must not drift apart."""

    def test_floor_and_range_wording_matches_the_markdown(self):
        failing = validate_spec(spec()).to_markdown()
        self.assertIn(report.FLOOR_NOTE, failing)
        self.assertIn(report.FLOOR_FAILS, failing)
        holds = validate_spec(edge_cases()["floor stays positive"]).to_markdown()
        self.assertIn("**%s**%s" % report.FLOOR_HOLDS, holds)
        no_range = validate_spec(edge_cases()["no sensitivity rows"]).to_markdown()
        self.assertIn(report.NO_RANGE_NOTE, no_range)


class TestScale(unittest.TestCase):
    def test_reproduces_the_design_axes(self):
        tornado = report.nice_scale([-72800, 238700, 105200])
        self.assertEqual((tornado.lo, tornado.hi), (-100000, 250000))
        self.assertEqual(tornado.ticks, [-100000, 0, 100000, 200000])
        cash = report.nice_scale([-217000, 218300, 14200], include_zero=True)
        self.assertEqual((cash.lo, cash.hi), (-250000, 250000))
        self.assertEqual(cash.ticks, [-200000, -100000, 0, 100000, 200000])

    def test_holds_every_value_on_clean_ticks(self):
        samples = [
            [1, 2],
            [0.004, 0.0013],
            [-5e9, 3e12],
            [1040000, 1160000],
            [-3, -2.5],
            [7, 7.000001],
            [123456.789, -98765.4321],
        ]
        for values in samples:
            for include_zero in (False, True):
                with self.subTest(values=values, zero=include_zero):
                    scale = report.nice_scale(values, include_zero=include_zero)
                    self.assertLessEqual(scale.lo, min(values))
                    self.assertGreaterEqual(scale.hi, max(values))
                    if include_zero:
                        self.assertIn(0.0, scale.ticks)
                    self.assertGreaterEqual(len(scale.ticks), 2)
                    self.assertLessEqual((scale.hi - scale.lo) / scale.step, 6 + 1e-9)
                    for tick in scale.ticks:
                        multiple = tick / scale.step
                        self.assertAlmostEqual(multiple, round(multiple), places=6)
                    labels = [report.tick_label(t, scale.exponent) for t in scale.ticks]
                    self.assertEqual(len(labels), len(set(labels)), labels)

    def test_ignores_non_numbers_and_handles_flat_series(self):
        scale = report.nice_scale([float("nan"), None, float("inf"), 5.0])
        self.assertTrue(scale.lo < 5.0 < scale.hi)
        flat = report.nice_scale([0.0, 0.0], include_zero=True)
        self.assertEqual(flat.ticks[len(flat.ticks) // 2], 0.0)
        self.assertTrue(all(math.isfinite(t) for t in flat.ticks))

    def test_min_span_widens_a_narrow_spread_about_its_middle(self):
        values = [-74867.5, -74865.0]
        tight = report.nice_scale(values)
        self.assertLess(tight.hi - tight.lo, 10)
        wide = report.nice_scale(values, min_span=1000)
        self.assertGreaterEqual(wide.hi - wide.lo, 1000)
        self.assertLessEqual(wide.lo, min(values))
        self.assertGreaterEqual(wide.hi, max(values))
        middle = (wide.lo + wide.hi) / 2
        self.assertLess(abs(middle - sum(values) / 2), wide.step)
        # A spread already wider than the minimum is left alone.
        self.assertEqual(
            report.nice_scale([-72800, 238700], min_span=1000).ticks,
            report.nice_scale([-72800, 238700]).ticks,
        )

    def test_currency_step_is_what_fmt_currency_rounds_to(self):
        for value in (74867, -74867, 1234567, 5e9, 512, 0.5, 999.4):
            step = report.currency_step(value)
            nearest = round(value / step) * step
            with self.subTest(value=value):
                self.assertEqual(
                    valuecase.fmt_currency(nearest), valuecase.fmt_currency(value)
                )
                self.assertNotEqual(
                    valuecase.fmt_currency(nearest + step),
                    valuecase.fmt_currency(value),
                )

    def test_tick_labels_carry_the_precision_the_step_needs(self):
        self.assertEqual(report.tick_label(1060000, 4), "$1.06M")
        self.assertEqual(report.tick_label(1500, 2), "$1.5k")
        self.assertEqual(report.tick_label(-200000, 5), "-$200k")
        self.assertEqual(report.tick_label(0, 5, "EUR"), "€0")
        self.assertEqual(report.tick_label(0.002, -3), "$0.002")
        self.assertEqual(report.tick_label(5e11, 11, "CHF"), "CHF 500B")


class TestCommandLine(unittest.TestCase):
    def test_format_html_writes_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            direct = os.path.join(tmp, "direct.html")
            front = os.path.join(tmp, "front door.html")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(
                    valuecase.main([EXAMPLE, "--format", "html", "--out", direct]), 0
                )
                self.assertEqual(
                    cli.main(
                        ["valuecase", EXAMPLE, "--format", "html", "--out", front]
                    ),
                    0,
                )
            with open(direct, encoding="utf-8") as handle:
                written = handle.read()
            with open(front, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), written)
            self.assertEqual(written, load_spec(EXAMPLE).to_html() + "\n")
            self.assertIn("wrote", err.getvalue())

    def test_unwritable_out_is_a_message_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "no such folder", "case.html")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = valuecase.main([EXAMPLE, "--format", "html", "--out", target])
            self.assertEqual(code, 1)
            self.assertIn("cannot write %s" % target, err.getvalue())
            self.assertFalse(os.path.exists(target))
            # The same through the gtmkit front door, in its own process.
            result = subprocess.run(
                [
                    sys.executable,
                    *("-m", "gtmkit", "valuecase", EXAMPLE),
                    *("--format", "html", "--out", target),
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"cannot write", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_json_output_is_unchanged_by_the_html_option(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(valuecase.main([EXAMPLE, "--format", "json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["name"], load_spec(EXAMPLE).name)


if __name__ == "__main__":
    unittest.main()
