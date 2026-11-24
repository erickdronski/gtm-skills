"""Tests for the business-case model, including the shipped example.

The example test matters more than it looks: the README quotes that output, and
a repo whose README shows numbers the code no longer produces is worse than one
with no README at all.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from copy import deepcopy

from gtmkit import valuecase
from gtmkit.valuecase import SpecError, load_spec, validate_spec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(
    REPO_ROOT, "examples", "value-case", "northwind-support-deflection.json"
)


def minimal_spec(**overrides):
    spec = {
        "name": "Test case",
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
    spec.update(overrides)
    return spec


class TestCashFlows(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_period_zero_has_no_benefit(self):
        self.assertEqual(self.case.benefit_flows()[0], 0.0)

    def test_ramp_and_realization_both_apply(self):
        # 1000 * 0.2 * 50 = 10000 run rate; year 1 = 10000 * 0.5 ramp * 0.8
        self.assertAlmostEqual(self.case.benefit_flows()[1], 4000.0)
        self.assertAlmostEqual(self.case.benefit_flows()[2], 8000.0)

    def test_schedule_length_matches_horizon(self):
        self.assertEqual(len(self.case.net_flows()), 4)

    def test_net_is_benefit_minus_cost(self):
        benefits = self.case.benefit_flows()
        costs = self.case.cost_flows()
        net = self.case.net_flows()
        for i in range(len(net)):
            self.assertAlmostEqual(net[i], benefits[i] - costs[i])

    def test_delayed_cost_never_recovers_in_the_report(self):
        spec = minimal_spec(horizon_years=2, discount_rate_annual=0.1)
        driver = spec["drivers"][0]
        driver["formula"] = "gain"
        driver["inputs"] = {
            "gain": {
                "value": 60,
                "confidence": "fact",
                "source": "Contract schedule for year two",
            }
        }
        driver.update(ramp=[0, 1], realization=1)
        spec["costs"] = [{"id": "year_one", "schedule": [0, 100, 0]}]
        case = validate_spec(spec)
        self.assertIsNone(case.summary()["discounted_payback_periods"])
        self.assertIsNone(case.floor_case()["payback_periods"])
        self.assertNotIn("immediate", case.to_markdown())

    def test_ramp_shorter_than_horizon_holds_last_value(self):
        spec = minimal_spec()
        spec["drivers"][0]["ramp"] = [0.5]
        case = validate_spec(spec)
        flows = case.benefit_flows()
        self.assertAlmostEqual(flows[1], flows[2])
        self.assertAlmostEqual(flows[2], flows[3])


class TestAttribution(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_shares_sum_to_one(self):
        shares = self.case.drivers[0].input_shares()
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)

    def test_pure_product_splits_evenly(self):
        """``a * b * c`` gives each input equal elasticity, so equal share."""
        shares = self.case.drivers[0].input_shares()
        for name, share in shares.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(share, 1.0 / 3.0, places=4)

    def test_insensitive_input_gets_a_small_share(self):
        spec = minimal_spec()
        spec["drivers"][0]["formula"] = "volume * rate * unit_value + tiny"
        spec["drivers"][0]["inputs"]["tiny"] = {
            "value": 1,
            "confidence": "assumption",
            "source": "Rounding allowance agreed with finance in July 2026",
            "low": 0,
            "high": 2,
        }
        case = validate_spec(spec)
        shares = case.drivers[0].input_shares()
        self.assertLess(shares["tiny"], 0.01)

    def test_evidence_grade_discriminates(self):
        """One soft input among three must not grade the same as all-soft."""
        mixed = validate_spec(minimal_spec()).evidence()

        spec = minimal_spec()
        for name in spec["drivers"][0]["inputs"]:
            spec["drivers"][0]["inputs"][name] = {
                "value": spec["drivers"][0]["inputs"][name]["value"],
                "confidence": "assumption",
                "source": "Bounded by the range seen across two peer accounts",
                "low": spec["drivers"][0]["inputs"][name]["value"] * 0.5,
                "high": spec["drivers"][0]["inputs"][name]["value"] * 1.5,
            }
        all_soft = validate_spec(spec).evidence()

        self.assertGreater(mixed["measured_share"], all_soft["measured_share"])
        self.assertEqual(all_soft["grade"], "F")
        self.assertNotEqual(mixed["grade"], "F")

    def test_attribution_totals_match_driver_npv(self):
        by_input = self.case.evidence_by_input()
        attributed = sum(row["npv_attributed"] for row in by_input)
        driver_npv = sum(row["npv"] for row in self.case.driver_contributions())
        self.assertAlmostEqual(attributed, driver_npv, places=6)


class TestSensitivity(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_only_ranged_inputs_appear(self):
        rows = self.case.sensitivity()
        self.assertEqual([r["input"] for r in rows], ["rate"])

    def test_low_bound_produces_lower_npv(self):
        row = self.case.sensitivity()[0]
        self.assertLess(row["npv_low"], row["npv_high"])

    def test_swing_is_absolute(self):
        row = self.case.sensitivity()[0]
        self.assertGreaterEqual(row["swing"], 0)

    def test_floor_case_is_no_better_than_base(self):
        floor = self.case.floor_case()
        self.assertLessEqual(floor["npv"], self.case.npv_with())

    def test_sorted_by_swing_descending(self):
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["unit_value"] = {
            "value": 50,
            "confidence": "assumption",
            "source": "Loaded cost varies between $40 and $60 by region",
            "low": 40,
            "high": 60,
        }
        rows = validate_spec(spec).sensitivity()
        swings = [r["swing"] for r in rows]
        self.assertEqual(swings, sorted(swings, reverse=True))


class TestBriefSaysWhatItLeavesOut(unittest.TestCase):
    """The markdown brief lists at most 12 rows per table and counts the rest."""

    def test_short_tables_carry_no_note(self):
        markdown = validate_spec(minimal_spec()).to_markdown()
        self.assertNotIn("are not listed here", markdown)

    def test_long_tables_say_how_many_rows_were_left_out(self):
        spec = minimal_spec()
        driver = spec["drivers"][0]
        for i in range(14):
            driver["inputs"]["x%d" % i] = {
                "value": 1.0,
                "confidence": "assumption",
                "source": "Calibration factor %d from the pilot readout, table 3" % i,
                "low": 0.9,
                "high": 1.1 + i * 0.01,
            }
        driver["formula"] += "".join(" * x%d" % i for i in range(14))
        case = validate_spec(spec)
        self.assertEqual(len(case.sensitivity()), 15)
        self.assertEqual(len(case.evidence_by_input()), 17)
        markdown = case.to_markdown()
        self.assertIn(
            "_3 more ranged inputs that move NPV less are not listed here; "
            "`--format html` and `--format json` include every one._",
            markdown,
        )
        self.assertIn(
            "_5 more inputs carrying less value are not listed here;", markdown
        )
        attribution = markdown.split("## Where the value actually comes from")[1]
        attribution = attribution.split("\n## ")[0]
        self.assertEqual(attribution.count("| Driver one / "), 12)
        html = case.to_html()
        self.assertEqual(html.count('<div class="t-row">'), 15)
        self.assertEqual(html.count('<div class="r-plot">'), 17)


class TestSharedInputs(unittest.TestCase):
    def setUp(self):
        self.rate = minimal_spec()["drivers"][0]["inputs"]["rate"]
        # Gross savings are 100r + 40(1-r). Subtract a fixed 50 at kickoff.
        self.spec = minimal_spec(
            horizon_years=1,
            discount_rate_annual=0,
            shared_inputs={"fraction": self.rate},
            drivers=[
                {
                    "id": "saved",
                    "formula": "100 * r",
                    "inputs": {"r": {"ref": "fraction"}},
                },
                {
                    "id": "retained",
                    "formula": "40 * (1 - share)",
                    "inputs": {"share": {"ref": "fraction"}},
                },
            ],
            costs=[{"id": "setup", "schedule": [50, 0]}],
        )

    def test_one_sensitivity_row_and_one_attainable_floor(self):
        case = validate_spec(self.spec)
        (row,) = case.sensitivity()
        self.assertEqual(row["shared_input"], "fraction")
        self.assertAlmostEqual(row["npv_low"], -4)
        self.assertAlmostEqual(row["npv_high"], 8)
        self.assertAlmostEqual(row["swing"], 12)
        self.assertTrue(row["flips_decision"])
        self.assertAlmostEqual(case.floor_case()["npv"], -4)
        self.assertAlmostEqual(case.evidence()["largest_assumption"]["swing"], 12)
        self.assertEqual(
            [entry["name"] for entry in case.to_dict()["ledger"]], ["r", "share"]
        )

    def test_floor_uses_the_jointly_adverse_bound(self):
        self.spec["drivers"][0]["formula"] = "10 * r"
        # The first driver improves as r rises, but the combined case loses 30r.
        case = validate_spec(self.spec)
        (row,) = case.sensitivity()
        self.assertAlmostEqual(row["npv_low"], -13)
        self.assertAlmostEqual(row["npv_high"], -19)
        self.assertAlmostEqual(case.floor_case()["npv"], -19)

    def test_overrides_follow_references_and_reject_conflicts(self):
        case = validate_spec(self.spec)
        self.assertAlmostEqual(case.npv_with({"retained": {"share": 0.1}}), -4)
        same = {"saved": {"r": 0.3}, "retained": {"share": 0.3}}
        self.assertAlmostEqual(case.npv_with(same), 8)
        with self.assertRaisesRegex(SpecError, "fraction"):
            case.npv_with({"saved": {"r": 0.1}, "retained": {"share": 0.3}})

    def test_unlinked_inputs_with_the_same_name_remain_independent(self):
        del self.spec["shared_inputs"]
        for driver in self.spec["drivers"]:
            driver["inputs"] = {"r": deepcopy(self.rate)}
        self.spec["drivers"][1]["formula"] = "40 * (1 - r)"
        case = validate_spec(self.spec)
        self.assertEqual(len(case.sensitivity()), 2)
        self.assertAlmostEqual(case.npv_with({"saved": {"r": 0.1}}), -8)
        self.assertAlmostEqual(case.floor_case()["npv"], -12)

    def test_shared_inputs_keep_normal_evidence_validation(self):
        del self.rate["low"]
        with self.assertRaisesRegex(SpecError, "fraction.*low"):
            validate_spec(self.spec)

    def test_unused_or_ambiguous_shared_definitions_are_rejected(self):
        self.spec["shared_inputs"]["unused"] = deepcopy(self.rate)
        with self.assertRaisesRegex(SpecError, "unused shared input"):
            validate_spec(self.spec)
        del self.spec["shared_inputs"]["unused"]
        self.rate["ref"] = "fraction"
        with self.assertRaisesRegex(SpecError, "shared input 'fraction'.*ref"):
            validate_spec(self.spec)

    def test_references_must_exist_and_cannot_redefine_the_input(self):
        for invalid in ({"ref": "missing"}, {"ref": []}, {"ref": "fraction", "low": 0}):
            with self.subTest(invalid=invalid):
                self.spec["drivers"][0]["inputs"]["r"] = invalid
                with self.assertRaisesRegex(SpecError, "driver 'saved'.*'r'"):
                    validate_spec(self.spec)


class TestSpecValidation(unittest.TestCase):
    def test_rejects_missing_name(self):
        spec = minimal_spec()
        del spec["name"]
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_percentage_style_discount_rate(self):
        with self.assertRaises(SpecError) as ctx:
            validate_spec(minimal_spec(discount_rate_annual=12))
        self.assertIn("decimal", str(ctx.exception))

    def test_rejects_absurd_horizon(self):
        with self.assertRaises(SpecError):
            validate_spec(minimal_spec(horizon_years=25))

    def test_rejects_benefit_only_case(self):
        spec = minimal_spec()
        spec["costs"] = []
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("wish list", str(ctx.exception))

    def test_rejects_undefined_formula_variable(self):
        spec = minimal_spec()
        spec["drivers"][0]["formula"] = "volume * rate * missing_input"
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("missing_input", str(ctx.exception))

    def test_rejects_declared_but_unused_input(self):
        """A stale ledger misleads reviewers as much as a stale formula."""
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["orphan"] = {
            "value": 1,
            "confidence": "fact",
            "source": "Left over from an earlier version of this model",
        }
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("never uses", str(ctx.exception))

    def test_rejects_wrong_length_cost_schedule(self):
        spec = minimal_spec()
        spec["costs"][0]["schedule"] = [0, 100]
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("schedule entries", str(ctx.exception))

    def test_rejects_negative_cost_entry(self):
        spec = minimal_spec()
        spec["costs"][0]["schedule"] = [0, -100, 0, 0]
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_realization_above_one(self):
        spec = minimal_spec()
        spec["drivers"][0]["realization"] = 1.4
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_duplicate_driver_ids(self):
        spec = minimal_spec()
        spec["drivers"].append(dict(spec["drivers"][0]))
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_propagates_evidence_errors_with_driver_context(self):
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["rate"]["source"] = "industry standard"
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("d1", str(ctx.exception))


class TestCommandLineErrors(unittest.TestCase):
    """Problems found while loading or computing a spec are one line, exit 2."""

    def test_a_range_bound_that_breaks_the_formula_is_a_spec_error(self):
        raw = minimal_spec()
        raw["drivers"][0]["formula"] = "volume * unit_value / rate"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "case.json")
            raw["drivers"][0]["inputs"]["rate"]["low"] = 0
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(raw, handle)
            for extra in (["--check"], ["--format", "html"]):
                with self.subTest(args=extra):
                    out, err = io.StringIO(), io.StringIO()
                    with (
                        contextlib.redirect_stdout(out),
                        contextlib.redirect_stderr(err),
                    ):
                        self.assertEqual(valuecase.main([path, *extra]), 2)
                    self.assertEqual(out.getvalue(), "")
                    self.assertIn("spec error: division by zero", err.getvalue())

    def test_meta_must_be_an_object(self):
        for meta in ("draft", ["draft"], 3):
            with self.subTest(meta=meta), self.assertRaises(SpecError):
                validate_spec(minimal_spec(meta=meta))

    def test_unreadable_spec_is_a_spec_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(valuecase.main([tmp, "--check"]), 2)
            self.assertIn("spec error: cannot read", err.getvalue())


class TestShippedExample(unittest.TestCase):
    """The example the README quotes must keep loading and keep its shape."""

    def setUp(self):
        self.case = load_spec(EXAMPLE)

    def test_loads(self):
        self.assertEqual(self.case.horizon, 3)
        self.assertEqual(len(self.case.drivers), 3)

    def test_is_internally_consistent(self):
        """Headcount and tickets-per-agent must not contradict each other.

        The first draft of this example claimed 62 agents while deriving cost
        per ticket from 6,400 tickets per agent-year against 124,800 tickets —
        implying 20 agents. Exactly the kind of quiet inconsistency this whole
        pack exists to catch, so it is pinned here.
        """
        attrition = next(d for d in self.case.drivers if d.id == "attrition")
        deflection = next(d for d in self.case.drivers if d.id == "deflection")
        agents = attrition.inputs["agents"].value
        tickets = deflection.inputs["tickets_per_year"].value
        implied_per_agent = tickets / agents
        self.assertTrue(
            5000 <= implied_per_agent <= 8000,
            "implied %.0f tickets per agent-year contradicts the stated 6,400"
            % implied_per_agent,
        )

    def test_case_is_positive_but_not_trivially_so(self):
        summary = self.case.summary()
        self.assertGreater(summary["npv"], 0)
        self.assertIsNotNone(summary["discounted_payback_periods"])
        # A margin of safety this thin is the interesting teaching case.
        self.assertLess(summary["break_even_benefit_multiplier"], 1.0)

    def test_floor_case_goes_negative(self):
        """The example is chosen so the stress test actually bites."""
        self.assertFalse(self.case.floor_case()["still_positive"])

    def test_top_assumption_flips_the_decision(self):
        top = self.case.sensitivity()[0]
        self.assertTrue(top["flips_decision"])
        self.assertEqual(top["input"], "deflection_rate")

    def test_deflection_sensitivity_changes_both_ticket_populations(self):
        rows = [r for r in self.case.sensitivity() if r["input"] == "deflection_rate"]
        self.assertEqual(len(rows), 1)

        # Compute both ticket populations independently of model overrides.
        def net_at(rate):
            net = [-217000]
            for i, cost in enumerate((126000, 116880, 119846)):
                deflected = 124800 * rate * 12.81 * (0.4, 0.9, 1)[i] * 0.85
                retained = 124800 * (1 - rate) * 1.8 / 60 * 39.42 * (0.5, 1, 1)[i] * 0.7
                backfill = 20 * 0.04 * 18500 * (0, 0.6, 1)[i] * 0.6
                net.append(deflected + retained + backfill - cost)
            return sum(value / 1.12**i for i, value in enumerate(net))

        self.assertAlmostEqual(rows[0]["npv_low"], net_at(0.10))
        self.assertAlmostEqual(rows[0]["npv_high"], net_at(0.24))
        self.assertIn("$311.6k", self.case.to_markdown())

    def test_renders_markdown_without_error(self):
        markdown = self.case.to_markdown()
        for heading in (
            "## Headline",
            "## Evidence grade",
            "## Value drivers",
            "## Cash flow",
            "## What would have to be true",
            "## Floor case",
            "## Assumption ledger",
        ):
            self.assertIn(heading, markdown)

    def test_serializes_to_json(self):
        payload = json.dumps(self.case.to_dict())
        self.assertGreater(len(payload), 1000)

    def test_no_pipe_characters_leak_into_tables(self):
        """A source string containing a pipe would silently corrupt a table."""
        for line in self.case.to_markdown().splitlines():
            if line.startswith("|"):
                # Escaped pipes are fine; raw ones inside a cell are not.
                self.assertNotIn("||", line)


class TestAdverseBounds(unittest.TestCase):
    def test_inverse_input_high_bound_can_reverse_the_decision(self):
        spec = minimal_spec(horizon_years=1, discount_rate_annual=0)
        spec["drivers"] = [
            {
                "id": "inverse",
                "formula": "1000 * (1 - loss)",
                "inputs": {
                    "loss": {
                        "value": 0.2,
                        "low": 0.1,
                        "high": 0.9,
                        "confidence": "assumption",
                        "source": "Illustrative planning interval",
                    }
                },
            }
        ]
        spec["costs"] = [{"id": "cost", "schedule": [500, 0]}]
        case = validate_spec(spec)
        row = case.sensitivity()[0]
        self.assertAlmostEqual(case.npv_with(), 300)
        self.assertAlmostEqual(row["npv_low"], 400)
        self.assertAlmostEqual(row["npv_high"], -400)
        self.assertAlmostEqual(row["downside"], -700)
        self.assertAlmostEqual(row["upside"], 100)
        self.assertTrue(row["flips_decision"])
        self.assertNotIn(
            "at its low bound", case.evidence()["largest_assumption"]["advice"]
        )

    def test_non_finite_schedules_are_rejected_before_calculation(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            for field in ("ramp", "cost"):
                spec = minimal_spec()
                if field == "ramp":
                    spec["drivers"][0]["ramp"][0] = value
                else:
                    spec["costs"][0]["schedule"][0] = value
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(SpecError, "non-finite"),
                ):
                    validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
